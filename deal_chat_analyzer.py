"""Анализатор чата сделки Bitrix — перенесён из бота DealCloser (2026-08-10).

Бот выключается: закрытие сделок переезжает в CRM, чтобы конверсия считалась
в одном месте и разбор переписки был виден оператору на экране, а не в чате
с ботом. Логика разбора не менялась — это тот же код, что крутился в проде
с апреля, только конфиг втянут внутрь и вызывается из Flask через asyncio.run.

Ключевая логика — не путать активность новой сделки с историей прошлых обменов
того же клиента. Перед анализом нужна "прошлая закрытая сделка" того же контакта:
её CLOSEDATE становится cutoff-точкой для фильтрации чата.

Правила cutoff:
- Прошлая WON → жёсткий: в LLM уходит ТОЛЬКО хвост после closedate.
  Суммы/метод из прошлого обмена игнорируются (защита от кейса Андрея).
- Прошлая LOSE → мягкий: хвост + прошлый LOSE-диалог как единый контекст.
  Клиент мог вернуться к тому же намерению ("давай как вчера"). Суммы можно
  брать из всего контекста, хвост приоритетнее. Факт оплаты — только из хвоста.
- Нет прошлой → весь чат.

Двухпроходная схема:
1. Intent-классификатор хвоста (дешёвый вызов) → cancel / rate_inquiry / greeting
   → ранний LOSE/UNKNOWN без полного анализа.
2. Полный анализ — только для new_payment / new_request / old_deal_inquiry /
   status_question / unclear.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from openai import AsyncOpenAI

# Константы перенесены из DealCloser (бот выключается, закрытие живёт в CRM).
# Фаундеры — по номеру телефона, которым подписаны выдачи в чате.
FOUNDER_BY_PHONE = {
    "0818429939": "Андрей",
    "0991971701": "Тёда",
}
DOVERKA_BONUS = 1.024
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-3-flash-preview")

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
# Промпты
# ────────────────────────────────────────────────────────────────────────────

INTENT_SYSTEM_PROMPT = """Ты классифицируешь последнее намерение клиента в чате обменника Grusha.

Тебе дают только хвост чата — сообщения после закрытия прошлой сделки клиента (или весь чат, если прошлых нет).
Нужно определить, ЗАЧЕМ клиент пишет сейчас.

Категории:
- "new_payment" — клиент ОПЛАТИЛ или ЗАВЕРШИЛ текущую сделку. Сигналы:
  • факт оплаты: "оплатил", "перевёл", "готово ✅", хэш транзакции, скрин чека, ссылка Doverka PAID
  • факт получения бат: "забрал", "получил баты", "получил деньги", "спасибо за обмен", "всё получил", "снял в банкомате"
  • в хвосте виден адрес кошелька/TX от клиента, потом менеджер пишет "получили" / "зачислено" и клиент благодарит — это тоже new_payment (обмен завершён)
- "new_request" — клиент хочет обменять, идёт обсуждение сумм/курса, но оплаты ещё нет
- "old_deal_inquiry" — клиент спрашивает или жалуется ПРО ПРОШЛУЮ сделку ("где мои баты", "не дошло", "когда выдача", "с прошлого раза не получил"). Ключевой признак: ссылка на предыдущий обмен, а не новый запрос.
- "cancel" — "случайно нажал", "передумал", "ошибся", "не надо", "отмена"
- "rate_inquiry" — только спрашивает курс/сколько получит, без намерения ("какой курс?", "сколько за 10к?")
- "greeting" — только здоровается, без сути ("привет", "на связи", "добрый день"). БЕЗ обсуждения сумм, без упоминания оплаты/получения.
- "unclear" — непонятно что хочет, мало данных

