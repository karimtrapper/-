"""Сервис курсов банков Таиланда — отдельный от бота и VPS (Railway).

Плановый сбор TT Buying USD трёх банков (Kasikornbank, SCB, Bangkok Bank) —
раз в сутки в 09:00 Asia/Bangkok. SCB временно выключен BANK_RATES_DISABLED
(Imperva режет запросы с серверных IP Railway). При старте сразу делает один
сбор (backfill),
чтобы таблица не была пустой. Между плановыми сборами раз в минуту проверяет
таблицу bank_rates_refresh_requests — запросы менеджера (кнопка «Обновить
курс» в tasks.html) на внеплановый сбор; несколько подряд схлопываются в один.

Публичного домена и HTTP-сервера у сервиса нет — только фоновый цикл.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2

import rate_fetchers as rf

LOGGER = logging.getLogger("bank_rates")
DAILY_COLLECTION_HOUR_BKK = 9  # плановый сбор раз в сутки в 09:00 по Бангкоку
REFRESH_POLL_INTERVAL_SECONDS = 60  # как часто проверяем очередь запросов менеджера
# SCB режет запросы с серверных IP Railway (Imperva) — временно не собираем, чтобы не сыпать 403 в лог.
# Схема общая с app.py (BANK_RATES_DISABLED): переменная даёт переключить без деплоя кода.
BANK_RATES_DISABLED = {b.strip() for b in os.environ.get("BANK_RATES_DISABLED", "SCB").split(",") if b.strip()}


def _database_url() -> str:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _connect():
    return psycopg2.connect(_database_url())


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bank_rates (
                id BIGSERIAL PRIMARY KEY,
                bank TEXT NOT NULL,
                rate NUMERIC(10, 4) NOT NULL,
                source_updated_at TEXT NOT NULL DEFAULT '',
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_bank_rates_bank_fetched "
            "ON bank_rates (bank, fetched_at DESC)"
        )
        # Запросы менеджера на внеплановый сбор — схема общая с app.py
        # (_ensure_bank_rates_refresh_table), менять обе стороны синхронно.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bank_rates_refresh_requests (
                id BIGSERIAL PRIMARY KEY,
                requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                requested_by TEXT NOT NULL DEFAULT '',
                done_at TIMESTAMPTZ,
                result JSONB
            )
            """
        )
    conn.commit()


def _last_rate(conn, bank: str) -> Decimal:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT rate FROM bank_rates WHERE bank = %s ORDER BY fetched_at DESC LIMIT 1",
            (bank,),
        )
        row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal("0")


def _insert_rate(conn, bank: str, value: Decimal, source_timestamp: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bank_rates (bank, rate, source_updated_at) VALUES (%s, %s, %s)",
            (bank, str(value), source_timestamp),
        )
    conn.commit()


def collect_once(conn, bangkok_bank_api_key: str) -> dict[str, str]:
    """Один цикл сбора трёх банков. Возвращает {банк: 'ok'|сообщение об ошибке}."""
    now = datetime.now(timezone.utc)
    fetchers = {
        "Kasikornbank": rf.fetch_kasikorn,
        "SCB": rf.fetch_scb,
        "Bangkok Bank": lambda: rf.fetch_bangkok_bank(bangkok_bank_api_key),
    }
    results: dict[str, str] = {}
    for bank, fetcher in fetchers.items():
        if bank in BANK_RATES_DISABLED:
            results[bank] = "disabled"
            continue
        try:
            result = fetcher()
            previous = _last_rate(conn, bank)
            rf.validate_value(result.value, previous)
            rf.validate_source_timestamp(result.source_timestamp, now)
            _insert_rate(conn, bank, result.value, result.source_timestamp)
            results[bank] = "ok"
            LOGGER.info("%s: %s (%s)", bank, result.value, result.source_timestamp)
        except Exception as exc:  # источник не ответил/не прошёл валидацию — не пишем
            message = str(exc) or type(exc).__name__
            results[bank] = message
            LOGGER.error("%s: отказ — %s. Прошлая валидная строка не затирается.", bank, message)
    return results


def _next_daily_run(after: datetime) -> datetime:
    """Следующее плановое время сбора — 09:00 Asia/Bangkok, строго после `after` (UTC)."""
    after_bkk = after.astimezone(rf.BANGKOK_TZ)
    candidate = after_bkk.replace(hour=DAILY_COLLECTION_HOUR_BKK, minute=0, second=0, microsecond=0)
    if candidate <= after_bkk:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _pending_refresh_requests(conn) -> list[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM bank_rates_refresh_requests WHERE done_at IS NULL ORDER BY id")
        return [row[0] for row in cur.fetchall()]


def _complete_refresh_requests(conn, ids: list[int], result: dict[str, str]) -> None:
    if not ids:
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE bank_rates_refresh_requests SET done_at = now(), result = %s WHERE id = ANY(%s)",
            (json.dumps(result), ids),
        )
    conn.commit()


def _tick(conn, bangkok_bank_api_key: str, next_daily_at: datetime, now: datetime) -> datetime:
    """Один проход цикла: сбор по расписанию и/или по запросам менеджера,
    схлопнутым в один вызов collect_once. Возвращает новый next_daily_at."""
    pending_ids = _pending_refresh_requests(conn)
    due_daily = now >= next_daily_at
    if pending_ids or due_daily:
        result = collect_once(conn, bangkok_bank_api_key)
        if pending_ids:
            _complete_refresh_requests(conn, pending_ids, result)
        if due_daily:
            next_daily_at = _next_daily_run(now)
    return next_daily_at


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    bangkok_bank_api_key = os.environ.get("BANGKOK_BANK_API_KEY", "")
    conn = _connect()
    ensure_schema(conn)
    LOGGER.info("Сервис курсов запущен. Backfill — немедленный сбор при старте.")
    collect_once(conn, bangkok_bank_api_key)
    next_daily_at = _next_daily_run(datetime.now(timezone.utc))
    while True:
        try:
            if conn.closed:
                conn = _connect()
            next_daily_at = _tick(conn, bangkok_bank_api_key, next_daily_at, datetime.now(timezone.utc))
        except Exception as exc:
            LOGGER.error("Цикл сбора упал целиком: %s", exc)
        time.sleep(REFRESH_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
