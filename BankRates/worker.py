"""Сервис курсов банков Таиланда — отдельный от бота и VPS (Railway).

Раз в час собирает TT Buying USD трёх банков (Kasikornbank, SCB,
Bangkok Bank) и пишет прошедшие валидацию значения в таблицу
bank_rates базы stand-db. При старте сразу делает один сбор (backfill),
чтобы таблица не была пустой.

Публичного домена и HTTP-сервера у сервиса нет — только фоновый цикл.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2

import rate_fetchers as rf

LOGGER = logging.getLogger("bank_rates")
POLL_INTERVAL_SECONDS = 3600  # раз в час — курс TT Buying обновляется банками реже


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
    while True:
        try:
            if conn.closed:
                conn = _connect()
            collect_once(conn, bangkok_bank_api_key)
        except Exception as exc:
            LOGGER.error("Цикл сбора упал целиком: %s", exc)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