ВАЖНО:
- Слова менеджера НЕ считаются как intent клиента, НО используются как контекст. Если менеджер пишет "Получили" после того как клиент прислал адрес/хэш, а клиент потом пишет "Забрал спасибо" — это new_payment, НЕ greeting.
- "Спасибо"/"благодарю" после обсуждения оплаты и кошелька/ATM-кода — это ПОДТВЕРЖДЕНИЕ получения (new_payment), а не просто вежливость (greeting).
- Если клиент написал "давай обменяю" и уже обсуждал сумму С МЕНЕДЖЕРОМ в хвосте — это new_request, НЕ old_deal_inquiry.
- Если клиент написал "где мои баты" — это old_deal_inquiry, даже если в хвосте больше ничего нет.
- "greeting" ставь ТОЛЬКО если в хвосте нет сумм, нет кошельков, нет обсуждения обмена — клиент просто поздоровался и молчит.

Верни ТОЛЬКО JSON: {"intent": "...", "confidence": "high" | "low", "reason": "краткое объяснение"}"""


FULL_SYSTEM_PROMPT_BASE = """Ты анализируешь чат между менеджером обменника Grusha и клиентом.
Grusha — обмен RUB→THB, USDT→THB для русскоязычных в Таиланде.

Твоя задача — извлечь структурированные данные текущей сделки.

## Методы оплаты (payin_method)
- "spp_doverka" — ссылка grushab-2-b.ru / doverkapay.com, СБП-ссылка (qr.nspk.ru), упоминание СБП/реквизитов
- "sber_wl" — оплата через Сбербанк / ссылка обменника WL / wl.grusha.agency, явное упоминание «Сбер», «сбербанк»
- "crypto_direct" — клиент отправляет USDT/крипту напрямую (Bybit, TRC-20, кошелёк)
- "partners_cash" — наличные, курьер привозит, партнёр
ВАЖНО: если СБП-оплата без явных признаков Сбера — ставь "spp_doverka" (дефолт). "sber_wl" только при явном Сбере; оператор переключит вручную при необходимости.

## Методы выдачи (payout_method)
- "atm" — банкомат, cardless, SCB ATM
- "transfer" — перевод на тайский счёт, QR-оплата
- "office" — выдача в офисе
- "courier" — курьер доставляет

## Фаундеры (кто выдал THB)
- Номер 0818429939 → "Андрей"
- Номер 0991971701 → "Тёда"
- Если номер не найден — по умолчанию "Андрей"

## WON/LOSE/UNKNOWN
- WON — клиент ОПЛАТИЛ или ЗАВЕРШИЛ текущую сделку. Сигналы:
  • факт оплаты от клиента: "оплатил", "готово ✅", "перевёл", скрин чека, хэш транзакции, Doverka PAID
  • факт получения бат: "забрал", "получил баты/деньги", "спасибо за обмен", "снял в банкомате", "всё ок"
  • связка "клиент прислал адрес кошелька/хэш → менеджер «получили»/«зачислено» → клиент «забрал»/«спасибо»" — это законченный обмен, WON с high confidence
  Описание флоу от менеджера ("переведёте → снимете") без подтверждения от клиента ≠ WON.
- LOSE — нет факта оплаты/получения в текущей сделке (клиент ушёл, передумал, только спрашивал курс, случайно написал, банк заблокирован)
- UNKNOWN — непонятно, мало данных, клиент в процессе обсуждения

## Суммы
- payin_amount_rub — сколько рублей получили. Форматы: "100 000", "100.000", "100,000", "100000" — всё это 100000. Точка и запятая могут быть разделителем тысяч!
- payin_amount_usdt — сколько USDT получили (из расчёта "XXX.XX USDT | Курс:")
- payout_amount_thb — ФИНАЛЬНАЯ сумма бат клиенту. Если финальная сумма неясна — ставь null.
- payout_amount_usdt — обычно равно payin_amount_usdt для крипты
- payment_time — примерное время оплаты клиентом (HH:MM из чата, когда клиент прислал чек/скрин/подтверждение). null если неясно.

НЕ УГАДЫВАЙ суммы. Лучше null, чем неправильное число. Но "Сумма 100.000₽" = 100000, НЕ null.

