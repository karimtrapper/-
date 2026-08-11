"""Списание бат с карты (THB-счёта) при выдаче клиенту.

До этих правок карта умела только расти: пополнения увеличивали balance_thb,
а выдачи клиентам не отражались нигде — таблица card_allocations была
объявлена и не заполнялась. Себестоимость сделки считалась (по среднему курсу
закупки карты), но остаток врал начиная с первой же выдачи.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_card_allocations.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

from app import (BankCard, CardAllocation, CardTopup, CashBatchStatus, Deal,
                 DealStatus, app as flask_app, get_session, _card_avg_rate)


@pytest.fixture(autouse=True)
def clean_db():
    def _wipe():
        s = get_session()
        try:
            s.query(CardAllocation).delete()
            s.query(CardTopup).delete()
            s.query(Deal).delete()
            s.query(BankCard).delete()
            s.commit()
        finally:
            s.close()
    _wipe()
    yield
    _wipe()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def _mk_card(amount_thb=261466.06, cost_usdt=7800.0, bank='IPPS'):
    """Карта с одним пополнением — как заводится кошелёк IPPS."""
    s = get_session()
    try:
        card = BankCard(bank_name=bank, card_name='e-money VA 120111220002535',
                        holder_name='MF Corporation', balance_thb=0,
                        status=CashBatchStatus.ACTIVE)
        s.add(card)
        s.commit()
        s.add(CardTopup(card_id=card.id, amount_thb=amount_thb, cost_usdt=cost_usdt,
                        purchase_rate=amount_thb / cost_usdt, source_type='separate',
                        reference='IDTT260723564098'))
        card.balance_thb = amount_thb
        s.commit()
        return card.id
    finally:
        s.close()


def _balance(card_id):
    s = get_session()
    try:
        return s.query(BankCard).filter(BankCard.id == card_id).first().balance_thb
    finally:
        s.close()


def _avg_rate(card_id):
    s = get_session()
    try:
        return _card_avg_rate(s.query(BankCard).filter(BankCard.id == card_id).first())
    finally:
        s.close()


def _deal_payload(card_id, payout_thb, **over):
    payload = {
        'deal_type': 'pay_in', 'status': 'completed', 'client_name': 'Ольга П.',
        'payin_amount_usdt': 1000.0, 'payout_source': 'bank_card',
        'bank_card_id': card_id, 'payout_amount_thb': payout_thb,
        'payout_amount_usdt': round(payout_thb / 33.5213, 2),
        'skip_sync': True,
    }
    payload.update(over)
    return payload


# ── Средний курс закупки ─────────────────────────────────────────────────

def test_avg_rate_from_topups():
    """Курс карты = все заведённые баты / все потраченные USDT."""
    card_id = _mk_card()
    assert round(_avg_rate(card_id), 4) == 33.5213


def test_avg_rate_without_topups_is_zero():
    """Карта без пополнений не даёт курса — делить не на что."""
    s = get_session()
    try:
        card = BankCard(bank_name='Пустая', balance_thb=0, status=CashBatchStatus.ACTIVE)
        s.add(card)
        s.commit()
        assert _card_avg_rate(card) == 0
    finally:
        s.close()


# ── Списание при создании сделки ─────────────────────────────────────────

def test_deal_reduces_card_balance(client):
    card_id = _mk_card()
    r = client.post('/api/deals', json=_deal_payload(card_id, 30740.0))
    assert r.status_code == 201, r.get_json()

    assert _balance(card_id) == 230726.06  # 261466.06 − 30740

    s = get_session()
    try:
        alloc = s.query(CardAllocation).filter(CardAllocation.card_id == card_id).one()
        assert alloc.amount_thb == 30740.0
        assert alloc.card_rate == 33.5213
        assert alloc.cost_usdt == round(30740.0 / 33.5213, 2)
    finally:
        s.close()


def test_lose_deal_does_not_touch_card(client):
    """LOSE — сделка, которой не было: деньги с карты не уходили."""
    card_id = _mk_card()
    r = client.post('/api/deals', json=_deal_payload(card_id, 30740.0, status='lose'))
    assert r.status_code == 201
    assert _balance(card_id) == 261466.06


def test_other_payout_source_does_not_touch_card(client):
    """Выдали из кассы — карта ни при чём, даже если id прилетел в форме."""
    card_id = _mk_card()
    r = client.post('/api/deals', json=_deal_payload(card_id, 30740.0,
                                                     payout_source='cash_batch'))
    assert r.status_code == 201
    assert _balance(card_id) == 261466.06


def test_overdraft_returns_warning(client):
    """В минус пускаем — выдача уже состоялась — но предупреждаем."""
    card_id = _mk_card(amount_thb=10000.0, cost_usdt=300.0)
    r = client.post('/api/deals', json=_deal_payload(card_id, 30740.0))
    assert r.status_code == 201
    assert 'минус' in r.get_json().get('warning', '')
    assert _balance(card_id) == -20740.0


# ── Правки сделки ────────────────────────────────────────────────────────

def test_amount_change_rewrites_allocation(client):
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_deal_payload(card_id, 30740.0)).get_json()['deal']['id']

    r = client.put(f'/api/deals/{deal_id}', json={'payout_amount_thb': 12500.0})
    assert r.status_code == 200, r.get_json()

    assert _balance(card_id) == 248966.06  # 261466.06 − 12500
    s = get_session()
    try:
        assert s.query(CardAllocation).filter(CardAllocation.deal_id == deal_id).count() == 1
    finally:
        s.close()


def test_card_switch_returns_money_to_old_card(client):
    old_id = _mk_card()
    new_id = _mk_card(amount_thb=100000.0, cost_usdt=3000.0, bank='SCB')
    deal_id = client.post('/api/deals', json=_deal_payload(old_id, 30740.0)).get_json()['deal']['id']

    client.put(f'/api/deals/{deal_id}', json={'bank_card_id': new_id})

    assert _balance(old_id) == 261466.06
    assert _balance(new_id) == 69260.0


def test_moving_deal_to_lose_returns_money(client):
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_deal_payload(card_id, 30740.0)).get_json()['deal']['id']

    client.put(f'/api/deals/{deal_id}', json={'status': 'lose'})

    assert _balance(card_id) == 261466.06
    s = get_session()
    try:
        assert s.query(CardAllocation).filter(CardAllocation.deal_id == deal_id).count() == 0
    finally:
        s.close()


def test_empty_card_id_keeps_binding(client):
    """Карта с нулевым остатком выпадает из дропдауна, форма шлёт пустое поле —
    привязка и списание при этом сохраняются."""
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_deal_payload(card_id, 30740.0)).get_json()['deal']['id']

    client.put(f'/api/deals/{deal_id}', json={'bank_card_id': ''})

    assert _balance(card_id) == 230726.06
    s = get_session()
    try:
        assert s.query(Deal).get(deal_id).bank_card_id == card_id
    finally:
        s.close()


def test_repeated_save_does_not_double_charge(client):
    """Повторное сохранение той же сделки не списывает баты второй раз."""
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_deal_payload(card_id, 30740.0)).get_json()['deal']['id']

    for _ in range(3):
        client.put(f'/api/deals/{deal_id}', json={'client_name': 'Ольга Пеганова'})

    assert _balance(card_id) == 230726.06


# ── Удаление ─────────────────────────────────────────────────────────────

def test_delete_deal_returns_money(client):
    card_id = _mk_card()
    deal_id = client.post('/api/deals', json=_deal_payload(card_id, 30740.0)).get_json()['deal']['id']

    r = client.delete(f'/api/deals/{deal_id}')
    assert r.status_code == 200

    assert _balance(card_id) == 261466.06
    s = get_session()
    try:
        assert s.query(CardAllocation).filter(CardAllocation.deal_id == deal_id).count() == 0
    finally:
        s.close()


# ── История карты ────────────────────────────────────────────────────────

def test_history_shows_spending_and_reference(client):
    card_id = _mk_card()
    client.post('/api/deals', json=_deal_payload(card_id, 30740.0))

    data = client.get(f'/api/cards/{card_id}/history').get_json()
    assert data['topups'][0]['reference'] == 'IDTT260723564098'
    assert data['total_spent_thb'] == 30740.0
    assert data['allocations'][0]['client_name'] == 'Ольга П.'


# ── Ручное списание (движения мимо клиентов) ─────────────────────────────

def test_adjust_reduces_balance_keeping_rate(client):
    """Тестовый перевод 10 000 ฿ ушёл со счёта — остаток падает,
    средний курс закупки остаётся прежним."""
    card_id = _mk_card()
    r = client.post(f'/api/cards/{card_id}/adjust',
                    json={'amount_thb': 10000, 'reason': 'Тестовый платёж 30.07'})
    assert r.status_code == 200, r.get_json()

    assert _balance(card_id) == 251466.06
    assert round(_avg_rate(card_id), 4) == 33.5213


def test_adjust_by_target_balance(client):
    """Можно задать не сумму списания, а желаемый остаток."""
    card_id = _mk_card()
    client.post(f'/api/cards/{card_id}/adjust', json={'new_balance_thb': 200974.06})
    assert _balance(card_id) == 200974.06


def test_adjust_requires_amount(client):
    card_id = _mk_card()
    r = client.post(f'/api/cards/{card_id}/adjust', json={'amount_thb': 0})
    assert r.status_code == 400
    assert _balance(card_id) == 261466.06


def test_adjust_shows_in_history(client):
    card_id = _mk_card()
    client.post(f'/api/cards/{card_id}/adjust',
                json={'amount_thb': 10000, 'reason': 'Тестовый платёж 30.07'})

    data = client.get(f'/api/cards/{card_id}/history').get_json()
    adj = [t for t in data['topups'] if t['source_type'] == 'adjustment']
    assert len(adj) == 1
    assert adj[0]['amount_thb'] == -10000
    assert adj[0]['notes'] == 'Тестовый платёж 30.07'


def test_topup_saves_reference(client):
    card_id = _mk_card(amount_thb=1.0, cost_usdt=1.0)
    r = client.post(f'/api/cards/{card_id}/topup', json={
        'amount_thb': 261466.06, 'cost_usdt': 7800.0,
        'source_type': 'separate', 'reference': 'IDTT260723564098',
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['topup']['reference'] == 'IDTT260723564098'
