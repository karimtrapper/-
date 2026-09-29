"""Synthetic real-browser trace for the network payin click; run by T31 fence."""
import json
import os
import socket
import threading
import time

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
import stand_notify
stand_notify.start_updates = lambda: False
import stand_sber_mirror
stand_sber_mirror.start = lambda appmod: False
import stand_egress
stand_egress.allow_test_target('127.0.0.1', int(os.environ['T31_PORT']))
stand_egress.read_get = lambda *args, **kwargs: (None, None, 'stand_blocked')

import app as A
from flask import jsonify
from playwright.sync_api import sync_playwright

@A.app.route('/api/stand/t31-noop', methods=['POST'])
def t31_noop():
    version, data = persisted()
    return jsonify({'success': True, 'version': version, 'data': data})


H = 'a' * 64
PART1, PART2, OVER, FOREIGN_HASH, PENDING = ('b' * 64, 'c' * 64, 'd' * 64,
                                              'e' * 64, 'f' * 64)
WALLET = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
SENDER = 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso'
OTHER = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
def fake_verify(tx_hash, *_args, **_kwargs):
    if tx_hash == PENDING:
        return {'status': 'pending', 'checkError': 'synthetic pending'}
    return {'status': 'confirmed', 'verifiedAmount': {
        H: 100, PART1: 1, PART2: 99, OVER: 110, FOREIGN_HASH: 100}[tx_hash],
        'from': OTHER if tx_hash == FOREIGN_HASH else SENDER, 'to': WALLET,
        'verifiedAt': 'synthetic', 'timestampMs': int(time.time()*1000)}
A.verify_transfer = fake_verify

def fixture(deals=None):
    main = {'id': 31, 'code': 'SYN-31', 'client': 'Synthetic',
        'type': 'Оплата недвижимости', 'kind': 'Недвижимость', 'payType': 'По реквизитам',
        'curBase': 'usdt', 'amountUsdt': 100, 'step': 's14', 'payerWallet': SENDER,
        'pay': {}, 'walletId': 'vitaly', 'log': [], 'payinHashes': []}
    return {'deals': deals or [main], 'wallets': [{'id': 'vitaly', 'addr': WALLET}],
        'notes': [], 'convs': [], 'seq': 31,
        'refs': [{'id': 1, 'name': 'Synthetic', 'code': 'SYN', 'prod': True}]}

def reset(deals=None):
    db = A.get_session()
    try:
        row = A._stand_row(db)
        row.data = json.dumps(fixture(deals))
        row.version = 1
        db.commit()
    finally:
        db.close()

def persisted():
    db = A.get_session()
    try:
        row = A._stand_row(db)
        return row.version, json.loads(row.data)
    finally:
        db.close()

db = A.get_session()
try:
    user = A.AdminUser(username='marina_t31', display_name='Marina T31', role='manager',
                       password_hash=A.AdminUser.hash_password('synthetic-t31'))
    db.add(user)
    db.commit()
finally:
    db.close()
reset()

port = int(os.environ['T31_PORT'])
threading.Thread(target=lambda: A.app.run(host='127.0.0.1', port=port, debug=False,
                                           use_reloader=False), daemon=True).start()
for _ in range(100):
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1', port)) == 0:
            break
    time.sleep(.05)
