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
        body = cli.post('/api/proxy/create-payment',
                        json={'provider': 'grusha', 'amount': 10000}).get_json()
        assert body['sbp_link'] is None
