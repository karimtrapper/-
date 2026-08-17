"""Уведомление «Оплачено» по платёжной ссылке: вебхук + страховочный поллер.

Симптом, с которого начали (2026-08-17): клиент оплатил ссылку по СБП,
коннектор пометил платёж PAID, но вебхук в CalcCRM не пришёл — команда
узнала об оплате от клиента. Ссылки жили только в памяти процесса и
терялись при каждом деплое. Теперь ссылка пишется в payment_link_orders,
а фоновый поллер перепроверяет статус в коннекторе; вебхук остаётся
быстрым путём, дедуп — атомарным PENDING→PAID.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_payment_link_paid.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'
os.environ['PAYMENT_POLL_ENABLED'] = '0'

import pytest

import app as appmod
from app import PaymentLinkOrder, app as flask_app

# UUID заведомо фейковый: если фоновый поллер всё же проснётся во время прогона,
# коннектор ответит 404 и ничего не произойдёт (не использовать реальные платежи!)
PUBLIC = 'https://grushab-2-b.ru/iframe-v2/00000000-dead-4bee-8000-000000000001/'
PAY_UUID = '00000000-dead-4bee-8000-000000000001'


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def notifications(monkeypatch):
    """Перехватывает send_telegram_notification."""
    sent = []
    monkeypatch.setattr(appmod, 'send_telegram_notification',
                        lambda text, *a, **kw: sent.append(text))
    return sent


@pytest.fixture
def db_cleanup():
    """Изолирует тест: до — убирает чужие PENDING-строки (другие тест-файлы
    создают ссылки и не чистят за собой), после — удаляет свои."""
    db = appmod.get_session()
    try:
        (db.query(PaymentLinkOrder)
           .filter(PaymentLinkOrder.status == 'PENDING')
           .delete(synchronize_session=False))
        db.commit()
    finally:
        db.close()
    order_ids = []
    yield order_ids
    db = appmod.get_session()
    try:
        if order_ids:
            (db.query(PaymentLinkOrder)
               .filter(PaymentLinkOrder.order_id.in_(order_ids))
               .delete(synchronize_session=False))
            db.commit()
    finally:
        db.close()


def _make_row(order_id, db_cleanup, **kw):
    db_cleanup.append(order_id)
    db = appmod.get_session()
    try:
        row = PaymentLinkOrder(order_id=order_id, payment_id=kw.pop('payment_id', PAY_UUID),
                               amount=kw.pop('amount', 35000.0), thb=kw.pop('thb', 11998.0), **kw)
        db.add(row)
        db.commit()
    finally:
        db.close()


def _row(order_id):
    db = appmod.get_session()
    try:
        return db.query(PaymentLinkOrder).filter_by(order_id=order_id).first()
    finally:
        db.close()


class _Resp:
    def __init__(self, payload, code=200):
        self._p, self.status_code = payload, code

    def json(self):
        return self._p


def test_create_payment_persists_row(cli, notifications, db_cleanup, monkeypatch):
    """Создание ссылки пишет строку в БД: поллер должен пережить деплой."""
    def _post(url, json=None, headers=None, timeout=None):
        return _Resp({'success': True, 'public_link': PUBLIC})

    monkeypatch.setattr(appmod.requests, 'post', _post)
    db_cleanup.append('T-PERSIST-1')
    r = cli.post('/api/proxy/create-payment',
                 json={'provider': 'grusha', 'amount': 35000,
                       'order_id': 'T-PERSIST-1',
                       'metadata': {'thb_amount': 11998, 'comment': 'Роман'}})
    assert r.status_code < 400
    row = _row('T-PERSIST-1')
    assert row is not None
    assert row.status == 'PENDING'
    assert row.payment_id == PAY_UUID   # uuid извлечён из public_link
    assert row.amount == 35000.0
    assert row.thb == 11998.0


def test_webhook_notifies_once(cli, notifications, db_cleanup):
    """Вебхук уведомляет и помечает PAID; дубль вебхука молчит."""
    _make_row('T-WH-1', db_cleanup, comment='Роман')
    key = appmod.payment_webhook_key()
    r = cli.post(f'/api/webhook/payment-link?key={key}',
                 json={'order_id': 'T-WH-1', 'status': 'PAID'})
    assert r.status_code == 200
    assert len(notifications) == 1
    assert 'Оплачено' in notifications[0] and '35,000' in notifications[0]
    assert '11,998' in notifications[0] and 'Роман' in notifications[0]
    assert _row('T-WH-1').status == 'PAID'

    cli.post(f'/api/webhook/payment-link?key={key}',
             json={'order_id': 'T-WH-1', 'status': 'PAID'})
    assert len(notifications) == 1   # второго уведомления нет


def test_webhook_legacy_without_row(cli, notifications):
    """Ссылка без строки в БД (создана до таблицы) — уведомление по старому пути."""
    key = appmod.payment_webhook_key()
    r = cli.post(f'/api/webhook/payment-link?key={key}',
                 json={'order_id': 'T-LEGACY-404', 'status': 'PAID', 'amount': 500})
    assert r.status_code == 200
    assert len(notifications) == 1
    assert 'Оплачено' in notifications[0] and '500' in notifications[0]


def test_webhook_bad_key_rejected(cli, notifications, db_cleanup):
    _make_row('T-WH-KEY', db_cleanup)
    r = cli.post('/api/webhook/payment-link?key=wrong',
                 json={'order_id': 'T-WH-KEY', 'status': 'PAID'})
    assert r.status_code == 403
    assert notifications == []
    assert _row('T-WH-KEY').status == 'PENDING'


def test_poller_catches_lost_webhook(notifications, db_cleanup, monkeypatch):
    """Кейс Романа: вебхук потерян, поллер сам находит PAID и уведомляет один раз."""
    _make_row('T-POLL-1', db_cleanup, comment='Роман')
    calls = []

    def _get(url, headers=None, timeout=None, **kw):
        calls.append(url)
        return _Resp({'payment_id': PAY_UUID, 'status': 'PAID'})

    monkeypatch.setattr(appmod.requests, 'get', _get)
    assert appmod._poll_pending_payment_links() == 1
    assert len(notifications) == 1
    assert 'Оплачено' in notifications[0] and '35,000' in notifications[0]
    assert PAY_UUID in calls[0]
    assert _row('T-POLL-1').status == 'PAID'

    # Второй тик: PENDING больше нет — ни запросов, ни уведомлений
    calls.clear()
    assert appmod._poll_pending_payment_links() == 0
    assert calls == [] and len(notifications) == 1


def test_poller_marks_expired(notifications, db_cleanup, monkeypatch):
    """Просроченные (>24ч) ссылки закрываются без запроса к коннектору."""
    from datetime import datetime, timedelta
    _make_row('T-POLL-OLD', db_cleanup)
    db = appmod.get_session()
    try:
        (db.query(PaymentLinkOrder).filter_by(order_id='T-POLL-OLD')
           .update({'created_at': datetime.utcnow() - timedelta(hours=25)}))
        db.commit()
    finally:
        db.close()

    def _get(*a, **kw):
        raise AssertionError('коннектор не должен опрашиваться для просроченных')

    monkeypatch.setattr(appmod.requests, 'get', _get)
    assert appmod._poll_pending_payment_links() == 0
    assert _row('T-POLL-OLD').status == 'EXPIRED'
    assert notifications == []


def test_poller_pending_stays(notifications, db_cleanup, monkeypatch):
    """PENDING в коннекторе — строка остаётся, уведомления нет."""
    _make_row('T-POLL-PEND', db_cleanup)
    monkeypatch.setattr(appmod.requests, 'get',
                        lambda *a, **kw: _Resp({'status': 'PENDING'}))
    assert appmod._poll_pending_payment_links() == 0
    assert _row('T-POLL-PEND').status == 'PENDING'
    assert notifications == []
