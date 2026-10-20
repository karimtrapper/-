"""CRM manager controls update status while retaining historical names."""
import uuid

import pytest

from app import Manager, app, get_session


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_put_and_delete_manager_keep_row(client):
    name = f'QA manager {uuid.uuid4().hex}'
    response = client.post('/api/managers', json={'name': name})
    assert response.status_code == 200, response.get_json()
    manager_id = response.get_json()['manager']['id']
    try:
        changed = client.put(f'/api/managers/{manager_id}', json={'active': False})
        assert changed.status_code == 200, changed.get_json()
        assert changed.get_json()['manager']['active'] is False
        listed = client.get('/api/managers').get_json()['managers']
        assert next(m for m in listed if m['id'] == manager_id)['active'] is False

        changed = client.put(f'/api/managers/{manager_id}', json={'active': True})
        assert changed.status_code == 200
        assert changed.get_json()['manager']['active'] is True

        removed = client.delete(f'/api/managers/{manager_id}')
        assert removed.status_code == 200
        assert removed.get_json() == {'success': True}
        listed = client.get('/api/managers').get_json()['managers']
        assert next(m for m in listed if m['id'] == manager_id)['active'] is False
        session = get_session()
        try:
            assert session.query(Manager).get(manager_id).name == name
        finally:
            session.close()
    finally:
        session = get_session()
        try:
            session.query(Manager).filter(Manager.id == manager_id).delete()
            session.commit()
        finally:
            session.close()


def test_manager_mutations_validate_payload_and_missing_id(client):
    for payload in ({}, {'active': 1}, {'active': 'false'}, {'active': None}, []):
        assert client.put('/api/managers/999999999', json=payload).status_code == 400
    assert client.put('/api/managers/999999999', json={'active': True}).status_code == 404
    assert client.delete('/api/managers/999999999').status_code == 404


def test_manager_mutations_require_auth(monkeypatch):
    monkeypatch.delenv('LOCAL_NO_AUTH', raising=False)
    with app.test_client() as client:
        assert client.put('/api/managers/999999999', json={'active': False}).status_code == 401
        assert client.delete('/api/managers/999999999').status_code == 401
