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

from app import (app, get_session, Referrer, Client, Deal, DealType, DealStatus,
                 AdminUser, DealAgent, PayOutSource)


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


# ── Фильтр по направлению (deal_kind) ─────────────────────────────────────

class TestDealKindFilter:

    @pytest.fixture
    def mixed_kinds(self, db):
        """Обычный обмен + лизхолд + фрихолд в одном периоде."""
        make_deal(db, profit=30)  # deal_kind NULL — обычный обмен
        lease = make_deal(db, profit=50, payin=2000)
        lease.deal_kind = 'mf_realty'
        lease.company_fee_thb = 33000.0
        lease.company_fee_usdt = 1000.0
        lease.crypto_remainder_usdt = 50.0
        lease.net_profit_usdt = 1050.0  # крипта + комиссия компании
        fh = make_deal(db, profit=200, payin=5000)
        fh.deal_kind = 'mf_freehold'
        db.commit()

    def test_exchange_only(self, tc, mixed_kinds):
        p = get_dash(tc, period='30d', deal_kind='exchange').get_json()['dashboard']['period']
        assert p['deals_count'] == 1
        assert p['profit_usdt'] == 30
        assert p['realty_fee_thb'] == 0

    def test_mf_realty_only(self, tc, mixed_kinds):
        p = get_dash(tc, period='30d', deal_kind='mf_realty').get_json()['dashboard']['period']
        assert p['deals_count'] == 1
        assert p['profit_usdt'] == 1050
        assert p['realty_fee_thb'] == 33000
        assert p['realty_fee_usdt'] == 1000
        # В USDT-кармане только остаток кошелька — без батов компании
        assert p['profit_wallet_usdt'] == 50

    def test_realty_combines_both_kinds(self, tc, mixed_kinds):
        p = get_dash(tc, period='30d', deal_kind='realty').get_json()['dashboard']['period']
        assert p['deals_count'] == 2
        assert p['profit_usdt'] == 1250

    def test_all_includes_everything_with_thb_pocket(self, tc, mixed_kinds):
        p = get_dash(tc, period='30d').get_json()['dashboard']['period']
        assert p['deals_count'] == 3
        # Батовый карман виден и без фильтра — иначе кажется, что всё в крипте
        assert p['realty_fee_thb'] == 33000
        assert p['profit_wallet_usdt'] == round(p['profit_usdt'] - 1000, 2)

    def test_invalid_kind_returns_400(self, tc, mixed_kinds):
        assert get_dash(tc, period='30d', deal_kind='bogus').status_code == 400

    def test_объём_и_себестоимость_разнесены_на_недвижимость_и_обмены(
            self, tc, mixed_kinds):
        """Транзит по недвижимости не должен топить обменную ногу: месяц с одной
        сделкой на застройщика иначе читается как «прогнали много, заработали
        копейки»."""
        p = get_dash(tc, period='30d').get_json()['dashboard']['period']
        assert p['realty_deals_count'] == 2
        assert p['exchange_deals_count'] == 1
        assert p['volume_realty_usdt'] == 7000     # лизхолд 2000 + фрихолд 5000
        assert p['volume_exchange_usdt'] == 1000
        assert p['cost_realty_usdt'] == 6750       # 1950 + 4800
        assert p['cost_exchange_usdt'] == 970
        # Разрез сходится с итогом, иначе цифры в шапке спорят друг с другом
        assert p['volume_realty_usdt'] + p['volume_exchange_usdt'] == p['volume_usdt']
        assert p['cost_realty_usdt'] + p['cost_exchange_usdt'] == p['cost_usdt']


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


# ── Маржа в разрезах ──────────────────────────────────────────────────────

