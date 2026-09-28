"""Личные уведомления стенда: только локальная БД и подмена канала Telegram."""

import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import text

import app as appmod
import stand_notify as notify


@pytest.fixture
def dm(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    notify.init(appmod)
    notify._bot_username = None
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_TG_CHAT', '-1003773734811')
    calls = []

    def telegram(method, payload):
        calls.append((method, payload))
        if method == 'getMe':
            return {'ok': True, 'result': {'username': 'grusha_stand_bot'}}
        if method == 'getWebhookInfo':
            return {'ok': True, 'result': {'url': ''}}
        if method == 'getUpdates':
            return {'ok': True, 'result': []}
        return {'ok': True}

    monkeypatch.setattr(notify.stand_egress, 'tg_call', telegram)
    db = appmod.SessionLocal()
    db.execute(text('DELETE FROM stand_notify_log'))
    db.execute(text('DELETE FROM stand_tg_bind'))
    db.execute(text('UPDATE stand_tg_offset SET next_offset=0 WHERE id=1'))
    db.query(appmod.AdminUser).filter(appmod.AdminUser.username.like('dm_test_%')).delete(synchronize_session=False)
    original_board = appmod._stand_row(db)
    original_data, original_version = original_board.data, original_board.version
    db.commit()
    users = {}
    for name, role, tg in [('karim', 'admin', 101), ('manager', 'manager', 102),
                           ('operator', 'operator', 103), ('admin', 'admin', 104)]:
        user = appmod.AdminUser(username='karim' if name == 'karim' else 'dm_test_' + name, display_name=name, role=role,
                                password_hash='unused', notify_enabled=True,
                                telegram_user_id=tg)
        db.add(user)
        users[name] = user
    db.commit()
    ids = {name: user.id for name, user in users.items()}
    db.close()

    def board(notes):
        db = appmod.SessionLocal()
        row = appmod._stand_row(db)
        row.data = json.dumps({'notes': notes, 'deals': [{'id': 7, 'code': 'T7', 'client': 'Иван'}]})
        db.commit(); db.close()

    yield calls, ids, board
    db = appmod.SessionLocal()
    db.execute(text('DELETE FROM stand_notify_log'))
    db.execute(text('DELETE FROM stand_tg_bind'))
    db.query(appmod.AdminUser).filter(appmod.AdminUser.id.in_(ids.values())).delete(synchronize_session=False)
    row = appmod._stand_row(db)
    row.data, row.version = original_data, original_version
    db.commit(); db.close()


def note(number, role='manager'):
    return {'id': f'dm-note-{number}', 'role': role, 'text': f'Задача {number}', 'dealId': 7}


def sends(calls):
    return [payload for method, payload in calls if method == 'sendMessage']


def log_status(note_id, admin_id):
    db = appmod.SessionLocal()
    try:
        return db.execute(text('SELECT status, attempts FROM stand_notify_log '
                               'WHERE note_id=:n AND admin_id=:a'), {'n': note_id, 'a': admin_id}).first()
    finally:
        db.close()


def test_roles_admin_and_dedup_after_double_delivery(dm):
    calls, ids, board = dm
    board([note(1), note(2, 'operator')])
    notify.deliver(); notify.deliver()
    assert [x['chat_id'] for x in sends(calls)] == [101, 103, 104, 101, 102, 104]
    assert all(x['chat_id'] > 0 for x in sends(calls))
    assert log_status('dm-note-1', ids['operator'])[0] == 'suppressed'
    assert log_status('dm-note-2', ids['manager'])[0] == 'suppressed'


def test_karim_only_mute_role_change_unbind_and_no_backfill(dm, monkeypatch):
    calls, ids, board = dm
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'karim_only')
    board([note(3)])
    notify.deliver()
    assert [x['chat_id'] for x in sends(calls)] == [101]
    assert log_status('dm-note-3', ids['manager'])[0] == 'suppressed'
    board([note(4), note(3)])
    notify.deliver()
    assert [x['chat_id'] for x in sends(calls)] == [101, 101]
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    db = appmod.SessionLocal()
    manager = db.query(appmod.AdminUser).get(ids['manager'])
    manager.notify_enabled = False
    db.commit(); db.close()
    board([note(5), note(4), note(3)])
    notify.deliver()
    assert log_status('dm-note-5', ids['manager'])[0] == 'suppressed'
    db = appmod.SessionLocal()
    manager = db.query(appmod.AdminUser).get(ids['manager'])
    manager.notify_enabled = True
    manager.role = 'operator'
    manager.telegram_user_id = None
    db.commit(); db.close()
    board([note(6, 'operator'), note(5), note(4), note(3)])
    notify.deliver()
    assert log_status('dm-note-6', ids['manager'])[0] == 'suppressed'
    assert log_status('dm-note-5', ids['manager'])[0] == 'suppressed'


def test_failed_403_429_and_timeout_retry_without_group(dm, monkeypatch):
    calls, ids, board = dm
    board([note(7)])
    outcomes = iter([{'ok': False, 'error_code': 403}, {'ok': False, 'error_code': 429},
                     TimeoutError(), {'ok': True}])
    def telegram(method, payload):
        calls.append((method, payload))
        if method != 'sendMessage' or payload['chat_id'] != 102:
            return {'ok': True}
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(notify.stand_egress, 'tg_call', telegram)
    for attempt in range(1, 5):
        notify.deliver()
        assert log_status('dm-note-7', ids['manager'])[1] == attempt
    assert log_status('dm-note-7', ids['manager'])[0] == 'sent'
    assert all(x['chat_id'] != -1003773734811 for x in sends(calls))


