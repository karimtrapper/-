"""T14: профиль lk_send_only (прод-бот @grusha_lk_bot, только отправка) и
явное назначение исполнителя задачника.

Сетевой уровень (что lk_call умеет вызывать только sendMessage, что
идентичность бота проверяется ДО сети по префиксу токена и латчится после
почтконтроля ответа) — здесь же, в процессе: stand_egress.install() в этих
тестах не вызывается, поэтому socket не патчится и заворачивать вызовы можно
прямо на локальный http.server, как и остальной стенд-код это делает.
"""
import json
import threading
import http.server

import pytest
from sqlalchemy import text

import app as appmod
import stand_egress
import stand_notify as notify


def _fake_server(handler_factory):
    srv = http.server.HTTPServer(('127.0.0.1', 0), handler_factory())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _identity_handler(from_id=555, username='grusha_lk_bot', is_bot=True,
                       chat_type='private', ok=True, status=200):
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
            hits.append({'path': self.path, 'body': body})
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            payload = {'ok': ok, 'result': {
                'message_id': 1,
                'from': {'id': from_id, 'is_bot': is_bot, 'username': username},
                'chat': {'id': body.get('chat_id'), 'type': chat_type},
            }} if ok else {'ok': False, 'error_code': status, 'description': 'nope'}
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *a):
            pass

    Handler.hits = hits
    return lambda: Handler


@pytest.fixture(autouse=True)
def _reset_lk_state():
    stand_egress._lk_blocked = False
    yield
    stand_egress._lk_blocked = False


