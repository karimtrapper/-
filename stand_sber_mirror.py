"""Зеркало приходов Сбера для стенда и мост из SQL в общую доску."""

import json
import math
import os
import re
import sys
import threading
from contextlib import nullcontext
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text

import stand_egress

WINDOW_LIMIT = 300
LOCK_KEY = 741098231
_thread = None
ACCOUNT_ASSUMPTION = 'Счёт проставлен по допущению: SberNotifier следит за одним счётом'


class ReadChannelError(Exception):
    """Код отказа закрытого канала без URL, ключа и параметров запроса."""


@lru_cache(maxsize=1)
def _sber_account_label():
    """Взять счёт MF из того же определения, что использует задачник.

    У банковского API нет номера счёта. При смене разметки MF в HTML лучше
    остановить мост с ошибкой, чем незаметно подставить чужие реквизиты.
    """
    html = (Path(__file__).parent / 'static/stand/tasks.html').read_text(encoding='utf-8')
    start = html.find('const MF={')
    if start < 0:
        raise ValueError('не найдены реквизиты MF')
    definition = html[start:html.find('};', start)]
    account = re.search(r"\bacc:'(\d{20})'", definition)
    if not account:
        raise ValueError('не найден счёт MF')
    return '…' + account.group(1)[-4:] + ' · Сбер'


def enabled(appmod):
    """Ключ разрешает опрос только на стенде и при явном включённом флаге."""
    return (appmod.STAND_MODE and bool(os.environ.get('STAND_PROD_RO_KEY'))
            and os.environ.get('STAND_SBER_MIRROR_ENABLED', '1') == '1')


def _days():
    try:
        return max(0, int(os.environ.get('STAND_SBER_BOARD_DAYS', '14')))
    except ValueError:
        return 14


def _board_income(row):
    """Счёт MF помечен как допущение об одном счёте SberNotifier."""
    operation = row.operation_date or ''
    day = operation[:10]
    if len(day) == 10 and day[4] == '-' and day[7] == '-':
        day = day[8:10] + '.' + day[5:7]
    from app import parse_sber_acquiring
    acquiring = parse_sber_acquiring(row.purpose)
    kind = 'эквайринг' if acquiring['kind'] == 'acquiring' else 'банк'
    return {'id': 'sber:' + row.uuid, 'uuid': row.uuid, 'source': 'sber',
            'date': day, 'arrivedAt': operation, 'payer': row.payer or '',
            'rub': row.amount_rub, 'grossRub': round(row.amount_rub + acquiring['fee_rub'], 2),
            'feeRub': round(acquiring['fee_rub'], 2), 'kind': kind,
            'acc': _sber_account_label(), 'accSource': 'sber_notifier_single_account',
            'purpose': row.purpose or '', 'docNumber': row.doc_number or '',
            'dealId': None, 'cnvId': None, 'excluded': False}


def _bridge(appmod, db):
    """Добавить свежую историю один раз, сохранив решения людей в доске."""
    cutoff = (datetime.utcnow() - timedelta(days=_days())).date().isoformat()
    rows = db.query(appmod.SberIncome).filter(
        appmod.SberIncome.operation_date >= cutoff).order_by(
        appmod.SberIncome.operation_date, appmod.SberIncome.id).all()
    if not rows:
        return 0
    board = appmod._stand_row(db, lock=True)
    data = json.loads(board.data or '{}')
    incomes = data.setdefault('incomes', [])
    present = {i.get('id'): pos for pos, i in enumerate(incomes) if isinstance(i, dict)}
    added = 0
    for row in rows:
        income_id = 'sber:' + row.uuid
        if income_id not in present:
            incomes.append(_board_income(row))
            present[income_id] = len(incomes) - 1
            added += 1
        elif incomes[present[income_id]].get('source') != 'sber':
            # Клиент мог заранее прислать запись с банковским id: факт из SQL
            # всегда побеждает такую подделку при следующем мосте.
            incomes[present[income_id]] = _board_income(row)
            added += 1
    if added:
        board.data = json.dumps(data, ensure_ascii=False)
        board.version = (board.version or 0) + 1
        board.updated_by = 'зеркало Сбера'
        board.updated_at = datetime.utcnow()
    return added


def _lock(appmod):
    """Один процесс держит advisory lock на всё время HTTP и записи."""
    if 'postgresql' not in appmod.DATABASE_URL:
        return nullcontext(None)
    return appmod.engine.connect()


def poll(appmod):
    """Один опрос. API прода ограничен последними 300 строками без пагинации."""
    if not enabled(appmod):
        return False
    with _lock(appmod) as connection:
        locked = connection is None or bool(connection.execute(
            text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_KEY}).scalar())
        if not locked:
            return False
        try:
            return _poll_locked(appmod)
        finally:
            if connection is not None:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_KEY})


