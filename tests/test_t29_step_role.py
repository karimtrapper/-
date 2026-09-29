"""Authenticated stand PUT regressions for step ownership and broker handoff."""
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
            user = m.AdminUser(username='t29_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user)
            db.flush()
            users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None):
        state = {'deals': [{'id': 1474, 'code': 'SYNTH-T29', 'client': 'Synthetic',
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


def _persisted():
    db = m.get_session()
    try:
        row = m._stand_row(db)
        return (row.version, row.data, row.notified,
                db.query(m.Deal).count(), db.query(m.StandCrmLink).count())
    finally:
        db.close()


def test_manager_cannot_advance_operator_s18_and_nothing_changes(board):
    install, client_for = board
    install('s18')
    manager = client_for('manager')
    before = manager.get('/api/stand/state').json
    persisted = _persisted()
    rejected = manager.put('/api/stand/state', json={
        'version': before['version'], 'role': 'operator',
        'data': _only_step(before['data'], 's18w')})
    assert rejected.status_code in (403, 409), rejected.json
    assert manager.get('/api/stand/state').json == before
    assert _persisted() == persisted
    with_requisites = _only_step(before['data'], 's18w')
    with_requisites['deals'][0]['payTo'] = {'acc': 'synthetic'}
    with_requisites['deals'][0]['log'] = [{'text': 'requisites only'}]
    rejected = manager.put('/api/stand/state', json={
        'version': before['version'], 'data': with_requisites})
    assert rejected.status_code in (403, 409), rejected.json
    assert _persisted() == persisted


def test_operator_cannot_skip_broker_conversion_facts(board):
    install, client_for = board
    install('s18')
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    persisted = _persisted()
    rejected = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's18w')})
    assert rejected.status_code in (403, 409), rejected.json
    assert operator.get('/api/stand/state').json == before
    assert _persisted() == persisted


@pytest.mark.parametrize('step,destination,wrong_role,owner', [
    ('s5', 's6', 'manager', 'operator'),
    ('s11', 's12', 'manager', 'operator'),
    ('s14', 's15', 'operator', 'manager'),
    ('s18', 's18w', 'manager', 'operator'),
    ('s18w', 's22', 'manager', 'operator'),
    ('s22', 's23', 'manager', 'operator'),
    ('s24', 's25', 'operator', 'teodor'),
    ('s25', 's26', 'manager', 'operator'),
    ('s27', 'done', 'operator', 'manager'),
])
def test_step_change_uses_authenticated_current_owner(board, step, destination,
                                                       wrong_role, owner):
    install, client_for = board
    install(step)
    client = client_for(wrong_role)
    before = client.get('/api/stand/state').json
    persisted = _persisted()
    response = client.put('/api/stand/state', json={
        'version': before['version'], 'role': owner,
        'data': _only_step(before['data'], destination)})
    assert response.status_code in (403, 409), response.json
    assert owner in response.json['error']
    assert _persisted() == persisted


@pytest.mark.parametrize('step,destination,owner', [
    ('s5', 's6', 'operator'), ('s6', 's8', 'manager'),
])
def test_lawful_owner_can_handoff_to_next_roles_step(board, step, destination, owner):
    install, client_for = board
    install(step)
    client = client_for(owner)
    before = client.get('/api/stand/state').json
    response = client.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], destination)})
    assert response.status_code == 200, response.json
    assert response.json['data']['deals'][0]['step'] == destination
    assert response.json['version'] == before['version'] + 1


def test_personal_wallet_signer_owns_s23(board):
    install, client_for = board
    install('s23', {'cnvId': 1}, {
        'convs': [{'id': 1, 'walletId': 'teodor', 'sources': [], 'txs': []}],
        'wallets': [{'id': 'teodor', 'role': 'teodor', 'multisig': False,
                     'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'}],
    })
    wrong = client_for('findir')
    before = wrong.get('/api/stand/state').json
    persisted = _persisted()
    denied = wrong.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert denied.status_code in (403, 409), denied.json
    assert _persisted() == persisted
    signer = client_for('teodor')
    allowed = signer.put('/api/stand/state', json={
        'version': before['version'], 'data': _only_step(before['data'], 's24')})
    assert allowed.status_code == 200, allowed.json


