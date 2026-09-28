"""Изолированные проверки серверного подтверждения переводов стенда."""

import json

import pytest

import app as appmod
from stand_transfers import (TRON_USDT, normalize_ref, send_fingerprint, preserve_server_fields,
                             verify_transfer)


FROM = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
TO = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
HASH = 'a' * 64


@pytest.fixture(autouse=True)
def authenticated_stand_client(monkeypatch):
    """Старые сценарии стенда проходят через настоящую тестовую cookie."""
    # Тесты меняют STAND_MODE после импорта app, поэтому готовим их таблицу здесь.
    appmod._stand_migrate()
    original = appmod.app.test_client

    def client_factory(*args, **kwargs):
        client = original(*args, **kwargs)
        if appmod.STAND_MODE:
            db = appmod.get_session()
            try:
                user = db.query(appmod.AdminUser).filter_by(username='stand_transfer_test').first()
                if not user:
                    user = appmod.AdminUser(username='stand_transfer_test', role='admin',
                                            password_hash=appmod.AdminUser.hash_password('test'))
                    db.add(user); db.commit()
                uid = user.id
            finally:
                db.close()
            with client.session_transaction() as sess:
                sess['user_id'] = uid
        return client

    monkeypatch.setattr(appmod.app, 'test_client', client_factory)


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
                {'id': 1, 'code': 'BIG', 'cnvId': 15, 'conv': [2], 'step': 's23',
                 'postConv': 'coins', 'transfer': {'addr': TO, 'amount': 100,
                                                  'sends': []}, 'pay': {}, 'log': []},
                {'id': 2, 'code': 'SMALL', 'cnvId': 15, 'conv': [], 'step': 'pack', 'closed': False,
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
    value = board()
    value['incomes'] = [{'id': 1, 'dealId': 1, 'rub': 100000, 'demo': True},
                        {'id': 2, 'dealId': 2, 'rub': 50000, 'demo': True}]
    value['deals'][0]['incomeAmount'] = 100000
    value['deals'][0]['payinParts'] = [{'incId': 1, 'amountRub': 100000}]
    value['deals'][1]['incomeAmount'] = 50000
    value['deals'][1]['payinParts'] = [{'incId': 2, 'amountRub': 50000}]
    value['convs'][0]['txs'] = [{'hash': 'b' * 64, 'net': 'TRC-20',
                                'amount': 700, 'status': 'confirmed'}]
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(value)
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


@pytest.mark.parametrize('funding_breaks_during_verify', [False, True])
@pytest.mark.parametrize('bad_first', [False, True])
@pytest.mark.parametrize('bad_kind', ['underfunded', 'malformed'])
def test_background_poll_isolates_underfunded_batch(
        monkeypatch, funding_breaks_during_verify, bad_first, bad_kind):
    """A bad batch cannot stall the board or consume a stale verified result."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    state = {'wallets': [{'id': 'grusha', 'addr': FROM}], 'incomes': [],
             'convs': [], 'deals': [], 'notes': []}
    for deal_id in ((2, 1) if bad_first else (1, 2)):
        tx_amount = (1 if deal_id == 2 and bad_kind == 'underfunded'
                     and not funding_breaks_during_verify else 600)
        source_rub = (0 if deal_id == 2 and bad_kind == 'malformed'
                      and not funding_breaks_during_verify else 100000)
        transfer_hash = str(deal_id) * 64
        state['incomes'].append({'id': deal_id, 'dealId': deal_id, 'rub': 100000,
                                 'demo': True})
        state['convs'].append({'id': deal_id, 'walletId': 'grusha',
                               'sources': [{'dealId': deal_id, 'rub': source_rub}],
                               'txs': [{'hash': transfer_hash, 'net': 'TRC-20',
                                        'amount': tx_amount, 'status': 'confirmed'}]})
        state['deals'].append({'id': deal_id, 'cnvId': deal_id, 'step': 's23',
                               'postConv': 'coins', 'incomeAmount': 100000,
                               'payinParts': [{'incId': deal_id, 'amountRub': 100000}],
                               'transfer': {'addr': TO, 'amount': 600, 'sends': [
                                   {'ref': transfer_hash, 'hash': transfer_hash,
                                    'net': 'TRC-20', 'amount': 600, 'status': 'pending'}]},
                               'pay': {}, 'log': []})
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.version = 1
        db.commit()
    finally:
        db.close()

    calls = []
    def verified(*args, **kwargs):
        calls.append(args[0])
        if funding_breaks_during_verify and len(calls) == 1:
            db = appmod.get_session()
            try:
                row = appmod._stand_row(db)
                changed = json.loads(row.data)
                bad_conv = next(c for c in changed['convs'] if c['id'] == 2)
                if bad_kind == 'underfunded':
                    bad_conv['txs'][0]['amount'] = 1
                else:
                    bad_conv['sources'][0]['rub'] = 0
                row.data = json.dumps(changed)
                row.version += 1
                db.commit()
            finally:
                db.close()
        return {'status': 'confirmed', 'verifiedAmount': 600,
                'verifiedAt': '2026-09-28T12:00:00Z', 'from': FROM, 'to': TO,
                'timestampMs': 1700000000000}

    monkeypatch.setattr(appmod, 'verify_transfer', verified)
    result = appmod._stand_check_transfers(poll=True)
    assert result['success'] is True
    after = {d['id']: d for d in result['data']['deals']}
    assert after[1]['transfer']['sends'][0]['status'] == 'confirmed'
    assert after[2]['transfer']['sends'][0]['status'] == 'pending'
    assert after[2]['step'] == 's23'
    assert not after[2].get('serverTransferComplete')
    assert not after[2].get('serverSettled')
    assert not any(str(note.get('id', '')).endswith(':2')
                   for note in result['data']['notes'])
    bad_before_replay = json.loads(json.dumps(after[2]))
    notes_before_replay = json.loads(json.dumps(result['data']['notes']))
    version_before_replay = result['version']
    calls_before_replay = len(calls)
    replay = appmod._stand_check_transfers(poll=True)
    assert replay['version'] == version_before_replay
    assert replay['data']['notes'] == notes_before_replay
    assert next(d for d in replay['data']['deals'] if d['id'] == 2) == bad_before_replay
    assert len(calls) == calls_before_replay
    rejected = appmod._stand_check_transfers(deal_id=2)
    assert rejected['httpStatus'] == 409
    assert 'data' not in rejected
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        assert row.version == version_before_replay
        assert json.loads(row.data)['notes'] == notes_before_replay
    finally:
        db.close()


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
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    import stand_notify
    stand_notify.init(appmod)
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_TG_CHAT', '-100123')
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
    db = appmod.SessionLocal()
    user = appmod.AdminUser(username='dm_retry_legacy', display_name='Тест', role='manager',
                            password_hash='test', telegram_user_id=12345, notify_enabled=True)
    db.add(user); db.commit()
    messages = []
    monkeypatch.setattr(stand_notify.stand_egress, 'tg_call',
                        lambda method, payload: messages.append(payload) or {'ok': False})
    appmod._stand_deliver_notes()
    assert db.execute(appmod.text("SELECT status FROM stand_notify_log WHERE note_id='n1' AND admin_id=:id"),
                      {'id': user.id}).scalar() == 'failed'
    assert '&lt;пример &amp; риск&gt;' in messages[0]['text']
    assert all(m['chat_id'] != -100123 for m in messages)
    monkeypatch.setattr(stand_notify.stand_egress, 'tg_call', lambda method, payload: {'ok': True})
    appmod._stand_deliver_notes()
    assert db.execute(appmod.text("SELECT status FROM stand_notify_log WHERE note_id='n1' AND admin_id=:id"),
                      {'id': user.id}).scalar() == 'sent'
    db.delete(user); db.commit(); db.close()


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


def test_network_confirmation_is_written_to_history_once():
    """Подтверждение сети по каждому переводу пишется в историю главной (Карим, 27.09)."""
    state = board()
    main, small = state['deals']
    main['step'] = 's24'
    main['transfer']['sends'] = [{'ref': HASH, 'hash': HASH, 'net': 'TRC-20', 'amount': 100,
                                  'status': 'confirmed', 'verifiedAmount': 100}]
    small['postConv'] = 'client'
    small['transfer']['sends'][0].update(status='confirmed', verifiedAmount=600)
    appmod._stand_settle_verified(state, state['deals'])
    texts = [entry['text'] for entry in main.get('log', [])]
    confirmed = [t for t in texts if t.startswith('Перевод подписан и подтверждён в сети')]
    assert confirmed == [f'Перевод подписан и подтверждён в сети · {HASH} · 100,00 USDT',
                         f'Перевод подписан и подтверждён в сети · {HASH} · 600,00 USDT · '
                         f'{small.get("code") or small["id"]}']
    assert all(entry['role'] == 'teodor' for entry in main['log']
               if entry['text'].startswith('Перевод подписан'))
    appmod._stand_settle_verified(state, state['deals'])
    assert len([e for e in main['log'] if e['text'].startswith('Перевод подписан')]) == 2


def _put_board(state):
    db = appmod.get_session()
    try:
        row = appmod._stand_row(db)
        row.data = json.dumps(state)
        row.version = 1
        db.commit()
    finally:
        db.close()


def test_crypto_payin_hash_fills_payer_wallet_and_flags_other_sender(monkeypatch):
    """Тестовый + основной перевод крипто-клиента: кошелёк клиента берётся из первого хеша,
    перевод с чужого кошелька помечается, дубль и перевод до сделки не принимаются."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'manager')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    state = {'deals': [{'id': 7, 'payType': 'Крипта', 'step': 's14', 'walletId': 'grusha',
                        'payinHashes': [], 'log': [{'at': 1700000000000, 'text': 'заведена'}]}],
             'convs': [], 'wallets': []}
    _put_board(state)
    seen = {}

    def fake(ref, network, sender, receiver, amount, **kw):
        seen['receiver'], seen['sender'] = receiver, sender
        return {'status': 'confirmed', 'verifiedAmount': fake.amount, 'verifiedAt': 'now',
                'from': fake.sender, 'to': receiver, 'timestampMs': fake.ts}
    fake.amount, fake.sender, fake.ts = 1.0, TO, 1700000000001
    monkeypatch.setattr(appmod, 'verify_transfer', fake)

    def role_lookup():
        # как настоящая current_role: закрывает общую scoped-сессию
        appmod.get_session().close()
        return 'manager'
    monkeypatch.setattr(appmod, 'current_role', role_lookup)
    with appmod.app.test_client() as client:
        first = client.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
        assert first.status_code == 200, first.json
        stored = client.get('/api/stand/state').json
        assert stored['version'] == first.json['version'], 'проверенный хеш сохранён в базе'
        assert stored['data']['deals'][0]['payinHashes'][0]['hash'] == HASH
        deal = first.json['data']['deals'][0]
        assert seen == {'receiver': FROM, 'sender': None}
        assert deal['payerWallet'] == TO
        assert deal['payinHashes'][0]['verified'] is True
        assert not deal['payinHashes'][0].get('otherSender')

        dup = client.post('/api/stand/payin/check', json={'dealId': 7, 'hash': HASH})
        assert dup.status_code == 409

        fake.amount, fake.sender = 599.0, FROM
        other = client.post('/api/stand/payin/check', json={'dealId': 7, 'hash': 'b' * 64})
        assert other.status_code == 200
        assert other.json['data']['deals'][0]['payinHashes'][1]['otherSender'] is True

        fake.ts = 1699999999999
        early = client.post('/api/stand/payin/check', json={'dealId': 7, 'hash': 'c' * 64})
        assert early.status_code == 422

        forged = other.json['data']
        forged['deals'][0]['payinHashes'][0]['amount'] = 5000
        forged['deals'][0]['payinHashes'].append({'hash': 'd' * 64, 'amount': 10, 'verified': True,
                                                  'network': 'TRC20'})
        applied = client.put('/api/stand/state', json={'version': other.json['version'], 'data': forged})
        assert applied.status_code == 200
        hs = applied.json['data']['deals'][0]['payinHashes']
        assert hs[0]['amount'] == 1.0, 'сумму проверенного хеша браузер не переписывает'
        assert 'verified' not in hs[2], 'отметку «проверено» браузер не ставит'


