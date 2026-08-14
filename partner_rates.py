"""Курс для партнёрских платёжных ссылок: Rapira (рублёвое плечо) + Bitazza (батовое).

Математика перенесена 1-в-1 из ветки `main` агентского бота
(`A-PseudoCode-A/telegram-bot-grusha`, коммит 012086d «Rapira +3.5%, агент 30% прибыли»),
чтобы кабинет и бот считали одинаково:

    RUB/USDT  = Rapira askPrice × (1 + наценка)
    USDT/THB  = VWAP по стакану Bitazza на нужный объём − 0.15% комиссии биржи
    минус фикс 20 ฿ за вывод на тайский банк

НЕ путать с `calculator.py` — там связка Доверки с лестницей комиссий (2.72%/1.7%/0.67%
и бонус 2.4%), это другие рельсы и другой продукт. Наценку партнёра через маржу
калькулятора задать нельзя: маппинг «прибыль → комиссия» упирается в потолок при 5%.

Дележ прибыли (правило от 2026-08-06 «сначала расходы, потом агенты»):
наценка партнёра идёт СВЕРХУ нашей — её платит клиент, наш заработок она не трогает.
Revshare считается от нашей базовой прибыли, то есть от остатка после наценки.
"""
import os
import time

import requests

# ── Источники курса (публичные, ключи не нужны) ─────────────────────────────
RAPIRA_RATES_URL = os.getenv('RAPIRA_RATES_URL', 'https://api.rapira.net/open/market/rates')
BITAZZA_L2_URL = os.getenv('BITAZZA_L2_URL', 'https://apexapi.bitazza.com/AP/GetL2Snapshot')
BITAZZA_INST_USDT_THB = int(os.getenv('BITAZZA_INST_USDT_THB', '5'))  # пара USDT/THB, OMSId=1

BITAZZA_FEE = float(os.getenv('BITAZZA_FEE', '0.0015'))        # 0.15% торговая комиссия биржи
FIXED_FEE_THB = float(os.getenv('PARTNER_FIXED_FEE_THB', '20'))  # фикс за вывод на тайский банк, ฿
DEFAULT_BASE_MARKUP = float(os.getenv('PARTNER_RUB_MARKUP', '3.5'))  # наша наценка по умолчанию, %

RAPIRA_TTL = float(os.getenv('RAPIRA_CACHE_TTL', '45'))   # сек
BITAZZA_TTL = float(os.getenv('BITAZZA_CACHE_TTL', '20'))  # сек
HTTP_TIMEOUT = float(os.getenv('RATES_HTTP_TIMEOUT', '6'))

# Последнее удачное значение переживает падение источника: курс на секунду устареет,
# но ссылка создастся. Полный отказ — только если кэша нет вовсе.
_CACHE = {'rapira_ask': None, 'rapira_ts': 0.0, 'bids': None, 'bids_ts': 0.0}


class RateError(RuntimeError):
    """Курс посчитать нечем: источник недоступен и кэша нет, либо стакан не покрыл объём."""


