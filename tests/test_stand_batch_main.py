"""Batch owner and approval role regressions for mixed stand transfers."""
import json

import pytest

import app as appmod


def state(main_route='ipps_swift', side_route='coins', step='s24', reverse=False):
    main = {'id': 1473, 'code': 'MAIN', 'cnvId': 1, 'conv': [1476],
            'postConv': main_route, 'step': step, 'demoTransfers': True,
            'transfer': {'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
                         'amount': 100, 'sends': [
                             {'ref': 'demo:1473:one', 'hash': 'demo:1473:one',
                              'net': 'TRC-20', 'amount': 60, 'status': 'pending'},
                             {'ref': 'demo:1473:two', 'hash': 'demo:1473:two',
                              'net': 'TRC-20', 'amount': 40, 'status': 'pending'}]},
            'pay': {}, 'log': []}
    side = {'id': 1476, 'code': 'SIDE', 'cnvId': 1, 'conv': [],
            'postConv': side_route, 'step': 'pack', 'demoTransfers': True,
            'transfer': {'addr': 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p',
                         'amount': 10, 'sends': [
                             {'ref': 'demo:1476:one', 'hash': 'demo:1476:one',
                              'net': 'TRC-20', 'amount': 10, 'status': 'pending'}]},
            'pay': {}, 'log': []}
    deals = [side, main] if reverse else [main, side]
    return {'deals': deals, 'convs': [{'id': 1, 'walletId': 'grusha',
            'sources': [{'dealId': 1476}, {'dealId': 1473}], 'txs': []}],
            'wallets': [{'id': 'grusha', 'role': 'findir', 'multisig': True,
                         'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'}], 'notes': []}


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, '_stand_deliver_notes', lambda: None)
    appmod._stand_migrate()
    def install(value):
        db = appmod.get_session()
        try:
            row = appmod._stand_row(db)
            row.data = json.dumps(value)
            row.version = 1
            db.commit()
        finally:
            db.close()
    return install


def call(role, deal_id, ref, outcome='confirmed'):
    db = appmod.get_session()
    try:
        user = db.query(appmod.AdminUser).filter_by(username='t23_' + role).first()
        if not user:
            user = appmod.AdminUser(username='t23_' + role, role=role,
                                    password_hash=appmod.AdminUser.hash_password('test'))
            db.add(user)
            db.commit()
        uid = user.id
    finally:
        db.close()
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        return client.post('/api/stand/transfers/demo', json={
            'dealId': deal_id, 'ref': ref, 'outcome': outcome})


def check(role, deal_id):
    db = appmod.get_session()
    try:
        uid = db.query(appmod.AdminUser).filter_by(username='t23_' + role).first().id
    finally:
        db.close()
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
        return client.post('/api/stand/transfers/check', json={'dealId': deal_id})


def test_canonical_owner_independent_of_order_and_route():
    for reverse in (False, True):
        for main_route, side_route in (('ipps_swift', 'coins'), ('coins', 'ipps_swift')):
            value = state(main_route, side_route, reverse=reverse)
            assert appmod._stand_batch_main(value, 1473)['id'] == 1473
            assert appmod._stand_batch_main(value, 1476)['id'] == 1473
    value = state()
    next(d for d in value['deals'] if d['id'] == 1476)['conv'] = [1473]
    assert appmod._stand_batch_main(value, 1476) is None
    value = state()
    next(d for d in value['deals'] if d['id'] == 1473)['conv'] = []
    assert appmod._stand_batch_main(value, 1473) is None
    single = state()
    single['deals'] = [d for d in single['deals'] if d['id'] == 1473]
    single['deals'][0]['conv'] = []
    single['convs'][0]['sources'] = [{'dealId': 1473}]
    assert appmod._stand_batch_main(single, 1473)['id'] == 1473


@pytest.mark.parametrize('role', ['findir', 'manager', 'operator'])
def test_wrong_role_cannot_mutate_s24_even_with_side_id(board, role):
    value = state(reverse=True)
    board(value)
    ref = 'demo:1476:one' if role == 'findir' else 'demo:1473:one'
    response = call(role, 1476 if role == 'findir' else 1473, ref)
    assert response.status_code == 403
    db = appmod.get_session()
    try:
        saved = json.loads(appmod._stand_row(db).data)
    finally:
        db.close()
    assert saved == value


def test_teodor_confirms_each_send_and_forwards_only_after_all(board):
    board(state(reverse=True))
    for deal_id, ref in [(1473, 'demo:1473:one'), (1476, 'demo:1476:one')]:
        response = call('teodor', deal_id, ref)
        assert response.status_code == 200
        main = next(d for d in response.json['data']['deals'] if d['id'] == 1473)
        assert main['step'] == 's24'
    response = call('teodor', 1473, 'demo:1473:two')
    assert response.status_code == 200
    main = next(d for d in response.json['data']['deals'] if d['id'] == 1473)
    assert main['step'] == 's25'
    assert main['serverTransferComplete'] is True
    assert len(main['payout']['hashes']) == 2
    assert call('teodor', 1473, 'demo:1473:two').status_code in (403, 409)


def test_step_ownership_and_ambiguity_fail_closed(board):
    board(state(step='s23'))
    assert call('teodor', 1473, 'demo:1473:one').status_code == 403
    assert call('findir', 1473, 'demo:1473:one').status_code == 409
    ambiguous = state()
    next(d for d in ambiguous['deals'] if d['id'] == 1476)['conv'] = [1473]
    board(ambiguous)
    assert call('admin', 1473, 'demo:1473:one').status_code == 409
    assert check('admin', 1476).status_code == 409


def test_admin_existing_scope_and_duplicate_ref(board):
    value = state()
    board(value)
    assert call('admin', 1473, 'demo:1473:one').status_code == 200
    duplicate = state()
    duplicate['deals'][0]['transfer']['sends'][1]['ref'] = 'demo:1473:one'
    duplicate['deals'][0]['transfer']['sends'][1]['hash'] = 'demo:1473:one'
    board(duplicate)
    response = call('teodor', 1473, 'demo:1473:one')
    assert response.status_code == 200
    main = next(d for d in response.json['data']['deals'] if d['id'] == 1473)
    assert main['step'] == 's24'
    assert not any(s['status'] == 'confirmed' for s in main['transfer']['sends'])


def test_real_check_uses_same_owner_with_mock_verifier(board, monkeypatch):
    value = state(reverse=True)
    for deal in value['deals']:
        deal['demoTransfers'] = False
        for i, send in enumerate(deal['transfer']['sends']):
            send['ref'] = send['hash'] = format(deal['id'] * 10 + i, '064x')
    board(value)
    calls = []
    def verifier(ref, network, sender, receiver, amount, **kwargs):
        calls.append(ref)
        return {'status': 'confirmed', 'verifiedAmount': amount,
                'verifiedAt': '2026-09-28T17:00:00Z', 'from': sender, 'to': receiver}
    monkeypatch.setattr(appmod, 'verify_transfer', verifier)
    response = check('admin', 1476)
    assert response.status_code == 200
    assert len(calls) == 3
    main = next(d for d in response.json['data']['deals'] if d['id'] == 1473)
    assert main['step'] == 's25'
    assert main['serverTransferComplete'] is True
