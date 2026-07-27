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
        assert ue['orders'] == 3
        assert ue['apc'] == 1.5
        assert ue['cm'] == 180
        assert ue['arpc'] == 90
        assert ue['profit_per_deal'] == 60
        assert ue['avp'] == 600  # (1000+500+300)/3
        assert ue['cogs_per_deal'] == 540  # (900+450+270)/3
        assert ue['revenue'] == 1800
        # архитектурные placeholder'ы: UA/C1/ARPU появятся с данными Bitrix, CPA=0 (органика)
        assert ue['ua'] is None and ue['c1'] is None and ue['arpu'] is None
        assert ue['cpa'] == 0.0

    def test_empty_period_zeros(self, tc):
        ue = get_dash(tc, period='today').get_json()['dashboard']['unit_economics']
        assert ue['buyers'] == 0 and ue['orders'] == 0 and ue['apc'] == 0
        assert ue['avp'] == 0 and ue['profit_per_deal'] == 0 and ue['arpc'] == 0 and ue['cm'] == 0


# ── Разбивка по рефererам ─────────────────────────────────────────────────

class TestReferrerBreakdown:

    def test_breakdown_per_referrer(self, db, tc):
        r1 = Referrer(name='Eduard', code='GR-ED2', token='tb1')
        r2 = Referrer(name='Malik', code='GR-ML2', token='tb2')
        db.add_all([r1, r2]); db.commit()
        c1 = Client(name='A'); db.add(c1); db.commit()
        d1 = make_deal(db, client_id=c1.id, referrer=r1, profit=100, payin=1000)
        d1.net_profit_usdt = 50.0  # gross 100, рефереру 50
        d2 = make_deal(db, referrer=r1, profit=60, payin=500)
        d2.net_profit_usdt = 30.0
        make_deal(db, referrer=r2, profit=30, payin=300)
        make_deal(db, profit=10)  # без реферала — не попадает
        db.commit()
        bd = get_dash(tc, period='30d', referrer_id='any').get_json()['dashboard']['referrer_breakdown']
        assert len(bd) == 2
        assert bd[0]['name'] == 'Eduard'  # сортировка по gross-прибыли
        assert bd[0]['deals'] == 2
        assert bd[0]['clients'] == 1
        assert bd[0]['volume_usdt'] == 1500
        assert bd[0]['profit_usdt'] == 160          # gross
        assert bd[0]['payout_usdt'] == 80           # 50+30 (make_deal ставит profit/2)
        assert bd[0]['net_usdt'] == 80              # 50 (net d1) + 30 (net d2)
        assert bd[1]['name'] == 'Malik'


# ── UA/C1 из эпизодов WON+LOSE ────────────────────────────────────────────

def make_lose(db, name, created_at=None):
    """LOSE-сделка из DealCloser: только имя, без client_id и финансов."""
    d = Deal(deal_type=DealType('pay_in'), status=DealStatus.LOSE, client_name=name)
    if created_at:
        d.created_at = created_at
    db.add(d)
    db.commit()
    return d


class TestUnitEconC1:

    def test_no_lose_in_period_c1_null(self, db, tc):
        """Нет LOSE в периоде — потока не знаем, UA/C1/ARPU = None (не фиктивные 100%)."""
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id)
        ue = get_dash(tc).get_json()['dashboard']['unit_economics']
        assert ue['ua'] is None
        assert ue['c1'] is None
        assert ue['arpu'] is None

    def test_c1_counts_lose_episodes(self, db, tc):
        """UA = уникальные клиенты WON+LOSE, C1 = B/UA×100, ARPU = ARPC×C1."""
        c1_, c2_ = Client(name='Иван'), Client(name='Пётр')
        db.add_all([c1_, c2_]); db.commit()
        make_deal(db, client_id=c1_.id, profit=100)
        make_deal(db, client_id=c2_.id, profit=100)
        make_lose(db, 'Олег')
        make_lose(db, 'Мария')
        ue = get_dash(tc).get_json()['dashboard']['unit_economics']
        assert ue['ua'] == 4
        assert ue['c1'] == 50.0
        # ARPC = 200/2 = 100, ARPU = 100 × 2/4 = 50
        assert ue['arpu'] == 50.0

    def test_same_client_won_and_lose_dedup(self, db, tc):
        """Тот же человек в WON (client.name) и LOSE (client_name, регистр/пробелы) — один UA."""
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id)
        make_lose(db, ' иВан ')
        ue = get_dash(tc).get_json()['dashboard']['unit_economics']
        assert ue['ua'] == 1
        assert ue['c1'] == 100.0

    def test_referrer_filter_gives_null(self, db, tc):
        """При фильтре по рефереру C1 не считаем — у LOSE нет referrer_id."""
        r = Referrer(name='Ref', code='GR-UA', token='t-ua')
        db.add(r); db.commit()
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id, referrer=r)
        make_lose(db, 'Олег')
        ue = get_dash(tc, referrer_id=r.id).get_json()['dashboard']['unit_economics']
        assert ue['ua'] is None
        assert ue['c1'] is None

    def test_lose_outside_period_ignored(self, db, tc):
        """LOSE вне диапазона дат не попадает в UA."""
        today = datetime.now()
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id)
        make_lose(db, 'Олег')
        make_lose(db, 'Старый', created_at=today - timedelta(days=90))
        ue = get_dash(tc).get_json()['dashboard']['unit_economics']
        assert ue['ua'] == 2
        assert ue['c1'] == 50.0


