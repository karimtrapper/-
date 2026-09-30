import json
import pytest
from app import app, get_session, StandState, _stand_strip_files, _stand_restore_files

def test_stand_files_payload(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'STAND_MODE', True)
    import app as m
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    
    manager = app.test_client()
    with manager.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'manager'
        sess['display_name'] = 'Manager'

    operator = app.test_client()
    with operator.session_transaction() as sess:
        sess['user_id'] = 2
        sess['role'] = 'operator'
        sess['display_name'] = 'Operator'

    with get_session() as db:
        m._stand_migrate()
        from app import AdminUser
        if not db.query(AdminUser).get(1):
            db.add(AdminUser(id=1, username='mgr', role='manager', password_hash=''))
        if not db.query(AdminUser).get(2):
            db.add(AdminUser(id=2, username='opr', role='operator', password_hash=''))
        state_data = {
            "deals": [
                {
                    "id": 1472,
                    "step": "s27",
                    "files": {
                        "receipt": [
                            {"file": "test.pdf", "bytes": 1000000, "data": "data:application/pdf;base64," + "A"*1000, "mime": "application/pdf"}
                        ]
                    },
                    "_managerDraft": {
                        "files": {
                            "receipt": [
                                {"file": "draft.pdf", "bytes": 500000, "data": "data:application/pdf;base64," + "B"*500, "mime": "application/pdf"}
                            ]
                        }
                    }
                }
            ]
        }
        db.query(StandState).delete()
        row = StandState(id=1, data=json.dumps(state_data), version=1)
        db.add(row)
        db.commit()

    resp = manager.get('/api/stand/state')
    assert resp.status_code == 200
    state = resp.json['data']

    file_info = state['deals'][0]['files']['receipt'][0]
    assert file_info['data'] == '__detached__'
    assert file_info['file'] == 'test.pdf'

    draft_info = state['deals'][0]['_managerDraft']['files']['receipt'][0]
    assert draft_info['data'] == '__detached__'

    # test missing files key restore
    state_no_files = json.loads(json.dumps(state))
    del state_no_files['deals'][0]['files']
    put_resp_no_files = manager.put('/api/stand/state', json={'version': 1, 'data': state_no_files})
    assert put_resp_no_files.status_code == 200
    with get_session() as db:
        row = db.query(StandState).get(1)
        db_state = json.loads(row.data)
        assert len(db_state['deals'][0]['files']['receipt'][0]['data']) > 1000

    put_resp = manager.put('/api/stand/state', json={'version': 2, 'data': state})
    assert put_resp.status_code == 200

    with get_session() as db:
        row = db.query(StandState).get(1)
        db_state = json.loads(row.data)
        assert len(db_state['deals'][0]['files']['receipt'][0]['data']) > 1000
        assert db_state['deals'][0]['_managerDraft']['files']['receipt'][0]['data'].startswith('data:application/pdf;base64,B')

    file_resp = manager.get('/api/stand/file/1472/receipt/0?draft=1')
    assert file_resp.status_code == 200
    assert b'\x04\x10A' in file_resp.data
    assert file_resp.headers.get('X-Content-Type-Options') == 'nosniff'
    
    file_resp2 = operator.get('/api/stand/file/1472/receipt/0')
    assert file_resp2.status_code == 200
    assert b'\x00\x00\x00' in file_resp2.data
    
    state['deals'][0]['files']['receipt'][0]['bytes'] = 999
    bad_put = manager.put('/api/stand/state', json={'version': 3, 'data': state})
    assert bad_put.status_code == 409
    
    del state['deals'][0]['_managerDraft']
    state['deals'][0]['files']['receipt'][0]['bytes'] = 1000000
    manager.put('/api/stand/state', json={'version': 3, 'data': state})
    
    file_resp3 = manager.get('/api/stand/file/1472/receipt/0?draft=1')
    assert file_resp3.status_code == 404
    
    no_auth = app.test_client()
    resp401 = no_auth.get('/api/stand/file/1472/receipt/0')
    assert resp401.status_code == 401

def test_identical_files_identity(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'STAND_MODE', True)
    import app as m
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    
    manager = app.test_client()
    with manager.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'manager'
        sess['display_name'] = 'Manager'

    with get_session() as db:
        m._stand_migrate()
        db.query(StandState).delete()
        state_data = {
            "deals": [
                {
                    "id": 1472,
                    "step": "s27",
                    "files": {
                        "receipt": [
                            {"file": "test.pdf", "bytes": 100, "data": "data:application/pdf;base64," + "A"*100, "mime": "application/pdf"},
                            {"file": "test.pdf", "bytes": 100, "data": "data:application/pdf;base64," + "B"*100, "mime": "application/pdf"},
                            {"file": "xss.html", "bytes": 100, "data": "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTs8L3NjcmlwdD4=", "mime": "text/html"}
                        ]
                    }
                }
            ]
        }
        row = StandState(id=1, data=json.dumps(state_data), version=1)
        db.add(row)
        db.commit()

    resp = manager.get('/api/stand/state')
    assert resp.status_code == 200
    state = resp.json['data']

    assert state['deals'][0]['files']['receipt'][0]['data'] == '__detached__'
    assert state['deals'][0]['files']['receipt'][1]['data'] == '__detached__'

    put_resp = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert put_resp.status_code == 200

    with get_session() as db:
        row = db.query(StandState).get(1)
        db_state = json.loads(row.data)
        assert db_state['deals'][0]['files']['receipt'][0]['data'].endswith('A'*100)
        assert db_state['deals'][0]['files']['receipt'][1]['data'].endswith('B'*100)

    # Test XSS prevention
    xss_resp = manager.get('/api/stand/file/1472/receipt/2')
    assert xss_resp.status_code == 400
    assert b'Invalid MIME type' in xss_resp.data

