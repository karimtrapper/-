"""
Тесты LOSE-сделок, revive-логики и /api/analytics/conversion.

Спека: docs/specs/2026-07-20-lose-conversion.md
Запуск: cd Dev/CalcCRM && python -m pytest tests/test_lose_conversion.py -v
"""
import pytest
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'

from app import app, get_session, Client, Deal, DealType, DealStatus, AdminUser, DealAgent


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


def _post_lose(tc, name='Иван', bitrix_id=101, reason='не устроил курс'):
    return tc.post('/api/deals', json={
        'status': 'lose', 'deal_type': 'pay_in', 'client_name': name,
        'lose_reason': reason, 'bitrix_deal_id': bitrix_id,
    })


def _post_won(tc, name='Иван', profit=100.0):
    return tc.post('/api/deals', json={
        'status': 'completed', 'deal_type': 'pay_in', 'client_name': name,
        'payin_amount_usdt': 1000.0, 'profit_usdt': profit, 'skip_sync': True,
    })


# ── Создание LOSE ─────────────────────────────────────────────────────────

def test_create_lose_deal(tc, db):
    """LOSE создаётся со статусом lose, причиной и bitrix_deal_id."""
    r = _post_lose(tc)
    assert r.status_code == 201
    deal = r.get_json()['deal']
    assert deal['status'] == 'lose'
    assert deal['lose_reason'] == 'не устроил курс'
    assert deal['bitrix_deal_id'] == 101


def test_lose_idempotent_by_bitrix_id(tc, db):
    """Повторный POST с тем же bitrix_deal_id не создаёт дубль."""
    r1 = _post_lose(tc, bitrix_id=202)
    r2 = _post_lose(tc, bitrix_id=202)
    assert r2.status_code == 200
    assert r2.get_json().get('duplicate') is True
    assert r1.get_json()['deal']['id'] == r2.get_json()['deal']['id']
    assert db.query(Deal).filter(Deal.status == DealStatus.LOSE).count() == 1


def test_lose_does_not_create_client(tc, db):
    """LOSE не создаёт нового клиента (не замусоривает базу непокупателями)."""
    _post_lose(tc, name='Новичок')
    assert db.query(Client).filter(Client.name.ilike('Новичок')).count() == 0


def test_lose_links_existing_client(tc, db):
    """Если клиент уже есть — LOSE привязывается к нему."""
    _post_won(tc, name='Старый')
    r = _post_lose(tc, name='Старый', bitrix_id=303)
    deal = r.get_json()['deal']
    client = db.query(Client).filter(Client.name.ilike('Старый')).first()
    assert deal['client_id'] == client.id


# ── Изоляция от денежных выборок ──────────────────────────────────────────

def test_lose_hidden_from_default_deals_list(tc, db):
    """LOSE не попадает в основной список сделок, виден по ?status=lose."""
    _post_lose(tc)
    _post_won(tc, name='Пётр')
    default = tc.get('/api/deals').get_json()['deals']
    assert all(d['status'] != 'lose' for d in default)
    lose_only = tc.get('/api/deals?status=lose').get_json()['deals']
    assert len(lose_only) == 1
    with_lose = tc.get('/api/deals?include_lose=1').get_json()['deals']
    assert len(with_lose) == 2


def test_lose_not_in_dashboard_analytics(tc, db):
    """LOSE не влияет на деньги/сделки в /api/analytics/dashboard."""
    _post_won(tc, name='Пётр', profit=100.0)
    before = tc.get('/api/analytics/dashboard?period=30d').get_json()['dashboard']['period']
    _post_lose(tc)
    after = tc.get('/api/analytics/dashboard?period=30d').get_json()['dashboard']['period']
    assert before['deals_count'] == after['deals_count']
    assert before['profit_usdt'] == after['profit_usdt']


def test_lose_not_in_reimbursements(tc, db):
    """LOSE не появляется в ожидающих возмещения."""
    _post_lose(tc)
    pending = tc.get('/api/reimbursements/pending').get_json()
    deals = pending.get('deals', pending.get('pending', []))
    assert all(d.get('status') != 'lose' for d in deals)


