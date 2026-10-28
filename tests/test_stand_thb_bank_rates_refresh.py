"""Кнопка менеджера «Обновить курс»: fresh=1 ставит запрос в
bank_rates_refresh_requests (дедуп за 2 минуты), /thb-bank-rates-status
отдаёт done, reload=1 только перечитывает таблицу без нового запроса."""
from datetime import datetime, timedelta

import pytest

import app as appmod


@pytest.fixture
def client_with_user(monkeypatch):
    appmod.app.config['TESTING'] = True
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    db = appmod.get_session()
    user = appmod.AdminUser(username='t-thb-refresh', password_hash='unused', role='admin')
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()
    appmod._THB_BANK_RATES_CACHE.update(data=None, ts=0.0)

    with appmod.app.test_client() as client:
        with client.session_transaction() as session:
            session['user_id'] = user_id
        yield client, user_id

    appmod._THB_BANK_RATES_CACHE.update(data=None, ts=0.0)
    appmod._ensure_bank_rates_refresh_table()
    with appmod.engine.begin() as conn:
        from sqlalchemy import text as _t
        conn.execute(_t('DELETE FROM bank_rates_refresh_requests'))
    db = appmod.get_session()
    db.query(appmod.AdminUser).filter_by(id=user_id).delete()
    db.commit()
    db.close()


def test_fresh_inserts_refresh_request(client_with_user, monkeypatch):
    client, _ = client_with_user
    monkeypatch.setattr(appmod.limiter, 'enabled', False)
    body = client.get('/api/stand/thb-bank-rates?fresh=1').json
    assert body['refresh_pending'] is True
    assert isinstance(body['request_id'], int)


def test_fresh_dedups_pending_request_within_two_minutes(client_with_user, monkeypatch):
    client, _ = client_with_user
    monkeypatch.setattr(appmod.limiter, 'enabled', False)
    first = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    second = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    assert second['inserted'] is False
    assert second['request_id'] == first['request_id']


def test_fresh_does_not_dedup_after_done(client_with_user):
    first = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    from sqlalchemy import text as _t
    with appmod.engine.begin() as conn:
        conn.execute(_t('UPDATE bank_rates_refresh_requests SET done_at = :now WHERE id = :id'),
                     {'now': datetime.utcnow(), 'id': first['request_id']})
    second = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    assert second['inserted'] is True
    assert second['request_id'] != first['request_id']


def test_fresh_does_not_dedup_after_two_minutes(client_with_user):
    first = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    from sqlalchemy import text as _t
    with appmod.engine.begin() as conn:
        conn.execute(_t('UPDATE bank_rates_refresh_requests SET requested_at = :old WHERE id = :id'),
                     {'old': datetime.utcnow() - timedelta(minutes=3), 'id': first['request_id']})
    second = appmod._thb_bank_rates_request_refresh('t-thb-refresh')
    assert second['inserted'] is True


def test_status_pending_then_done(client_with_user, monkeypatch):
    client, _ = client_with_user
    monkeypatch.setattr(appmod.limiter, 'enabled', False)
    body = client.get('/api/stand/thb-bank-rates?fresh=1').json
    request_id = body['request_id']
    pending = client.get(f'/api/stand/thb-bank-rates-status?request_id={request_id}').json
    assert pending['success'] and pending['done'] is False
    from sqlalchemy import text as _t
    with appmod.engine.begin() as conn:
        conn.execute(_t('UPDATE bank_rates_refresh_requests SET done_at = :now WHERE id = :id'),
                     {'now': datetime.utcnow(), 'id': request_id})
    done = client.get(f'/api/stand/thb-bank-rates-status?request_id={request_id}').json
    assert done['success'] and done['done'] is True


def test_status_unknown_request_id(client_with_user):
    client, _ = client_with_user
    res = client.get('/api/stand/thb-bank-rates-status?request_id=999999999')
    assert res.status_code == 404


def test_status_requires_login():
    with appmod.app.test_client() as client:
        res = client.get('/api/stand/thb-bank-rates-status?request_id=1')
    assert res.status_code == 401


def test_reload_rereads_without_inserting_request(client_with_user, monkeypatch):
    from datetime import datetime as dt
    client, _ = client_with_user
    from contextlib import contextmanager
    from types import SimpleNamespace
    calls = []
    real_engine = appmod.engine

    class Connection:
        def execute(self, statement):
            calls.append(str(statement))
            return SimpleNamespace(fetchall=lambda: [('Kasikornbank', 33.5, None, dt.now())])
    @contextmanager
    def connect():
        yield Connection()
    monkeypatch.setattr(appmod, 'engine', SimpleNamespace(connect=connect, begin=real_engine.begin,
                                                           dialect=real_engine.dialect))
    body = client.get('/api/stand/thb-bank-rates?reload=1').json
    assert body['success'] and body['rates']['Kasikornbank'] == 33.5
    assert 'refresh_pending' not in body
    appmod._ensure_bank_rates_refresh_table()
    with real_engine.begin() as conn:
        from sqlalchemy import text as _t
        count = conn.execute(_t('SELECT COUNT(*) FROM bank_rates_refresh_requests')).scalar()
    assert count == 0
