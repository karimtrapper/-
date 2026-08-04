"""
Тесты реферальной системы CalcCRM.
Покрывает: модель Referrer, CRUD, авто-заполнение, авто-расчёт payout,
привязка клиента, нормализованный поиск кода, выплата, публичный stats API.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_referral.py -v
"""
import pytest
import sys
import os
import secrets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import app, get_session, Referrer, Client, Deal, DealType, DealStatus, AdminUser, DealAgent

import bcrypt


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Чистим таблицы перед каждым тестом."""
    session = get_session()
    try:
        session.query(DealAgent).delete()
        session.query(Deal).delete()
        session.query(Client).delete()
        session.query(Referrer).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = get_session()
    try:
        session.query(DealAgent).delete()
        session.query(Deal).delete()
        session.query(Client).delete()
        session.query(Referrer).delete()
        session.commit()
    finally:
        session.close()


@pytest.fixture
def db():
    session = get_session()
    yield session
    session.close()


@pytest.fixture
def referrer(db):
    """Тестовый реферер."""
    r = Referrer(
        name='Ed', code='GR-ED', token=secrets.token_hex(16),
        default_percent=10.0, telegram='@ed_test', payout_currency='USDT',
    )
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def client_with_referrer(db, referrer):
    """Клиент, привязанный к рефереру."""
    c = Client(name='Test Client', referrer_id=referrer.id)
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def tc():
    """Flask test client с авторизацией."""
    app.config['TESTING'] = True
    # check_auth ревалидирует сессию по БД → нужен реально существующий админ
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


# ── Модель Referrer ───────────────────────────────────────────────────────

class TestReferrerModel:
    """Тесты модели Referrer."""

    def test_create_referrer(self, db):
        r = Referrer(name='Test', code='GR-TEST', token='abc123', default_percent=50.0)
        db.add(r)
        db.commit()
        assert r.id is not None
        assert r.active is True

    def test_to_dict_contains_links(self, referrer):
        d = referrer.to_dict()
        assert d['referral_link'] == 'https://grusha.space/?ref=GR-ED'
        assert d['bot_link'] == 'https://t.me/Grushath_bot?start=ref__GRED'
        assert 'wa_link' in d
        assert 'ref_GRED' in d['wa_link']

    def test_to_dict_pending_calculation(self, db):
        r = Referrer(name='X', code='GR-X', token='xxx', total_earned_usdt=100, total_paid_usdt=30)
        db.add(r)
        db.commit()
        assert r.to_dict()['pending_usdt'] == 70.0

    def test_payout_currency_default(self, referrer):
        assert referrer.payout_currency == 'USDT'

    def test_code_with_dash_generates_clean_bot_link(self, referrer):
        """GR-ED в bot_link становится GRED (TG start не поддерживает дефис)."""
        assert 'GRED' in referrer.to_dict()['bot_link']
        assert '-' not in referrer.to_dict()['bot_link'].split('start=')[1]


# ── Client-Referrer привязка ─────────────────────────────────────────────

class TestClientReferrerBinding:
    """Привязка клиента к рефереру (lifetime)."""

    def test_client_referrer_id(self, client_with_referrer, referrer):
        assert client_with_referrer.referrer_id == referrer.id

    def test_client_to_dict_includes_referrer(self, client_with_referrer):
        d = client_with_referrer.to_dict()
        assert d['referrer_id'] is not None
        assert d['referrer_name'] == 'Ed'

    def test_referrer_has_referred_clients(self, referrer, client_with_referrer, db):
        db.refresh(referrer)
        assert len(referrer.referred_clients) == 1


# ── CRUD API ─────────────────────────────────────────────────────────────

class TestReferrerCRUD:
    """CRUD эндпоинты /api/referrers."""

    def test_create_referrer_api(self, tc):
        resp = tc.post('/api/referrers', json={
            'name': 'API Test', 'default_percent': 30, 'telegram': '@api',
        })
        assert resp.json['success']
        r = resp.json['referrer']
        assert r['name'] == 'API Test'
        assert r['default_percent'] == 30.0
        assert r['code'].startswith('GR-')
        assert len(r['token']) == 32

    def test_create_referrer_custom_code(self, tc):
        resp = tc.post('/api/referrers', json={
            'name': 'Custom', 'code': 'GR-CUSTOM',
        })
        assert resp.json['referrer']['code'] == 'GR-CUSTOM'

    def test_create_referrer_duplicate_code(self, tc, referrer):
        resp = tc.post('/api/referrers', json={
            'name': 'Dup', 'code': 'GR-ED',
        })
        assert not resp.json['success']
        assert resp.status_code == 400

    def test_create_referrer_empty_name(self, tc):
        resp = tc.post('/api/referrers', json={'name': ''})
        assert not resp.json['success']

    def test_list_referrers(self, tc, referrer):
        resp = tc.get('/api/referrers')
        assert resp.json['success']
        assert len(resp.json['referrers']) == 1

    def test_update_referrer(self, tc, referrer):
        resp = tc.put(f'/api/referrers/{referrer.id}', json={
            'default_percent': 50, 'payout_currency': 'THB',
        })
        assert resp.json['referrer']['default_percent'] == 50.0
        assert resp.json['referrer']['payout_currency'] == 'THB'

    def test_update_payout_currency_invalid(self, tc, referrer):
        resp = tc.put(f'/api/referrers/{referrer.id}', json={
            'payout_currency': 'BTC',
        })
        # BTC не в списке допустимых → остаётся USDT
        assert resp.json['referrer']['payout_currency'] == 'USDT'

    def test_delete_referrer_soft(self, tc, referrer):
        resp = tc.delete(f'/api/referrers/{referrer.id}')
        assert resp.json['success']
        # Мягкое удаление — active=False
        resp2 = tc.get('/api/referrers')
        assert any(r['id'] == referrer.id and not r['active'] for r in resp2.json['referrers'])


# ── Нормализованный поиск кода ───────────────────────────────────────────

class TestCodeNormalization:
    """Поиск реферера по коду: GR-ED = GRED (для TG start-параметра)."""

    def test_lookup_exact(self, tc, referrer):
        resp = tc.get('/api/referrers/lookup?code=GR-ED')
        assert resp.json['success']
        assert resp.json['referrer']['code'] == 'GR-ED'

    def test_lookup_normalized_no_dash(self, tc, referrer):
        resp = tc.get('/api/referrers/lookup?code=GRED')
        assert resp.json['success']
        assert resp.json['referrer']['code'] == 'GR-ED'

    def test_lookup_case_insensitive(self, tc, referrer):
        resp = tc.get('/api/referrers/lookup?code=gr-ed')
        assert resp.json['success']

    def test_lookup_not_found(self, tc):
        resp = tc.get('/api/referrers/lookup?code=GR-NONEXISTENT')
        assert not resp.json['success']
        assert resp.status_code == 404


# ── Привязка клиента к рефереру через API ────────────────────────────────

class TestSetClientReferrer:
    """POST /api/clients/<id>/set-referrer."""

    def test_set_referrer_by_code(self, tc, referrer, db):
        c = Client(name='New Client')
        db.add(c)
        db.commit()
        resp = tc.post(f'/api/clients/{c.id}/set-referrer', json={'code': 'GR-ED'})
        assert resp.json['success']
        assert resp.json['client']['referrer_id'] == referrer.id

    def test_set_referrer_normalized_code(self, tc, referrer, db):
        """GRED (без дефиса) тоже работает."""
        c = Client(name='New Client 2')
        db.add(c)
        db.commit()
        resp = tc.post(f'/api/clients/{c.id}/set-referrer', json={'code': 'GRED'})
        assert resp.json['success']

    def test_set_referrer_duplicate_rejected(self, tc, referrer, db):
        """Клиент не может сменить реферера (lifetime)."""
        c = Client(name='Bound Client', referrer_id=referrer.id)
        db.add(c)
        r2 = Referrer(name='Other', code='GR-OTHER', token='other123', default_percent=5)
        db.add(r2)
        db.commit()
        resp = tc.post(f'/api/clients/{c.id}/set-referrer', json={'code': 'GR-OTHER'})
        assert not resp.json['success']
        assert resp.status_code == 400

    def test_set_referrer_increments_count(self, tc, referrer, db):
        c = Client(name='Counter Client')
        db.add(c)
        db.commit()
        resp = tc.post(f'/api/clients/{c.id}/set-referrer', json={'code': 'GR-ED'})
        assert resp.json['referrer']['total_referred_clients'] >= 1


# ── Авто-заполнение реферера при создании сделки ─────────────────────────

class TestAutoPopulateReferrer:
    """Если у клиента есть referrer_id → сделка автоматически получает referrer."""

    def test_auto_populate_from_client(self, tc, client_with_referrer, referrer):
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 500,
            'payout_amount_usdt': 485,
            'payout_method': 'transfer',
        })
        deal = resp.json['deal']
        assert deal['referrer_name'] == 'Ed'
        assert deal['referrer_percent'] == 10.0
        assert deal['referrer_id'] == referrer.id

    def test_manual_referrer_not_overwritten(self, tc, client_with_referrer):
        """Если referrer_name явно указан — авто-подстановка не перезаписывает."""
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 100,
            'payout_amount_usdt': 97,
            'payout_method': 'transfer',
            'referrer_name': 'Manual Override',
            'referrer_percent': 99,
        })
        deal = resp.json['deal']
        assert deal['referrer_name'] == 'Manual Override'
        assert deal['referrer_percent'] == 99

    def test_no_referrer_for_unbound_client(self, tc, db):
        c = Client(name='Free Client')
        db.add(c)
        db.commit()
        resp = tc.post('/api/deals', json={
            'client_id': c.id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 100,
            'payout_amount_usdt': 97,
            'payout_method': 'transfer',
        })
        deal = resp.json['deal']
        assert deal['referrer_name'] is None
        assert deal['referrer_id'] is None


# ── Резолв реферального кода в referrer_id при создании сделки ───────────

class TestReferrerCodeResolution:
    """DealCloser шлёт referrer_name='GR-XXX' — код должен стать профилем.

    Баг до 2026-08-04: код оставался текстом, referrer_id=None → сделка не
    попадала в кабинет реферера и не начисляла выплату (кейс insight Estate
    «GR-INSIGH (вручную)»).
    """

    def _deal(self, tc, client_id, **extra):
        payload = {
            'client_id': client_id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000,
            'payout_amount_usdt': 970,
            'payout_method': 'transfer',
        }
        payload.update(extra)
        return tc.post('/api/deals', json=payload).json['deal']

    def test_code_resolved_to_profile(self, tc, referrer, db):
        c = Client(name='Client By Code')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-ED')
        assert deal['referrer_id'] == referrer.id
        assert deal['referrer_name'] == 'Ed'
        assert deal['referrer_percent'] == 10.0

    def test_code_normalized(self, tc, referrer, db):
        """GRED (из TG start-параметра, без дефиса) находит GR-ED."""
        c = Client(name='Client Normalized')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GRED')
        assert deal['referrer_id'] == referrer.id
        assert deal['referrer_name'] == 'Ed'

    def test_code_lowercase_resolved(self, tc, referrer, db):
        c = Client(name='Client Lower')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='gr-ed')
        assert deal['referrer_id'] == referrer.id

    def test_unknown_code_stays_text(self, tc, db):
        """Незарегистрированный код (кейс GR-KARIM) — остаётся пометкой без id."""
        c = Client(name='Client Phantom')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-KARIM')
        assert deal['referrer_id'] is None
        assert deal['referrer_name'] == 'GR-KARIM'

    def test_plain_name_not_resolved(self, tc, db):
        """Свободное имя не код — не ищем и не перезаписываем."""
        c = Client(name='Client Manual')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='Manual Override', referrer_percent=99)
        assert deal['referrer_id'] is None
        assert deal['referrer_name'] == 'Manual Override'
        assert deal['referrer_percent'] == 99

    def test_explicit_percent_wins(self, tc, referrer, db):
        """Явный процент не затирается дефолтом профиля."""
        c = Client(name='Client Pct')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-ED', referrer_percent=25)
        assert deal['referrer_id'] == referrer.id
        assert deal['referrer_percent'] == 25

    def test_inactive_referrer_not_resolved(self, tc, db):
        r = Referrer(name='Off', code='GR-OFF', token=secrets.token_hex(16),
                     default_percent=10.0, active=False)
        db.add(r); db.commit()
        c = Client(name='Client Inactive')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-OFF')
        assert deal['referrer_id'] is None
        assert deal['referrer_name'] == 'GR-OFF'

    def test_self_referral_code_ignored(self, tc, db):
        """Клиент = реферер → код не линкуем (защита от самореферала)."""
        c = Client(name='Self Ref')
        db.add(c); db.commit()
        r = Referrer(name='Self', code='GR-SELF', token=secrets.token_hex(16),
                     default_percent=10.0, client_id=c.id)
        db.add(r); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-SELF')
        assert deal['referrer_id'] is None

    def test_lose_deal_not_linked(self, tc, referrer, db):
        """LOSE-сделка реферера не получает (не начисляем за непокупку)."""
        c = Client(name='Client Lose')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-ED', status='lose')
        assert deal['referrer_id'] is None

    def test_resolved_code_creates_deal_agent(self, tc, referrer, db):
        """Главное следствие: строка в deal_agents → сделка видна в кабинете."""
        c = Client(name='Client Agent Row')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_name='GR-ED')
        rows = db.query(DealAgent).filter(DealAgent.deal_id == deal['id']).all()
        assert len(rows) == 1
        assert rows[0].referrer_id == referrer.id

    def test_referrer_id_without_name_takes_profile_name(self, tc, referrer, db):
        """Скрипт шлёт только referrer_id — имя берём из профиля, не NULL."""
        c = Client(name='Client Id Only')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_id=referrer.id)
        assert deal['referrer_id'] == referrer.id
        assert deal['referrer_name'] == 'Ed'

    def test_agents_without_name_keep_partner_visible(self, tc, referrer, db):
        """PUT agents без name не должен затирать referrer_name в NULL.

        Грабля 04.08: партнёр пропадал из колонки списка сделок после правки
        сделки скриптом (форма CRM имя шлёт всегда, интеграции — нет).
        """
        c = Client(name='Client Agents')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id)
        resp = tc.put(f"/api/deals/{deal['id']}", json={
            'agents': [{'referrer_id': referrer.id, 'tier': 1,
                        'comp_model': 'revshare', 'percent': 10}],
        })
        updated = resp.json['deal']
        assert updated['referrer_id'] == referrer.id
        assert updated['referrer_name'] == 'Ed'
        rows = db.query(DealAgent).filter(DealAgent.deal_id == deal['id']).all()
        assert [r.name for r in rows] == ['Ed']

    def test_explicit_referrer_id_wins_over_code(self, tc, referrer, db):
        other = Referrer(name='Other', code='GR-OTHR', token=secrets.token_hex(16),
                         default_percent=5.0)
        db.add(other); db.commit()
        c = Client(name='Client Both')
        db.add(c); db.commit()
        deal = self._deal(tc, c.id, referrer_id=other.id, referrer_name='GR-ED')
        assert deal['referrer_id'] == other.id


# ── Авто-расчёт referrer_payout_usdt ─────────────────────────────────────

class TestAutoReferrerPayout:
    """referrer_payout_usdt = profit × percent / 100 при пересчёте прибыли."""

    def test_payout_calculated_on_completion(self, tc, client_with_referrer):
        # Создаём сделку
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000,
            'payout_amount_usdt': 970,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']

        # Завершаем
        resp2 = tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})
        deal = resp2.json['deal']
        # profit = 1000 - 970 = 30, referrer_payout = 30 * 10% = 3.0
        assert deal['profit_usdt'] == 30.0
        assert deal['referrer_payout_usdt'] == 3.0
        assert deal['net_profit_usdt'] == 27.0  # 30 - 3

    def test_manual_payout_not_overwritten(self, tc, client_with_referrer):
        """Если referrer_payout_usdt передан явно — не перезаписывается формулой."""
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id,
            'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000,
            'payout_amount_usdt': 970,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']

        resp2 = tc.put(f'/api/deals/{deal_id}', json={
            'status': 'completed', 'referrer_payout_usdt': 5.0,
        })
        deal = resp2.json['deal']
        assert deal['referrer_payout_usdt'] == 5.0  # не 3.0
        assert deal['net_profit_usdt'] == 25.0  # 30 - 5

    def test_payout_zero_when_no_percent(self, tc, db):
        """Без referrer_percent payout не считается."""
        c = Client(name='No Ref')
        db.add(c)
        db.commit()
        resp = tc.post('/api/deals', json={
            'client_id': c.id, 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 1000, 'payout_amount_usdt': 970,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']
        resp2 = tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})
        assert resp2.json['deal']['referrer_payout_usdt'] is None


# ── Выплата рефереру ─────────────────────────────────────────────────────

class TestPayReferrer:
    """POST /api/referrers/<id>/pay — выплата всех неоплаченных сделок."""

    def _create_completed_deal(self, tc, client_id, payin=500, payout=485):
        resp = tc.post('/api/deals', json={
            'client_id': client_id, 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': payin, 'payout_amount_usdt': payout,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']
        tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})
        return deal_id

    def test_pay_marks_deals_as_paid(self, tc, client_with_referrer, referrer):
        self._create_completed_deal(tc, client_with_referrer.id)
        resp = tc.post(f'/api/referrers/{referrer.id}/pay')
        assert resp.json['success']
        assert resp.json['deals_paid'] == 1
        assert resp.json['amount_usdt'] > 0

    def test_pay_twice_no_double_payout(self, tc, client_with_referrer, referrer):
        self._create_completed_deal(tc, client_with_referrer.id)
        tc.post(f'/api/referrers/{referrer.id}/pay')
        # Второй раз — 0 сделок
        resp2 = tc.post(f'/api/referrers/{referrer.id}/pay')
        assert resp2.json['deals_paid'] == 0
        assert resp2.json['amount_usdt'] == 0

    def test_pay_multiple_deals(self, tc, client_with_referrer, referrer):
        self._create_completed_deal(tc, client_with_referrer.id, 500, 485)
        self._create_completed_deal(tc, client_with_referrer.id, 1000, 970)
        resp = tc.post(f'/api/referrers/{referrer.id}/pay')
        assert resp.json['deals_paid'] == 2
        # profit1 = 15 * 10% = 1.5, profit2 = 30 * 10% = 3.0
        assert resp.json['amount_usdt'] == 4.5


class TestMultiAgentAPI:
    """Мультиагенты через реальный API создания сделки (каскад)."""

    def test_create_deal_with_cascade_agents(self, tc, db):
        # Два агента-реферала
        a1 = Referrer(name='Иван', code='GR-IVAN', token=secrets.token_hex(8), default_percent=20)
        a2 = Referrer(name='Николай', code='GR-NIK2', token=secrets.token_hex(8), default_percent=50)
        c = Client(name='Maksim Multi')
        db.add_all([a1, a2, c]); db.commit()
        a1_id, a2_id, cid = a1.id, a2.id, c.id

        resp = tc.post('/api/deals', json={
            'client_id': cid, 'deal_type': 'pay_in', 'is_custom': True,
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 58409.06, 'payout_amount_usdt': 55615.91,
            'payout_method': 'transfer',
            'profit_usdt': 2793.15,
            'agents': [
                {'referrer_id': a1_id, 'name': 'Иван', 'tier': 1, 'comp_model': 'revshare', 'percent': 20},
                {'referrer_id': a2_id, 'name': 'Николай', 'tier': 2, 'comp_model': 'revshare', 'percent': 50},
            ],
        })
        assert resp.status_code in (200, 201)
        deal = resp.json['deal']
        agents = sorted(deal['agents'], key=lambda x: x['tier'])
        assert len(agents) == 2
        assert agents[0]['payout_usdt'] == 558.63          # 20% × 2793.15
        assert agents[1]['payout_usdt'] == 1117.26         # 50% × (2793.15 − 558.63)
        assert agents[1]['base_usdt'] == 2234.52
        assert deal['net_profit_usdt'] == 1117.26
        # Кэш ур.1 = первый агент
        assert deal['referrer_id'] == a1_id
        # Суммарная выплата агентам в кэше
        assert deal['referrer_payout_usdt'] == 1675.89     # 558.63 + 1117.26


# ── Публичный Stats API ──────────────────────────────────────────────────

class TestPublicStats:
    """/api/ref/<token>/stats — без авторизации."""

    def test_stats_without_auth(self, referrer):
        """Публичный эндпоинт, не требует логина."""
        with app.test_client() as tc:
            resp = tc.get(f'/api/ref/{referrer.token}/stats')
            assert resp.json['success']
            assert resp.json['name'] == 'Ed'

    def test_stats_invalid_token(self):
        with app.test_client() as tc:
            resp = tc.get('/api/ref/nonexistent/stats')
            assert not resp.json['success']

    def test_stats_shows_deals(self, tc, client_with_referrer, referrer):
        # Создаём и завершаем сделку
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id, 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 500, 'payout_amount_usdt': 485,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']
        tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})

        # Проверяем публичный stats
        with app.test_client() as pub:
            stats = pub.get(f'/api/ref/{referrer.token}/stats').json
            assert stats['total_deals'] == 1
            assert stats['total_earned_usdt'] == 1.5  # 15 * 10%
            assert len(stats['recent_deals']) == 1
            assert stats['recent_deals'][0]['commission_usdt'] == 1.5

    def test_stats_pending_after_pay(self, tc, client_with_referrer, referrer):
        resp = tc.post('/api/deals', json={
            'client_id': client_with_referrer.id, 'deal_type': 'pay_in',
            'payin_method': 'crypto_direct',
            'payin_amount_usdt': 500, 'payout_amount_usdt': 485,
            'payout_method': 'transfer',
        })
        deal_id = resp.json['deal']['id']
        tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})
        # Выплачиваем
        tc.post(f'/api/referrers/{referrer.id}/pay')

        with app.test_client() as pub:
            stats = pub.get(f'/api/ref/{referrer.token}/stats').json
            assert stats['pending_usdt'] == 0
            assert stats['total_paid_usdt'] == 1.5
            assert stats['recent_deals'][0]['paid'] is True

    def test_stats_contains_links(self, referrer):
        with app.test_client() as tc:
            stats = tc.get(f'/api/ref/{referrer.token}/stats').json
            assert 'grusha.space/?ref=GR-ED' in stats['referral_link']
            assert 'ref__GRED' in stats['bot_link']
            assert 'wa_link' in stats

    def test_stats_referred_clients_count(self, tc, referrer, db):
        # Два клиента привязаны
        c1 = Client(name='C1', referrer_id=referrer.id)
        c2 = Client(name='C2', referrer_id=referrer.id)
        db.add_all([c1, c2])
        db.commit()

        with app.test_client() as pub:
            stats = pub.get(f'/api/ref/{referrer.token}/stats').json
            assert stats['total_referred_clients'] == 2


# ── Регрессия: возмещение синхронизирует deal_agents с net (кейс 367) ──────

class TestReimbursementRefreshesAgents:
    """Сделка с THB-выплатой через личные фаундера: payout_usdt появляется
    только при возмещении. Строки deal_agents (источник TG-уведомления) должны
    пересчитываться вместе с net, иначе уведомление показывает payout=$0 при
    ненулевой выплате агенту (баг сделки 367)."""

    def test_agent_payout_matches_net_after_reimbursement(self, tc, db):
        # реферер 20% revshare, привязан к клиенту
        r = Referrer(name='Диана', code='GR-DIANA', token=secrets.token_hex(16),
                     default_percent=20.0, comp_model='revshare', payout_currency='USDT')
        db.add(r); db.commit()
        c = Client(name='Сергей', referrer_id=r.id)
        db.add(c); db.commit()

        # сделка THB через личные фаундера: payout USDT ещё неизвестен → 0
        resp = tc.post('/api/deals', json={
            'client_id': c.id, 'deal_type': 'pay_in',
            'payin_method': 'partners_cash', 'payin_amount_usdt': 5245,
            'payout_method': 'transfer', 'payout_source': 'founder_personal',
            'payout_amount_thb': 165000, 'status': 'pending',
        })
        deal_id = resp.json['deal']['id']
        # на этом этапе выплата агенту ещё 0 (прибыль неизвестна)
        agent0 = db.query(DealAgent).filter(DealAgent.deal_id == deal_id).first()
        assert (agent0.payout_usdt or 0) == 0

        # возмещение: фаундеру вернули $5048 → прибыль $197, агенту 20% = $39.40
        resp = tc.post('/api/reimbursements', json={
            'founder_name': 'Андрей', 'deal_ids': [deal_id], 'amount_usdt': 5048,
            'tx_hash': 'e7272240619d2faaebaa',
        })
        assert resp.json['success'] is True

        db.expire_all()
        deal = db.query(Deal).get(deal_id)
        agent = db.query(DealAgent).filter(DealAgent.deal_id == deal_id).first()
        # ключевая инварианта: строка агента и net считаны из ОДНОГО расчёта
        assert deal.profit_usdt == 197.0
        assert agent.payout_usdt == 39.40
        assert deal.net_profit_usdt == 157.60
        assert round(deal.profit_usdt - agent.payout_usdt, 2) == deal.net_profit_usdt
