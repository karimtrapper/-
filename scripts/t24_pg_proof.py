"""Focused PG17 proof for T24; run only inside own exact-port/Unix sandbox."""
import json
import os
import secrets
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from werkzeug.serving import make_server

import app as m


assert m.STAND_MODE
assert 'calccrm-t24-pg-own/socket' in m.DATABASE_URL
port = 29991
m.stand_egress.allow_test_target('127.0.0.1', port)


def board():
    return {'deals': [{'id': 1474, 'code': 'СД-1474', 'client': 'PG synthetic T24',
                       'type': 'Обмен валюты', 'step': 's27', 'closed': False,
                       'crmDealId': None, 'sentToClient': True, 'pay': {},
                       'amountUsdt': 100, 'payout': {'usdt': 90},
                       'files': {'receipt': [{'file': 'receipt.pdf',
                           'mime': 'application/pdf',
                           'data': 'data:application/pdf;base64,JVBERi0='}]},
                       'log': []}], 'notes': []}


def crm():
    return {'deal_kind': 'exchange', 'client_name': 'PG synthetic T24',
            'manager_name': 'Марина', 'payin_method': 'sber_reqs',
            'payin_amount_usdt': 100, 'payout_method': 'transfer',
            'payout_source': 'cash_batch', 'payout_amount_usdt': 90}


def reset_fixture():
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps(board())
        row.version = (row.version or 0) + 1
        row.generation = secrets.token_hex(16)
        db.commit()
        seed_synthetic_evidence(db, row, board())
        return row.version
    finally:
        db.close()


def seed_synthetic_evidence(db, row, state):
    """Preverified synthetic board for the independent transaction proof."""
    deal = state['deals'][0]
    for kind in m._stand_close_required(deal):
        entry = db.query(m.StandCloseEvidence).filter_by(
            generation=row.generation, stand_deal_id=deal['id'], kind=kind).first()
        if entry is None:
            entry = m.StandCloseEvidence(generation=row.generation,
                stand_deal_id=deal['id'], kind=kind)
            db.add(entry)
        entry.fingerprint = m._stand_close_fingerprint(deal, kind)
        entry.actor_id = uid
        entry.provenance = 'synthetic_preverified_fixture'
    db.commit()


def snapshot():
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        return (db.query(m.Deal).count(), db.query(m.StandCrmLink).count(),
                row.version, json.loads(row.data))
    finally:
        db.close()


db = m.get_session()
try:
    manager = db.query(m.AdminUser).filter_by(username='marina').one()
    uid = manager.id
finally:
    db.close()
cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
base_url = f'http://127.0.0.1:{port}'
close_url = base_url + '/api/stand/deals/1474/crm-close'
headers = {'Cookie': 'session=' + cookie}
server = make_server('127.0.0.1', port, m.app, threaded=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()


def post(version, data=None):
    with requests.Session() as client:
        return client.post(close_url, headers=headers,
                           json={'version': version, 'crm': crm() if data is None else data},
                           timeout=10)


try:
    version = reset_fixture()
    before = snapshot()
    gate = threading.Barrier(2)
    def concurrent(_):
        gate.wait()
        return post(version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pair = list(pool.map(concurrent, (1, 2)))
    assert sorted(r.status_code for r in pair) == [200, 201], [r.text for r in pair]
    one_id = pair[0].json()['deal']['id']
    assert pair[1].json()['deal']['id'] == one_id
    after = snapshot()
    assert after[:2] == (before[0] + 1, before[1] + 1)
    assert after[3]['deals'][0]['crmDealId'] == one_id
    assert after[3]['deals'][0]['closed'] is True
    print('PG concurrent HTTP: 201+200, one origin/id/board PASS')

    version = reset_fixture()
    before = snapshot()
    body = json.dumps({'version': version, 'crm': crm()}).encode()
    with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
        raw.sendall((f'POST /api/stand/deals/1474/crm-close HTTP/1.1\r\n'
                     f'Host: 127.0.0.1:{port}\r\nCookie: session={cookie}\r\n'
                     f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n').encode() + body)
        # Close before recv: server commits without the client observing response.
    deadline = time.monotonic() + 5
    while snapshot()[1] != before[1] + 1:
        assert time.monotonic() < deadline, 'lost-response commit did not finish'
        time.sleep(.02)
    retry = post(version, {**crm(), 'payin_amount_usdt': 999999})
    assert retry.status_code == 200 and retry.json()['duplicate'] is True
    lost_id = retry.json()['deal']['id']
    assert snapshot()[:2] == (before[0] + 1, before[1] + 1)
    db = m.get_session()
    try:
        assert db.query(m.Deal).filter_by(id=lost_id).one().payin_amount_usdt == 100
    finally:
        db.close()
    print('PG lost response + changed-money retry: same id and money PASS')

    version = reset_fixture()
    before = snapshot()
    original = m._stand_completion_notes
    def fail(*_):
        raise RuntimeError('synthetic precommit failure')
    m._stand_completion_notes = fail
    try:
        failed = post(version)
    finally:
        m._stand_completion_notes = original
    assert failed.status_code == 500
    after = snapshot()
    assert after[:2] == before[:2]
    assert after[3]['deals'][0]['crmDealId'] is None
    print('PG precommit exception: CRM/link/board rollback PASS')

    version = reset_fixture()
    state = snapshot()[3]
    state['notes'].append({'id': 10, 'text': 'PG competing note'})
    edited = requests.put(base_url + '/api/stand/state', headers=headers,
                          json={'version': version, 'data': state}, timeout=10)
    assert edited.status_code == 200, edited.text
    stale = post(version)
    assert stale.status_code == 409 and stale.json()['error'] == 'conflict'
    assert stale.json()['data']['notes'][-1]['text'] == 'PG competing note'
    good = post(edited.json()['version'])
    assert good.status_code == 201, good.text
    assert snapshot()[3]['notes'][-1]['text'] == 'PG competing note'
    print('PG note/version conflict retained, then close PASS')

    version = reset_fixture()
    before = snapshot()
    foreign = post(version, {**crm(), 'bitrix_deal_id': 123456})
    assert foreign.status_code == 400
    assert snapshot()[:2] == before[:2]
    m._tron_tx_info = lambda _: {
        'amount_usdt': 100.0,
        'from_address': 'TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb',
        'to_address': 'TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74'}
    stated = snapshot()[3]
    stated['deals'][0]['payout'] = {'hashes': [{'hash': 'b' * 64,
                                                'net': 'TRC20', 'amount': 120}]}
    saved = requests.put(base_url + '/api/stand/state', headers=headers,
                         json={'version': version, 'data': stated}, timeout=10)
    assert saved.status_code == 200, saved.text
    version = saved.json()['version']
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        seed_synthetic_evidence(db, row, saved.json()['data'])
    finally:
        db.close()
    over = {**crm(), 'payout_amount_usdt': 120,
            'payout_tx_hashes': [{'hash': 'b' * 64, 'network': 'trc20',
                                  'amount_usdt': 120}]}
    warn = post(version, over)
    assert warn.status_code == 409 and warn.json()['requires_confirmation'] is True
    assert snapshot()[:2] == before[:2]
    accepted = post(version, {**over, 'confirm_payout_tx_overage': True})
    assert accepted.status_code == 201, accepted.text
    assert snapshot()[:2] == (before[0] + 1, before[1] + 1)
    print('PG foreign origin rejected; overage cancel/accept atomic PASS')

    def manual_fixture():
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            row.data = json.dumps({'deals': [], 'notes': []})
            row.version += 1
            row.generation = secrets.token_hex(16)
            db.commit()
            base_version = row.version
        finally:
            db.close()
        draft = board()['deals'][0]
        draft.update(manual=True, step='manual', sentToClient=False,
                     files={}, isTask=False)
        created = requests.put(base_url + '/api/stand/state', headers=headers,
            json={'version': base_version, 'data': {'deals': [draft], 'notes': []}}, timeout=10)
        assert created.status_code == 200, created.text
        assert created.json()['data']['deals'][0]['originMode'] == 'manual'
        return created.json()['version']

    version = manual_fixture()
    before = snapshot()
    gate = threading.Barrier(2)
    def manual_concurrent(_):
        gate.wait()
        return post(version)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pair = list(pool.map(manual_concurrent, (1, 2)))
    assert sorted(r.status_code for r in pair) == [200, 201]
    assert pair[0].json()['deal']['id'] == pair[1].json()['deal']['id']
    assert snapshot()[:2] == (before[0] + 1, before[1] + 1)
    print('PG manual concurrent HTTP: one origin/id/board PASS')

    version = manual_fixture()
    before = snapshot()
    body = json.dumps({'version': version, 'crm': crm()}).encode()
    with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
        raw.sendall((f'POST /api/stand/deals/1474/crm-close HTTP/1.1\r\n'
                     f'Host: 127.0.0.1:{port}\r\nCookie: session={cookie}\r\n'
                     f'Content-Type: application/json\r\nContent-Length: {len(body)}\r\n'
                     'Connection: close\r\n\r\n').encode() + body)
    deadline = time.monotonic() + 5
    while snapshot()[1] != before[1] + 1:
        assert time.monotonic() < deadline
        time.sleep(.02)
    retry = post(version)
    assert retry.status_code == 200 and retry.json()['duplicate'] is True
    assert snapshot()[:2] == (before[0] + 1, before[1] + 1)
    print('PG manual lost response: retry same id PASS')

    ledger = Path(os.environ['CALCCRM_FENCE_LEDGER'])
    entries = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    unexpected = [e for e in entries if not e.get('expected')]
    print(f'NETWORK_FENCE attempts={len(entries)} unexpected={len(unexpected)}')
    assert not unexpected
finally:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()
