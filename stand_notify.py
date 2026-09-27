"""Личные уведомления и привязка Telegram для задачника стенда."""

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from html import escape
from urllib.parse import quote

from sqlalchemy import text

import stand_egress

_app = None
_bot_username = None
_status = 'disabled'
_delivery_lock = threading.Lock()
_update_lock = threading.Lock()
_LOCK_KEY = 726483291
_MAX_ATTEMPTS = 5


def init(app_module):
    """Создать собственные таблицы T5 и подключить политику T1."""
    global _app
    _app = app_module
    if not app_module.STAND_MODE:
        return
    with app_module.engine.begin() as conn:
        # T5-временно: колонку вводит T2. Повторный запуск безопасен.
        cols = {row[1] for row in conn.execute(text('PRAGMA table_info(admin_users)'))} if conn.dialect.name == 'sqlite' else None
        for name in ('notify_enabled', 'login_disabled'):
            if conn.dialect.name == 'postgresql':
                conn.execute(text(f'ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS {name} BOOLEAN DEFAULT FALSE'))
            elif name not in cols:
                conn.execute(text(f'ALTER TABLE admin_users ADD COLUMN {name} BOOLEAN DEFAULT 0'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS stand_notify_log ('
                          'note_id VARCHAR(200) NOT NULL, admin_id INTEGER NOT NULL, '
                          'status VARCHAR(20) NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, '
                          'at TIMESTAMP NOT NULL, PRIMARY KEY (note_id, admin_id))'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS stand_tg_bind ('
                          'nonce VARCHAR(100) PRIMARY KEY, admin_id INTEGER NOT NULL, '
                          'expires_at TIMESTAMP NOT NULL, used BOOLEAN NOT NULL DEFAULT FALSE)'))
        conn.execute(text('CREATE TABLE IF NOT EXISTS stand_tg_offset ('
                          'id INTEGER PRIMARY KEY, next_offset BIGINT NOT NULL DEFAULT 0)'))
        conn.execute(text('INSERT INTO stand_tg_offset (id, next_offset) VALUES (1, 0) ON CONFLICT (id) DO NOTHING'))
    stand_egress.set_policy(can_send)


def mode():
    value = os.environ.get('STAND_NOTIFY_MODE', 'karim_only')
    return value if value in ('karim_only', 'enabled') else 'karim_only'


def _positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _user_allowed(user):
    return (_positive_id(user.telegram_user_id) and bool(user.notify_enabled)
            and not bool(user.login_disabled)
            and (mode() == 'enabled' or user.username == 'karim'))


def can_send(channel, recipient, operation):
    """Чат допустим только после привязки к активному аккаунту с включённой галкой."""
    if channel != 'telegram' or not _app or not _app.STAND_MODE:
        return False
    if operation in ('getMe', 'getWebhookInfo', 'getUpdates'):
        return True
    if operation != 'sendMessage' or not _positive_id(recipient):
        return False
    db = _app.SessionLocal()
    try:
        users = db.query(_app.AdminUser).filter(_app.AdminUser.telegram_user_id == recipient).all()
        return any(_user_allowed(u) for u in users)
    finally:
        db.close()


def bot_username():
    global _bot_username
    if _bot_username:
        return _bot_username
    try:
        result = stand_egress.tg_call('getMe', {})
    except Exception:
        _app.app.logger.exception('stand bot identity lookup failed')
        return None
    if not isinstance(result, dict):
        return None
    name = (result.get('result') or {}).get('username') if isinstance(result, dict) else None
    if result.get('ok') and isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_]{5,32}', name):
        _bot_username = name
    return _bot_username


def create_bind(admin_id):
    username = bot_username()
    if not username:
        return None
    nonce = secrets.token_urlsafe(24)
    db = _app.SessionLocal()
    try:
        db.execute(text('INSERT INTO stand_tg_bind (nonce, admin_id, expires_at, used) '
                        'VALUES (:nonce, :admin_id, :expires_at, FALSE)'),
                   {'nonce': nonce, 'admin_id': admin_id,
                    'expires_at': datetime.utcnow() + timedelta(minutes=10)})
        db.commit()
    finally:
        db.close()
    return f'https://t.me/{username}?start=bind_{quote(nonce)}'


def consume_bind(nonce, from_id):
    """Одним UPDATE забрать nonce; повторный апдейт больше не получит владельца."""
    if not isinstance(nonce, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,100}', nonce) or not _positive_id(from_id):
        return False
    db = _app.SessionLocal()
    try:
        row = db.execute(text('UPDATE stand_tg_bind SET used=TRUE WHERE nonce=:nonce '
                              'AND used=FALSE AND expires_at>:now RETURNING admin_id'),
                         {'nonce': nonce, 'now': datetime.utcnow()}).first()
        if not row:
            db.rollback()
            return False
        user = db.query(_app.AdminUser).filter_by(id=row[0]).first()
        if not user or bool(user.login_disabled):
            db.rollback()
            return False
        user.telegram_user_id = from_id
        db.commit()
        return True
    finally:
        db.close()


def process_update(update):
    message = update.get('message') or {}
    chat = message.get('chat') or {}
    sender = message.get('from') or {}
    if chat.get('type') != 'private' or not _positive_id(sender.get('id')):
        return False
    if chat.get('id') != sender['id']:
        return False
    match = re.fullmatch(r'/start(?:@[A-Za-z0-9_]+)? bind_([A-Za-z0-9_-]{20,100})', message.get('text') or '')
    if not match or not consume_bind(match.group(1), sender['id']):
        return False
    if can_send('telegram', sender['id'], 'sendMessage'):
        try:
            stand_egress.tg_call('sendMessage', {'chat_id': sender['id'], 'text': 'Подключено. Уведомления стенда включены.'})
        except Exception:
            _app.app.logger.exception('stand bind reply failed')
    return True


def _format_note(note, deals):
    who = _app.STAND_ROLE_PEOPLE.get(note.get('role'), note.get('role') or '')
    deal = deals.get(str(note.get('dealId'))) or {}
    tail = ''
    if deal:
        base = os.environ.get('STAND_BASE_URL', '').rstrip('/')
        label = escape(f"{deal.get('code') or ''} · {deal.get('client') or ''}")
        link = f'<a href="{escape(base, quote=True)}/tasks?deal={quote(str(deal.get("id")))}">{label}</a>' if base else f'<i>{label}</i>'
        tail = f'\n{link}'
    return f"🔔 <b>{escape(str(who))}</b>\n{escape(str(note.get('text') or ''))}{tail}"


def deliver():
    """Повторять только failed; suppressed и sent остаются окончательными."""
    if not _app or not _app.STAND_MODE:
        return
    with _delivery_lock:
        lock_conn = None
        db = _app.SessionLocal()
        try:
            if db.bind.dialect.name == 'postgresql':
                lock_conn = _app.engine.connect()
                locked = lock_conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': _LOCK_KEY + 1}).scalar()
                if not locked:
                    return
            row = _app._stand_row(db)
            state = json.loads(row.data or '{}')
            deals = {str(d.get('id')): d for d in state.get('deals') or []}
            users = db.query(_app.AdminUser).all()
            for note in reversed(state.get('notes') or []):
                note_id = str(note.get('id') or '')
                if not note_id:
                    continue
                for user in users:
                    existing = db.execute(text('SELECT status, attempts FROM stand_notify_log '
                                               'WHERE note_id=:note_id AND admin_id=:admin_id'),
                                          {'note_id': note_id, 'admin_id': user.id}).first()
                    if existing and (existing[0] != 'failed' or existing[1] >= _MAX_ATTEMPTS):
                        continue
                    chat_id = user.telegram_user_id
                    # Фиксируем также прежнюю несовпадающую роль: после её смены
                    # старые задачи не должны внезапно прийти сотруднику.
                    recipient = (user.role or 'admin') in ('admin', note.get('role'))
                    allowed = recipient and _user_allowed(user) and can_send('telegram', chat_id, 'sendMessage')
                    status = 'suppressed'
                    attempts = (existing[1] if existing else 0)
                    if allowed:
                        attempts += 1
                        try:
                            result = stand_egress.tg_call('sendMessage', {
                                'chat_id': chat_id, 'text': _format_note(note, deals),
                                'parse_mode': 'HTML', 'disable_web_page_preview': True})
                            status = 'sent' if isinstance(result, dict) and result.get('ok') else 'failed'
                        except Exception:
                            status = 'failed'
                            _app.app.logger.exception('stand notification failed')
                    db.execute(text('INSERT INTO stand_notify_log (note_id, admin_id, status, attempts, at) '
                                    'VALUES (:note_id, :admin_id, :status, :attempts, :at) '
                                    'ON CONFLICT (note_id, admin_id) DO UPDATE SET '
                                    'status=EXCLUDED.status, attempts=EXCLUDED.attempts, at=EXCLUDED.at'),
                               {'note_id': note_id, 'admin_id': user.id, 'status': status,
                                'attempts': attempts, 'at': datetime.utcnow()})
                    db.commit()
        finally:
            db.close()
            if lock_conn is not None:
                try:
                    lock_conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _LOCK_KEY + 1})
                finally:
                    lock_conn.close()