def test_crypto_payin_check_rejects_ruble_deal_and_wrong_step(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'manager')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    _put_board({'deals': [{'id': 1, 'payType': 'По реквизитам', 'step': 's14', 'log': []},
                          {'id': 2, 'payType': 'Крипта', 'step': 's15', 'log': []}],
                'convs': [], 'wallets': []})
    with appmod.app.test_client() as client:
        assert client.post('/api/stand/payin/check', json={'dealId': 1, 'hash': HASH}).status_code == 404
        assert client.post('/api/stand/payin/check', json={'dealId': 2, 'hash': HASH}).status_code == 409
        assert client.post('/api/stand/payin/check', json={'dealId': 2, 'hash': 'demo:2:x'}).status_code == 400


def test_verify_without_amount_and_sender_takes_both_from_chain():
    """Приход крипто-клиента: сумму и отправителя не знаем — берём из сети (баг приёмки 25.09:
    _amount(None) давал 0, и любой настоящий перевод считался несовпавшим)."""
    result = verify_transfer(HASH, 'TRC-20', None, TO, None,
                             get=lambda *a, **kw: Response(200, chain()))
    assert result['status'] == 'confirmed'
    assert result['verifiedAmount'] == 600
    assert result['from'] == FROM
    other = verify_transfer(HASH, 'TRC-20', None, FROM, None,
                            get=lambda *a, **kw: Response(200, chain()))
    assert other['status'] == 'mismatch', 'перевод не на наш кошелёк не засчитывается'


