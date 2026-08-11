"""
Тесты витрины реферального кабинета: сделки и клиенты с `is_test=True` видны
рефереру в его кабинете, но НЕ попадают в CRM (сделки, клиенты, дашборд,
конверсия, возмещения) и не уезжают в Google Sheets / Telegram.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_demo_referrer.py -v
"""
import pytest
import sys
import os
import secrets
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import (app, get_session, Referrer, Client, Deal, DealAgent, PayoutRequest,
                 DealType, DealStatus, AdminUser)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    def _clean():
        session = get_session()
        try:
            session.query(PayoutRequest).delete()
            session.query(DealAgent).delete()
            session.query(Deal).delete()
            session.query(Client).delete()
            session.query(Referrer).delete()
            session.commit()
        finally:
            session.close()
    _clean()
    yield
    _clean()


@pytest.fixture
def db():
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def tc():
    """Flask test client с авторизацией админа."""
    app.config['TESTING'] = True
    s = get_session()
    try:
        a = s.query(AdminUser).first()
        if not a:
            a = AdminUser(username='test_admin', display_name='T',
                          password_hash=AdminUser.hash_password('x'))
            s.add(a); s.commit()
        aid = a.id
    finally:
        s.close()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = aid
        yield client


@pytest.fixture
def demo(db):
    """Демо-реферер + демо-сделка + обычная сделка для контраста."""
    r = Referrer(name='Теодор', code='GR-TEODOR', token=secrets.token_hex(16),
                 default_percent=30.0, comp_model='revshare', is_test=True,
                 auth_mode='link')
    db.add(r)
    db.commit()

    demo_client = Client(name='Демо Клиент', referrer_id=r.id, is_test=True)
    real_client = Client(name='Живой Клиент')
    db.add_all([demo_client, real_client])
    db.commit()

    when = datetime.utcnow() - timedelta(days=3)
    demo_deal = Deal(
        created_at=when, deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
        is_test=True, client_id=demo_client.id, client_name=demo_client.name,
        payin_amount_usdt=10000.0, payout_amount_thb=320000.0,
        profit_usdt=300.0, net_profit_usdt=210.0,
        referrer_id=r.id, referrer_name=r.name, referrer_percent=30.0,
        referrer_payout_usdt=90.0, needs_reimbursement=False,
    )
    real_deal = Deal(
        created_at=when, deal_type=DealType.PAY_IN, status=DealStatus.COMPLETED,
        client_id=real_client.id, client_name=real_client.name,
        payin_amount_usdt=5000.0, payout_amount_thb=160000.0,
        profit_usdt=100.0, net_profit_usdt=100.0, needs_reimbursement=False,
    )
    db.add_all([demo_deal, real_deal])
    db.flush()
    db.add(DealAgent(deal_id=demo_deal.id, referrer_id=r.id, name=r.name, tier=1,
                     comp_model='revshare', percent=30.0, payout_usdt=90.0,
                     base_usdt=300.0, paid=False))
    db.commit()
    return {'referrer': r, 'demo_deal': demo_deal, 'real_deal': real_deal,
            'demo_client': demo_client, 'real_client': real_client}


# ── CRM не видит демо-данные ──────────────────────────────────────────────

class TestCrmHidesDemo:

    def test_deals_list_skips_test(self, tc, demo):
        r = tc.get('/api/deals')
        ids = [d['id'] for d in r.get_json()['deals']]
        assert demo['demo_deal'].id not in ids
        assert demo['real_deal'].id in ids

    def test_deals_list_include_test(self, tc, demo):
        r = tc.get('/api/deals?include_test=1')
        ids = [d['id'] for d in r.get_json()['deals']]
        assert demo['demo_deal'].id in ids

    def test_deals_total_excludes_test(self, tc, demo):
        assert tc.get('/api/deals').get_json()['total'] == 1

    def test_search_does_not_leak_test_deal(self, tc, demo):
        r = tc.get('/api/deals?q=Демо')
        assert r.get_json()['deals'] == []

    def test_clients_list_skips_test(self, tc, demo):
        names = [c['name'] for c in tc.get('/api/clients').get_json()['clients']]
        assert 'Демо Клиент' not in names
        assert 'Живой Клиент' in names

    def test_dashboard_excludes_test_profit(self, tc, demo):
        period = tc.get('/api/analytics/dashboard?period=30d').get_json()['dashboard']['period']
        # В периоде только реальная сделка: прибыль 100, а не 310
        assert period['profit_usdt'] == pytest.approx(100.0)
        assert period['deals_count'] == 1
        assert period['volume_usdt'] == pytest.approx(5000.0)

    def test_conversion_excludes_test(self, tc, demo):
        d = tc.get('/api/analytics/conversion?months=3').get_json()
        assert d['success'] is True
        # Эпизод только один — от реальной сделки
        assert d['totals']['new']['total'] == 1

    def test_payout_requests_hide_test_referrer(self, tc, demo, db):
        db.add(PayoutRequest(referrer_id=demo['referrer'].id, amount_usdt=90.0,
                             wallet='TDemo', contact_method='telegram',
                             contact_value='@demo', status='paid'))
        db.commit()
        assert tc.get('/api/payout-requests').get_json()['requests'] == []
        assert len(tc.get('/api/payout-requests?include_test=1').get_json()['requests']) == 1


# ── Кабинет реферера видит демо-данные ────────────────────────────────────

class TestCabinetSeesDemo:

    def test_stats_include_test_deal(self, demo):
        with app.test_client() as c:
            d = c.get(f"/api/ref/{demo['referrer'].token}/stats").get_json()
        assert d['success'] is True
        assert d['total_deals'] == 1
        assert d['total_earned_usdt'] == pytest.approx(90.0)
        assert d['available_for_withdraw'] == pytest.approx(90.0)
        assert len(d['recent_deals']) == 1


# ── Демо не уезжает наружу ────────────────────────────────────────────────

class TestNoExternalSideEffects:

    def test_gsheet_sync_skips_test_deal(self, demo):
        from app import sync_deals_to_gsheet
        with patch('app._sync_deals_to_gsheet_impl') as impl:
            sync_deals_to_gsheet([demo['demo_deal']])
            impl.assert_not_called()
            sync_deals_to_gsheet([demo['real_deal']])
            impl.assert_called_once()

    def test_telegram_skips_test_deal(self, demo):
        from app import _send_deal_telegram
        with patch('app.send_telegram_notification') as notify:
            _send_deal_telegram(demo['demo_deal'])
            notify.assert_not_called()
