"""
Тесты /api/analytics/dashboard: кастомный диапазон дат, фильтр по рефереру,
блок юнит-экономики (Красинский).

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_dashboard_analytics.py -v
"""
import pytest
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import app, get_session, Referrer, Client, Deal, DealType, DealStatus, AdminUser, DealAgent


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Чистим таблицы перед каждым тестом."""
    def _clean():
        session = get_session()
        try:
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
    """Flask test client с авторизацией."""
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


def make_deal(db, client_id=None, referrer=None, profit=100.0, payin=1000.0,
              created_at=None, status=DealStatus.COMPLETED):
    d = Deal(
        deal_type=DealType('pay_in'),
        status=status,
        client_id=client_id,
        payin_amount_usdt=payin,
        payout_amount_usdt=payin - profit,
        profit_usdt=profit,
        profit_percent=round(profit / payin * 100, 2),
    )
    if referrer:
        d.referrer_id = referrer.id
        d.referrer_payout_usdt = profit / 2
    if created_at:
        d.created_at = created_at
    db.add(d)
    db.commit()
    return d


def get_dash(tc, **params):
    qs = '&'.join(f'{k}={v}' for k, v in params.items())
    res = tc.get(f'/api/analytics/dashboard?{qs}')
    return res


# ── Кастомный диапазон дат ────────────────────────────────────────────────

class TestCustomDateRange:

    def test_range_includes_only_deals_inside(self, db, tc):
        today = datetime.now()
        make_deal(db, profit=100)  # сегодня
        make_deal(db, profit=50, created_at=today - timedelta(days=40))  # вне диапазона
        frm = (today - timedelta(days=7)).strftime('%Y-%m-%d')
        to = today.strftime('%Y-%m-%d')
        data = get_dash(tc, date_from=frm, date_to=to).get_json()
        assert data['success']
        assert data['dashboard']['period']['deals_count'] == 1
        assert data['dashboard']['period']['profit_usdt'] == 100

    def test_range_ending_in_past(self, db, tc):
        """Диапазон, закончившийся в прошлом — сегодняшние сделки не попадают."""
        today = datetime.now()
        make_deal(db, profit=100)  # сегодня
        make_deal(db, profit=70, created_at=today - timedelta(days=20))
        frm = (today - timedelta(days=25)).strftime('%Y-%m-%d')
        to = (today - timedelta(days=15)).strftime('%Y-%m-%d')
        data = get_dash(tc, date_from=frm, date_to=to).get_json()
        p = data['dashboard']['period']
        assert p['deals_count'] == 1
        assert p['profit_usdt'] == 70
        # график не должен тянуться до сегодня
        last_chart_day = data['dashboard']['charts']['daily'][-1]['date']
        assert last_chart_day == (today - timedelta(days=15)).strftime('%d.%m')

    def test_invalid_date_returns_400(self, tc):
        res = get_dash(tc, date_from='07-07-2026')
        assert res.status_code == 400

    def test_preset_period_still_works(self, db, tc):
        make_deal(db, profit=42)
        data = get_dash(tc, period='30d').get_json()
        assert data['success']
        assert data['dashboard']['period']['profit_usdt'] == 42


# ── Фильтр по рефереру ────────────────────────────────────────────────────

class TestReferrerFilter:

    @pytest.fixture
    def two_referrers(self, db):
        r1 = Referrer(name='Eduard', code='GR-ED', token='t1')
        r2 = Referrer(name='Malik', code='GR-ML', token='t2')
        db.add_all([r1, r2]); db.commit()
        make_deal(db, referrer=r1, profit=100)
        make_deal(db, referrer=r2, profit=60)
        make_deal(db, profit=30)  # без реферала
        return r1, r2

    def test_all_by_default(self, tc, two_referrers):
        p = get_dash(tc, period='30d').get_json()['dashboard']['period']
        assert p['deals_count'] == 3
        assert p['profit_usdt'] == 190

    def test_specific_referrer(self, tc, two_referrers):
        r1, _ = two_referrers
        p = get_dash(tc, period='30d', referrer_id=r1.id).get_json()['dashboard']['period']
        assert p['deals_count'] == 1
        assert p['profit_usdt'] == 100
        assert p['referrer_payout_usdt'] == 50

    def test_none_referrer(self, tc, two_referrers):
        p = get_dash(tc, period='30d', referrer_id='none').get_json()['dashboard']['period']
        assert p['deals_count'] == 1
        assert p['profit_usdt'] == 30

    def test_any_referrer(self, tc, two_referrers):
        """«Только рефералы» — сделки с любым реферером."""
        p = get_dash(tc, period='30d', referrer_id='any').get_json()['dashboard']['period']
        assert p['deals_count'] == 2
        assert p['profit_usdt'] == 160
        assert p['referrer_payout_usdt'] == 80

    def test_invalid_referrer_returns_400(self, tc, two_referrers):
        assert get_dash(tc, period='30d', referrer_id='abc').status_code == 400


# ── Юнит-экономика ────────────────────────────────────────────────────────

class TestUnitEconomics:

    def test_metrics_math(self, db, tc):
        """2 клиента, 3 сделки: B=2, APC=1.5, ARPC=CM/B."""
        c1 = Client(name='A'); c2 = Client(name='B')
        db.add_all([c1, c2]); db.commit()
        make_deal(db, client_id=c1.id, profit=100, payin=1000)
        make_deal(db, client_id=c1.id, profit=50, payin=500)
        make_deal(db, client_id=c2.id, profit=30, payin=300)
        ue = get_dash(tc, period='30d').get_json()['dashboard']['unit_economics']
        assert ue['buyers'] == 2
        assert ue['apc'] == 1.5
        assert ue['cm'] == 180
        assert ue['arpc'] == 90
        assert ue['profit_per_deal'] == 60
        assert ue['avp'] == 600  # (1000+500+300)/3

    def test_empty_period_zeros(self, tc):
        ue = get_dash(tc, period='today').get_json()['dashboard']['unit_economics']
        assert ue == {'buyers': 0, 'apc': 0, 'avp': 0, 'profit_per_deal': 0, 'arpc': 0, 'cm': 0}
