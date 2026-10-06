"""Сбор курса TT Buying USD трёх тайских банков.

Перенесено (не импортировано) из Dev/PropertyPaymentBot/app/rate_updater.py —
только банковская часть: парсеры, валидация диапазона/скачка и свежести
котировки источника. ЦБ, Telegram-алерты и запись в JSON-файл бота сюда
не переносились — это отдельный сервис курсов на Railway, независимый
от бота и VPS (решение Карима).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

BANGKOK_TZ = ZoneInfo("Asia/Bangkok")
SCB_URL = (
    "https://www.scb.co.th/services/scb/exchangeRateService/latest.json"
    "?_charset_=UTF-8&lang=en&"
    "page=2ea9c13a-6fb9-4a75-9abd-87ef79ee71cc%2C907ab931-1989-41b4-b599-10bff5593570"
)
BANGKOK_BANK_URL = "https://www.bangkokbank.com/api/exchangerateservice/GetLatestfxrates"
KASIKORN_URL = "https://www.kasikornbank.com/en/rate/pages/foreign-exchange.aspx"
HTTP_TIMEOUT_SECONDS = 30
BANK_SOURCE_MAX_AGE = timedelta(hours=24)
BANK_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%d %B %Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
)
# Диапазон и максимально допустимый скачок курса — как в rate_updater.py бота.
RATE_LOW, RATE_HIGH, RATE_MAX_CHANGE = Decimal("15"), Decimal("60"), Decimal("0.03")


class RateSourceError(RuntimeError):
    """Источник не вернул пригодный курс."""


@dataclass(frozen=True)
class SourceValue:
    value: Decimal
    source_timestamp: str


def _request_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {
        "Accept": "application/json,text/xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": "GrushaBankRates/1.0 (+https://grusha.space)",
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RateSourceError(f"сеть: {exc}") from exc


def parse_scb_json(payload: bytes) -> SourceValue:
    try:
        data = json.loads(payload)
        row = next(item for item in data["exchangeRates"] if item["curCode"] == "USD")
        value = Decimal(str(row["buyTT"]))
    except (json.JSONDecodeError, KeyError, StopIteration, InvalidOperation) as exc:
        raise RateSourceError("SCB не вернул USD TT Buying") from exc
    stamp = f"{row.get('runDate', '')} {row.get('runTime', '')}".strip()
    return SourceValue(value=value, source_timestamp=stamp)


def parse_bangkok_bank_json(payload: bytes) -> SourceValue:
    try:
        data = json.loads(payload)
        row = next(item for item in data if item.get("Family") == "USD50")
        value = Decimal(str(row["TT"]).strip())
    except (json.JSONDecodeError, KeyError, StopIteration, InvalidOperation) as exc:
        raise RateSourceError("Bangkok Bank не вернул USD TT Buying") from exc
    stamp = f"{row.get('Ddate', '')} {str(row.get('DTime', '')).strip()}".strip()
    return SourceValue(value=value, source_timestamp=stamp)


def parse_kasikorn_rows(rows: list[list[str]], page_text: str = "") -> SourceValue:
    for parts in rows:
        cleaned = [part.strip() for part in parts if part.strip()]
        if len(cleaned) >= 4 and cleaned[0] == "USD 1":
            try:
                value = Decimal(cleaned[3])
            except InvalidOperation as exc:
                raise RateSourceError("Kasikorn вернул некорректный Telex Transfer") from exc
            match = re.search(
                r"Date\s+(\d{1,2}\s+\w+\s+\d{4})\s+Time\s+(\d{2}:\d{2}:\d{2})",
                page_text,
            )
            stamp = " ".join(match.groups()) if match else ""
            return SourceValue(value=value, source_timestamp=stamp)
    raise RateSourceError("Kasikorn не вернул USD Telex Transfer")


def fetch_scb() -> SourceValue:
    return parse_scb_json(_request_bytes(SCB_URL))


def fetch_bangkok_bank(api_key: str) -> SourceValue:
    if not api_key:
        raise RateSourceError("не задан BANGKOK_BANK_API_KEY")
    try:
        from scrapling.fetchers import Fetcher
    except ImportError as exc:
        raise RateSourceError("не установлен HTTP-загрузчик Scrapling") from exc
    try:
        response = Fetcher.get(
            BANGKOK_BANK_URL,
            impersonate="chrome",
            headers={
                "Accept": "application/json",
                "Ocp-Apim-Subscription-Key": api_key,
                "Referer": (
                    "https://www.bangkokbank.com/en/Personal/Other-Services/"
                    "View-Rates/Foreign-Exchange-Rates"
                ),
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        return parse_bangkok_bank_json(response.body)
    except RateSourceError:
        raise
    except Exception as exc:
        raise RateSourceError(f"Bangkok Bank: {type(exc).__name__}: {exc}") from exc


def fetch_kasikorn() -> SourceValue:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as exc:
        raise RateSourceError("не установлен браузерный загрузчик Scrapling") from exc
    try:
        page = StealthyFetcher.fetch(
            KASIKORN_URL,
            headless=True,
            network_idle=True,
        )
        rows = [row.css("::text").getall() for row in page.css("tr")]
        page_text = " ".join(page.css("body ::text").getall())
        return parse_kasikorn_rows(rows, page_text)
    except RateSourceError:
        raise
    except Exception as exc:
        raise RateSourceError(f"браузер Kasikorn: {type(exc).__name__}: {exc}") from exc


def validate_value(value: Decimal, previous: Decimal) -> None:
    """Диапазон 15–60 и скачок не больше 3% к последнему известному курсу."""
    if not RATE_LOW <= value <= RATE_HIGH:
        raise RateSourceError(f"значение {value} вне допустимого диапазона {RATE_LOW}–{RATE_HIGH}")
    if previous > 0:
        change = abs(value - previous) / previous
        if change > RATE_MAX_CHANGE:
            percent = (change * Decimal("100")).quantize(Decimal("0.01"))
            raise RateSourceError(f"скачок {percent}%: было {previous}, стало {value}")


def validate_source_timestamp(raw_timestamp: str, now: datetime) -> None:
    """Котировка источника не старше 24 часов и со временем в разборном формате."""
    for timestamp_format in BANK_TIMESTAMP_FORMATS:
        try:
            timestamp = datetime.strptime(raw_timestamp, timestamp_format).replace(tzinfo=BANGKOK_TZ)
            break
        except ValueError:
            continue
    else:
        raise RateSourceError("нет корректного времени котировки")
    if now.astimezone(BANGKOK_TZ) - timestamp > BANK_SOURCE_MAX_AGE:
        raise RateSourceError("котировка источника старше 24 часов")


FETCHERS = {
    "Kasikornbank": fetch_kasikorn,
    "SCB": fetch_scb,
    # Bangkok Bank требует BANGKOK_BANK_API_KEY — подставляется в worker.py.
}
