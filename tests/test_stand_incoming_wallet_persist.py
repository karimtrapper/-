"""Роль читается из БД: вложенное чтение не должно откатывать запись доски."""
import json

import pytest
import app as m
from tests.test_stand_freehold_e2e_fixes import api as fake_role_api, base_api, chain
from tests.test_stand_demo_and_broker_wallet import (
    snapshot_1473, initial_board, prepare_after_rub, send_broker,
    test_prepay_actual_broker_wallet_to_close as prepaid_flow,
)
from tests.test_stand_prepay import seed, FOUNDER

REAL_CURRENT_ROLE = m.current_role


@pytest.fixture
def api(fake_role_api, monkeypatch):
    client, roles = fake_role_api
    monkeypatch.setattr(m, 'current_role', REAL_CURRENT_ROLE)
    monkeypatch.delenv('STAND_ALLOW_DEMO', raising=False)
    with client.session_transaction() as session:
        uid = session['user_id']
    with m.SessionLocal() as db:
        old_role = db.get(m.AdminUser, uid).role
    class Roles(list):
        def __setitem__(self, index, value):
            with m.SessionLocal() as db:
                db.get(m.AdminUser, uid).role = value
                db.commit()
            super().__setitem__(index, value)
    actual = Roles(roles)
    actual[0] = roles[0]
    yield client, actual
    with m.SessionLocal() as db:
        db.get(m.AdminUser, uid).role = old_role
        db.commit()


def durable_board():
    # Новая независимая сессия, а не identity map исходного запроса.
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        return row.version, json.loads(row.data)


@pytest.mark.parametrize('username_in_cookie', [False, True])
def test_wallet_post_survives_new_get_and_independent_db_read(api, username_in_cookie):
    initial_board(api); prepare_after_rub(api); saved = send_broker(api)
    with api[0].session_transaction() as session:
        if username_in_cookie: session['username'] = 'operator_test'
        else: session.pop('username', None)
    result = api[0].post('/api/stand/incoming/wallet', json={
        'dealId': 1484, 'walletId': 'founder', 'version': saved['version']})
    assert result.status_code == 200, result.json
    version, state = durable_board()
    assert version == result.json['version'] == saved['version'] + 1
    assert state['convs'][0]['walletId'] == 'founder'
    assert state['deals'][0]['walletId'] == 'founder'
    assert FOUNDER in state['deals'][0]['log'][-1]['text']
    loaded = api[0].get('/api/stand/state').json
    assert loaded['version'] == version
    assert loaded['data']['convs'][0]['walletId'] == 'founder'


def test_demo_flag_migration_is_committed_with_real_role_lookup(api):
    state = snapshot_1473()
    state['deals'][0].update(payinHashes=[], pay={}, log=[])
    seed(state)
    first = api[0].get('/api/stand/state').json
    version, saved = durable_board()
    assert version == first['version'] == 2
    assert saved['deals'][0]['demoTransfers'] is False
    assert api[0].get('/api/stand/state').json['version'] == version


def test_prepay_third_wallet_closes_with_real_database_roles(api, chain):
    prepaid_flow(api, chain, 'founder')
    _, state = durable_board()
    assert state['deals'][0]['closed']
    assert state['convs'][0]['walletId'] == 'founder'


def test_role_lookup_does_not_close_or_detach_callers_transaction(api):
    initial_board(api)
    db = m.get_session()
    try:
        row = m._stand_row(db, lock=True)
        old_version = row.version
        row.version += 1
        with m.app.test_request_context('/'):
            with api[0].session_transaction() as session:
                m.flask_session['user_id'] = session['user_id']
            assert m.current_role() == 'operator'
        assert row in db
        db.commit()
        assert durable_board()[0] == old_version + 1
    finally:
        db.close()


def test_real_role_change_is_applied_immediately_and_cookie_cannot_override(api):
    initial_board(api); prepare_after_rub(api); saved = send_broker(api)
    api[1][0] = 'manager'
    with api[0].session_transaction() as session:
        session['role'] = 'operator'
    response = api[0].post('/api/stand/incoming/wallet', json={
        'dealId': 1484, 'walletId': 'founder', 'version': saved['version']})
    assert response.status_code == 403
    version, state = durable_board()
    assert version == saved['version']
    assert state['convs'][0]['walletId'] == 'company'
