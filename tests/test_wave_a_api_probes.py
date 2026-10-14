"""Isolated API probes for the 2026-10-14 stand audit."""
import copy
import json

import requests

from tests.test_stand_board_concurrency import board_server
from tests.test_stand_dm import dm, note, sends, log_status
import app as appmod
import stand_notify as notify


def test_missing_version_cannot_overwrite_newer_money(board_server):
    base = board_server['BOARD_RACE_URL'] + '/api/stand/state'
    manager, operator = [
        {'Cookie': cookie} for cookie in json.loads(board_server['BOARD_RACE_COOKIES'])
    ]
    initial = requests.get(base, headers=manager, timeout=5).json()
    board = {'deals': [{
        'id': 98501, 'client': 'Synthetic', 'type': 'Обмен валюты',
        'step': 's4', 'amountRub': 100000, 'log': [],
    }], 'notes': []}
    created = requests.put(base, headers=manager, timeout=5,
                           json={'version': initial['version'], 'data': board})
    assert created.status_code == 200, created.text
    handed_off = copy.deepcopy(created.json()['data'])
    handed_off['deals'][0]['step'] = 's5'
    transferred = requests.put(base, headers=manager, timeout=5,
                               json={'version': created.json()['version'], 'data': handed_off})
    assert transferred.status_code == 200, transferred.text
    stale = copy.deepcopy(transferred.json()['data'])
    newer = copy.deepcopy(stale)
    newer['deals'][0]['amountRub'] = 120000
    saved = requests.put(base, headers=operator, timeout=5, json={
        'version': transferred.json()['version'], 'data': newer})
    assert saved.status_code == 200, saved.text
    stale['deals'][0]['amountRub'] = 100000
    guarded = requests.put(base, headers=operator, timeout=5, json={
        'version': transferred.json()['version'], 'data': stale})
    assert guarded.status_code == 409, guarded.text
    bypass = requests.put(base, headers=operator, timeout=5, json={'data': stale})
    after = requests.get(base, headers=operator, timeout=5).json()
    print('MISSING_VERSION', json.dumps({
        'guarded_status': guarded.status_code,
        'guarded_error': guarded.json().get('error'),
        'bypass_status': bypass.status_code,
        'bypass_error': bypass.json().get('error'),
        'before_bypass_amount': saved.json()['data']['deals'][0]['amountRub'],
        'after_bypass_amount': after['data']['deals'][0]['amountRub'],
        'versions': [transferred.json()['version'], saved.json()['version'],
                     after['version']],
    }, ensure_ascii=False))
    assert bypass.status_code == 400, bypass.text
    assert after['data']['deals'][0]['amountRub'] == 120000


def test_operator_cannot_skip_tasks_by_direct_put(board_server):
    base = board_server['BOARD_RACE_URL'] + '/api/stand/state'
    manager, operator = [
        {'Cookie': cookie} for cookie in json.loads(board_server['BOARD_RACE_COOKIES'])
    ]
    initial = requests.get(base, headers=manager, timeout=5).json()
    board = {'deals': [{
        'id': 98502, 'client': 'Synthetic', 'type': 'Обмен валюты',
        'step': 's4', 'amountRub': 100000, 'log': [],
    }], 'notes': []}
    created = requests.put(base, headers=manager, timeout=5,
                           json={'version': initial['version'], 'data': board})
    assert created.status_code == 200, created.text
    handed_off = copy.deepcopy(created.json()['data'])
    handed_off['deals'][0]['step'] = 's5'
    transferred = requests.put(base, headers=manager, timeout=5,
                               json={'version': created.json()['version'], 'data': handed_off})
    assert transferred.status_code == 200, transferred.text
    skipped = copy.deepcopy(transferred.json()['data'])
    skipped['deals'][0]['step'] = 's14'
    result = requests.put(base, headers=operator, timeout=5,
                          json={'version': transferred.json()['version'], 'data': skipped})
    print('SKIP_STEPS', json.dumps({
        'status': result.status_code, 'response': result.json().get('error'),
        'stored_step': requests.get(base, headers=operator, timeout=5).json()['data']['deals'][0]['step'],
    }, ensure_ascii=False))
    assert result.status_code == 409, result.text


def test_notification_suppressed_before_bind_is_not_retried(dm):
    calls, ids, board = dm
    with appmod.SessionLocal() as db:
        user = db.get(appmod.AdminUser, ids['operator'])
        user.telegram_user_id = None
        db.commit()
    board([note(98503, 'operator')])
    first = notify.deliver()
    first_status = log_status('dm-note-98503', ids['operator'])
    with appmod.SessionLocal() as db:
        user = db.get(appmod.AdminUser, ids['operator'])
        user.telegram_user_id = 103
        db.commit()
    second = notify.deliver()
    print('NOTIFY_BEFORE_BIND', json.dumps({
        'initial_status': first_status[0],
        'after_bind_status': log_status('dm-note-98503', ids['operator'])[0],
        'operator_sends': [x['chat_id'] for x in sends(calls) if x['chat_id'] == 103],
        'first': first, 'second': second,
    }, ensure_ascii=False))
    assert first_status[0] == 'suppressed'
    assert log_status('dm-note-98503', ids['operator'])[0] == 'suppressed'
    assert not [x for x in sends(calls) if x['chat_id'] == 103]