def rapira_ask(force=False):
    """Курс RUB за 1 USDT — askPrice пары USDT/RUB. Кэш 45 сек, фоллбэк на последнее удачное."""
    now = time.time()
    if not force and _CACHE['rapira_ask'] and now - _CACHE['rapira_ts'] < RAPIRA_TTL:
        return _CACHE['rapira_ask']
    try:
        r = requests.get(RAPIRA_RATES_URL, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        rows = rows.get('data') if isinstance(rows, dict) else rows
        for row in rows or []:
            if row.get('symbol') == 'USDT/RUB':
                ask = float(row['askPrice'])
                if ask > 0:
                    _CACHE.update(rapira_ask=ask, rapira_ts=now)
                    return ask
        raise ValueError('нет пары USDT/RUB в ответе Rapira')
    except Exception as e:
        print(f'[Rapira] error: {e}')
        if _CACHE['rapira_ask'] is None:
            raise RateError('Rapira недоступна и кэша нет')
        return _CACHE['rapira_ask']


def bitazza_bids(force=False):
    """Bids стакана USDT/THB [(price, qty), …] по цене ↓. Кэш 20 сек, фоллбэк на последний удачный."""
    now = time.time()
    if not force and _CACHE['bids'] and now - _CACHE['bids_ts'] < BITAZZA_TTL:
        return _CACHE['bids']
    try:
        r = requests.get(BITAZZA_L2_URL, timeout=HTTP_TIMEOUT, params={
            'OMSId': 1, 'InstrumentId': BITAZZA_INST_USDT_THB, 'Depth': 400})
        r.raise_for_status()
        # уровень стакана: idx 6 = Price, 8 = Quantity, 9 = Side (0=bid, 1=ask)
        bids = sorted(((float(l[6]), float(l[8])) for l in r.json()
                       if l[9] == 0 and float(l[8]) > 0), reverse=True)
        if bids:
            _CACHE.update(bids=bids, bids_ts=now)
    except Exception as e:
        print(f'[Bitazza] book error: {e}')
    if not _CACHE['bids']:
        raise RateError('Стакан Bitazza недоступен и кэша нет')
    return _CACHE['bids']


def vwap(usdt_amount, bids):
    """Средневзвешенная цена продажи usdt_amount USDT по стакану.

    По неполному стакану не считаем — лучше отказать, чем назвать курс, которого нет.
    """
    if usdt_amount <= 0:
        raise RateError('Объём должен быть больше нуля')
    remaining, thb_total = usdt_amount, 0.0
    for price, qty in bids:
        take = min(remaining, qty)
        thb_total += take * price
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 1e-9:
        raise RateError(f'Стакан Bitazza не покрыл объём {usdt_amount:.2f} USDT — сумма слишком большая')
    return thb_total / usdt_amount


def solve_usdt_for_thb(thb_amount, bids):
    """Объём USDT, при котором клиент получает ровно thb_amount батов на руки.

    Ищем неподвижную точку: VWAP зависит от объёма, объём — от VWAP. Стакан монотонный,
    сходится за пару шагов. Возвращает (usdt, vwap, nett_price).
    """
    if thb_amount <= 0:
        raise RateError('Сумма в батах должна быть больше нуля')
    thb_gross = thb_amount + FIXED_FEE_THB       # столько нужно «вытащить» из биржи
    nett_price = bids[0][0] * (1 - BITAZZA_FEE)
    usdt = thb_gross / nett_price
    for _ in range(12):
        v = vwap(usdt, bids)
        nett_price = v * (1 - BITAZZA_FEE)
        new_usdt = thb_gross / nett_price
        if abs(new_usdt - usdt) <= 1e-9 * max(1.0, usdt):
            usdt = new_usdt
            break
        usdt = new_usdt
    return usdt, vwap(usdt, bids), nett_price


def quote(thb_amount=None, rub_amount=None, base_markup=None,
          partner_markup=0.0, partner_revshare=0.0, ask=None, bids=None):
    """Котировка партнёрской ссылки. Задаётся ЛИБО сумма в батах, ЛИБО в рублях.

    base_markup     — наша наценка, % (None → глобальная PARTNER_RUB_MARKUP)
    partner_markup  — наценка партнёра, % СВЕРХУ нашей (платит клиент)
    partner_revshare — доля партнёра от нашей базовой прибыли, %

    Возвращает суммы, курс и разложенную прибыль. Внутренние поля (ask, vwap, прибыль)
    наружу партнёру не отдаём — фильтрует вызывающий.
    """
    if (thb_amount is None) == (rub_amount is None):
        raise RateError('Нужна ровно одна сумма: либо в батах, либо в рублях')
    if ask is None:
        ask = rapira_ask()
    if bids is None:
        bids = bitazza_bids()

    base_m = (DEFAULT_BASE_MARKUP if base_markup is None else base_markup) / 100.0
    part_m = (partner_markup or 0.0) / 100.0
    client_multiplier = 1 + base_m + part_m      # наценки складываются, не перемножаются

    if thb_amount is None:
        # Ввод в рублях: подбираем баты обратным ходом. Прямой формулы нет —
        # VWAP зависит от объёма, поэтому идём той же неподвижной точкой.
        thb_amount = _solve_thb_for_rub(rub_amount, ask, bids, client_multiplier)

    usdt, book_vwap, nett_price = solve_usdt_for_thb(thb_amount, bids)
    pays_rub = usdt * ask * client_multiplier

    # Прибыль = поступление по рынку − выплаченное. Раскладывается ровно на наценки.
    total_profit_usdt = usdt * (base_m + part_m)
    partner_markup_usdt = usdt * part_m
    our_base_usdt = usdt * base_m
    partner_revshare_usdt = our_base_usdt * (partner_revshare or 0.0) / 100.0
    partner_usdt = partner_markup_usdt + partner_revshare_usdt
    our_usdt = our_base_usdt - partner_revshare_usdt

    return {
        'amount_rub': round(pays_rub, 2),
        'amount_thb': round(thb_amount, 2),
        'rate': round(pays_rub / thb_amount, 4) if thb_amount else 0.0,  # ₽ за 1 ฿
        'usdt': round(usdt, 8),
        'rapira_ask': round(ask, 8),
        'usdt_thb_vwap': round(book_vwap, 4),
        'usdt_thb_nett': round(nett_price, 4),
        'base_markup_percent': round(base_m * 100, 4),
        'partner_markup_percent': round(part_m * 100, 4),
        'total_profit_usdt': round(total_profit_usdt, 2),
        'partner_markup_usdt': round(partner_markup_usdt, 2),
        'partner_revshare_usdt': round(partner_revshare_usdt, 2),
        'partner_usdt': round(partner_usdt, 2),
        'partner_thb': round(partner_usdt * nett_price, 2),
        'our_usdt': round(our_usdt, 2),
        'our_thb': round(our_usdt * nett_price, 2),
    }


def _solve_thb_for_rub(rub_amount, ask, bids, client_multiplier):
    """Сколько батов на руки соответствует заданной сумме в рублях."""
    if rub_amount <= 0:
        raise RateError('Сумма в рублях должна быть больше нуля')
    usdt = rub_amount / (ask * client_multiplier)
    thb = max(usdt * bids[0][0] * (1 - BITAZZA_FEE) - FIXED_FEE_THB, 0.01)
    for _ in range(24):
        u, _v, nett = solve_usdt_for_thb(thb, bids)
        got_rub = u * ask * client_multiplier
        if abs(got_rub - rub_amount) <= 0.01:
            break
        # Корректируем баты в пропорции промаха по рублям.
        thb = max(thb * (rub_amount / got_rub), 0.01)
    return thb