def _broker_state(install):
    return install('s18', {
        'incomeAmount': 10000, 'payinParts': [{'incId': 1, 'amountRub': 10000}],
        'rates': {}, 'conv': [],
    }, {
        'incomes': [{'id': 1, 'dealId': 1474, 'rub': 10000, 'demo': True}],
        'wallets': [{'id': 'grusha', 'role': 'findir', 'multisig': True,
                     'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}],
    })


def _broker_proposal(state):
    proposed = _only_step(state, 's18w')
    deal = proposed['deals'][0]
    deal.update(cnvId=1, walletId='grusha', demoTransfers=True)
    deal['rates']['broker'] = '100'
    proposed['convs'] = [{
        'id': 1, 'broker': 'Tradex', 'requestNo': '41', 'rate': '100',
        'status': 'sent', 'at': '29.09, 02:59', 'sentTs': 1790640000000,
        'walletId': 'grusha', 'rubTotal': 10000, 'held': 70, 'sent': 9930,
        'feePct': .3, 'feeFix': 40, 'feeCtrl': 50, 'feeOurs': 20,
        'feeCtrlPct': .1, 'feeOursPct': .2,
        'sources': [{'dealId': 1474, 'rub': 10000, 'usdt': 99.30}], 'txs': [],
    }]
    return proposed


def test_operator_broker_send_with_registered_sources_and_wallet_succeeds(board):
    install, client_for = board
    _broker_state(install)
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    response = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': _broker_proposal(before['data'])})
    assert response.status_code == 200, response.json
    saved = response.json['data']
    assert saved['deals'][0]['step'] == 's18w'
    assert saved['deals'][0]['cnvId'] == saved['convs'][0]['id']
    assert saved['convs'][0]['status'] == 'sent'


@pytest.mark.parametrize('broken', [
    'missing_conv', 'missing_wallet', 'missing_source', 'empty_broker',
    'bare_status', 'bad_fee', 'bad_rate', 'reused_conv', 'malformed_members',
    'unfunded', 'bad_wallet_role', 'bad_wallet_net', 'negative_timestamp',
])
def test_broker_handoff_needs_complete_linked_facts(board, broken):
    install, client_for = board
    _broker_state(install)
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = _broker_proposal(before['data'])
    conv = proposed['convs'][0]
    if broken == 'missing_conv':
        proposed['convs'] = []
    elif broken == 'missing_wallet':
        conv['walletId'] = 'unknown'
    elif broken == 'missing_source':
        conv['sources'] = []
    elif broken == 'empty_broker':
        conv['broker'] = ''
    elif broken == 'bare_status':
        proposed['convs'][0] = {'id': 1, 'status': 'sent', 'sources': conv['sources']}
    elif broken == 'bad_fee':
        conv['sent'] = 10000
    elif broken == 'bad_rate':
        conv['rate'] = '0'
    elif broken == 'reused_conv':
        state = copy.deepcopy(before['data'])
        state['convs'] = [copy.deepcopy(conv)]
        install('s18', state['deals'][0], {'convs': state['convs'],
                'wallets': state['wallets'], 'incomes': state['incomes']})
        before = operator.get('/api/stand/state').json
        proposed = _broker_proposal(before['data'])
    elif broken == 'malformed_members':
        proposed['deals'][0]['conv'] = [{'id': 1475}]
    elif broken == 'unfunded':
        proposed['deals'][0]['payinParts'] = []
    elif broken == 'bad_wallet_role':
        proposed['wallets'][0]['role'] = 'manager'
        install('s18', before['data']['deals'][0], {
            'wallets': proposed['wallets'], 'incomes': before['data']['incomes']})
        before = operator.get('/api/stand/state').json
        proposed = _broker_proposal(before['data'])
    elif broken == 'bad_wallet_net':
        proposed['wallets'][0]['net'] = 'ERC20'
        install('s18', before['data']['deals'][0], {
            'wallets': proposed['wallets'], 'incomes': before['data']['incomes']})
        before = operator.get('/api/stand/state').json
        proposed = _broker_proposal(before['data'])
    elif broken == 'negative_timestamp':
        conv['sentTs'] = -1
    persisted = _persisted()
    denied = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': proposed})
    assert denied.status_code in (403, 409), (broken, denied.json)
    assert _persisted() == persisted
