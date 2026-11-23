"""Stand board transport must keep version, projection and repair semantics."""
import gzip
import json
import secrets

import app as m
from tests.test_stand_crm_close_atomic import _client, _setup


def _packed(snapshot):
    return gzip.compress(json.dumps({'version': snapshot['version'],
        'fileStorageVersion': 1, 'data': snapshot['data']}).encode())


def _put(client, body, encoding='gzip'):
    return client.put('/api/stand/state', data=body,
        headers={'Content-Type': 'application/json', 'Content-Encoding': encoding})


def test_compressed_board_save_conflict_and_decode_errors(monkeypatch):
    client = _client(_setup(monkeypatch))
    before = client.get('/api/stand/state').json
    body = _packed(before)
    saved = _put(client, body)
    assert saved.status_code == 200 and saved.json['success'] is True
    assert client.get('/api/stand/state').json['version'] == before['version'] + 1
    stale = _put(client, body)
    assert stale.status_code == 409 and stale.json['error'] == 'conflict'
    assert _put(client, b'bad-gzip').status_code == 400
    assert _put(client, gzip.compress(b'123')).json['error'] == 'invalid_json'
    assert _put(client, b'{}', 'br').json['error'] == 'unsupported_content_encoding'
    monkeypatch.setitem(m.app.config, 'MAX_CONTENT_LENGTH', 2048)
    oversized = _put(client, gzip.compress(b' ' * 2050))
    assert oversized.status_code == 413 and oversized.json['error'] == 'state_too_large'


def test_board_etag_respects_generation_and_role(monkeypatch):
    uid = _setup(monkeypatch)
    manager = _client(uid)
    first = manager.get('/api/stand/state')
    assert first.status_code == 200 and first.headers['ETag']
    same = manager.get('/api/stand/state', headers={'If-None-Match': first.headers['ETag']})
    assert same.status_code == 304 and not same.data
    assert same.headers['Cache-Control'] == 'private, no-cache'
    assert 'Cookie' in same.headers['Vary']
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        row.generation = secrets.token_hex(16)
        db.commit()
    changed = manager.get('/api/stand/state', headers={'If-None-Match': first.headers['ETag']})
    assert changed.status_code == 200 and changed.headers['ETag'] != first.headers['ETag']
    with m.SessionLocal() as db:
        operator = m.AdminUser(username='transport-operator-' + secrets.token_hex(4),
            role='operator', password_hash='unused')
        db.add(operator)
        db.commit()
        operator_id = operator.id
    other_role = _client(operator_id).get('/api/stand/state',
        headers={'If-None-Match': changed.headers['ETag']})
    assert other_role.status_code == 200 and other_role.headers['ETag'] != changed.headers['ETag']
    assert all('_managerDraft' not in deal for deal in other_role.json['data']['deals'])


def test_analytics_snapshot_never_repairs_or_creates_board(monkeypatch):
    browser = _client(_setup(monkeypatch))
    url = '/api/stand/state?read_only=1'
    assert m.app.test_client().get(url).status_code == 401

    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        state['deals'][0]['_managerDraft'] = {'comment': 'Fixture manager draft'}
        row.data = json.dumps(state)
        before = (row.version, row.data, row.notified, row.generation)
        operator = m.AdminUser(username='analytics-reader-' + secrets.token_hex(4),
                               role='operator', password_hash='unused')
        db.add(operator)
        db.commit()
        operator_id = operator.id

    def forbidden_repair(*args, **kwargs):
        raise AssertionError('An analytics snapshot tried to repair the board or send a note')

    monkeypatch.setattr(m.stand_demo, 'repair', forbidden_repair)
    monkeypatch.setattr(m, '_stand_move_legacy_s14_to_operator', forbidden_repair)
    monkeypatch.setattr(m, '_stand_reconcile_payto_confirm_notes', forbidden_repair)
    monkeypatch.setattr(m, '_stand_deliver_notes', forbidden_repair)
    response = browser.get(url)
    assert response.status_code == 200
    assert response.json['version'] == before[0]
    assert response.json['data']['deals'][0]['_managerDraft'] == {'comment': 'Fixture manager draft'}
    assert 'Cookie' in response.headers['Vary']
    validator = {'If-None-Match': response.headers['ETag']}
    assert browser.get(url, headers=validator).status_code == 304
    projected = _client(operator_id).get(url, headers=validator)
    assert projected.status_code == 200 and projected.json['role'] == 'operator'
    assert all('_managerDraft' not in deal for deal in projected.json['data']['deals'])

    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        assert (row.version, row.data, row.notified, row.generation) == before
        db.delete(row)
        db.commit()
    empty = browser.get(url)
    assert empty.status_code == 200 and empty.json['version'] == 0
    assert not empty.json['data'].get('deals')
    with m.SessionLocal() as db:
        assert db.get(m.StandState, 1) is None


def test_analytics_creation_timestamp_is_server_owned(monkeypatch):
    manager_id = _setup(monkeypatch)
    browser = _client(manager_id)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    snapshot = browser.get('/api/stand/state?read_only=1').json
    legacy = snapshot['data']['deals'][0]
    assert 'createdTs' not in legacy
    legacy['createdTs'] = 978307200000
    snapshot['data']['deals'].append({
        'id': 2001, 'code': 'СД-2001', 'client': 'Fixture new deal',
        'managerUserId': manager_id, 'step': 's5', 'isTask': True, 'closed': False,
        'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'payType': 'По реквизитам',
        'amountThb': 10000, 'source': 'none',
        'createdTs': legacy['createdTs'], 'closedTs': legacy['createdTs'],
    })
    saved = _put(browser, _packed(snapshot))
    assert saved.status_code == 200, saved.json
    old, new = saved.json['data']['deals']
    assert 'createdTs' not in old
    assert 'closedTs' not in new
    stamp = new.pop('createdTs')
    assert stamp > legacy['createdTs']
    edited = _put(browser, _packed(saved.json))
    assert edited.status_code == 200, edited.json
    assert edited.json['data']['deals'][-1]['createdTs'] == stamp
