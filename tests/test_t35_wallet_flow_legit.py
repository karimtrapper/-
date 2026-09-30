"""Легитимные флоу поверх da674e1 — не должны быть задеты фиксом на conv.walletId.
Фикстуры взяты по образцу tests/test_t29_step_role.py (_broker_state/_broker_proposal)."""
import copy
import json
import secrets

import pytest

import app as m


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    m._stand_migrate()
    users = {}
    db = m.get_session()
    try:
        for role in ('operator', 'findir', 'teodor', 'admin'):
            user = m.AdminUser(username='qarleg_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user); db.flush(); users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None, deal_id=1474):
        state = {'deals': [{'id': deal_id, 'code': 'QARLEG-T35', 'client': 'Synthetic',
                            'type': 'Обмен валюты', 'step': step, 'log': [],
                            **(extra or {})}],
                 'convs': [], 'wallets': [], 'incomes': [], 'notes': []}
        state.update(state_extra or {})
        db = m.get_session()
        try:
            row = m._stand_row(db)
            row.data = json.dumps(state, ensure_ascii=False)
            row.version = (row.version or 0) + 1
            db.commit()
        finally:
            db.close()
        return copy.deepcopy(state)

    def client(role):
        test_client = m.app.test_client()
        with test_client.session_transaction() as sess:
            sess['user_id'] = users[role]
            sess['role'] = 'operator' if role == 'manager' else 'manager'
        return test_client

    return install, client


def _only_step(state, destination):
    proposed = copy.deepcopy(state)
    proposed['deals'][0]['step'] = destination
    return proposed


# 1. s18: штатный выбор кошелька пачки без смены шага
def test_legit_s18_wallet_choice(board):
    install, client_for = board
    install('s18', {'cnvId': 1, 'walletId': 'grusha', 'payType': 'По реквизитам'}, {
        'convs': [{'id': 1, 'walletId': 'grusha', 'sources': [], 'txs': []}],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['convs'][0]['walletId'] = 'teodor'
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code == 200, resp.json


def _broker_state(install):
    return install('s18', {
        'incomeAmount': 10000, 'payinParts': [{'incId': 1, 'amountRub': 10000}],
        'rates': {}, 'conv': [],
    }, {
        'incomes': [{'id': 1, 'dealId': 1474, 'rub': 10000, 'demo': True}],
        'wallets': [{'id': 'grusha', 'role': 'findir', 'multisig': True,
                     'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}],
    })


def _broker_proposal(state, wallet_id='grusha'):
    proposed = _only_step(state, 's18w')
    deal = proposed['deals'][0]
    deal.update(cnvId=1, walletId=wallet_id, demoTransfers=True)
    deal['rates']['broker'] = '100'
    proposed['convs'] = [{
        'id': 1, 'broker': 'Tradex', 'requestNo': '41', 'rate': '100',
        'status': 'sent', 'at': '29.09, 02:59', 'sentTs': 1790640000000,
        'walletId': wallet_id, 'rubTotal': 10000, 'held': 70, 'sent': 9930,
        'feePct': .3, 'feeFix': 40, 'feeCtrl': 50, 'feeOurs': 20,
        'feeCtrlPct': .1, 'feeOursPct': .2,
        'sources': [{'dealId': 1474, 'rub': 10000, 'usdt': 99.30}], 'txs': [],
    }]
    return proposed


# 2. s18 -> s18w: новая пачка создаётся и шаг двигается в одном PUT — штатно
def test_legit_s18_to_s18w_broker_handoff_new_pack(board):
    install, client_for = board
    _broker_state(install)
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _broker_proposal(before['data'])})
    assert resp.status_code == 200, resp.json
    saved = resp.json['data']
    assert saved['deals'][0]['step'] == 's18w'
    assert saved['convs'][0]['walletId'] == 'grusha'


# 3. Личный кошелёк пачки (не мультисиг) на s18->s18w — тоже должен пройти
def test_legit_s18_to_s18w_personal_wallet(board):
    install, client_for = board
    _broker_state(install)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        state['wallets'] = [{'id': 'teodor', 'role': 'teodor', 'multisig': False,
                             'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'}]
        row.data = json.dumps(state, ensure_ascii=False)
        row.version += 1
        db.commit()
    finally:
        db.close()
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _broker_proposal(before['data'], wallet_id='teodor')})
    assert resp.status_code == 200, resp.json


# 4. Крипто-сделка s22: прямой outbound через deal.walletId без conv (как в
#    tests/test_stand_transfers.py::test_erc_outbound_route_stops_at_s22) — не
#    трогает pack-гейт вовсе, должен продолжать работать штатно (up to s23
#    ограничен только ERC-маршрутом, TRC проходит).
def test_legit_crypto_s22_to_s23_direct_wallet_no_conv(board):
    install, client_for = board
    install('s22', {'walletId': 'teodor', 'payType': 'Крипта'}, {
        'wallets': [{'id': 'teodor', 'role': 'teodor', 'multisig': False,
                     'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'}],
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's23')})
    assert resp.status_code == 200, resp.json
