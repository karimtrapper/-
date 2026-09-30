"""QA независимая проверка коммита 31dfecf (wallet-registry).
Не является частью функционального пакета автора — отдельный ревью-набор.
"""
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
        for role in ('manager', 'operator', 'findir', 'teodor', 'admin'):
            user = m.AdminUser(username='qar_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user)
            db.flush()
            users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None):
        state = {'deals': [{'id': 9535, 'code': 'QAR-T35', 'client': 'Synthetic',
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


def _with_step(state, destination):
    proposed = copy.deepcopy(state)
    proposed['deals'][0]['step'] = destination
    return proposed


# 1. multisig custom deal: teodor role cannot perform s23->s24
def test_qa_multisig_custom_teodor_cannot_advance(board):
    install, client_for = board
    install('s23', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'Q' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    teodor = client_for('teodor')
    before = teodor.get('/api/stand/state').json
    resp = teodor.put('/api/stand/state', json={
        'version': before['version'], 'data': _with_step(before['data'], 's24')})
    assert resp.status_code in (403, 409), resp.json
    findir = client_for('findir')
    before2 = findir.get('/api/stand/state').json
    resp2 = findir.put('/api/stand/state', json={
        'version': before2['version'], 'data': _with_step(before2['data'], 's24')})
    assert resp2.status_code == 200, resp2.json


# 2. personal Теодор deal: s23 goes to teodor, no findir step (findir denied)
def test_qa_personal_teodor_deal_no_findir_step(board):
    install, client_for = board
    install('s23', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'R' * 33,
                        'owner': 'Теодор', 'multisig': False},
    })
    findir = client_for('findir')
    before = findir.get('/api/stand/state').json
    resp = findir.put('/api/stand/state', json={
        'version': before['version'], 'data': _with_step(before['data'], 's24')})
    assert resp.status_code in (403, 409), resp.json
    teodor = client_for('teodor')
    before2 = teodor.get('/api/stand/state').json
    resp2 = teodor.put('/api/stand/state', json={
        'version': before2['version'], 'data': _with_step(before2['data'], 's24')})
    assert resp2.status_code == 200, resp2.json


# 3. manager PUT changing payinCustom.multisig after s11 (docPack set) is rejected
def test_qa_manager_cannot_flip_multisig_after_lock(board):
    install, client_for = board
    install('s11', {
        'walletId': 'custom', 'payType': 'Крипта', 'docPack': True,
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'S' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['payinCustom']['multisig'] = False
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json


def test_qa_manager_cannot_flip_multisig_after_step_advanced(board):
    install, client_for = board
    install('s12', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'U' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['payinCustom']['multisig'] = False
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json


# 4. legacy grusha deal still requires findir at s23
def test_qa_legacy_grusha_wallet_requires_findir(board):
    install, client_for = board
    install('s23', {'cnvId': 1}, {
        'convs': [{'id': 1, 'walletId': 'grusha', 'sources': [], 'txs': []}],
        'wallets': [],
    })
    teodor = client_for('teodor')
    before = teodor.get('/api/stand/state').json
    resp = teodor.put('/api/stand/state', json={
        'version': before['version'], 'data': _with_step(before['data'], 's24')})
    assert resp.status_code in (403, 409), resp.json
    findir = client_for('findir')
    before2 = findir.get('/api/stand/state').json
    resp2 = findir.put('/api/stand/state', json={
        'version': before2['version'], 'data': _with_step(before2['data'], 's24')})
    assert resp2.status_code == 200, resp2.json