def test_bind_valid_expired_repeated_group_and_offset_restart(dm, monkeypatch):
    calls, ids, _ = dm
    link = notify.create_bind(ids['manager'])
    nonce = parse_qs(urlparse(link).query)['start'][0].removeprefix('bind_')
    group = {'update_id': 1, 'message': {'chat': {'type': 'group', 'id': -10},
                                       'from': {'id': 777}, 'text': '/start bind_' + nonce}}
    assert not notify.process_update(group)
    assert not notify.process_update({'message': {'chat': {'type': 'private', 'id': 777},
                                                  'from': {'id': 777}, 'text': '/start'}})
    monkeypatch.setattr(notify.stand_egress, 'tg_call',
                        lambda method, payload: {'ok': True, 'result': [group, {
                            'update_id': 2, 'message': {'chat': {'type': 'private', 'id': 777},
                            'from': {'id': 777}, 'text': '/start bind_' + nonce}}]} if method == 'getUpdates' else {'ok': True})
    assert notify.poll_once()
    assert not notify.process_update({'message': {'chat': {'type': 'private', 'id': 777},
                                                  'from': {'id': 777}, 'text': '/start bind_' + nonce}})
    db = appmod.SessionLocal()
    assert db.query(appmod.AdminUser).get(ids['manager']).telegram_user_id == 777
    assert db.execute(text('SELECT next_offset FROM stand_tg_offset WHERE id=1')).scalar() == 3
    db.close()
    assert notify.poll_once()  # апдейты 1 и 2 повторились; offset не откатывается
    expired = notify.create_bind(ids['operator']).split('bind_')[1]
    db = appmod.SessionLocal()
    db.execute(text('UPDATE stand_tg_bind SET expires_at=:past WHERE nonce=:nonce'),
               {'past': datetime.utcnow() - timedelta(seconds=1), 'nonce': expired})
    db.commit(); db.close()
    assert not notify.consume_bind(expired, 888)


def test_webhook_disables_poll_and_notify_test_requires_admin(dm, monkeypatch):
    calls, ids, _ = dm
    monkeypatch.setenv('STAND_TG_TOKEN', 'fake-token')
    monkeypatch.setattr(notify.stand_egress, 'tg_call',
                        lambda method, payload: {'ok': True, 'result': {'url': 'https://example.test/hook'}})
    assert not notify.start_updates()
    assert notify.status() == 'webhook_set'
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = ids['manager']
        assert client.post('/api/stand/notify-test/' + str(ids['manager'])).status_code == 403
        assert client.get('/api/stand/tg-status').status_code == 403
        with client.session_transaction() as sess:
            sess['user_id'] = ids['admin']
        monkeypatch.setattr(notify.stand_egress, 'tg_call', lambda method, payload: {'ok': True})
        assert client.post('/api/stand/notify-test/' + str(ids['manager'])).json['status'] == 'sent'
        monkeypatch.setenv('STAND_NOTIFY_MODE', 'karim_only')
        assert client.post('/api/stand/notify-test/' + str(ids['manager'])).json['status'] == 'suppressed'


def test_double_put_and_poll_do_not_resend(dm, monkeypatch):
    calls, ids, board = dm
    board([])
    monkeypatch.setattr(appmod, 'current_role', lambda: 'admin')
    with appmod.app.test_client() as client:
        # После gate стенда (T2) обхода LOCAL_NO_AUTH нет — входим сессией админа.
        with client.session_transaction() as sess:
            sess['user_id'] = ids['admin']
        first = client.get('/api/stand/state').json
        state = first['data']
        state['notes'] = [note(8)]
        assert client.put('/api/stand/state', json={'version': first['version'], 'data': state}).status_code == 200
        second = client.get('/api/stand/state').json
        assert client.put('/api/stand/state', json={'version': second['version'], 'data': second['data']}).status_code == 200
    notify.deliver(); notify.deliver()  # два фоновых прохода после PUT
    assert [x['chat_id'] for x in sends(calls)] == [101, 102, 104]
    assert log_status('dm-note-8', ids['manager'])[0] == 'sent'


def test_bind_route_uses_current_account_and_policy_requires_numeric_private_id(dm, monkeypatch):
    calls, ids, _ = dm
    with appmod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = ids['manager']
        result = client.post('/api/stand/tg-bind', json={'admin_id': ids['admin']})
        assert result.status_code == 200
        nonce = result.json['url'].split('bind_')[1]
    db = appmod.SessionLocal()
    assert db.execute(text('SELECT admin_id FROM stand_tg_bind WHERE nonce=:nonce'),
                      {'nonce': nonce}).scalar() == ids['manager']
    db.close()
    assert not notify.can_send('telegram', '-1003773734811', 'sendMessage')
    assert not notify.can_send('telegram', -1003773734811, 'sendMessage')
    assert not notify.can_send('telegram', True, 'sendMessage')
    assert not notify.process_update({'message': {'chat': {'type': 'private', 'id': 999},
                                                  'from': {'id': '999'}, 'text': '/start bind_' + nonce}})
    assert notify.process_update({'message': {'chat': {'type': 'private', 'id': 999},
                                              'from': {'id': 999}, 'text': '/start bind_' + nonce}})
    assert notify.can_send('telegram', 999, 'sendMessage')