@pytest.fixture
def lk(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    appmod._stand_migrate()
    notify.init(appmod)
    notify._bot_username = None
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    db = appmod.SessionLocal()
    db.execute(text('DELETE FROM stand_notify_log'))
    db.query(appmod.AdminUser).filter(appmod.AdminUser.username.like('lk_test_%')).delete(synchronize_session=False)
    row = appmod._stand_row(db)
    original_data, original_version = row.data, row.version
    db.commit()
    users = {}
    for name, role, tg, disabled in [
        ('karim', 'admin', 201, False), ('manager', 'manager', 202, False),
        ('manager2', 'manager', 203, False), ('operator', 'operator', 204, False),
        ('offduty', 'manager', 205, True),
    ]:
        uname = 'karim' if name == 'karim' else 'lk_test_' + name
        user = appmod.AdminUser(username=uname, display_name=name, role=role,
                                password_hash='unused', notify_enabled=True,
                                telegram_user_id=tg, login_disabled=disabled)
        db.add(user)
        users[name] = user
    db.commit()
    ids = {name: u.id for name, u in users.items()}
    db.close()

    def board(notes, deals=None):
        db = appmod.SessionLocal()
        row = appmod._stand_row(db)
        row.data = json.dumps({
            'notes': notes,
            'deals': deals or [{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4'}],
        })
        db.commit()
        db.close()

    yield ids, board
    db = appmod.SessionLocal()
    db.execute(text('DELETE FROM stand_notify_log'))
    db.query(appmod.AdminUser).filter(appmod.AdminUser.id.in_(ids.values())).delete(synchronize_session=False)
    row = appmod._stand_row(db)
    row.data, row.version = original_data, original_version
    db.commit()
    db.close()


def note(number, role='manager', deal_id=7):
    return {'id': f'lk-note-{number}', 'role': role, 'text': f'Задача {number}', 'dealId': deal_id}


def log_rows(note_id):
    """Строка исполнителя-адресата живёт под составным ключом
    '<note_id>::assignee:<id>' (см. deliver()) — здесь собираем оба варианта
    ключа в один словарь по admin_id, как удобно тестам."""
    db = appmod.SessionLocal()
    try:
        return {r[0]: (r[1], r[2]) for r in db.execute(
            text("SELECT admin_id, status, attempts FROM stand_notify_log "
                "WHERE note_id=:n OR note_id LIKE :prefix"),
            {'n': note_id, 'prefix': note_id + '::assignee:%'}).all()}
    finally:
        db.close()


# ---------- уровень канала: lk_call ----------

def test_lk_call_wrong_token_prefix_never_touches_network(monkeypatch):
    factory = _identity_handler()
    srv = _fake_server(factory)
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '999:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')  # не совпадает с префиксом токена
    stand_egress.set_policy(lambda *a: True)
    res = stand_egress.lk_call({'chat_id': 1}, _base_url=f'http://127.0.0.1:{srv.server_port}')
    assert res == {'ok': False, 'error': 'bot_identity_mismatch'}
    assert len(factory().hits) == 0


def test_lk_call_missing_pinned_id_never_touches_network(monkeypatch):
    srv = _fake_server(_identity_handler())
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.delenv('STAND_LK_BOT_ID', raising=False)
    stand_egress.set_policy(lambda *a: True)
    res = stand_egress.lk_call({'chat_id': 1}, _base_url=f'http://127.0.0.1:{srv.server_port}')
    assert res['ok'] is False


def test_lk_call_no_token_configured(monkeypatch):
    monkeypatch.delenv('STAND_LK_BOT_TOKEN', raising=False)
    res = stand_egress.lk_call({'chat_id': 1})
    assert res == {'ok': False, 'error': 'no_token'}


def test_lk_call_valid_identity_reaches_fake_server(monkeypatch):
    Handler = _identity_handler(from_id=555, username='grusha_lk_bot')
    srv = _fake_server(Handler)
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    stand_egress.set_policy(lambda channel, recipient, op: channel == 'telegram_lk' and recipient == 42)
    res = stand_egress.lk_call({'chat_id': 42, 'text': 'hi'}, _base_url=f'http://127.0.0.1:{srv.server_port}')
    assert res['ok'] is True


def test_lk_call_identity_mismatch_latches_no_retry(monkeypatch):
    handler_factory = _identity_handler(username='someone_else')
    srv = _fake_server(handler_factory)
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    stand_egress.set_policy(lambda *a: True)
    base = f'http://127.0.0.1:{srv.server_port}'
    first = stand_egress.lk_call({'chat_id': 42}, _base_url=base)
    assert first == {'ok': False, 'error': 'bot_identity_mismatch'}
    assert stand_egress._lk_blocked is True
    second = stand_egress.lk_call({'chat_id': 42}, _base_url=base)
    assert second == {'ok': False, 'error': 'bot_identity_mismatch'}


def test_lk_call_only_sendmessage_url_shape(monkeypatch):
    """lk_call не принимает method — физически не может собрать другой путь."""
    import inspect
    assert 'method' not in inspect.signature(stand_egress.lk_call).parameters


def test_lk_call_rejects_group_and_non_int_chat_id(monkeypatch):
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    stand_egress.set_policy(lambda *a: True)
    for bad in (-100123, '42', True, 0):
        res = stand_egress.lk_call({'chat_id': bad})
        assert res == {'ok': False, 'error': 'invalid_chat_id'}


# ---------- can_send('telegram_lk', ...) ----------

def test_can_send_telegram_lk_duplicate_active_ids_denied(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    db = appmod.SessionLocal()
    db.query(appmod.AdminUser).filter_by(id=ids['manager2']).update({'telegram_user_id': 202})
    db.commit()
    db.close()
    assert notify.can_send('telegram_lk', 202, 'sendMessage') is False


def test_can_send_telegram_lk_foreign_id_not_in_admin_users_denied(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    assert notify.can_send('telegram_lk', 999999, 'sendMessage') is False


def test_can_send_telegram_lk_karim_only_mode(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'karim_only')
    assert notify.can_send('telegram_lk', 201, 'sendMessage') is True
    assert notify.can_send('telegram_lk', 202, 'sendMessage') is False


def test_can_send_telegram_lk_only_sendmessage(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    for op in ('getMe', 'getWebhookInfo', 'getUpdates'):
        assert notify.can_send('telegram_lk', 201, op) is False


def test_can_send_telegram_lk_disabled_account_denied(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    assert notify.can_send('telegram_lk', 205, 'sendMessage') is False


def test_can_send_telegram_denies_all_when_profile_is_lk_send_only(lk, monkeypatch):
    """N01: у бота стенда не остаётся ни одной операции, даже read-only, если
    выбран lk_send_only — даже когда STAND_TG_TOKEN остался в env."""
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    for op in ('getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage'):
        assert notify.can_send('telegram', 201, op) is False


def test_can_send_denies_both_channels_when_profile_unrecognized(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'typo')
    assert notify.can_send('telegram', 201, 'getMe') is False
    assert notify.can_send('telegram_lk', 201, 'sendMessage') is False


# ---------- профиль и маршрутизация deliver() ----------

def test_notify_profile_default_and_explicit(monkeypatch):
    monkeypatch.delenv('STAND_NOTIFY_PROFILE', raising=False)
    assert notify.notify_profile() == 'stand_bot'
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', '')
    assert notify.notify_profile() == 'stand_bot'
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    assert notify.notify_profile() == 'lk_send_only'
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'stand_bot')
    assert notify.notify_profile() == 'stand_bot'
    # Непустое, но нераспознанное значение — fail-closed отказ обоих
    # профилей, а НЕ молчаливый откат на боевой бот стенда (лидер/QA N01).
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'garbage')
    assert notify.notify_profile() == 'disabled'


def test_deliver_lk_profile_selected_but_not_ready_suppresses_no_fallback(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.delenv('STAND_LK_BOT_TOKEN', raising=False)

    def boom(*a, **k):
        raise AssertionError('tg_call (бот стенда) не должен вызываться в lk_send_only')
    monkeypatch.setattr(notify.stand_egress, 'tg_call', boom)

    def lk_boom(*a, **k):
        raise AssertionError('lk_call не должен вызываться, если профиль не готов')
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lk_boom)

    board([note(1)])
    notify.deliver()
    rows = log_rows('lk-note-1')
    assert rows[ids['manager']][0] == 'suppressed'
    assert rows[ids['karim']][0] == 'suppressed'


def test_deliver_lk_profile_sends_to_assignee_and_admin_no_role_fanout(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    sent = []

    def fake_lk_call(payload):
        sent.append(payload)
        return {'ok': True}
    monkeypatch.setattr(notify.stand_egress, 'lk_call', fake_lk_call)
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)

    board([note(1)], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4',
                              'assigneeAdminId': ids['manager']}])
    notify.deliver()
    rows = log_rows('lk-note-1')
    assert rows[ids['manager']][0] == 'sent'
    assert rows[ids['karim']][0] == 'sent'
    assert rows[ids['manager2']][0] == 'suppressed'  # роль та же, но не назначен — не получает
    assert len(sent) == 2
    assert all('СТЕНД' in p['text'] for p in sent)


def test_deliver_invalid_assignee_is_suppressed_not_role_fallback(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p) or {'ok': True})
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)

    # исполнитель отключён — не должен превращаться в рассылку на всю роль manager
    board([note(1)], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4',
                              'assigneeAdminId': ids['offduty']}])
    notify.deliver()
    rows = log_rows('lk-note-1')
    assert rows[ids['manager']][0] == 'suppressed'
    assert rows[ids['manager2']][0] == 'suppressed'
    assert rows[ids['karim']][0] == 'sent'  # копия админу — отдельное условие
    assert len(sent) == 1