def test_prod_agents_sync_disabled_in_stand_mode(monkeypatch):
    """Режим «тишина» (T1, план п.1.9): чтение боевого CRM с тестового стенда
    выключено насовсем, вне зависимости от роли и наличия STAND_PROD_RO_KEY —
    после копии прод-данных агенты берутся из локальной таблицы referrers."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setenv('STAND_PROD_RO_KEY', 'ro')

    def fail_get(*a, **kw):
        raise AssertionError('прод-CRM не должен вызываться из STAND_MODE')
    monkeypatch.setattr(appmod.requests, 'get', fail_get)
    with appmod.app.test_client() as client:
        res = client.post('/api/stand/prod-agents')
    assert res.status_code == 403 and res.json['error'] == 'stand_blocked'


def _unlink_board(step='s22', status='received', sends=None):
    return {'deals': [{'id': 1, 'step': step, 'cnvId': 'CNV-1', 'postConv': 'coins', 'log': [],
                       'payinHashes': [{'hash': HASH, 'amount': 100}], 'pay': {'usdt': 100, 'hash': HASH},
                       'transfer': {'sends': sends or []}}],
            'convs': [{'id': 'CNV-1', 'status': status, 'receivedAt': 'x', 'walletId': 'grusha',
                       'sources': [{'dealId': 1, 'rub': 1000, 'usdtFact': 100}],
                       'txs': [{'hash': HASH, 'net': 'TRC20', 'amount': 100, 'status': 'confirmed'},
                               {'hash': 'b' * 64, 'net': 'TRC20', 'amount': 5, 'status': 'confirmed'}]}]}


def test_unlink_confirmed_incoming_returns_pack_to_waiting(monkeypatch):
    """Ошибочно выбранный подтверждённый приход отвязывается с причиной; принятая пачка
    возвращается на «Ждём USDT», доли прихода у сделок обнуляются (Карим, 25.09)."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setattr(appmod, 'current_role', lambda: 'operator')
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    _put_board(_unlink_board())
    with appmod.app.test_client() as client:
        assert client.post('/api/stand/incoming/unlink', json={'dealId': 1, 'hash': HASH}).status_code == 400
        res = client.post('/api/stand/incoming/unlink', json={'dealId': 1, 'hash': HASH, 'reason': 'не тот перевод'})
        assert res.status_code == 200, res.json
        st = client.get('/api/stand/state').json['data']
    conv, deal = st['convs'][0], st['deals'][0]
    assert [t['hash'] for t in conv['txs']] == ['b' * 64]
    assert conv['status'] == 'sent' and deal['step'] == 's18w'
    assert deal['payinHashes'] == [] and deal['pay']['usdt'] is None
    assert any('не тот перевод' in l['text'] for l in deal['log'])


