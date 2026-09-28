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


def notify_profile():
    """Явный выбор профиля отправки (T14). Пустая переменная — старый бот
    стенда (переезд ещё не произошёл); НЕПУСТОЕ, но нераспознанное значение —
    fail-closed отказ обоих профилей, а не молчаливый откат на stand_bot
    (опечатка в env не должна тайно продолжать слать боевым ботом)."""
    value = os.environ.get('STAND_NOTIFY_PROFILE', '').strip()
    if not value:
        return 'stand_bot'
    return value if value in ('lk_send_only', 'stand_bot') else 'disabled'


def _positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _user_allowed(user):
    return (_positive_id(user.telegram_user_id) and bool(user.notify_enabled)
            and not bool(user.login_disabled)
            and (mode() == 'enabled' or user.username == 'karim'))


def can_send(channel, recipient, operation):
    """Чат допустим только после привязки к активному аккаунту с включённой галкой.

    Один и тот же canonical-путь для обоих профилей (T14): у lk_send_only нет
    ни getMe, ни getUpdates — единственная разрешённая операция — sendMessage,
    и та же самая проверка получателя, что и у бота стенда (та же таблица
    admin_users, тот же режим karim_only). Если положительному id соответствует
    больше одного АКТИВНОГО сотрудника (дубликат Telegram ID) — неоднозначность,
    отказ, а не отправка «кому получится».
    """
    if channel not in ('telegram', 'telegram_lk') or not _app or not _app.STAND_MODE:
        return False
    profile = notify_profile()
    # Изоляция профилей (лидер/QA N01): выбран lk_send_only (или профиль вовсе
    # не распознан) — у бота стенда не остаётся ни одной разрешённой операции,
    # даже read-only getMe/getUpdates/getWebhookInfo, даже если STAND_TG_TOKEN
    # остался в env. Симметрично — телеграм_lk доступен только в lk_send_only.
    if channel == 'telegram' and profile != 'stand_bot':
        return False
    if channel == 'telegram_lk' and profile != 'lk_send_only':
        return False
    if channel == 'telegram' and operation in ('getMe', 'getWebhookInfo', 'getUpdates'):
        return True
    if operation != 'sendMessage' or not _positive_id(recipient):
        return False
    db = _app.SessionLocal()
    try:
        users = db.query(_app.AdminUser).filter(_app.AdminUser.telegram_user_id == recipient).all()
        active = [u for u in users if not u.login_disabled]
        if len(active) != 1:
            return False
        return _user_allowed(active[0])
    finally:
        db.close()


def bot_username():
    global _status
    if notify_profile() != 'stand_bot':
        # Профиль lk_send_only (или нераспознанный) — у бота стенда нет
        # никаких сетевых операций, даже getMe (лидер/QA N01).
        _status = 'disabled'
        return None
    expected = stand_egress.expected_bot_username()
    if not expected:
        _status = 'bot_identity_mismatch'
        return None
    try:
        result = stand_egress.tg_call('getMe', {})
    except Exception:
        _status = 'bot_identity_mismatch'
        _app.app.logger.warning('stand bot identity lookup failed')
        return None
    if not isinstance(result, dict):
        _status = 'bot_identity_mismatch'
        _app.app.logger.warning('stand bot_identity_mismatch')
        return None
    bot = result.get('result') if isinstance(result.get('result'), dict) else {}
    name = bot.get('username')
    if result.get('ok') and isinstance(name, str) and name.lower() == expected.lower():
        if _status == 'bot_identity_mismatch':
            _status = 'disabled'
        return expected
    _status = 'bot_identity_mismatch'
    _app.app.logger.warning('stand bot_identity_mismatch')
    return None


def create_bind(admin_id):
    global _status
    if notify_profile() != 'stand_bot':
        _status = 'disabled'
        return None
    username = bot_username()
    if not username or username != stand_egress.expected_bot_username():
        _status = 'bot_identity_mismatch'
        _app.app.logger.warning('stand bot_identity_mismatch')
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