else:
    raise AssertionError('server did not start')

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(service_workers='block')
    base = f'http://127.0.0.1:{port}'
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base)
                  else route.abort())
    page = context.new_page()
    trace = []
    def capture(response):
        if response.request.method in ('POST', 'PUT') and response.url.endswith(
                ('/api/stand/payin/check', '/api/stand/state')):
            request = json.loads(response.request.post_data or '{}')
            body = response.json()
            deal = next((d for d in (body.get('data') or {}).get('deals', [])
                         if d.get('id') == 31), {})
            trace.append({'method': response.request.method, 'status': response.status,
                          'request_version': request.get('version'), 'response_version': body.get('version'),
                          'error': body.get('error'), 'step': deal.get('step'),
                          'hashes': len(deal.get('payinHashes') or []), 'body': body})
    page.on('response', capture)
    login = page.request.post(base + '/api/auth/login', data={'username': 'marina_t31',
                                                           'password': 'synthetic-t31'})
    assert login.status == 200, login.text()
    page.goto(base + '/tasks', wait_until='domcontentloaded')
    for _ in range(100):
        if page.evaluate('standVer !== null && !standBusy'):
            break
        time.sleep(.05)
    time.sleep(1)
    page.evaluate('S.open=31; S.view="task"; render()')
    def click(tx_hash):
        before = len(trace)
        page.evaluate('''async h => {document.getElementById('ph_31').value=h;
          await payinCheck(31);}''', tx_hash)
        page.wait_for_timeout(250)
        return trace[before:]
    def ui():
        return page.evaluate('''() => ({version:standVer, step:deal(31).step,
          hashes:(deal(31).payinHashes||[]).length,
          toast:document.querySelector('#toast').textContent})''')
    def reload_fixture(deals=None):
        reset(deals)
        page.reload(wait_until='domcontentloaded')
        for _ in range(100):
            if page.evaluate('standVer === 1 && !standBusy'):
                break
            time.sleep(.05)
        page.evaluate('S.open=31; S.view="task"; render()')
    full = click(H)
    version, state = persisted()
    d = state['deals'][0]
    assert [(r['method'],r['status'],r['request_version'],r['response_version']) for r in full] == [
        ('POST',200,None,2),('PUT',200,2,3)], full
    assert version == ui()['version'] == 3 and d['step'] == ui()['step'] == 's22'
    assert len(d['payinHashes']) == 1 and len(d['log']) == 2 and len(state['notes']) == 2

    reload_fixture()
    first = click(PART1)
    v1, s1 = persisted()
    assert [(r['method'],r['status']) for r in first] == [('POST',200)], first
    assert v1 == 2 and s1['deals'][0]['step'] == ui()['step'] == 's14'
    second = click(PART2)
    v2, s2 = persisted()
    assert [(r['method'],r['status']) for r in second] == [('POST',200),('PUT',200)], second
    assert v2 == ui()['version'] == 4 and s2['deals'][0]['step'] == ui()['step'] == 's22'
    assert len(s2['deals'][0]['payinHashes']) == 2 and s2['deals'][0]['incomeAmount'] == 100
    assert len(s2['deals'][0]['log']) == 3 and len(s2['notes']) == 2

    reload_fixture()
    over = click(OVER)
    vo, so = persisted()
    assert [(r['method'],r['status']) for r in over] == [('POST',200),('PUT',200)], over
    assert vo == ui()['version'] == 3 and so['deals'][0]['step'] == ui()['step'] == 's14m'
    assert 'Переплата' in so['deals'][0]['incomeReview'][0]

    reload_fixture()
    foreign = click(FOREIGN_HASH)
    vf, sf = persisted()
    assert [(r['method'],r['status']) for r in foreign] == [('POST',200)], foreign
    assert vf == 2 and sf['deals'][0]['step'] == ui()['step'] == 's14'
    assert sf['deals'][0]['payinHashes'][0]['otherSender'] is True
    assert sf['deals'][0].get('incomeAmount') is None
    before_manual = len(trace)
    page.evaluate('payinSenderOk(31,0)')
    page.wait_for_timeout(350)
    manual = trace[before_manual:]
    vm, sm = persisted()
    assert [(r['method'],r['status']) for r in manual] == [('PUT',200)], manual
    assert vm == ui()['version'] == 3 and sm['deals'][0]['step'] == ui()['step'] == 's22'
    assert len(sm['notes']) == 2 and len(sm['deals'][0]['log']) == 3

    reload_fixture()
    before_demo = len(trace)
    page.evaluate("payinDemo(31,'rest')")
    page.wait_for_timeout(350)
    demo = trace[before_demo:]
    vdemo, sdemo = persisted()
    assert [(r['method'],r['status']) for r in demo] == [('PUT',200)], demo
    assert vdemo == ui()['version'] == 2 and sdemo['deals'][0]['step'] == 's22'
    assert len(sdemo['notes']) == 2 and len(sdemo['deals'][0]['log']) == 2

    reset()
    noop_before = len(trace)
    noop = page.evaluate("standAction('/api/stand/t31-noop',{dealId:31})")
    assert noop['success'] is True and len(trace) == noop_before

    manual_deal = fixture()['deals'][0]
    manual_deal.update(manual=True, originMode='manual', step='manual')
    reset([manual_deal])
    forged = fixture([manual_deal])
    forged['deals'][0]['manual'] = False
    spoof = page.evaluate('''async payload => {const r=await fetch('/api/stand/state',{
      method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)});return {status:r.status,body:await r.json()};}''',
      {'version': 1, 'data': forged})
    assert spoof['status'] == 409 and spoof['body']['error'] == 'Происхождение сделки нельзя изменить', spoof
    assert persisted()[0] == 1 and persisted()[1]['deals'][0]['manual'] is True

    reload_fixture()
    pending = click(PENDING)
    vp, sp = persisted()
    assert [(r['method'],r['status']) for r in pending] == [('POST',422)], pending
    assert vp == ui()['version'] == 1 and sp['deals'][0]['payinHashes'] == []

    other = fixture()['deals'][0].copy()
    other.update(id=32, code='SYN-32', payinHashes=[{'hash': H, 'verified': True, 'amount': 3}])
    reload_fixture([fixture()['deals'][0], other])
    duplicate = click(H)
    vd, sd = persisted()
    assert [(r['method'],r['status']) for r in duplicate] == [('POST',409)], duplicate
    assert vd == ui()['version'] == 1 and sd['deals'][0]['payinHashes'] == []

    reload_fixture()
    conflict_seen = {'count': 0}
    def inject_conflict(route):
        if route.request.method == 'PUT':
            conflict_seen['count'] += 1
            db = A.get_session()
            try:
                row = A._stand_row(db)
                row.version += 1
                row.updated_by = 'synthetic colleague'
                db.commit()
            finally:
                db.close()
        route.continue_()
    context.route(base + '/api/stand/state', inject_conflict)
    conflict = click(H)
    context.unroute(base + '/api/stand/state', inject_conflict)
    vc, sc = persisted()
    assert [(r['method'],r['status'],r['response_version']) for r in conflict] == [
        ('POST',200,2),('PUT',409,3)], conflict
    assert conflict[1]['error'] == 'conflict' and conflict_seen['count'] == 1
    assert vc == ui()['version'] == 3 and sc['deals'][0]['step'] == ui()['step'] == 's14'
    assert len(sc['deals'][0]['payinHashes']) == 1
    assert 'коллега' in ui()['toast']

    raw = {'full': full, 'partial_first': first, 'partial_second': second,
           'overpay': over, 'foreign': foreign, 'manual': manual, 'demo': demo,
           'pending': pending, 'dedup': duplicate, 'conflict': conflict,
           'origin_spoof': spoof}
    with open(os.environ['T31_TRACE_OUT'], 'w') as out:
        json.dump(raw, out, ensure_ascii=False, indent=2)
    print('T31_CASES full=pass partial=pass overpay=pass foreign=pass manual=pass '
          'demo=pass pending=pass dedup=pass conflict=pass origin_spoof=pass noop=pass', flush=True)
    print('T31_RAW_TRACE', os.environ['T31_TRACE_OUT'], flush=True)
    browser.close()