def test_unlink_blocked_after_sends_and_for_manager(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'current_role', lambda: 'manager')
    _put_board(_unlink_board())
    with appmod.app.test_client() as client:
        assert client.post('/api/stand/incoming/unlink',
                           json={'dealId': 1, 'hash': HASH, 'reason': 'x'}).status_code == 403
    monkeypatch.setattr(appmod, 'current_role', lambda: 'operator')
    _put_board(_unlink_board(step='s23', sends=[{'ref': 'demo:1:x', 'amount': 100}]))
    with appmod.app.test_client() as client:
        assert client.post('/api/stand/incoming/unlink',
                           json={'dealId': 1, 'hash': HASH, 'reason': 'x'}).status_code == 409


def test_manager_can_edit_requisites_on_operator_steps(monkeypatch):
    """Реквизиты — параллельная задача менеджера: на s22/s26 он может менять только их,
    любая другая правка сделки на чужом шаге по-прежнему запрещена (Карим, 25.09)."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'current_role', lambda: 'manager')
    for step in ('s22', 's26'):
        _put_board({'deals': [{'id': 1, 'step': step, 'reqTask': 'open', 'log': [], 'pay': {}}],
                    'convs': [], 'wallets': []})
        with appmod.app.test_client() as client:
            cur = client.get('/api/stand/state').json
            data = cur['data']
            data['deals'][0].update(payTo={'dev': 'Dev Co', 'acc': '123', 'bank': 'SCB', 'amount': 100,
                                           'purpose': 'inv 1'}, reqTask='done', dev='Dev Co')
            data['deals'][0]['log'].append({'text': 'Реквизиты для оплаты заполнены'})
            ok = client.put('/api/stand/state', json={'version': cur['version'], 'data': data})
            assert ok.status_code == 200, (step, ok.json)
            cur = client.get('/api/stand/state').json
            data = cur['data']
            data['deals'][0]['step'] = 's27'
            bad = client.put('/api/stand/state', json={'version': cur['version'], 'data': data})
            assert bad.status_code == 409, step
    _put_board({'deals': [{'id': 1, 'step': 's26', 'log': [], 'pay': {'invoicePaid': True}}],
                'convs': [], 'wallets': []})
    with appmod.app.test_client() as client:
        cur = client.get('/api/stand/state').json
        data = cur['data']
        data['deals'][0]['payTo'] = {'acc': '999'}
        assert client.put('/api/stand/state', json={'version': cur['version'], 'data': data}).status_code == 409


def test_manager_can_upload_signed_contract_on_any_step(monkeypatch):
    """Подписанный договор менеджер загружает на любом шаге, в том числе на чужом
    (Карим, 27.09). Чек оплаты или другие поля сделки так менять нельзя."""
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(appmod, 'current_role', lambda: 'manager')
    signed = {'file': 'signed.pdf', 'size': '1 КБ', 'at': '27.09', 'mime': 'application/pdf',
              'bytes': 10, 'data': 'data:application/pdf;base64,JVBERi0=', 'demo': False}
    for step in ('s22', 's26'):
        _put_board({'deals': [{'id': 1, 'step': step, 'log': [], 'pay': {}, 'docs': {'inv': True},
                               'files': {'inv': []}, 'docMeta': {}}],
                    'convs': [], 'wallets': []})
        with appmod.app.test_client() as client:
            cur = client.get('/api/stand/state').json
            data = cur['data']
            deal = data['deals'][0]
            deal['files']['signed'] = [signed]
            deal['docs']['signed'] = True
            deal['docMeta']['signed'] = {'file': 'signed.pdf', 'size': '1 КБ', 'at': '27.09'}
            deal['log'].append({'text': 'Приложен файл: Подписанный пакет от клиента · signed.pdf'})
            ok = client.put('/api/stand/state', json={'version': cur['version'], 'data': data})
            assert ok.status_code == 200, (step, ok.json)
            cur = client.get('/api/stand/state').json
            data = cur['data']
            data['deals'][0]['files']['receipt'] = [signed]
            data['deals'][0]['docs']['receipt'] = True
            bad = client.put('/api/stand/state', json={'version': cur['version'], 'data': data})
            assert bad.status_code == 409, step