def test_manual_deal_drop_guard(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'STAND_MODE', True)
    import app as m
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    
    manager = app.test_client()
    with manager.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'manager'

    with get_session() as db:
        db.query(StandState).delete()
        state_data = {
            "deals": [
                {
                    "id": 1,
                    "manualNew": True,
                    "client": "John"
                },
                {
                    "id": 2,
                    "manualNew": True,
                    "amountUsdt": 100
                },
                {
                    "id": 3,
                    "manualNew": True,
                    "files": {"receipt": [{"file": "test"}]}
                },
                {
                    "id": 4,
                    "manualNew": True
                }
            ]
        }
        row = StandState(id=1, data=json.dumps(state_data), version=1)
        db.add(row)
        db.commit()

    resp = manager.get('/api/stand/state')
    state = resp.json['data']

    # Try to drop all deals
    state['deals'] = []
    put_resp = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert put_resp.status_code == 409
    assert put_resp.json['error'] == 'missing_deals_forbidden'

    # Try to drop just the truly empty deal (id 4)
    resp = manager.get('/api/stand/state')
    state = resp.json['data']
    state['deals'] = [d for d in state['deals'] if d['id'] != 4]
    
    put_resp = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert put_resp.status_code == 200

def test_put_erases_files_protection(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'STAND_MODE', True)
    import app as m
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    
    manager = app.test_client()
    with manager.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'manager'

    with get_session() as db:
        m._stand_migrate()
        db.query(StandState).delete()
        state_data = {
            "deals": [
                {
                    "id": 1472,
                    "step": "s27",
                    "files": {
                        "receipt": [
                            {"file": "test.pdf", "bytes": 100, "data": "data:application/pdf;base64," + "A"*100, "mime": "application/pdf"}
                        ]
                    }
                }
            ]
        }
        row = StandState(id=1, data=json.dumps(state_data), version=1)
        db.add(row)
        db.commit()

    resp = manager.get('/api/stand/state')
    state = resp.json['data']

    # Send files: null
    state['deals'][0]['files'] = None
    put_resp = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert put_resp.status_code == 200
    
    with get_session() as db:
        row = db.query(StandState).get(1)
        db_state = json.loads(row.data)
        assert len(db_state['deals'][0]['files']['receipt'][0]['data']) > 100

    # Send files explicitly empty (intentional deletion)
    state['deals'][0]['files'] = {'receipt': []}
    put_resp = manager.put('/api/stand/state', json={'version': 2, 'data': state})
    assert put_resp.status_code == 200
    with get_session() as db:
        row = db.query(StandState).get(1)
        db_state = json.loads(row.data)
        assert len(db_state['deals'][0]['files']['receipt']) == 0

def test_truly_empty_manual_draft_guard(monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'STAND_MODE', True)
    import app as m
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    
    manager = app.test_client()
    with manager.session_transaction() as sess:
        sess['user_id'] = 1
        sess['role'] = 'manager'

    with get_session() as db:
        db.query(StandState).delete()
        state_data = {
            "deals": [
                {
                    "id": 1,
                    "manualNew": True,
                    "_managerDraft": {"notes": [{"text": "hello"}]}
                },
                {
                    "id": 2,
                    "manualNew": True,
                    "files": {"receipt": [{"file": "test.pdf"}]}
                }
            ]
        }
        row = StandState(id=1, data=json.dumps(state_data), version=1)
        db.add(row)
        db.commit()

    resp = manager.get('/api/stand/state')
    state = resp.json['data']

    # Drop deal 1 (has draft notes)
    state_drop1 = json.loads(json.dumps(state))
    state_drop1['deals'] = [d for d in state_drop1['deals'] if d['id'] != 1]
    put1 = manager.put('/api/stand/state', json={'version': 1, 'data': state_drop1})
    assert put1.status_code == 409

    # Drop deal 2 (has files)
    state_drop2 = json.loads(json.dumps(state))
    state_drop2['deals'] = [d for d in state_drop2['deals'] if d['id'] != 2]
    put2 = manager.put('/api/stand/state', json={'version': 1, 'data': state_drop2})
    assert put2.status_code == 409


