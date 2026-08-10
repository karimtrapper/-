"""Платёжная ссылка идёт по сберовскому СБП, а не через Доверку.

Симптом, с которого начали: ссылка из калькулятора создавалась, но уведомления
в рабочий чат не было — потому что это был вообще другой рельс. В коннектор
`grushab-2-b.ru/api/payments` рельс задаётся заголовком `X-Provider-Name`,
и там был зашит `doverkapay`. Проверено на живом коннекторе: с `sberbank-sbp`
и мерчантом `grusha` возвращается ссылка НСПК (`qr.nspk.ru/...`) — тот же QR,
которым платят клиенты WL-бота.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payment_link_provider.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import app as flask_app

NSPK = 'https://qr.nspk.ru/BD1010443KNQA7PL9BPOR8CTCSI3P78T'
PUBLIC = 'https://grushab-2-b.ru/iframe-v2/a9763d09-eb62-4005-8c14-c9a6a7d5da59/'


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


class _Resp:
    def __init__(self, payload, code=200):
        self._p, self.status_code = payload, code

    def json(self):
        return self._p


@pytest.fixture
def capture_post(monkeypatch):
    """Подменяет requests.post и запоминает, с какими заголовками звали коннектор."""
    calls = {}

    def _post(url, json=None, headers=None, timeout=None):
        calls['url'], calls['json'], calls['headers'] = url, json, headers
        return _Resp({
            'success': True,
            'public_link': PUBLIC,
            'approve_url': NSPK,
            'provider_payload': {'externalParams': {'sbpPayload': NSPK}},
        })

    monkeypatch.setattr(appmod.requests, 'post', _post)
    monkeypatch.setattr(appmod, 'send_telegram_notification', lambda *a, **kw: True)
    return calls


class TestConnectorProvider:
    def test_uses_sberbank_sbp_not_doverka(self, cli, capture_post):
        resp = cli.post('/api/proxy/create-payment',
                        json={'provider': 'grusha', 'amount': 10000, 'merchant_id': 'grusha'})
        assert resp.status_code == 200
        assert capture_post['headers']['X-Provider-Name'] == 'sberbank-sbp'
        assert capture_post['headers']['X-Provider-Name'] != 'doverkapay'

    def test_returns_direct_sbp_link(self, cli, capture_post):
        body = cli.post('/api/proxy/create-payment',
                        json={'provider': 'grusha', 'amount': 10000}).get_json()
        assert body['public_link'] == PUBLIC
        assert body['sbp_link'] == NSPK

    def test_no_sbp_link_when_not_nspk(self, cli, monkeypatch):
        """Форма payecom (провайдер sberbank) — не НСПК, прямую ссылку не показываем."""
        monkeypatch.setattr(appmod.requests, 'post', lambda *a, **kw: _Resp(
            {'public_link': PUBLIC, 'approve_url': 'https://payecom.ru/pay_ru?orderId=1'}))
        monkeypatch.setattr(appmod, 'send_telegram_notification', lambda *a, **kw: True)
        body = cli.post('/api/proxy/create-payment',
                        json={'provider': 'grusha', 'amount': 10000}).get_json()
        assert body['sbp_link'] is None


class TestNotification:
    def test_notifies_working_chat(self, cli, monkeypatch, capture_post):
        sent = []
        monkeypatch.setattr(appmod, 'send_telegram_notification', lambda text, *a, **kw: sent.append(text))
        cli.post('/api/proxy/create-payment', json={
            'provider': 'grusha', 'amount': 10000,
            'metadata': {'thb_amount': 3544.67, 'comment': 'Мария, заказ 12'},
        })
        assert len(sent) == 1
        assert 'Ссылка на оплату создана' in sent[0]
        assert 'Мария, заказ 12' in sent[0]
        assert PUBLIC in sent[0]

    def test_notify_failure_does_not_break_link(self, cli, monkeypatch, capture_post):
        """Телеграм лёг — ссылка всё равно должна вернуться менеджеру."""
        def _boom(*a, **kw):
            raise RuntimeError('tg down')
        monkeypatch.setattr(appmod, 'send_telegram_notification', _boom)
        resp = cli.post('/api/proxy/create-payment', json={'provider': 'grusha', 'amount': 10000})
        assert resp.status_code == 200
        assert resp.get_json()['public_link'] == PUBLIC

class TestDescription:
    def test_no_amounts_in_description(self, cli, capture_post):
        """Описание видно клиенту на странице оплаты — суммы туда не пишем."""
        cli.post('/api/proxy/create-payment', json={
            'provider': 'grusha', 'amount': 100000,
            'description': 'Обмен 100 000.00 RUB на 35 758.68 THB',
        })
        assert capture_post['json']['description'] == 'Grusha Exchange'


class TestPaidWebhook:
    """Коннектор сообщает об оплате → уведомление в рабочий чат."""

    def _create_link(self, cli, capture_post):
        cli.post('/api/proxy/create-payment', json={
            'provider': 'grusha', 'amount': 100000, 'order_id': 'GR-777',
            'metadata': {'thb_amount': 35758.68, 'comment': 'Мария'},
        })
        return capture_post['json']['webhook_url']

    def test_webhook_url_passed_to_connector(self, cli, capture_post):
        url = self._create_link(cli, capture_post)
        assert '/api/webhook/payment-link?key=' in url

    def test_paid_status_notifies(self, cli, capture_post, monkeypatch):
        self._create_link(cli, capture_post)
        sent = []
        monkeypatch.setattr(appmod, 'send_telegram_notification', lambda text, *a, **kw: sent.append(text))
        resp = cli.post(f'/api/webhook/payment-link?key={appmod.payment_webhook_key()}',
                        json={'order_id': 'GR-777', 'status': 'PAID'})
        assert resp.status_code == 200
        assert len(sent) == 1
        assert 'Оплачено' in sent[0] and 'Мария' in sent[0]

    def test_pending_status_is_silent(self, cli, capture_post, monkeypatch):
        self._create_link(cli, capture_post)
        sent = []
        monkeypatch.setattr(appmod, 'send_telegram_notification', lambda text, *a, **kw: sent.append(text))
        cli.post(f'/api/webhook/payment-link?key={appmod.payment_webhook_key()}',
                 json={'order_id': 'GR-777', 'status': 'PENDING'})
        assert sent == []

    def test_wrong_key_rejected(self, cli, monkeypatch):
        sent = []
        monkeypatch.setattr(appmod, 'send_telegram_notification', lambda text, *a, **kw: sent.append(text))
        resp = cli.post('/api/webhook/payment-link?key=nope',
                        json={'order_id': 'GR-777', 'status': 'PAID'})
        assert resp.status_code == 403
        assert sent == []

    def test_garbage_body_answers_200(self, cli):
        """Мусор не должен вызывать ретраи коннектора."""
        resp = cli.post(f'/api/webhook/payment-link?key={appmod.payment_webhook_key()}',
                        data='not json', content_type='text/plain')
        assert resp.status_code == 200
