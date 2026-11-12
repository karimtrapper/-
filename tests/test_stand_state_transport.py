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