# ── Revive ────────────────────────────────────────────────────────────────

def test_lose_candidates_by_name(tc, db):
    """Кандидаты ищутся по имени без регистра, только непривязанные."""
    _post_lose(tc, name='Иван', bitrix_id=1)
    _post_lose(tc, name='Иван', bitrix_id=2)
    _post_lose(tc, name='Мария', bitrix_id=3)
    r = tc.get('/api/deals/lose-candidates?client_name=иван')
    cands = r.get_json()['candidates']
    assert len(cands) == 2


def test_revive_links_loses_to_won(tc, db):
    """Revive привязывает LOSE к WON; кандидаты исчезают из выдачи."""
    l1 = _post_lose(tc, bitrix_id=1).get_json()['deal']['id']
    l2 = _post_lose(tc, bitrix_id=2).get_json()['deal']['id']
    won_id = _post_won(tc).get_json()['deal']['id']
    r = tc.post(f'/api/deals/{won_id}/revive', json={'lose_ids': [l1, l2]})
    assert r.get_json()['success'] is True
    assert sorted(r.get_json()['revived']) == sorted([l1, l2])
    cands = tc.get('/api/deals/lose-candidates?client_name=Иван').get_json()['candidates']
    assert cands == []


def test_revive_validations(tc, db):
    """Нельзя: привязать не-LOSE, привязать к lose-сделке, перепривязать чужой LOSE."""
    lose_id = _post_lose(tc, bitrix_id=1).get_json()['deal']['id']
    other_lose = _post_lose(tc, bitrix_id=2).get_json()['deal']['id']
    won1 = _post_won(tc).get_json()['deal']['id']
    won2 = _post_won(tc, name='Пётр').get_json()['deal']['id']
    # не-LOSE в lose_ids
    assert tc.post(f'/api/deals/{won1}/revive', json={'lose_ids': [won2]}).status_code == 400
    # привязка к lose-сделке
    assert tc.post(f'/api/deals/{other_lose}/revive', json={'lose_ids': [lose_id]}).status_code == 400
    # перепривязка уже забранного
    tc.post(f'/api/deals/{won1}/revive', json={'lose_ids': [lose_id]})
    assert tc.post(f'/api/deals/{won2}/revive', json={'lose_ids': [lose_id]}).status_code == 400


def test_unrevive(tc, db):
    """Unrevive отвязывает LOSE обратно."""
    lose_id = _post_lose(tc, bitrix_id=1).get_json()['deal']['id']
    won_id = _post_won(tc).get_json()['deal']['id']
    tc.post(f'/api/deals/{won_id}/revive', json={'lose_ids': [lose_id]})
    r = tc.post(f'/api/deals/{won_id}/unrevive', json={})
    assert r.get_json()['unrevived'] == 1
    cands = tc.get('/api/deals/lose-candidates?client_name=Иван').get_json()['candidates']
    assert len(cands) == 1


def test_delete_won_unlinks_loses(tc, db):
    """Удаление WON отвязывает revive-привязанные LOSE (не блокируется FK)."""
    lose_id = _post_lose(tc, bitrix_id=1).get_json()['deal']['id']
    won_id = _post_won(tc).get_json()['deal']['id']
    tc.post(f'/api/deals/{won_id}/revive', json={'lose_ids': [lose_id]})
    assert tc.delete(f'/api/deals/{won_id}').get_json()['success'] is True
    lose = db.query(Deal).get(lose_id)
    assert lose.revived_by_deal_id is None


def test_status_change_from_lose_clears_revive(tc, db):
    """LOSE, переведённый вручную в completed, выходит из revive-привязки."""
    lose_id = _post_lose(tc, bitrix_id=1).get_json()['deal']['id']
    won_id = _post_won(tc).get_json()['deal']['id']
    tc.post(f'/api/deals/{won_id}/revive', json={'lose_ids': [lose_id]})
    tc.put(f'/api/deals/{lose_id}', json={'status': 'pending'})
    lose = db.query(Deal).get(lose_id)
    assert lose.revived_by_deal_id is None