def status():
    return _status


def poll_once():
    """Один цикл getUpdates; offset фиксируется после каждого обработанного апдейта."""
    global _status
    db = _app.SessionLocal()
    try:
        offset = db.execute(text('SELECT next_offset FROM stand_tg_offset WHERE id=1')).scalar() or 0
        result = stand_egress.tg_call('getUpdates', {'offset': offset, 'timeout': 20, 'allowed_updates': ['message']})
        if not isinstance(result, dict) or not result.get('ok'):
            _status = 'error'
            _app.app.logger.warning('stand update poll rejected: %s',
                                    result.get('error_code', 'unknown') if isinstance(result, dict) else 'invalid_response')
            return False
        for update in result.get('result') or []:
            update_id = update.get('update_id')
            if not isinstance(update_id, int) or update_id < offset:
                continue
            process_update(update)
            offset = update_id + 1
            db.execute(text('UPDATE stand_tg_offset SET next_offset=:offset WHERE id=1'), {'offset': offset})
            db.commit()
        _status = 'running'
        return True
    finally:
        db.close()


def _poll_loop():
    global _status
    while True:
        try:
            if not poll_once():
                time.sleep(5)
        except Exception:
            _status = 'error'
            _app.app.logger.exception('stand update poll failed')
            time.sleep(5)