def _poll_locked(appmod):
    try:
        # После заливки копии SQL история должна появиться даже при сбое прода.
        bootstrap = appmod.get_session()
        try:
            _bridge(appmod, bootstrap)
            bootstrap.commit()
        finally:
            bootstrap.close()
        status_code, payload, error_code = stand_egress.read_get(
            'prod_incomes', {'all': '1'})
        if error_code:
            safe_code = error_code if isinstance(error_code, str) and re.fullmatch(
                r'[a-z][a-z0-9_]{0,49}', error_code) else 'channel_error'
            raise ReadChannelError(safe_code)
        if status_code != 200:
            raise ValueError('HTTP ' + str(status_code))
        if not isinstance(payload, dict) or payload.get('success') is not True:
            raise ValueError('некорректный ответ')
        items = payload.get('incomes')
        if not isinstance(items, list) or len(items) > WINDOW_LIMIT:
            raise ValueError('некорректный список')
        # Строки с одним UUID и разными банковскими фактами отвергаем целиком.
        seen = {}
        conflicting = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            uid = str(item.get('uuid') or '').strip()[:64]
            facts = tuple(item.get(k) for k in (
                'operation_date', 'amount_rub', 'payer', 'purpose', 'doc_number'))
            if uid in seen and seen[uid] != facts:
                conflicting.add(uid)
            seen[uid] = facts
        db = appmod.get_session()
        try:
            state = db.query(appmod.StandSberMirrorState).filter_by(id=1).first()
            if state is None:
                state = appmod.StandSberMirrorState(id=1)
                db.add(state)
            uuids = [str(i.get('uuid') or '')[:64] for i in items if isinstance(i, dict)]
            existing = {r[0] for r in db.query(appmod.SberIncome.uuid).filter(
                appmod.SberIncome.uuid.in_(uuids)).all()} if uuids else set()
            created = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                uid = str(item.get('uuid') or '').strip()[:64]
                if not uid or uid in existing or uid in conflicting:
                    continue
                try:
                    amount = float(item.get('amount_rub'))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(amount) or not 0 < amount <= 1_000_000_000_000:
                    continue
                db.add(appmod.SberIncome(
                    uuid=uid, operation_date=str(item.get('operation_date') or '')[:40],
                    amount_rub=amount, payer=str(item.get('payer') or '')[:255],
                    purpose=str(item.get('purpose') or '')[:1000],
                    doc_number=str(item.get('doc_number') or '')[:40]))
                existing.add(uid)
                created += 1
            db.flush()
            _bridge(appmod, db)
            if items:
                newest = items[0]
                state.last_uuid = str(newest.get('uuid') or '')[:64]
                state.last_operation_date = str(newest.get('operation_date') or '')[:40]
                state.last_remote_id = newest.get('id') if isinstance(newest.get('id'), int) else None
            state.last_success_at = datetime.utcnow()
            state.last_new_count = created
            state.last_seen_count = len(items)
            state.last_error = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:
        # Ошибка клиента может содержать URL и заголовки. Пишем только тип/код.
        reason = str(exc) if isinstance(exc, (ValueError, ReadChannelError)) else type(exc).__name__
        if not isinstance(exc, ReadChannelError) and not reason.startswith('HTTP '):
            reason = 'ошибка опроса: ' + type(exc).__name__
        appmod.app.logger.warning('Зеркало Сбера: %s', reason)
        db = appmod.get_session()
        try:
            state = db.query(appmod.StandSberMirrorState).filter_by(id=1).first()
            if state is None:
                state = appmod.StandSberMirrorState(id=1)
                db.add(state)
            state.last_error = reason[:100]
            db.commit()
        finally:
            db.close()
        return False


def status(appmod):
    db = appmod.get_session()
    try:
        state = db.query(appmod.StandSberMirrorState).filter_by(id=1).first()
        return {'success': True, 'enabled': enabled(appmod),
                'window_limit': WINDOW_LIMIT, 'limited_window': True,
                'account_assumption': ACCOUNT_ASSUMPTION,
                'last_seen_count': state.last_seen_count or 0 if state else 0,
                'last_success_at': state.last_success_at.isoformat() + 'Z'
                if state and state.last_success_at else None,
                'last_new_count': state.last_new_count or 0 if state else 0,
                'last_error': state.last_error if state else None}
    finally:
        db.close()


def _loop(appmod):
    while True:
        try:
            poll(appmod)
        except Exception:
            # Даже сбой локальной БД не завершает фоновый потребитель.
            appmod.app.logger.warning('Зеркало Сбера: сбой локального цикла')
        try:
            interval = max(1, int(os.environ.get('STAND_SBER_MIRROR_INTERVAL', '60')))
        except ValueError:
            interval = 60
        threading.Event().wait(interval)


def start(appmod):
    global _thread
    if not enabled(appmod) or 'pytest' in sys.modules:
        return False
    if _thread and _thread.is_alive():
        return False
    _thread = threading.Thread(target=_loop, args=(appmod,), daemon=True,
                               name='stand-sber-mirror')
    _thread.start()
    return True