# ── Конверсия ─────────────────────────────────────────────────────────────

def test_conversion_math(tc, db):
    """Сценарий: Иван 2×LOSE→WON (revive), Мария LOSE (потеряна), Пётр WON чистый.
    CR новых = 2/3 (Иван и Пётр won, Мария lost). Касания Ивана = 3."""
    l1 = _post_lose(tc, name='Иван', bitrix_id=1).get_json()['deal']['id']
    l2 = _post_lose(tc, name='Иван', bitrix_id=2).get_json()['deal']['id']
    won = _post_won(tc, name='Иван').get_json()['deal']['id']
    tc.post(f'/api/deals/{won}/revive', json={'lose_ids': [l1, l2]})
    _post_lose(tc, name='Мария', bitrix_id=3)
    _post_won(tc, name='Пётр')

    data = tc.get('/api/analytics/conversion?months=12').get_json()
    t = data['totals']
    assert t['new']['total'] == 3
    assert t['new']['won'] == 2
    assert t['new']['cr'] == 66.7
    assert t['lost_episodes'] == 1
    # Иван: 3 касания, Пётр: 1 → среднее по won-эпизодам месяца = 2
    m = data['months'][-1]
    assert m['avg_touches_to_won'] == 2.0
    # lose_list: Мария потеряна, Иван×2 — «ожили»
    revived = [l for l in data['lose_list'] if l['revived_by_deal_id']]
    lost = [l for l in data['lose_list'] if not l['revived_by_deal_id']]
    assert len(revived) == 2 and len(lost) == 1


def test_conversion_repeat_client(tc, db):
    """LOSE повторного клиента (уже покупал) идёт в CR повторных, не портит CR новых."""
    # Иван купил месяц назад
    s = get_session()
    old = Deal(deal_type=DealType('pay_in'), status=DealStatus.COMPLETED,
               client_name='Иван', payin_amount_usdt=500.0, profit_usdt=50.0,
               created_at=datetime.now() - timedelta(days=40))
    s.add(old); s.commit(); s.close()
    # Сейчас пришёл снова и слился
    _post_lose(tc, name='Иван', bitrix_id=1)

    data = tc.get('/api/analytics/conversion?months=12').get_json()
    t = data['totals']
    assert t['repeat']['total'] == 1
    assert t['repeat']['won'] == 0
    # Новых эпизодов в этом сценарии: старая победа Ивана (эпизод новый, won)
    assert t['new']['won'] == 1
    assert t['new']['total'] == 1


def test_conversion_cohort_first_touch(tc, db):
    """Когорта — месяц ПЕРВОГО касания: LOSE в прошлом месяце + WON сейчас
    с revive → эпизод падает в месяц LOSE."""
    s = get_session()
    prev_month = (datetime.now().replace(day=1) - timedelta(days=1)).replace(day=15)
    old_lose = Deal(deal_type=DealType('pay_in'), status=DealStatus.LOSE,
                    client_name='Иван', lose_reason='думал', created_at=prev_month)
    s.add(old_lose); s.commit()
    lose_id = old_lose.id
    s.close()

    won = _post_won(tc, name='Иван').get_json()['deal']['id']
    tc.post(f'/api/deals/{won}/revive', json={'lose_ids': [lose_id]})

    data = tc.get('/api/analytics/conversion?months=12').get_json()
    cohort_key = prev_month.strftime('%Y-%m')
    row = next(m for m in data['months'] if m['month'] == cohort_key)
    assert row['new_won'] == 1  # эпизод учтён в месяце первого касания
    current_key = datetime.now().strftime('%Y-%m')
    current = [m for m in data['months'] if m['month'] == current_key]
    assert not current or current[0]['new_total'] == 0