def start_updates():
    """Проверить вебхук и запустить единственного потребителя на процесс."""
    global _status
    if not _app or not _app.STAND_MODE or not os.environ.get('STAND_TG_TOKEN') or os.environ.get('STAND_TG_UPDATES_ENABLED', '1') != '1':
        _status = 'disabled'
        return False
    try:
        info = stand_egress.tg_call('getWebhookInfo', {})
        if not isinstance(info, dict) or not info.get('ok'):
            _status = 'error'
            _app.app.logger.warning('stand webhook check failed')
            return False
        if (info.get('result') or {}).get('url'):
            _status = 'webhook_set'
            return False
        if not _update_lock.acquire(blocking=False):
            _status = 'already_running'
            return False
        if _app.engine.dialect.name == 'postgresql':
            conn = _app.engine.connect()
            if not conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': _LOCK_KEY}).scalar():
                conn.close()
                _update_lock.release()
                _status = 'already_running'
                return False
            conn.commit()
            # Отдельное соединение держит session lock до завершения потока.
            def run():
                try:
                    _poll_loop()
                finally:
                    conn.close()
                    _update_lock.release()
        else:
            # SQLite в приложении работает в одном процессе; потоковый lock достаточен.
            def run():
                try:
                    _poll_loop()
                finally:
                    _update_lock.release()
        _status = 'running'
        threading.Thread(target=run, daemon=True, name='stand-tg-updates').start()
        return True
    except Exception:
        _status = 'error'
        _app.app.logger.exception('stand update startup failed')
        return False
