"""Изолированные проверки серверного подтверждения переводов стенда."""

import json

import pytest

import app as appmod
from stand_transfers import (TRON_USDT, normalize_ref, send_fingerprint, preserve_server_fields,
                             verify_transfer)


FROM = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
TO = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
HASH = 'a' * 64


class Response:
    def __init__(self, status, data):
        self.status_code = status
        self.data = data

    def json(self):
        return self.data


def chain(status='SUCCESS', confirmed=True, receiver=TO, amount='600000000',
          contract=TRON_USDT, timestamp=1700000000000):
    return {'hash': HASH, 'confirmed': confirmed, 'contractRet': status,
            'revert': status != 'SUCCESS', 'timestamp': timestamp,
            'trc20TransferInfo': [{'contract_address': contract, 'from_address': FROM,
                                   'to_address': receiver, 'amount_str': amount,
                                   'decimals': 6, 'type': 'Transfer', 'status': 0}]}


@pytest.mark.parametrize('payload,expected', [
    (chain(), 'confirmed'),
    (chain(confirmed=False), 'pending'),
    (chain(status='REVERT'), 'failed'),
    (chain(receiver=FROM), 'mismatch'),
    (chain(contract=TO), 'mismatch'),
    (chain(amount='599000000'), 'mismatch'),
])
def test_tron_verification_requires_success_token_addresses_and_amount(payload, expected):
    result = verify_transfer(HASH, 'TRC-20', FROM, TO, 600,
                             get=lambda *a, **kw: Response(200, payload))
    assert result['status'] == expected
    if expected == 'confirmed':
        assert result['verifiedAmount'] == 600
        assert result['timestampMs'] == 1700000000000


def test_unavailable_provider_is_not_confirmation():
    result = verify_transfer(HASH, 'TRC-20', FROM, TO, 600,
                             get=lambda *a, **kw: Response(429, {}))
    assert result['status'] == 'error'


def test_tronscan_request_uses_existing_user_agent_and_optional_key(monkeypatch):
    calls = []

    def capture(url, **kwargs):
        calls.append((url, kwargs))
        return Response(200, chain())

    monkeypatch.setenv('TRONSCAN_API_KEY', 'test-api-key')
    result = verify_transfer(HASH, 'TRC-20', FROM, TO, 600, get=capture)
    assert result['status'] == 'confirmed'
    assert calls[0][1]['headers']['User-Agent'].startswith('Mozilla/5.0')
    assert calls[0][1]['headers']['TRON-PRO-API-KEY'] == 'test-api-key'
    monkeypatch.delenv('TRONSCAN_API_KEY')
    calls.clear()
    verify_transfer(HASH, 'TRC-20', FROM, TO, 600, get=capture)
    assert 'TRON-PRO-API-KEY' not in calls[0][1]['headers']


def test_hash_normalization_and_tron_case_sensitive_address():
    assert normalize_ref('0x' + HASH.upper(), 'trc20') == HASH
    result = verify_transfer(HASH, 'TRC-20', FROM.lower(), TO, 600,
                             get=lambda *a, **kw: Response(200, chain()))
    assert result['status'] == 'mismatch'


def test_fingerprint_uses_canonical_amount_and_checks_ref_hash_agreement():
    state = board()
    deal = state['deals'][1]
    send = deal['transfer']['sends'][0]
    first = send_fingerprint(state, deal, send)
    send['amount'] = 600.0
    assert send_fingerprint(state, deal, send) == first
    send['ref'] = 'b' * 64
    assert send_fingerprint(state, deal, send)[0] is None


def board():
    return {'wallets': [{'id': 'grusha', 'addr': FROM}, {'id': 'teodor', 'addr': TO}],
            'convs': [{'id': 15, 'walletId': 'grusha', 'sources': [
                {'dealId': 1, 'rub': 100000}, {'dealId': 2, 'rub': 50000}], 'txs': []}],
            'deals': [
                {'id': 1, 'code': 'BIG', 'cnvId': 15, 'step': 's23',
                 'postConv': 'coins', 'transfer': {'addr': TO, 'amount': 100,
                                                  'sends': []}, 'pay': {}, 'log': []},
                {'id': 2, 'code': 'SMALL', 'cnvId': 15, 'step': 'pack', 'closed': False,
                 'postConv': 'refund', 'pay': {'usdt': 620},
                 'transfer': {'addr': TO, 'amount': 600, 'sends': [
                     {'ref': HASH, 'hash': HASH, 'net': 'TRC-20', 'amount': 600,
                      'status': 'pending'}]}, 'payout': {}, 'log': []}], 'notes': []}


def test_browser_cannot_forge_or_reuse_verified_fields():
    old = board()
    new = json.loads(json.dumps(old))
    new['deals'][1]['transfer']['sends'][0]['status'] = 'confirmed'
    new['deals'][1]['transfer']['sends'][0]['verifiedAmount'] = 600
    preserve_server_fields(old, new)
    assert new['deals'][1]['transfer']['sends'][0]['status'] == 'pending'
    old['deals'][1]['transfer']['sends'][0].update(status='confirmed', verifiedAmount=600)
    new['deals'][1]['transfer']['sends'][0]['amount'] = 601
    preserve_server_fields(old, new)
    assert new['deals'][1]['transfer']['sends'][0]['status'] == 'pending'