def test_deliver_no_assignee_falls_back_to_role_and_admin_copy(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: {'ok': True})
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)

    board([note(1)], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4'}])
    notify.deliver()
    rows = log_rows('lk-note-1')
    assert rows[ids['manager']][0] == 'sent'
    assert rows[ids['manager2']][0] == 'sent'
    assert rows[ids['karim']][0] == 'sent'
    assert rows[ids['operator']][0] == 'suppressed'


# ---------- сервер: назначение исполнителя через PUT /api/stand/state ----------

def _login(client, uid):
    with client.session_transaction() as sess:
        sess['user_id'] = uid


def _get_state(client):
    return client.get('/api/stand/state').get_json()


def test_assignee_admin_can_assign_and_manager_can_self_take(lk):
    ids, board = lk
    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': None}])
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = ids['manager']
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 200, res.get_json()
        assert res.get_json()['data']['deals'][0]['assigneeAdminId'] == ids['manager']

    board([], deals=[{'id': 8, 'code': 'T8', 'client': 'Пётр', 'step': 's4', 'assigneeAdminId': None}])
    with appmod.app.test_client() as c:
        _login(c, ids['manager'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = ids['manager']
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 200, res.get_json()


def test_assignee_manager_cannot_assign_someone_else(lk):
    ids, board = lk
    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': None}])
    with appmod.app.test_client() as c:
        _login(c, ids['manager'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = ids['manager2']
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 409
        assert res.get_json()['success'] is False


def test_assignee_wrong_role_rejected(lk):
    ids, board = lk
    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': None}])
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = ids['operator']  # s4 требует manager
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 409


def test_assignee_disabled_and_nonexistent_rejected(lk):
    ids, board = lk
    for bad_id in (ids['offduty'], 999999, -1):
        board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': None}])
        with appmod.app.test_client() as c:
            _login(c, ids['karim'])
            cur = _get_state(c)
            data = cur['data']
            data['deals'][0]['assigneeAdminId'] = bad_id
            res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
            assert res.status_code == 409, bad_id


def test_assignee_release_only_by_admin_or_self(lk):
    ids, board = lk
    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': ids['manager']}])
    with appmod.app.test_client() as c:
        _login(c, ids['manager2'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = None
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 409

    with appmod.app.test_client() as c:
        _login(c, ids['manager'])
        cur = _get_state(c)
        data = cur['data']
        data['deals'][0]['assigneeAdminId'] = None
        res = c.put('/api/stand/state', json={'data': data, 'version': cur['version']})
        assert res.status_code == 200


# ---------- админ: Telegram ID вручную ----------

def test_admin_can_set_telegram_id_manager_cannot_reach_route(lk):
    ids, board = lk
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        res = c.put(f'/api/admins/{ids["manager"]}', json={'telegram_user_id': 909090})
        assert res.status_code == 200, res.get_json()
        assert res.get_json()['admin']['telegram_user_id'] == 909090

    with appmod.app.test_client() as c:
        _login(c, ids['manager'])
        res = c.put(f'/api/admins/{ids["manager2"]}', json={'telegram_user_id': 111})
        assert res.status_code == 403


def test_admin_telegram_id_rejects_non_numeric_and_duplicates(lk):
    ids, board = lk
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        res = c.put(f'/api/admins/{ids["manager"]}', json={'telegram_user_id': 'abc'})
        assert res.status_code == 400
        res = c.put(f'/api/admins/{ids["manager"]}', json={'telegram_user_id': -5})
        assert res.status_code == 400
        res = c.put(f'/api/admins/{ids["manager"]}', json={'telegram_user_id': 203})  # id уже у manager2
        assert res.status_code == 400


def test_tg_status_reports_active_profile(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.delenv('STAND_LK_BOT_TOKEN', raising=False)
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        res = c.get('/api/stand/tg-status')
        body = res.get_json()
        assert body['profile'] == 'lk_send_only'
        assert body['lk_status'] == 'disabled'
        assert res.status_code == 200


def test_tg_status_never_leaks_token(lk, monkeypatch):
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:super-secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    ids, board = lk
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        res = c.get('/api/stand/tg-status')
        assert '555:super-secret-fake' not in res.get_data(as_text=True)


# ---------- N01: изоляция профиля ----------

def test_stand_bot_functions_noop_when_profile_is_lk_send_only(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    calls = []
    monkeypatch.setattr(notify.stand_egress, 'tg_call',
                        lambda *a, **k: calls.append(a) or {'ok': False})
    assert notify.bot_username() is None
    assert notify.create_bind(ids['karim']) is None
    assert notify.poll_once() is False
    assert notify.start_updates() is False
    assert calls == []


# ---------- N04: рефереры/клиенты никогда не адресаты канала ----------

def test_referrer_and_client_ids_never_valid_recipients(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    db = appmod.SessionLocal()
    ref = appmod.Referrer(name='QA', code='qa-t14-ref', token='qa-t14-ref-token',
                          auth_mode='telegram', telegram_user_id=555555, active=True)
    db.add(ref)
    db.commit()
    ref_id = ref.telegram_user_id
    db.close()
    try:
        assert notify.can_send('telegram_lk', ref_id, 'sendMessage') is False
    finally:
        db = appmod.SessionLocal()
        db.query(appmod.Referrer).filter_by(code='qa-t14-ref').delete()
        db.commit()
        db.close()


# ---------- N10: STAND_MODE=0 — обе схемы канала инертны ----------

def test_channel_inert_when_stand_mode_off(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setattr(appmod, 'STAND_MODE', False)
    try:
        assert notify.can_send('telegram_lk', ids['karim'], 'sendMessage') is False
        assert notify.can_send('telegram', ids['karim'], 'getMe') is False
    finally:
        monkeypatch.setattr(appmod, 'STAND_MODE', True)


# ---------- N05: устаревшее назначение — авто-сброс, не отправка по старому id ----------

def test_stale_assignee_auto_healed_on_step_change_put(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p['chat_id']) or {'ok': True})

    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4',
                      'assigneeAdminId': ids['manager']}])
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        state = c.get('/api/stand/state').get_json()
        data = state['data']
        data['deals'][0]['step'] = 's5'  # s5 требует operator, исполнитель — manager
        data['notes'] = [{'id': 'stale-note-1', 'role': 'operator', 'dealId': 7, 'text': 'x'}]
        res = c.put('/api/stand/state', json={'version': state['version'], 'data': data})
        body = res.get_json()
        assert res.status_code == 200, body
        assert body['data']['deals'][0]['assigneeAdminId'] is None
    assert 204 in sent  # operator получил по роли, не manager
    assert 202 not in sent


def test_invalid_string_assignee_suppressed_not_fanned_out_to_role(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p['chat_id']) or {'ok': True})
    board([note(1, role='manager')],
         deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': 'bad'}])
    notify.deliver()
    assert 202 not in sent and 203 not in sent
    assert 201 in sent  # копия админу остаётся


# ---------- N07: переназначение — новый адресат получает, старый не повторно ----------

def test_reassignment_new_recipient_gets_it_old_does_not_repeat(lk, monkeypatch):
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p['chat_id']) or {'ok': True})

    board([note(1, role='manager')],
         deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': ids['manager']}])
    notify.deliver()
    assert sorted(sent) == [201, 202]

    # PUT сам доставляет новые/изменившиеся заметки (_stand_deliver_notes) —
    # переназначение проявляется уже здесь, отдельный notify.deliver() не нужен.
    sent.clear()
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        state = c.get('/api/stand/state').get_json()
        state['data']['deals'][0]['assigneeAdminId'] = ids['manager2']
        res = c.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
        assert res.status_code == 200, res.get_json()
        assert len(res.get_json()['data']['notes']) == 1  # не новое событие, то же самое
    assert sent == [203]  # только новый исполнитель, без повтора admin/старого

    sent.clear()
    notify.deliver()
    assert sent == []  # повторный цикл доставки ничего не шлёт заново


# ---------- N05 (перепроверка): admin-исполнитель и сохранённое disabled-назначение ----------

def test_admin_as_assignee_gets_single_send_no_role_fanout(lk, monkeypatch):
    """admin — законный исполнитель любого шага: получает одно уведомление
    (роль совпадает с копией админу — не два письма), остальные менеджеры роли
    не получают ничего."""
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p['chat_id']) or {'ok': True})

    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4', 'assigneeAdminId': None}])
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        state = c.get('/api/stand/state').get_json()
        data = state['data']
        data['deals'][0]['assigneeAdminId'] = ids['karim']
        data['notes'] = [{'id': 'admin-assignee-note', 'dealId': 7, 'role': 'manager', 'text': 'x'}]
        res = c.put('/api/stand/state', json={'version': state['version'], 'data': data})
        assert res.status_code == 200, res.get_json()
        assert res.get_json()['data']['deals'][0]['assigneeAdminId'] == ids['karim']
    assert sent == [201]  # ровно одна отправка, не рассылка на роль


def test_disabled_assignee_preserved_on_put_not_cleared_to_role_fallback(lk, monkeypatch):
    """Отключённый исполнитель при PUT — НЕ «нет назначения»: поле сохраняется,
    заметка подавляется адресно (assignee_disabled), а не уходит всей роли.
    Автосброс допустим только при реальном дрифте роли шага."""
    ids, board = lk
    monkeypatch.setenv('STAND_NOTIFY_PROFILE', 'lk_send_only')
    monkeypatch.setenv('STAND_NOTIFY_MODE', 'enabled')
    monkeypatch.setenv('STAND_LK_BOT_TOKEN', '555:secret-fake')
    monkeypatch.setenv('STAND_LK_BOT_ID', '555')
    monkeypatch.setattr(notify.stand_egress, 'lk_preflight_ok', lambda: True)
    sent = []
    monkeypatch.setattr(notify.stand_egress, 'lk_call', lambda p: sent.append(p['chat_id']) or {'ok': True})

    board([], deals=[{'id': 7, 'code': 'T7', 'client': 'Иван', 'step': 's4',
                      'assigneeAdminId': ids['offduty']}])
    with appmod.app.test_client() as c:
        _login(c, ids['karim'])
        state = c.get('/api/stand/state').get_json()
        data = state['data']
        data['notes'] = [{'id': 'disabled-assignee-note', 'dealId': 7, 'role': 'manager', 'text': 'x'}]
        # step не трогаем — assigneeAdminId остаётся неизменным (та же роль,
        # просто сотрудник отключён), это НЕ дрифт роли.
        res = c.put('/api/stand/state', json={'version': state['version'], 'data': data})
        body = res.get_json()
        assert res.status_code == 200, body
        assert body['data']['deals'][0]['assigneeAdminId'] == ids['offduty']  # не обнулилось
    assert sent == [201]  # только копия админу; ни отключённый, ни роль-фолбэк