class TestMargins:
    """Блок margins: среднее по сделкам против доли от объёма, срез по рефералам.

    Запрос Карима: «мне нужен инструмент, где я почти всё вижу — сколько маржи
    закладываем, сколько реально забираем, сколько с реферала и сколько без».
    Одна плитка «ср. маржа» отвечала только на первый вопрос и делала это молча.
    """

    def test_среднее_по_сделкам_не_равно_доле_от_объёма(self, db, tc):
        """Невзвешенное среднее задирает маржу: мелкая сделка весит как крупная."""
        make_deal(db, profit=50, payin=500)        # 10% на $500
        make_deal(db, profit=2000, payin=200000)   # 1% на $200 000
        m = get_dash(tc, period='30d').get_json()['dashboard']['margins']['all']
        assert m['avg_margin_deal'] == 5.5                       # (10 + 1) / 2
        assert m['margin_gross'] == 1.02                         # 2050 / 200500
        assert m['volume_usdt'] == 200500
        assert m['gross_profit_usdt'] == 2050

    def test_убыточная_сделка_попадает_в_среднее(self, db, tc):
        """Старая плитка avg_margin режет всё, что <= 0, и показывает only-профит."""
        make_deal(db, profit=100, payin=1000)      # +10%
        make_deal(db, profit=-100, payin=1000)     # −10%
        d = get_dash(tc, period='30d').get_json()['dashboard']
        assert d['margins']['all']['avg_margin_deal'] == 0.0     # (10 − 10) / 2
        assert d['margins']['all']['loss_deals'] == 1
        assert d['margins']['all']['rated_deals'] == 2
        assert d['period']['avg_margin'] == 10.0                 # легаси-плитка: только плюс

    def test_срез_с_рефералом_и_без(self, db, tc):
        """Партнёрский поток отдельно от своего — видно, во что обходятся выплаты."""
        r = Referrer(name='Eduard', code='GR-ED9', token='tm1')
        db.add(r); db.commit()
        d1 = make_deal(db, referrer=r, profit=200, payin=2000)
        d1.net_profit_usdt = 100.0                  # 100 ушло рефереру
        make_deal(db, profit=300, payin=1000)       # своя сделка
        db.commit()
        m = get_dash(tc, period='30d').get_json()['dashboard']['margins']
        assert m['with_referrer']['deals'] == 1
        assert m['with_referrer']['margin_gross'] == 10.0        # 200 / 2000
        assert m['with_referrer']['margin_net'] == 5.0           # 100 / 2000
        assert m['with_referrer']['referrer_payout_usdt'] == 100
        assert m['own']['deals'] == 1
        assert m['own']['margin_gross'] == 30.0                  # выплат нет
        assert m['own']['margin_net'] == 30.0
        assert m['all']['profit_per_deal'] == 200.0              # (100 + 300) / 2

    def test_уровни_рефералов_считаются_врозь(self, db, tc):
        """Второй уровень — не реферал: он в доле от выплаты, клиента не приводил.

        Пока обе роли лежали в одной цифре, «уникальных рефералов» показывало
        больше, чем людей, реально приносящих сделки.
        """
        r1 = Referrer(name='Eduard', code='GR-ED8', token='tm2')
        r2 = Referrer(name='Malik', code='GR-ML8', token='tm3')
        db.add_all([r1, r2]); db.commit()
        d1 = make_deal(db, referrer=r1, profit=100, payin=1000)
        db.add(DealAgent(deal_id=d1.id, referrer_id=r1.id, name='Eduard', tier=1,
                         comp_model='revshare', percent=50, payout_usdt=50))
        db.add(DealAgent(deal_id=d1.id, referrer_id=r2.id, name='Malik', tier=2,
                         comp_model='revshare', percent=10, payout_usdt=10))
        make_deal(db, referrer=r1, profit=50, payin=500)   # тот же реферер — не дубль
        make_deal(db, profit=20, payin=200)                # своя сделка
        db.commit()
        m = get_dash(tc, period='30d').get_json()['dashboard']['margins']
        assert m['unique_referrers'] == 1          # только Eduard привёл сделки
        assert m['unique_agents_l2'] == 1          # Malik сидит в доле
        assert m['with_referrer']['deals'] == 2

    def test_пустой_период_без_деления_на_ноль(self, tc):
        m = get_dash(tc, period='today').get_json()['dashboard']['margins']
        assert m['all']['deals'] == 0
        assert m['all']['margin_gross'] is None
        assert m['all']['avg_margin_deal'] is None
        assert m['unique_referrers'] == 0
        assert m['unique_agents_l2'] == 0


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


# ── Сходимость таблицы (цифры должны биться друг с другом) ────────────────