def test_confirmed_send_and_incoming_cannot_be_duplicated_or_target_reduced():
    old = board()
    send = old['deals'][1]['transfer']['sends'][0]
    send.update(status='confirmed', verifiedAmount=600)
    old['convs'][0]['txs'] = [{'hash': 'b' * 64, 'net': 'TRC-20',
                               'amount': 100, 'status': 'confirmed'}]
    doubled = json.loads(json.dumps(old))
    doubled['deals'][1]['transfer']['sends'].append(dict(send))
    assert appmod._stand_guard_transition(old, doubled, 'admin')
    preserve_server_fields(old, doubled)
    assert [s['status'] for s in doubled['deals'][1]['transfer']['sends']] == ['confirmed', 'pending']
    doubled = json.loads(json.dumps(old))
    doubled['convs'][0]['txs'].append(dict(old['convs'][0]['txs'][0]))
    assert appmod._stand_guard_transition(old, doubled, 'admin')
    preserve_server_fields(old, doubled)
    assert len(doubled['convs'][0]['txs']) == 1
    lowered = json.loads(json.dumps(old))
    lowered['deals'][1]['transfer']['amount'] = 500
    assert appmod._stand_guard_transition(old, lowered, 'admin')
    incoming_only = board()
    incoming_only['convs'][0]['txs'] = [{'hash': HASH, 'net': 'TRC-20',
                                         'amount': 1, 'status': 'confirmed'}]
    lowered = json.loads(json.dumps(incoming_only))
    lowered['convs'][0]['sources'][1]['usdtFact'] = 1
    lowered['deals'][1]['transfer']['amount'] = 1
    assert appmod._stand_guard_transition(incoming_only, lowered, 'admin')


def test_auto_refund_requires_actual_incoming_coverage():
    state = board()
    state['deals'][1]['transfer']['sends'] = []
    state['deals'][1]['transfer']['walletId'] = 'grusha'
    state['convs'][0]['sources'][1]['usdt'] = 600
    state['convs'][0]['txs'] = [{'hash': HASH, 'net': 'TRC-20', 'amount': 1,
                               'status': 'confirmed'}]
    appmod._stand_settle_verified(state, state['deals'])
    assert not state['deals'][1]['closed']
    state['convs'][0]['txs'][0]['amount'] = 600
    state['deals'][0]['step'] = 's22'
    appmod._stand_settle_verified(state, state['deals'])
    assert not state['deals'][1]['closed']
    edited = json.loads(json.dumps(state))
    edited['deals'][1]['transfer']['amount'] = 599
    assert appmod._stand_guard_transition(state, edited, 'admin') is None
    state['deals'][0]['step'] = 's23'
    appmod._stand_settle_verified(state, state['deals'])
    assert state['deals'][1]['closed']