## Реферальный код
Если в чате клиент упоминает реферальный код (формат "GR-XXX"), или говорит "от друга", "по рекомендации [имя]", "посоветовал [имя]", или менеджер спрашивает "откуда узнали?" и клиент называет имя — извлеки:
- referral_code: строка (код GR-XXX) или null
- referred_by_name: имя реферера если упоминается, или null
Также проверь start-параметр бота: если видишь "ref__GRKARIM" — это реферальный код GR-KARIM.

Верни ТОЛЬКО валидный JSON, без markdown-обёртки."""


USER_PROMPT_TEMPLATE = """Проанализируй сделку "{deal_title}" и верни JSON:

```
{{
  "verdict": "WON" | "LOSE" | "UNKNOWN",
  "confidence": "high" | "low",
  "payin_method": "spp_doverka" | "sber_wl" | "crypto_direct" | "partners_cash",
  "payin_amount_usdt": число или null,
  "payin_amount_rub": число или null,
  "payout_amount_thb": число или null,
  "payout_amount_usdt": число или null,
  "payout_method": "atm" | "transfer" | "office" | "courier",
  "payout_founder_name": "Андрей" | "Тёда",
  "payment_time": "HH:MM" или null,
  "lose_reason": "причина если LOSE, иначе пустая строка",
  "referral_code": "GR-XXX или null",
  "referred_by_name": "имя реферера или null",
  "summary": "краткое описание сделки в 1-2 предложения"
}}
```

{context_block}