def _format_note(note, deals, stand_label=False):
    """`stand_label` — метка «СТЕНД» перед текстом (T14, профиль lk_send_only):
    тот же бот доставляет и боевые задания, поэтому сообщение со стенда
    обязано быть невозможно спутать с продовым."""
    who = _app.STAND_ROLE_PEOPLE.get(note.get('role'), note.get('role') or '')
    deal = deals.get(str(note.get('dealId'))) or {}
    tail = ''
    if deal:
        base = os.environ.get('STAND_BASE_URL', '').rstrip('/')
        label = escape(f"{deal.get('code') or ''} · {deal.get('client') or ''}")
        link = f'<a href="{escape(base, quote=True)}/tasks?deal={quote(str(deal.get("id")))}">{label}</a>' if base else f'<i>{label}</i>'
        tail = f'\n{link}'
    prefix = '🧪 <b>СТЕНД</b> (не прод)\n' if stand_label else ''
    return f"{prefix}🔔 <b>{escape(str(who))}</b>\n{escape(str(note.get('text') or ''))}{tail}"


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
            profile = notify_profile()
            channel = {'lk_send_only': 'telegram_lk', 'stand_bot': 'telegram'}.get(profile)
            # lk_send_only не переключается на бота стенда сам ни при каком сбое
            # (нет токена/ID, рассинхрон префикса, identity mismatch), а
            # нераспознанный профиль не откатывается ни на один из ботов —
            # решение Карима: явный выбор профиля важнее доступности канала.
            profile_ready = (channel == 'telegram' or
                             (channel == 'telegram_lk' and stand_egress.lk_preflight_ok()))
            for note in reversed(state.get('notes') or []):
                note_id = str(note.get('id') or '')
                if not note_id:
                    continue
                # Исполнитель шага смотрится заново на каждый цикл доставки —
                # переназначение или отзыв применяется сразу же, без нового
                # события: старый исполнитель просто перестаёт быть recipient.
                deal = deals.get(str(note.get('dealId'))) or {}
                raw_assignee = deal.get('assigneeAdminId')
                has_assignee_field = raw_assignee is not None
                assignee_id = raw_assignee if _positive_id(raw_assignee) else None
                # Присутствующее, но испорченное значение (строка, отрицательное,
                # bool, 0) — это НЕ «поля нет»: фолбэка на роль не будет, только
                # подавление (кроме копии админу). Отдельно от этого —
                # действительный активный сотрудник, но не той роли для текущей
                # note (шаг ушёл дальше, поле не тронули) — это тоже не «нет
                # назначения», но здесь корректно откатиться на роль: реального
                # исполнителя для ЭТОЙ задачи просто не осталось.
                assignee_user = next((u for u in users if assignee_id is not None and u.id == assignee_id), None)
                assignee_broken = has_assignee_field and assignee_id is None
                assignee_missing_or_disabled = assignee_id is not None and (
                    assignee_user is None or assignee_user.login_disabled)
                # admin — законный исполнитель любого шага (делает любую роль
                # на стенде), поэтому для него роль никогда не «не та»: иначе
                # его собственное назначение самого себя откатывалось бы на
                # рассылку по роли note, а не оставалось персональным.
                assignee_role_mismatch = (assignee_id is not None and assignee_user is not None
                                          and not assignee_user.login_disabled
                                          and (assignee_user.role or 'admin') not in
                                          ('admin', note.get('role') or 'admin'))
                suppress_only = assignee_broken or assignee_missing_or_disabled
                fallback_to_role = (not has_assignee_field) or assignee_role_mismatch
                for user in users:
                    # Слот конкретного исполнителя ведёт свой дедуп-ключ: у нового
                    # адресата после переназначения нет истории под этим ключом,
                    # поэтому suppressed/sent прежнего исполнителя (под обычным
                    # note_id) ему не наследуется, а сам прежний исполнитель по
                    # старому ключу повторно не получает (см. фильтр ниже).
                    is_exact_assignee = (not suppress_only and not fallback_to_role
                                         and assignee_id is not None and user.id == assignee_id)
                    row_key = f'{note_id}::assignee:{assignee_id}' if is_exact_assignee else note_id
                    existing = db.execute(text('SELECT status, attempts FROM stand_notify_log '
                                               'WHERE note_id=:note_id AND admin_id=:admin_id'),
                                          {'note_id': row_key, 'admin_id': user.id}).first()
                    if existing and (existing[0] != 'failed' or existing[1] >= _MAX_ATTEMPTS):
                        continue
                    chat_id = user.telegram_user_id
                    if suppress_only:
                        recipient = (user.role or 'admin') == 'admin'
                    elif fallback_to_role:
                        recipient = (user.role or 'admin') in ('admin', note.get('role'))
                    else:
                        recipient = user.id == assignee_id or (user.role or 'admin') == 'admin'
                    allowed = (profile_ready and channel and recipient and _user_allowed(user)
                               and can_send(channel, chat_id, 'sendMessage'))
                    status = 'suppressed'
                    attempts = (existing[1] if existing else 0)
                    if allowed:
                        attempts += 1
                        try:
                            text_body = _format_note(note, deals, stand_label=(profile == 'lk_send_only'))
                            payload = {'chat_id': chat_id, 'text': text_body,
                                       'parse_mode': 'HTML', 'disable_web_page_preview': True}
                            if profile == 'lk_send_only':
                                result = stand_egress.lk_call(payload)
                            else:
                                result = stand_egress.tg_call('sendMessage', payload)
                            status = 'sent' if isinstance(result, dict) and result.get('ok') else 'failed'
                        except Exception:
                            status = 'failed'
                            _app.app.logger.exception('stand notification failed')
                    db.execute(text('INSERT INTO stand_notify_log (note_id, admin_id, status, attempts, at) '
                                    'VALUES (:note_id, :admin_id, :status, :attempts, :at) '
                                    'ON CONFLICT (note_id, admin_id) DO UPDATE SET '
                                    'status=EXCLUDED.status, attempts=EXCLUDED.attempts, at=EXCLUDED.at'),
                               {'note_id': row_key, 'admin_id': user.id, 'status': status,
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
    if notify_profile() != 'stand_bot':
        _status = 'disabled'
        return False
    db = _app.SessionLocal()
    try:
        offset = db.execute(text('SELECT next_offset FROM stand_tg_offset WHERE id=1')).scalar() or 0
        result = stand_egress.tg_call('getUpdates', {'offset': offset, 'timeout': 20, 'allowed_updates': ['message']})
        if not isinstance(result, dict) or not result.get('ok'):
            _status = ('bot_identity_mismatch' if isinstance(result, dict)
                       and result.get('error') == 'bot_identity_mismatch' else 'error')
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
    if (not _app or not _app.STAND_MODE or notify_profile() != 'stand_bot'
            or not os.environ.get('STAND_TG_TOKEN') or os.environ.get('STAND_TG_UPDATES_ENABLED', '1') != '1'):
        _status = 'disabled'
        return False
    if not bot_username():
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