# ── Воронка по каналам ────────────────────────────────────────────────────

class TestChannels:

    def test_channels_aggregate_won_and_lose(self, db, tc):
        """Канал из source_channel: лиды = WON+LOSE, покупатели = WON, CR₂ = B/лиды."""
        c1_, c2_ = Client(name='Иван'), Client(name='Пётр')
        db.add_all([c1_, c2_]); db.commit()
        d1 = make_deal(db, client_id=c1_.id, profit=100)
        d1.source_channel = 'insta'
        d2 = make_deal(db, client_id=c2_.id, profit=50)
        d2.source_channel = 'site'
        db.commit()
        l = make_lose(db, 'Олег'); l.source_channel = 'insta'; db.commit()
        ch = {r['channel']: r for r in get_dash(tc).get_json()['dashboard']['channels']}
        assert ch['insta']['leads'] == 2
        assert ch['insta']['buyers'] == 1
        assert ch['insta']['cr_lead_buyer'] == 50.0
        assert ch['site']['leads'] == 1
        assert ch['site']['buyers'] == 1

    def test_channel_fallback_ref_and_unmarked(self, db, tc):
        """Без source_channel: рефские → 'ref:<имя>', остальные → 'без метки'."""
        c = Client(name='Иван'); db.add(c); db.commit()
        d = make_deal(db, client_id=c.id)
        d.referrer_name = 'GR-KARIM'
        db.commit()
        c2_ = Client(name='Пётр'); db.add(c2_); db.commit()
        make_deal(db, client_id=c2_.id)
        make_lose(db, 'Олег')  # LOSE без канала — «без метки»
        ch = {r['channel']: r for r in get_dash(tc).get_json()['dashboard']['channels']}
        assert 'ref:GR-KARIM' in ch
        assert ch['без метки']['leads'] == 2  # Пётр (WON) + Олег (LOSE)

    def test_new_buyers_split(self, db, tc):
        """Новые/повторные: первая сделка клиента в периоде → новый («Старые = Все − Новые»)."""
        today = datetime.now()
        c = Client(name='Иван'); db.add(c); db.commit()
        old = make_deal(db, client_id=c.id, created_at=today - timedelta(days=90))
        d = make_deal(db, client_id=c.id)
        d.source_channel = 'insta'
        db.commit()
        make_lose(db, 'Олег')
        ch = {r['channel']: r for r in get_dash(tc).get_json()['dashboard']['channels']}
        assert ch['insta']['buyers'] == 1
        assert ch['insta']['new_buyers'] == 0  # первая сделка Ивана 90 дней назад — повторный

    def test_channels_null_on_referrer_filter(self, db, tc):
        """При фильтре по рефереру блок каналов не считается."""
        r = Referrer(name='Ref', code='GR-CH', token='t-ch')
        db.add(r); db.commit()
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id, referrer=r)
        data = get_dash(tc, referrer_id=r.id).get_json()['dashboard']
        assert data['channels'] is None

    def test_source_channel_accepted_on_create(self, db, tc):
        """POST /api/deals принимает source_channel (WON и LOSE пути)."""
        res = tc.post('/api/deals', json={
            'client_name': 'Тест Канал', 'status': 'pending',
            'payin_method': 'crypto_direct', 'payin_amount_usdt': 1,
            'source_channel': 'insta',
        })
        assert res.get_json()['deal']['source_channel'] == 'insta'
        res2 = tc.post('/api/deals', json={
            'status': 'lose', 'deal_type': 'pay_in', 'client_name': 'Лося',
            'lose_reason': 'тест', 'bitrix_deal_id': 999001, 'source_channel': 'site',
        })
        assert res2.get_json()['deal']['source_channel'] == 'site'
