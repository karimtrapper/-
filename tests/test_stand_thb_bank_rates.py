"""Прокси курсов банков-застройщиков для THB-инвойса фрихолда (Карим, 06.10):
GET /api/stand/thb-bank-rates читает локальную таблицу bank_rates, кэширует 10 минут в памяти, отдаёт
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


def fake_bank_database(monkeypatch, rows=None, error=False):
    from contextlib import contextmanager
    from types import SimpleNamespace
    calls = []
    class Connection:
        def execute(self, statement):
            calls.append(str(statement))
            if error:
                raise RuntimeError('synthetic database unavailable')
            return SimpleNamespace(fetchall=lambda: rows or [])
    @contextmanager
    def connect():
        yield Connection()
    monkeypatch.setattr(appmod, 'engine', SimpleNamespace(connect=connect))
    return calls


def test_success_reads_bank_rates_without_external_channel(client_with_user, monkeypatch):
    from datetime import datetime
    client, user_id = client_with_user
    _login(client, user_id)
    calls = fake_bank_database(monkeypatch, [('SCB', 32.9, 'source time', datetime.now())])
    body = client.get('/api/stand/thb-bank-rates').json
    assert body['success'] and body['rates']['SCB'] == 32.9 and not body['stale']
    assert len(calls) == 1 and 'FROM bank_rates' in calls[0]
    assert 'ROW_NUMBER() OVER (PARTITION BY bank ORDER BY fetched_at DESC)' in calls[0]
    assert 'exgreen_thb_bank_rates' not in stand_egress._READ_CHANNELS


def test_cache_avoids_second_query_within_ttl(client_with_user, monkeypatch):
    from datetime import datetime
    client, user_id = client_with_user
    _login(client, user_id)
    calls = fake_bank_database(monkeypatch, [('SCB', 33, None, datetime.now())])
    first = client.get('/api/stand/thb-bank-rates').json
    assert client.get('/api/stand/thb-bank-rates').json == first
    assert first['success'] and len(calls) == 1


def test_fresh_bypasses_cache_and_is_limited_per_user(client_with_user, monkeypatch):
    from datetime import datetime
    # Некоторые независимые тесты отключают общий limiter и не восстанавливают его.
    monkeypatch.setattr(appmod.limiter, 'enabled', True)
    client, user_id = client_with_user
    _login(client, user_id)
    calls = fake_bank_database(monkeypatch, [('SCB', 33, None, datetime.now())])
    assert client.get('/api/stand/thb-bank-rates').status_code == 200
    assert client.get('/api/stand/thb-bank-rates?fresh=1').status_code == 200
    assert len(calls) == 2
    assert client.get('/api/stand/thb-bank-rates?fresh=1').status_code == 429
    assert len(calls) == 2
    assert client.get('/api/stand/thb-bank-rates').status_code == 200
    # Другой залогиненный пользователь имеет собственный лимит.
    db = appmod.get_session()
    other = appmod.AdminUser(username='t-thb-rates-other', password_hash='unused', role='admin')
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()
    with client.session_transaction() as session:
        session['user_id'] = other_id
    assert client.get('/api/stand/thb-bank-rates?fresh=1').status_code == 200
    assert len(calls) == 3
    db = appmod.get_session()
    db.query(appmod.AdminUser).filter_by(id=other_id).delete()
    db.commit()
    db.close()


def test_database_error_returns_stale_cached_value(client_with_user, monkeypatch):
    from datetime import datetime
    client, user_id = client_with_user
    _login(client, user_id)
    fake_bank_database(monkeypatch, [('SCB', 33.1, None, datetime.now())])
    assert client.get('/api/stand/thb-bank-rates').json['success']
    appmod._THB_BANK_RATES_CACHE['ts'] = 0
    fake_bank_database(monkeypatch, error=True)
    body = client.get('/api/stand/thb-bank-rates').json
    assert body['success'] and body['stale'] and body['rates']['SCB'] == 33.1


def test_no_cache_and_database_error_is_explicit_failure(client_with_user, monkeypatch):
    client, user_id = client_with_user
    _login(client, user_id)
    fake_bank_database(monkeypatch, error=True)
    body = client.get('/api/stand/thb-bank-rates').json
    assert not body['success'] and not body['stale']


def test_old_database_rows_are_stale(client_with_user, monkeypatch):
    from datetime import datetime, timedelta
    client, user_id = client_with_user
    _login(client, user_id)
    fake_bank_database(monkeypatch, [('SCB', 33, None, datetime.now()-timedelta(hours=4))])
    body = client.get('/api/stand/thb-bank-rates').json
    assert body['success'] and body['stale']


def test_old_bank_quote_is_stale_even_when_recently_fetched(client_with_user, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    client, user_id = client_with_user
    _login(client, user_id)
    old_source = (datetime.now(ZoneInfo('Asia/Bangkok')) - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')
    fake_bank_database(monkeypatch, [('SCB', 33, old_source, datetime.now())])
    body = client.get('/api/stand/thb-bank-rates').json
    assert body['success'] and body['stale']