def test_manager_cannot_forge_operator_notification(dm):
    calls, ids, board = dm
    board([])
    client = appmod.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = ids['manager']
    current = client.get('/api/stand/state').json
    forged = copy.deepcopy(current['data'])
    forged['notes'].insert(0, {
        'id': 'api-audit-forged-98504', 'role': 'operator', 'dealId': 7,
        'text': 'Синтетика: Теодор подписал, можно отправлять',
    })
    result = client.put('/api/stand/state', json={
        'version': current['version'], 'data': forged})
    delivered_to = [x['chat_id'] for x in sends(calls)]
    print('FORGED_NOTE', json.dumps({
        'status': result.status_code,
        'error': result.json.get('error'),
        'stored_note': (result.json.get('data', {}).get('notes') or [None])[0]
        if result.status_code == 200 else None,
        'delivered_to': delivered_to,
    }, ensure_ascii=False))
    assert result.status_code == 200, result.json
    assert not delivered_to
    assert not any(n['id'] == 'api-audit-forged-98504' for n in result.json['data']['notes'])


def test_operator_cannot_erase_server_journal_event(board_server):
    root = board_server['BOARD_RACE_URL']
    manager, operator = [
        {'Cookie': cookie} for cookie in json.loads(board_server['BOARD_RACE_COOKIES'])
    ]
    board = {'deals': [{
        'id': 98505, 'client': 'Synthetic', 'type': 'Обмен валюты',
        'step': 's14', 'amountRub': 100000, 'payType': 'По реквизитам',
        'log': [],
    }], 'notes': []}
    # Seed an existing s14 board directly, as the repository's role tests do.
    with appmod.SessionLocal() as db:
        row = db.get(appmod.StandState, 1)
        row.data = json.dumps(board, ensure_ascii=False)
        row.version = 1
        db.commit()
    ping = requests.post(root + '/api/stand/s14/ping', headers=manager,
                         timeout=5, json={'version': 1,
                                          'dealId': 98505, 'text': 'Клиент отправил чек'})
    assert ping.status_code == 200, ping.text
    before = requests.get(root + '/api/stand/state', headers=operator, timeout=5).json()
    original_log = before['data']['deals'][0]['log']
    assert any('пинганул операциониста' in x['text'] for x in original_log)
    altered = copy.deepcopy(before['data'])
    altered['deals'][0]['log'] = []
    erased = requests.put(root + '/api/stand/state', headers=operator, timeout=5,
                          json={'version': before['version'], 'data': altered})
    after = requests.get(root + '/api/stand/state', headers=manager, timeout=5).json()
    print('ERASE_JOURNAL', json.dumps({
        'status': erased.status_code, 'error': erased.json().get('error'),
        'before': [x['text'] for x in original_log],
        'after': [x['text'] for x in after['data']['deals'][0]['log']],
    }, ensure_ascii=False))
    assert erased.status_code == 409, erased.text
    assert after['data']['deals'][0]['log'] == original_log


def test_second_application_with_unchanged_first_s5_is_accepted(board_server):
    base = board_server['BOARD_RACE_URL'] + '/api/stand/state'
    manager = {'Cookie': json.loads(board_server['BOARD_RACE_COOKIES'])[0]}
    first = {'id': 98511, 'code': 'СД-98511', 'client': 'Synthetic A',
             'type': 'Обмен валюты', 'pair': 'RUB → USDT', 'step': 's5',
             'amountRub': 100000, 'log': [], 'isTask': True, 'partial': False}
    initial = requests.get(base, headers=manager, timeout=5).json()
    created = requests.put(base, headers=manager, timeout=5, json={
        'version': initial['version'], 'data': {'deals': [first], 'notes': []}})
    assert created.status_code == 200, created.text
    second = {'id': 98512, 'code': 'СД-98512', 'client': 'Synthetic B',
              'type': 'Обмен валюты', 'pair': 'THB → USDT', 'step': 's5',
              'amountThb': 50000, 'log': [], 'isTask': True}
    board = copy.deepcopy(created.json()['data'])
    board['deals'].insert(0, second)
    added = requests.put(base, headers=manager, timeout=5, json={
        'version': created.json()['version'], 'data': board})
    after = requests.get(base, headers=manager, timeout=5).json()
    print('SECOND_APPLICATION_CLEAN', json.dumps({
        'status': added.status_code, 'error': added.json().get('error'),
        'ids': [d['id'] for d in after['data']['deals']],
    }, ensure_ascii=False))
    assert added.status_code == 200, added.text


def test_second_application_accepted_if_browser_adds_exact_defaults(board_server):
    base = board_server['BOARD_RACE_URL'] + '/api/stand/state'
    manager = {'Cookie': json.loads(board_server['BOARD_RACE_COOKIES'])[0]}
    first = {'id': 98513, 'code': 'СД-98513', 'client': 'Synthetic A',
             'type': 'Обмен валюты', 'pair': 'RUB → USDT', 'step': 's5',
             'amountRub': 100000, 'log': [], 'isTask': True, 'partial': False}
    initial = requests.get(base, headers=manager, timeout=5).json()
    created = requests.put(base, headers=manager, timeout=5, json={
        'version': initial['version'], 'data': {'deals': [first], 'notes': []}})
    assert created.status_code == 200, created.text
    board = copy.deepcopy(created.json()['data'])
    # newDeal() does not include compare; migrate() adds it after the GET response.
    board['deals'][0]['compare'] = False
    board['deals'].insert(0, {'id': 98514, 'client': 'Synthetic B',
        'type': 'Обмен валюты', 'pair': 'THB → USDT', 'step': 's5',
        'amountThb': 50000, 'log': [], 'isTask': True})
    added = requests.put(base, headers=manager, timeout=5, json={
        'version': created.json()['version'], 'data': board})
    print('SECOND_APPLICATION_NORMALIZED', json.dumps({
        'status': added.status_code, 'error': added.json().get('error'),
    }, ensure_ascii=False))
    assert added.status_code == 200
    assert len(added.json()['data']['deals']) == 2