class TestUnitEconConsistency:
    """Инварианты строки Красинского. Ловили: COGS без агентских выплат,
    B по client_id в шапке против имени в каналах, клиент в двух каналах."""

    def test_cogs_includes_agent_payout(self, db, tc):
        """AvP − COGS == маржа со сделки: COGS = закупка + выплата агенту."""
        r = Referrer(name='Ref', code='GR-CS', token='t-cs')
        db.add(r); db.commit()
        c = Client(name='Иван'); db.add(c); db.commit()
        d = make_deal(db, client_id=c.id, referrer=r, profit=100, payin=1000)
        d.net_profit_usdt = 50.0  # gross 100, агенту 50
        db.commit()
        ue = get_dash(tc).get_json()['dashboard']['unit_economics']
        assert ue['avp'] == 1000
        assert ue['cogs_per_deal'] == 950        # 900 закупка + 50 агенту
        assert ue['profit_per_deal'] == 50
        assert round(ue['avp'] - ue['cogs_per_deal'], 2) == ue['profit_per_deal']
        assert round(ue['avp'] * ue['orders'], 2) == ue['revenue']
        assert round(ue['arpc'] * ue['buyers'], 2) == ue['cm']

    def test_buyer_without_client_id_counted(self, db, tc):
        """Сделка без карточки клиента — тоже покупатель; по имени сливается с client_id."""
        c = Client(name='Иван'); db.add(c); db.commit()
        make_deal(db, client_id=c.id, profit=100)
        d = make_deal(db, profit=50)          # без client_id, но тот же человек
        d.client_name = ' иВан '
        db.commit()
        d2 = make_deal(db, profit=30)         # без client_id, другой человек
        d2.client_name = 'Олег'
        db.commit()
        dash = get_dash(tc).get_json()['dashboard']
        assert dash['unit_economics']['buyers'] == 2   # Иван (2 сделки) + Олег
        assert dash['unit_economics']['orders'] == 3
        assert dash['charts']['buyers']['total'] == 2

    def test_channel_sums_match_totals(self, db, tc):
        """Клиент со сделками в двух каналах не задваивается: сумма по каналам = итог."""
        today = datetime.now()
        c = Client(name='Анна'); db.add(c); db.commit()
        d1 = make_deal(db, client_id=c.id, profit=100, created_at=today - timedelta(days=5))
        d1.source_channel = 'insta'
        d2 = make_deal(db, client_id=c.id, profit=50, created_at=today - timedelta(days=2))
        d2.source_channel = 'site'
        db.commit()
        make_lose(db, 'Олег')
        dash = get_dash(tc).get_json()['dashboard']
        ue, chans = dash['unit_economics'], dash['channels']
        assert sum(r['leads'] for r in chans) == ue['ua']      # 2: Анна + Олег
        assert sum(r['buyers'] for r in chans) == ue['buyers']  # 1: Анна
        assert sum(r['deals'] for r in chans) == ue['orders']
        ch = {r['channel']: r for r in chans}
        assert ch['insta']['buyers'] == 1   # первое касание Анны
        assert ch['site']['buyers'] == 0
        assert ch['site']['deals'] == 1     # сделки — по метке самой сделки


# ── Баннер «ожидают возмещения» ───────────────────────────────────────────

class TestAttentionUnreimbursed:
    """Баннер считает долгом только то, что реально надо вернуть фаундеру."""

    def make_founder_deal(self, db, needs_reimb=True, founder='Андрей', payout_usdt=500.0):
        d = make_deal(db, profit=50)
        d.payout_source = PayOutSource.FOUNDER_PERSONAL
        d.payout_founder_name = founder
        d.needs_reimbursement = needs_reimb
        d.payout_amount_usdt = payout_usdt
        db.commit()
        return d

    def test_deal_without_debt_not_counted(self, db, tc):
        """needs_reimbursement=False — возвращать нечего, в баннер не идёт."""
        self.make_founder_deal(db, needs_reimb=True, payout_usdt=100)
        self.make_founder_deal(db, needs_reimb=False, payout_usdt=500000)
        att = get_dash(tc).get_json()['dashboard']['attention']
        assert att['unreimbursed_founders'] == 1
        assert att['unreimbursed_total_usdt'] == 100

    def test_deal_without_founder_not_counted(self, db, tc):
        """Без имени фаундера возмещать некому — как в /api/reimbursements/pending."""
        self.make_founder_deal(db, founder=None, payout_usdt=300)
        att = get_dash(tc).get_json()['dashboard']['attention']
        assert att['unreimbursed_founders'] == 0
        assert att['unreimbursed_total_usdt'] == 0

    def test_banner_matches_pending_endpoint(self, db, tc):
        """Цифра баннера сходится со списком, который открывается по клику."""
        self.make_founder_deal(db, needs_reimb=True, founder='Андрей', payout_usdt=100)
        self.make_founder_deal(db, needs_reimb=True, founder='Теодор', payout_usdt=200)
        self.make_founder_deal(db, needs_reimb=False, founder='Андрей', payout_usdt=9999)
        att = get_dash(tc).get_json()['dashboard']['attention']
        pending = tc.get('/api/reimbursements/pending').get_json()['by_founder']
        assert att['unreimbursed_founders'] == sum(len(f['deals']) for f in pending) == 2