Сообщения чата (от новых к старым):
{chat_text}"""


# ────────────────────────────────────────────────────────────────────────────
# Валидация enum-полей (LLM-output → CalcCRM-enum)
# ────────────────────────────────────────────────────────────────────────────

VALID_PAYIN_METHODS = {"spp_doverka", "sber_wl", "crypto_direct", "partners_cash"}
VALID_PAYOUT_METHODS = {"office", "courier", "atm", "transfer"}

# Алиасы для типичных галлюцинаций LLM
PAYIN_ALIASES = {
    "usdt": "crypto_direct",
    "crypto": "crypto_direct",
    "usdt_trc20": "crypto_direct",
    "trc20": "crypto_direct",
    "sbp": "spp_doverka",
    "spp": "spp_doverka",
    "doverka": "spp_doverka",
    "sber": "sber_wl",
    "sberbank": "sber_wl",
    "сбер": "sber_wl",
    "сбербанк": "sber_wl",
    "wl": "sber_wl",
    "cash": "partners_cash",
    "partner": "partners_cash",
    "partners": "partners_cash",
}
PAYOUT_ALIASES = {
    "crypto": "transfer",
    "usdt": "transfer",
    "wallet": "transfer",
    "cash": "office",
    "office_cash": "office",
    "atm_cash": "atm",
}


def _normalize_payin_method(value: str | None) -> str:
    """Нормализует payin_method к валидному CalcCRM enum. Дефолт — crypto_direct."""
    if not value:
        return "crypto_direct"
    v = value.strip().lower()
    if v in VALID_PAYIN_METHODS:
        return v
    if v in PAYIN_ALIASES:
        normalized = PAYIN_ALIASES[v]
        logger.warning(f"payin_method '{value}' нормализован → '{normalized}'")
        return normalized
    logger.warning(f"payin_method '{value}' неизвестен — дефолт crypto_direct")
    return "crypto_direct"


def _normalize_payout_method(value: str | None) -> str:
    """Нормализует payout_method к валидному CalcCRM enum. Дефолт — transfer."""
    if not value:
        return "transfer"
    v = value.strip().lower()
    if v in VALID_PAYOUT_METHODS:
        return v
    if v in PAYOUT_ALIASES:
        normalized = PAYOUT_ALIASES[v]
        logger.warning(f"payout_method '{value}' нормализован → '{normalized}'")
        return normalized
    logger.warning(f"payout_method '{value}' неизвестен — дефолт transfer")
    return "transfer"


# ────────────────────────────────────────────────────────────────────────────
# AnalysisResult
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """Результат анализа чата сделки."""
    verdict: str = "UNKNOWN"          # WON / LOSE / UNKNOWN
    confidence: str = "low"           # high / low
    payin_method: str = "crypto_direct"
    payin_amount_usdt: float | None = None
    payin_amount_rub: float | None = None
    payout_amount_thb: float | None = None
    payout_amount_usdt: float | None = None
    payout_method: str = "transfer"
    payout_founder_name: str = "Андрей"
    lose_reason: str = ""
    summary: str = ""
    payin_tx_hash: str = ""
    doverka_transaction_id: str = ""
    raw_messages: list = field(default_factory=list)
    # Контекст прошлых сделок — для отображения оператору
    prev_deal_id: int | None = None
    prev_deal_stage: str = ""        # "WON" / "LOSE" / ""
    prev_deal_closedate: str = ""
    prev_deal_summary: str = ""      # "157.62 USDT → 5000 THB"
    total_closed_deals: int = 0
    intent: str = ""                 # результат intent-классификатора
    cutoff_iso: str = ""             # ISO-дата отсечки (для verify)
    payment_time: str = ""           # HH:MM — примерное время оплаты из чата
    referral_code: str = ""          # реферальный код GR-XXX из чата
    referred_by_name: str = ""       # имя реферера из чата
    source_channel: str = ""         # канал привлечения из /start-парама (utm_source__/ref__)

    def to_calccrm_payload(self, client_id: int | None = None, client_name: str | None = None) -> dict:
        """Конвертация в payload для POST /api/deals.
        CalcCRM сам создаёт клиента по client_name если client_id не указан."""
        payload = {}
        if client_id:
            payload["client_id"] = client_id
        elif client_name:
            payload["client_name"] = client_name
        payload.update({
            "payin_method": self.payin_method,
            "payin_amount_usdt": self.payin_amount_usdt,
            "payin_amount_rub": self.payin_amount_rub,
            "payout_amount_thb": self.payout_amount_thb,
            "payout_amount_usdt": self.payout_amount_usdt,
            "payout_method": self.payout_method,
            "payout_source": "founder_personal",
            "payout_founder_name": self.payout_founder_name,
            "status": "pending",
            "payin_tx_hash": self.payin_tx_hash or None,
            "doverka_transaction_id": self.doverka_transaction_id or None,
        })
        # Реферер: если LLM нашёл код или имя — передаём
        if self.referral_code:
            payload["referrer_name"] = self.referral_code
        elif self.referred_by_name:
            payload["referrer_name"] = self.referred_by_name
        if self.source_channel:
            payload["source_channel"] = self.source_channel
        return payload


# ────────────────────────────────────────────────────────────────────────────
# Утилиты чата
# ────────────────────────────────────────────────────────────────────────────


# Bitrix автор менеджера — Kareem. Все системные сообщения имеют author_id=0.
MANAGER_AUTHOR_IDS = {967}


def _msg_datetime(msg: dict) -> datetime | None:
    """Парсит дату сообщения Bitrix в datetime."""
    raw = msg.get("date", "")
    if not raw:
        return None
    try:
        # Bitrix отдаёт формат "2026-04-10T14:12:34+03:00"
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_cutoff(cutoff_iso: str) -> datetime | None:
    """Парсит ISO-строку cutoff (CLOSEDATE прошлой сделки)."""
    if not cutoff_iso:
        return None
    try:
        return datetime.fromisoformat(cutoff_iso.replace("Z", "+00:00"))
    except Exception:
        return None


def _filter_after_cutoff(messages: list[dict], cutoff_iso: str) -> list[dict]:
    """Оставляет сообщения после cutoff. Если cutoff пустой — возвращает всё.

    Bitrix отдаёт сообщения от новых к старым, поэтому проходим до первого
    сообщения с датой <= cutoff и обрезаем.
    """
    cutoff = _parse_cutoff(cutoff_iso)
    if not cutoff:
        return messages
    tail = []
    for msg in messages:
        mdt = _msg_datetime(msg)
        if mdt is None:
            # Если дату не распарсили — не режем, на всякий случай включаем
            tail.append(msg)
            continue
        # Сравнение tz-aware/naive: приводим к одному виду
        if mdt.tzinfo and not cutoff.tzinfo:
            mdt = mdt.replace(tzinfo=None)
        elif cutoff.tzinfo and not mdt.tzinfo:
            mdt = mdt.replace(tzinfo=cutoff.tzinfo)
        if mdt > cutoff:
            tail.append(msg)
    return tail


# Пустышки, "ага/да/ок" — не считаются содержательными
_TRIVIAL_TEXTS = {
    "ок", "ok", "окей", "okay", "ага", "да", "yes", "нет", "no",
    "спасибо", "thanks", "thx", "+", "👍", "🙏", "✅", "понял",
    "хорошо", "добро", "здрав", "привет", "hi", "hello",
}


def _is_content_message(msg: dict) -> bool:
    """Содержательное ли сообщение от клиента (не пустое, не эмодзи/ок)."""
    author = msg.get("author_id", 0)
    if author == 0 or author in MANAGER_AUTHOR_IDS:
        return False
    text = (msg.get("text") or "").strip().lower()
    if not text:
        return False
    if text in _TRIVIAL_TEXTS:
        return False
    # Только эмодзи или одна буква
    if len(text) <= 2:
        return False
    return True


def _extract_referral_code(messages: list[dict]) -> str:
    """Извлекает реферальный код из /start ref__GRXXXX в сообщениях.

    Regex надёжнее LLM для детерминированного формата.
    Возвращает код в формате GR-XXXX или пустую строку.
    """
    for msg in messages:
        text = (msg.get("text") or "").strip()
        # Формат: /start ref__GRKARIM или ref__GR629889_calc_RUB_1kk_THB
        match = re.search(r"ref__GR([A-Za-z0-9_]+)", text)
        if match:
            raw = match.group(1)
            # Отсекаем суффиксы _calc_... (это параметры калькулятора, не часть кода)
            code_part = raw.split("_calc_")[0].split("_")[0] if "_calc_" in raw else raw
            # Убираем числовые ID сделок (ref__GR629889 → не реферал, а ссылка на сделку)
            if code_part.isdigit():
                continue
            return f"GR-{code_part.upper()}"
    return ""


def _extract_source_channel(messages: list[dict]) -> str:
    """Канал привлечения из /start-парама бота в сообщениях чата.

    Лендинг зашивает канал в start: utm_source__insta_calc_... → 'insta',
    ref__GRKARIM... → 'ref:GR-KARIM'. Нет метки — пустая строка (органика/директ).
    """
    for msg in messages:
        text = (msg.get("text") or "").strip()
        # Значение utm очищено лендингом до [A-Za-z0-9], суффиксы _calc_/_quiz_ отсекает regex
        match = re.search(r"utm_source__([A-Za-z0-9]+)", text)
        if match:
            return match.group(1).lower()[:50]
    ref = _extract_referral_code(messages)
    if ref:
        return f"ref:{ref}"
    return ""


def _last_client_message(messages: list[dict]) -> dict | None:
    """Последнее сообщение клиента в списке (сообщения идут от новых к старым)."""
    for msg in messages:
        author = msg.get("author_id", 0)
        if author != 0 and author not in MANAGER_AUTHOR_IDS:
            text = (msg.get("text") or "").strip()
            if text:
                return msg
    return None


def _format_chat_for_llm(messages: list[dict], label: str | None = None) -> str:
    """Форматирует сообщения Bitrix в читаемый текст для LLM."""
    lines = []
    if label:
        lines.append(f"=== {label} ===")
    for msg in messages:
        author = msg.get("author_id", 0)
        text = (msg.get("text") or "").strip()
        date = (msg.get("date") or "")[:16]
        if not text:
            continue
        if author == 0:
            role = "[СИСТЕМА]"
        elif author in MANAGER_AUTHOR_IDS:
            role = "[МЕНЕДЖЕР]"
        else:
            role = "[КЛИЕНТ]"
        lines.append(f"{date} {role}: {text}")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
# LLM клиент
# ────────────────────────────────────────────────────────────────────────────


def _llm_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    )


def _strip_markdown_json(text: str) -> str:
    """Убирает обёртку ```json ... ``` если есть."""
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("\n", 1)
        if len(parts) > 1:
            text = parts[1]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


# ────────────────────────────────────────────────────────────────────────────
# Intent классификатор (Проход 1)
# ────────────────────────────────────────────────────────────────────────────


async def _classify_intent(
    tail_text: str,
    prev_context: str,
) -> tuple[str, str, str]:
    """Дешёвый LLM-вызов — определяет intent последнего намерения клиента.

    Возвращает (intent, confidence, reason).
    """
    if not tail_text.strip():
        return "empty", "high", "хвост пустой"

    user_prompt = f"""{prev_context}

