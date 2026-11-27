"""Превью «Итог сделки» в задачнике: считает теми же функциями, что сохранение в CRM."""
import secrets

import app as m
import pytest

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _client(monkeypatch, role='manager'):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    db = m.get_session()
    try:
        user = m.AdminUser(username='pv-' + secrets.token_hex(6), display_name='PV',
                           role=role, password_hash='unused')
        db.add(user)
        db.commit()
        uid = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _exchange(**over):
    crm = {'deal_kind': 'exchange', 'client_name': 'Preview', 'manager_name': 'Елизавета',
           'payin_method': 'sber_reqs', 'payin_amount_usdt': 1000, 'payout_method': 'transfer',
           'payout_source': 'cash_batch', 'payout_amount_usdt': 900, 'agents': []}
    crm.update(over)
    return crm


def test_preview_exchange_profit_without_agents(monkeypatch):
    client = _client(monkeypatch)
    r = client.post('/api/stand/crm-preview', json={'crm': _exchange()})
    j = r.get_json()
    assert r.status_code == 200 and j['success'] is True
    assert j['profit_usdt'] == 100
    assert j['profit_percent'] == pytest.approx(11.11, abs=0.01)
    assert j['net_profit_usdt'] == 100
    assert j['agents'] == []


def test_preview_agent_cascade_matches_crm_formula(monkeypatch):
    client = _client(monkeypatch)
    agents = [{'name': 'Агент', 'tier': 1, 'comp_model': 'revshare', 'percent': 10},
              {'name': 'Выше', 'tier': 2, 'comp_model': 'revshare', 'percent': 10}]
    j = client.post('/api/stand/crm-preview', json={'crm': _exchange(agents=agents)}).get_json()
    # ур.1 — 10 % от прибыли 100; ур.2 — 10 % от остатка базы 100 − 10 (каскад compute_agent_cascade)
    assert [a['payout_usdt'] for a in j['agents']] == [10.0, 9.0]
    assert j['referrer_payout_usdt'] == 19.0
    assert j['net_profit_usdt'] == 81.0


def test_preview_agent_change_recomputes_immediately(monkeypatch):
    client = _client(monkeypatch)
    one = [{'name': 'А', 'tier': 1, 'comp_model': 'revshare', 'percent': 10}]
    two = [{'name': 'А', 'tier': 1, 'comp_model': 'revshare', 'percent': 25}]
    first = client.post('/api/stand/crm-preview', json={'crm': _exchange(agents=one)}).get_json()
    second = client.post('/api/stand/crm-preview', json={'crm': _exchange(agents=two)}).get_json()
    assert first['net_profit_usdt'] == 90.0
    assert second['net_profit_usdt'] == 75.0


def test_preview_writes_nothing(monkeypatch):
    client = _client(monkeypatch)
    before = m.get_session().query(m.Deal).count()
    client.post('/api/stand/crm-preview', json={'crm': _exchange()})
    db = m.get_session()
    try:
        assert db.query(m.Deal).count() == before
    finally:
        db.close()


def test_preview_forbidden_for_operator(monkeypatch):
    client = _client(monkeypatch, role='operator')
    r = client.post('/api/stand/crm-preview', json={'crm': _exchange()})
    assert r.status_code == 403


def test_preview_rejects_bad_payload(monkeypatch):
    client = _client(monkeypatch)
    r = client.post('/api/stand/crm-preview', json={'crm': 'x'})
    assert r.status_code == 400
