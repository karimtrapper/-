"""Прокси курсов банков-застройщиков для THB-инвойса фрихолда (Карим, 06.10):
GET /api/stand/thb-bank-rates читает ExGreen через единственный разрешённый
канал egress (exgreen_thb_bank_rates), кэширует 10 минут в памяти, отдаёт
stale=True при ошибке, если есть что отдавать из кэша.
"""
import pytest

import app as appmod
import stand_egress


@pytest.fixture
def client_with_user(monkeypatch):
    appmod.app.config['TESTING'] = True
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    db = appmod.get_session()
    user = appmod.AdminUser(username='t-thb-rates', password_hash='unused', role='admin')
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()
    appmod._THB_BANK_RATES_CACHE.update(data=None, ts=0.0)

    with appmod.app.test_client() as client:
        yield client, user_id

    appmod._THB_BANK_RATES_CACHE.update(data=None, ts=0.0)
    db = appmod.get_session()
    db.query(appmod.AdminUser).filter_by(id=user_id).delete()
    db.commit()
    db.close()


def _login(client, user_id):
    with client.session_transaction() as session:
        session['user_id'] = user_id


def test_requires_stand_mode(monkeypatch):
    # На проде (STAND_MODE=False) путь закрыт общим guard'ом раньше, чем роут
    # успевает ответить 404 — любой /api/* без сессии/ключа получает 401.
    # Сути это не меняет: без STAND_MODE этот эндпоинт недостижим в принципе.
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    with appmod.app.test_client() as client:
        res = client.get('/api/stand/thb-bank-rates')
    assert res.status_code == 401


def test_requires_login(client_with_user):
    client, _ = client_with_user
    res = client.get('/api/stand/thb-bank-rates')
    assert res.status_code == 401
    assert res.get_json()['success'] is False


def test_success_uses_only_allowed_channel(client_with_user, monkeypatch):
    client, user_id = client_with_user
    _login(client, user_id)
    calls = []

    def read_get(op, params=None, _base_url=None):
        calls.append((op, params))
        return (200, {'success': True,
                      'rates': {'Kasikornbank': 32.91, 'SCB': 32.9, 'Bangkok Bank': 32.9},
                      'source_updated_at': {'SCB': '2026-10-06 08:28:28'},
                      'updated_at': '2026-10-06T13:33:49+07:00'}, None)

    monkeypatch.setattr(stand_egress, 'read_get', read_get)
    res = client.get('/api/stand/thb-bank-rates')
    assert res.status_code == 200
    body = res.get_json()
    assert body['success'] is True
    assert body['rates']['SCB'] == 32.9
    assert body['stale'] is False
    assert calls == [('exgreen_thb_bank_rates', {})]


def test_cache_avoids_second_network_call_within_ttl(client_with_user, monkeypatch):
    client, user_id = client_with_user
    _login(client, user_id)
    calls = []

    def read_get(op, params=None, _base_url=None):
        calls.append(op)
        return (200, {'success': True, 'rates': {'SCB': 33.0}, 'updated_at': 't'}, None)

    monkeypatch.setattr(stand_egress, 'read_get', read_get)
    first = client.get('/api/stand/thb-bank-rates').get_json()
    second = client.get('/api/stand/thb-bank-rates').get_json()
    assert first == second
    assert len(calls) == 1  # второй запрос обслужен из кэша, не из сети


def test_network_error_returns_stale_cached_value(client_with_user, monkeypatch):
    client, user_id = client_with_user
    _login(client, user_id)

    def read_get_ok(op, params=None, _base_url=None):
        return (200, {'success': True, 'rates': {'SCB': 33.1}, 'updated_at': 't1'}, None)

    monkeypatch.setattr(stand_egress, 'read_get', read_get_ok)
    first = client.get('/api/stand/thb-bank-rates').get_json()
    assert first['success'] is True and first['stale'] is False

    # Кэш остыл — следующий вызов обязан снова дёргать сеть, которая теперь падает.
    appmod._THB_BANK_RATES_CACHE['ts'] = 0.0

    def read_get_fail(op, params=None, _base_url=None):
        return (None, None, 'network_error')

    monkeypatch.setattr(stand_egress, 'read_get', read_get_fail)
    second = client.get('/api/stand/thb-bank-rates').get_json()
    assert second['success'] is True
    assert second['stale'] is True
    assert second['rates']['SCB'] == 33.1


def test_no_cache_and_network_error_is_explicit_failure(client_with_user, monkeypatch):
    client, user_id = client_with_user
    _login(client, user_id)

    def read_get_fail(op, params=None, _base_url=None):
        return (None, None, 'network_error')

    monkeypatch.setattr(stand_egress, 'read_get', read_get_fail)
    res = client.get('/api/stand/thb-bank-rates').get_json()
    assert res['success'] is False
    assert res['stale'] is False


def test_channel_whitelisted_host_and_path_exact():
    spec = stand_egress._READ_CHANNELS['exgreen_thb_bank_rates']
    assert spec['host'] == 'api.exgreen.pro'
    assert spec['path'] == '/api/thb-bank-rates'
    assert spec['params'] == {}
    assert spec['required'] == set()
