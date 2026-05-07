"""CR-08: тесты валидации пароля и advisory lock в /api/auth/setup."""
import pytest
import os
os.environ.setdefault('SECRET_KEY', 'test-only')
os.environ['SETUP_ENABLED'] = 'true'

from app import app, get_session, AdminUser, limiter

# Отключаем rate-limit на /api/auth/setup в тестах (3/minute мешает 6 тестам подряд).
limiter.enabled = False


@pytest.fixture
def clean_admins():
    """Чистим admin_users перед/после теста чтобы setup-флоу проходил."""
    s = get_session()
    s.query(AdminUser).delete()
    s.commit()
    s.close()
    yield
    s = get_session()
    s.query(AdminUser).delete()
    s.commit()
    s.close()


@pytest.fixture
def client():
    with app.test_client() as c:
        yield c


def test_setup_rejects_short_password(client, clean_admins):
    r = client.post('/api/auth/setup', json={
        'username': 'a', 'password': 'short', 'display_name': 'A'
    })
    assert r.status_code == 400
    assert 'минимум 12' in r.get_json()['error']


def test_setup_rejects_11_chars(client, clean_admins):
    r = client.post('/api/auth/setup', json={
        'username': 'a', 'password': 'eleven_chrs', 'display_name': 'A'
    })
    assert r.status_code == 400


def test_setup_accepts_12_chars(client, clean_admins):
    r = client.post('/api/auth/setup', json={
        'username': 'a', 'password': 'twelvechars1', 'display_name': 'A'
    })
    assert r.status_code == 200
    assert r.get_json()['success'] is True


def test_setup_blocked_when_admin_exists(client, clean_admins):
    # первый — успех
    r1 = client.post('/api/auth/setup', json={
        'username': 'a', 'password': 'twelvechars1', 'display_name': 'A'
    })
    assert r1.status_code == 200
    # второй — должен отказать
    r2 = client.post('/api/auth/setup', json={
        'username': 'b', 'password': 'twelvechars2', 'display_name': 'B'
    })
    assert r2.status_code == 403
    assert 'уже создан' in r2.get_json()['error']


def test_setup_no_username_or_password(client, clean_admins):
    for body in [
        {'username': '', 'password': 'twelvechars1'},
        {'username': 'a', 'password': ''},
        {},
    ]:
        r = client.post('/api/auth/setup', json=body)
        assert r.status_code == 400


def test_setup_disabled_when_env_off(client, clean_admins, monkeypatch):
    monkeypatch.setenv('SETUP_ENABLED', 'false')
    r = client.post('/api/auth/setup', json={
        'username': 'a', 'password': 'twelvechars1', 'display_name': 'A'
    })
    assert r.status_code == 403