def test_state_put_persists_with_role_lookup_using_scoped_session(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(board())
        row.version = 18
        db.commit()
    finally:
        db.close()

    def role_lookup():
        appmod.get_session().close()
        return 'admin'

    monkeypatch.setattr(appmod, 'current_role', role_lookup)
    with appmod.app.test_client() as client:
        before = client.get('/api/stand/state')
        state = before.json['data']
        state['deals'][0]['client'] = 'Проверка сохранения'
        put = client.put('/api/stand/state', json={'version': before.json['version'], 'data': state})
        after = client.get('/api/stand/state')
    assert put.status_code == 200
    assert after.json['version'] == 19
    assert after.json['data']['deals'][0]['client'] == 'Проверка сохранения'


def test_demo_endpoint_cannot_reverse_confirmed_send(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    state = board()
    for deal in state['deals']:
        deal['demoTransfers'] = True
    state['deals'][0]['step'] = 's24'
    send = state['deals'][1]['transfer']['sends'][0]
    send.update(ref='demo:2:abc', hash='demo:2:abc', status='confirmed',
                verifiedAmount=600, demoOutcome='confirmed')
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    with appmod.app.test_client() as client:
        result = client.post('/api/stand/transfers/demo', json={
            'dealId': 2, 'ref': 'demo:2:abc', 'outcome': 'failed'})
        assert result.status_code == 409
        persisted = client.get('/api/stand/state').json['data']
    assert persisted['deals'][1]['transfer']['sends'][0]['status'] == 'confirmed'


def test_receipt_extension_matches_mime_and_bytes():
    import base64
    sample = {'file': 'receipt.html', 'mime': 'application/pdf',
              'data': 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4\n%%EOF').decode()}
    deal = {'files': {'receipt': [sample]}}
    assert not appmod._stand_valid_receipt(deal)
    sample['file'] = 'receipt.pdf'
    assert appmod._stand_valid_receipt(deal)


def test_small_refund_only_closes_after_verified_coverage():
    state = board()
    members = state['deals']
    appmod._stand_settle_verified(state, members)
    assert not members[1]['closed']
    members[1]['transfer']['sends'][0].update(status='confirmed', verifiedAmount=600)
    appmod._stand_settle_verified(state, members)
    assert members[1]['closed']
    assert members[1]['payout']['reimbursement']['hash'] == HASH
    assert len(state['notes']) == 1
    appmod._stand_settle_verified(state, members)
    assert len(state['notes']) == 1


def test_check_endpoint_closes_small_and_rejects_rewriting_confirmed(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'verify_transfer', lambda *a, **kw: {
        'status': 'confirmed', 'verifiedAmount': 600, 'verifiedAt': '2026-09-24T12:00:00Z',
        'from': FROM, 'to': TO, 'timestampMs': 1700000000000})
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(board())
        row.version = 1
        db.commit()
    finally:
        db.close()
    with appmod.app.test_client() as client:
        result = client.post('/api/stand/transfers/check', json={'dealId': 1})
        assert result.status_code == 200
        state = result.json['data']
        small = next(d for d in state['deals'] if d['id'] == 2)
        assert small['closed'] is True
        assert small['transfer']['sends'][0]['status'] == 'confirmed'
        assert state['notes'][0]['id'] == 'stand:refund:2'
        small['transfer']['sends'] = []
        rejected = client.put('/api/stand/state', json={
            'version': result.json['version'], 'data': state})
        assert rejected.status_code == 409


def test_incoming_endpoint_rejects_old_tx_and_persists_verified(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    state = board()
    state['convs'][0]['sentTs'] = 1700000000000
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.version = 1
        db.commit()
    finally:
        db.close()
    payload = {'dealId': 1, 'hash': HASH, 'network': 'TRC-20'}
    with appmod.app.test_client() as client:
        monkeypatch.setattr(appmod, 'verify_transfer', lambda *a, **kw: {
            'status': 'confirmed', 'verifiedAmount': 100, 'verifiedAt': 'now',
            'from': TO, 'to': FROM, 'timestampMs': 1699999999999})
        old = client.post('/api/stand/incoming/check', json=payload)
        assert old.status_code == 422
        monkeypatch.setattr(appmod, 'verify_transfer', lambda *a, **kw: {
            'status': 'confirmed', 'verifiedAmount': 100, 'verifiedAt': 'now',
            'from': TO, 'to': FROM, 'timestampMs': 1700000000001})
        saved = client.post('/api/stand/incoming/check', json=payload)
        assert saved.status_code == 200
        assert saved.json['tx']['status'] == 'confirmed'
        forged = saved.json['data']
        forged['convs'][0]['txs'][0]['amount'] = 1000000
        applied = client.put('/api/stand/state', json={
            'version': saved.json['version'], 'data': forged})
        assert applied.status_code == 200
        assert applied.json['data']['convs'][0]['txs'][0]['amount'] == 100


def test_notification_retry_marks_sent_only_after_http_success(monkeypatch):
    monkeypatch.setenv('STAND_TG_TOKEN', 'test-token')
    monkeypatch.setenv('STAND_TG_CHAT', 'test-chat')
    state = board()
    state['notes'] = [{'id': 'n1', 'role': 'manager', 'text': '<пример & риск>',
                       'dealId': 1, 'at': 1}]
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.notified = '[]'
        db.commit()
    finally:
        db.close()
    messages = []
    monkeypatch.setattr(appmod, '_stand_tg_send', lambda message: messages.append(message) or False)
    appmod._stand_deliver_notes()
    db = appmod.get_session()
    try:
        assert json.loads(appmod._stand_row(db).notified) == []
    finally:
        db.close()
    assert '&lt;пример &amp; риск&gt;' in messages[0]
    monkeypatch.setattr(appmod, '_stand_tg_send', lambda message: True)
    appmod._stand_deliver_notes()
    db = appmod.get_session()
    try:
        assert json.loads(appmod._stand_row(db).notified) == ['n1']
    finally:
        db.close()


def test_small_coins_and_client_close_with_payout_hashes_when_pack_confirmed():
    """Мелкие Coins/клиент закрываются сервером вместе с подтверждением пачки (24.09)."""
    state = board()
    main, small = state['deals']
    main['step'] = 's24'
    main['transfer']['sends'] = [{'ref': HASH, 'hash': HASH, 'net': 'TRC-20', 'amount': 100,
                                  'status': 'confirmed', 'verifiedAmount': 100}]
    small['postConv'] = 'client'
    small['transfer']['sends'][0].update(status='pending')
    appmod._stand_settle_verified(state, state['deals'])
    assert not small['closed'] and main['step'] == 's24'
    small['transfer']['sends'][0].update(status='confirmed', verifiedAmount=600)
    appmod._stand_settle_verified(state, state['deals'])
    assert main['step'] == 's25'
    assert small['closed'] and small['step'] == 'done'
    assert small['payout']['usdt'] == 600 and small['payout']['hash'] == HASH
    appmod._stand_settle_verified(state, state['deals'])
    assert sum(1 for n in state['notes'] if n['id'] == 'stand:payout:2') == 1
