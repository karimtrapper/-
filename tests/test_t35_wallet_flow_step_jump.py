import copy, json, secrets
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
            user = m.AdminUser(username='qarj_' + role + '_' + secrets.token_hex(4),
                               role=role, password_hash='synthetic-disabled')
            db.add(user); db.flush(); users[role] = user.id
        db.commit()
    finally:
        db.close()

    def install(step, extra=None, state_extra=None):
        state = {'deals': [{'id': 9635, 'code': 'QARJ-T35', 'client': 'Synthetic',
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


def test_qa_operator_cannot_jump_s11_to_s23_while_flipping_multisig(board):
    install, client_for = board
    install('s11', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'Z' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['deals'][0]['payinCustom']['multisig'] = False
    resp = operator.put('/api/stand/state', json={
        'version': before['version'], 'data': proposed})
    print('STATUS', resp.status_code, resp.json)
    assert resp.status_code in (403, 409), resp.json


def test_jump_with_multisig_flip_is_rejected_and_deal_unchanged(board):
    """Прыжок s11->s23 с подменой multisig true->false отклоняется, сделка остаётся
    на s11 с мультисигом — шаг фин дира не выпадает (QA 30.09)."""
    install, client_for = board
    install('s11', {
        'walletId': 'custom', 'payType': 'Крипта',
        'payinCustom': {'network': 'TRC-20', 'addr': 'T' + 'Y' * 33,
                        'owner': 'компания', 'multisig': True},
    })
    operator = client_for('operator')
    before = operator.get('/api/stand/state').json
    proposed = copy.deepcopy(before['data'])
    proposed['deals'][0]['step'] = 's23'
    proposed['deals'][0]['payinCustom']['multisig'] = False
    resp = operator.put('/api/stand/state', json={'version': before['version'], 'data': proposed})
    assert resp.status_code in (403, 409), resp.json
    after = operator.get('/api/stand/state').json['data']['deals'][0]
    assert after['step'] == 's11'
    assert after['payinCustom']['multisig'] is True