Хвост чата (после закрытия прошлой сделки или весь чат если прошлых нет):
{tail_text}

Классифицируй последнее намерение клиента. Верни только JSON."""

    try:
        client = _llm_client()
        response = await client.chat.completions.create(
            model=OPENROUTER_MODEL,
            max_tokens=256,
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content
        data = json.loads(_strip_markdown_json(raw))
        intent = data.get("intent", "unclear")
        confidence = data.get("confidence", "low")
        reason = data.get("reason", "")
        logger.info(
            f"Intent: {intent} ({confidence}) — {reason}, "
            f"tokens: {response.usage.prompt_tokens}+{response.usage.completion_tokens}"
        )
        return intent, confidence, reason
    except Exception as e:
        logger.error(f"Intent classifier error: {e}")
        return "unclear", "low", f"ошибка классификатора: {e}"


# ────────────────────────────────────────────────────────────────────────────
# Полный анализ (Проход 2)
# ────────────────────────────────────────────────────────────────────────────


async def _full_analysis(
    deal_title: str,
    chat_text: str,
    context_block: str,
) -> dict | None:
    """Полный LLM-анализ сделки. Возвращает распарсенный JSON или None."""
    try:
        client = _llm_client()
        response = await client.chat.completions.create(
            model=OPENROUTER_MODEL,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": FULL_SYSTEM_PROMPT_BASE},
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(
                        deal_title=deal_title,
                        context_block=context_block,
                        chat_text=chat_text,
                    ),
                },
            ],
        )
        raw = response.choices[0].message.content
        data = json.loads(_strip_markdown_json(raw))
        logger.info(
            f"Full analysis #{deal_title}: {data.get('verdict')} ({data.get('confidence')}), "
            f"tokens: {response.usage.prompt_tokens}+{response.usage.completion_tokens}"
        )
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Full analysis JSON parse error: {e}")
        return None
    except Exception as e:
        logger.error(f"Full analysis LLM error: {e}")
        return None


# ────────────────────────────────────────────────────────────────────────────
# Главная функция
# ────────────────────────────────────────────────────────────────────────────


def _format_prev_summary(prev_deal: dict | None) -> str:
    """Краткое саммари прошлой сделки для контекста."""
    if not prev_deal:
        return ""
    pid = prev_deal.get("ID", "?")
    stage = prev_deal.get("STAGE_ID", "")
    if "WON" in stage:
        stage_label = "WON"
    elif "LOSE" in stage:
        stage_label = "LOSE"
    else:
        stage_label = stage
    closedate = (prev_deal.get("CLOSEDATE") or "")[:10]
    title = prev_deal.get("TITLE", "")
    return f"#{pid} {stage_label} {closedate} ({title})"


async def analyze_chat(
    messages: list[dict],
    deal_title: str = "",
    extra_context: str = "",
    prev_deal: dict | None = None,
    prev_deal_messages: list[dict] | None = None,
    total_closed: int = 0,
) -> AnalysisResult:
    """Анализирует чат сделки с учётом истории прошлых закрытых сделок клиента.

    messages — сообщения ТЕКУЩЕЙ сделки (от новых к старым, как отдаёт Bitrix)
    prev_deal — данные последней закрытой сделки того же контакта (или None)
    prev_deal_messages — сообщения прошлого LOSE-диалога (только для мягкого cutoff)
    total_closed — сколько всего закрытых сделок было у клиента
    """
    result = AnalysisResult()
    result.raw_messages = messages
    result.total_closed_deals = total_closed

    if not messages:
        result.verdict = "UNKNOWN"
        result.summary = "Нет сообщений в чате"
        return result

    # ─── Cutoff по прошлой сделке ───────────────────────────────────
    cutoff_iso = ""
    prev_stage_label = ""
    if prev_deal:
        cutoff_iso = prev_deal.get("CLOSEDATE", "") or ""
        stage_id = prev_deal.get("STAGE_ID", "")
        prev_stage_label = "WON" if "WON" in stage_id else ("LOSE" if "LOSE" in stage_id else "")
        result.prev_deal_id = int(prev_deal.get("ID", 0)) or None
        result.prev_deal_stage = prev_stage_label
        result.prev_deal_closedate = cutoff_iso[:10]
        result.prev_deal_summary = _format_prev_summary(prev_deal)
    result.cutoff_iso = cutoff_iso

    # Хвост чата — сообщения текущей сделки после cutoff
    tail = _filter_after_cutoff(messages, cutoff_iso)

    # Ранний выход: нет содержательных сообщений клиента в хвосте
    client_content_msgs = [m for m in tail if _is_content_message(m)]
    if not client_content_msgs:
        result.verdict = "UNKNOWN"
        result.confidence = "high"
        result.summary = (
            "Новой активности от клиента в текущей сделке нет. "
            + (f"Прошлая сделка: {result.prev_deal_summary}." if prev_deal else "")
        ).strip()
        return result

    # ─── Проход 1: intent хвоста ───────────────────────────────────
    tail_text = _format_chat_for_llm(tail, label="Хвост текущей сделки")
    if extra_context:
        tail_text += f"\n\n[ДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ОТ МЕНЕДЖЕРА]: {extra_context}"

    prev_context_line = ""
    if prev_deal:
        prev_context_line = (
            f"Контекст: у клиента была прошлая сделка {result.prev_deal_summary}. "
            f"Всего закрытых сделок у клиента: {total_closed}."
        )

    intent, intent_conf, intent_reason = await _classify_intent(tail_text, prev_context_line)
    result.intent = intent

    # ─── Ранние вердикты без полного анализа ───────────────────────
    if intent == "cancel":
        result.verdict = "LOSE"
        result.confidence = "high" if intent_conf == "high" else "low"
        result.lose_reason = "ошибочное обращение"
        result.summary = f"Клиент отменил/написал случайно ({intent_reason})."
        return result

    if intent == "rate_inquiry":
        result.verdict = "LOSE"
        result.confidence = "high" if intent_conf == "high" else "low"
        result.lose_reason = "только спрашивал курс"
        result.summary = f"Клиент только уточнял курс, без намерения обмена ({intent_reason})."
        return result

    if intent == "greeting":
        result.verdict = "UNKNOWN"
        result.confidence = "low"
        result.summary = f"Клиент только поздоровался, сути нет ({intent_reason})."
        return result

    # ─── Проход 2: полный анализ ───────────────────────────────────
    # Собираем вход для LLM в зависимости от стадии прошлой сделки
    if prev_stage_label == "LOSE" and prev_deal_messages:
        # Мягкий cutoff: прошлый LOSE-диалог + хвост как единый контекст
        prev_text = _format_chat_for_llm(
            prev_deal_messages,
            label=f"Предыдущее обсуждение (сделка #{result.prev_deal_id} LOSE, {result.prev_deal_closedate})",
        )
        chat_text = f"{prev_text}\n\n{tail_text}"
        context_block = (
            f"КОНТЕКСТ ПРОШЛОЙ СДЕЛКИ:\n"
            f"Прошлая сделка клиента #{result.prev_deal_id} была LOSE ({result.prev_deal_closedate}). "
            f"Клиент мог вернуться к тому же намерению — сообщения после её закрытия "
            f"это продолжение того же обсуждения.\n\n"
            f"Правила использования контекста:\n"
            f"- Суммы, метод оплаты, курс, способ выдачи — бери из ВСЕЙ переписки. "
            f"Если клиент в хвосте ссылается на прошлое ('как вчера', 'те же 10к') — бери детали из LOSE-диалога.\n"
            f"- Если клиент в хвосте назвал НОВЫЕ цифры — они переопределяют старые.\n"
            f"- Факт оплаты (verdict WON) ищи ТОЛЬКО в хвосте. В прошлом LOSE оплаты не было по определению.\n"
        )
    elif prev_stage_label == "WON":
        # Жёсткий cutoff: только хвост, прошлое даже не показываем
        chat_text = tail_text
        context_block = (
            f"КОНТЕКСТ ПРОШЛОЙ СДЕЛКИ:\n"
            f"У клиента была прошлая сделка #{result.prev_deal_id} — WON {result.prev_deal_closedate}. "
            f"Эта сделка ЗАВЕРШЕНА. Её суммы, метод оплаты и способ выдачи относятся "
            f"к ТОЙ операции и НЕ используй их для текущей сделки.\n"
            f"Всего закрытых сделок у клиента: {total_closed}.\n"
            f"Анализируй ТОЛЬКО сообщения ниже — это активность после закрытия прошлой сделки.\n"
        )
    else:
        # Новый клиент — весь чат
        chat_text = tail_text
        context_block = "КОНТЕКСТ: у клиента нет прошлых закрытых сделок, это новый клиент."

    data = await _full_analysis(deal_title, chat_text, context_block)

    if not data:
        result.verdict = "UNKNOWN"
        result.summary = "Ошибка полного анализа — проверь логи"
        return result

    result.verdict = data.get("verdict", "UNKNOWN")
    result.confidence = data.get("confidence", "low")
    # Валидация enum-полей: LLM может галлюцинировать ("usdt", "crypto" и т.п.),
    # а CalcCRM API ругается 400 на неизвестное значение. Нормализуем к ближайшему валидному.
    result.payin_method = _normalize_payin_method(data.get("payin_method"))
    result.payin_amount_usdt = data.get("payin_amount_usdt")
    result.payin_amount_rub = data.get("payin_amount_rub")
    result.payout_amount_thb = data.get("payout_amount_thb")
    result.payout_amount_usdt = data.get("payout_amount_usdt")
    result.payout_method = _normalize_payout_method(data.get("payout_method"))
    result.payout_founder_name = data.get("payout_founder_name", "Андрей")
    result.lose_reason = data.get("lose_reason", "")
    result.summary = data.get("summary", "")
    result.payment_time = data.get("payment_time") or ""
    result.referral_code = data.get("referral_code") or ""
    result.referred_by_name = data.get("referred_by_name") or ""

    # Regex-фоллбэк: если LLM не нашёл реферала, ищем ref__GRXXXX в сообщениях
    if not result.referral_code:
        regex_ref = _extract_referral_code(messages)
        if regex_ref:
            result.referral_code = regex_ref
            logger.info(f"Referral code from regex: {regex_ref}")

    # Канал привлечения из /start-парама (utm_source__/ref__) — для воронки по каналам
    result.source_channel = _extract_source_channel(messages)
    if result.source_channel:
        logger.info(f"Source channel: {result.source_channel}")

    # Применяем бонус Doverka если метод spp_doverka
    if result.payin_method == "spp_doverka" and result.payout_amount_usdt:
        result.payin_amount_usdt = round(result.payout_amount_usdt * DOVERKA_BONUS, 2)

    return result
