"""
Exchange Calculator Bot - Калькулятор обмена RUB-THB
Получает реальные курсы от Binance (USDT/THB) и Rapira (RUB/USDT)
"""

import aiohttp
import asyncio
import os
import threading
import time as _time
from queue import PriorityQueue
from typing import Dict, Tuple
from dotenv import load_dotenv
from decimal import Decimal, ROUND_HALF_UP
from playwright.async_api import async_playwright

# Загружаем переменные окружения
def load_env():
    # Пробуем найти .env, поднимаясь наверх от текущего файла
    current_path = os.path.dirname(os.path.abspath(__file__))
    
    # Проверяем текущую папку и 4 уровня выше
    for _ in range(5):
        env_path = os.path.join(current_path, '.env')
        if os.path.exists(env_path):
            load_dotenv(env_path)
            print(f"✅ Загружен .env из: {env_path}")
            return True
        parent = os.path.dirname(current_path)
        if parent == current_path: # Дошли до корня диска
            break
        current_path = parent
        
    print("⚠️ Файл .env не найден")
    return False

load_env()


class _PlaywrightQueue:
    """Приоритетная очередь для Playwright-запросов.

    Один worker-поток по очереди прогоняет async-задачи через `asyncio.run`.
    Параллельные Chromium не запускаются → защита от OOM и падений CRM.
    Приоритет: 0 = партнёр (важнее), 1 = CRM.
    """

    def __init__(self):
        self.queue = PriorityQueue()
        self._seq = 0
        self._seq_lock = threading.Lock()
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def _worker(self):
        while True:
            _prio, _seq, coro_factory, event, holder = self.queue.get()
            try:
                holder['result'] = asyncio.run(coro_factory())
            except Exception as e:
                holder['error'] = e
            finally:
                event.set()

    def submit(self, coro_factory, priority: int = 1, timeout: int = 60) -> dict:
        """Ставит задачу в очередь и ждёт результат.

        Args:
            coro_factory: callable → coroutine (чтобы asyncio.run её запустил)
            priority: 0=партнёр, 1=CRM. Меньше = раньше.
            timeout: сколько секунд ждать в очереди до отказа.

        Returns:
            dict — результат get_precise_binance_rate(),
                   либо {'error': 'queue_timeout'},
                   либо {'error': '<exception>'}.
        """
        event = threading.Event()
        holder: dict = {}
        seq = self._next_seq()
        self.queue.put((priority, seq, coro_factory, event, holder))

        if not event.wait(timeout=timeout):
            # Задача может быть ещё в очереди — worker её выполнит, но результат мы уже не ждём
            return {'error': 'queue_timeout'}

        if 'error' in holder:
            return {'error': str(holder['error'])}
        return holder['result']


# Глобальный инстанс — создаётся при импорте модуля
playwright_queue = _PlaywrightQueue()

# Функция округления как в Excel
def excel_round(value, decimals=2):
    """
    Округление как в Excel (коммерческое округление)
    0.5 всегда округляется вверх
    """
    d = Decimal(str(value))
    if decimals == 0:
        return float(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    else:
        places = Decimal(10) ** -decimals
        return float(d.quantize(places, rounding=ROUND_HALF_UP))


def safe_rate(numerator, denominator, decimals=6):
    """Итоговый курс с защитой от деления на ноль.

    Когда сумма выдачи после вычета фикс-комиссии округляется в 0 (слишком
    маленькая сумма обмена), знаменатель = 0 → ZeroDivisionError роняет весь
    /api/calculate. Возвращаем 0.0, чтобы валидацию суммы делал вызывающий код.
    """
    if not denominator:
        return 0.0
    return excel_round(numerator / denominator, decimals)

# Импорт детального калькулятора брокера
try:
    from broker_detailed import BrokerCalculatorDetailed
except ImportError:
    # Если файл в другой директории
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from broker_detailed import BrokerCalculatorDetailed


class ExchangeRateProvider:
    """Провайдер курсов валют"""
    
    BINANCE_API = "https://api.binance.th/api/v1"
    RAPIRA_API = "https://api.rapira.net"

    # API ключи из переменных окружения
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')

    # RUB-USDT = чистый стакан Рапиры, без наценки (решение Карима 19.08.2026).
    # Раньше было +2% «за прогон рублей через биржу», но эти 2% сидели внутри
    # курса и не попадали в показанную прибыль: при заявленных 5% фактическая
    # маржа выходила 7.1% к стакану. Теперь база = ask, вся маржа собирается
    # видимой комиссией USDT-THB, profit_percent_actual = правда.
    # Доверка как источник курса убрана 17.08.2026 — её курс был на ~5% выше
    # рынка и держал экономику на бонусе 2.4%.
    RAPIRA_MARKUP = 1.0

    # Фоллбэк, если Рапира недоступна (стакан + тикер): уровень стакана без наценки
    FALLBACK_RUB_USDT = 88.0  # обновлён 19.08.2026
    
    @staticmethod
    async def get_binance_rate(symbol: str = "USDTTHB") -> float:
        """
        Получить курс от Binance (сначала TH, потом Global как фоллбэк)
        """
        # 1. Пробуем Binance Thailand (2 попытки)
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{ExchangeRateProvider.BINANCE_API}/ticker/price"
                    params = {"symbol": symbol}
                    headers = {}
                    if ExchangeRateProvider.BINANCE_API_KEY:
                        headers['X-MBX-APIKEY'] = ExchangeRateProvider.BINANCE_API_KEY

                    async with session.get(url, params=params, headers=headers, timeout=10) as response:
                        print(f"DEBUG: Binance TH status: {response.status}", flush=True)
                        if response.status == 200:
                            data = await response.json()
                            print(f"DEBUG: Binance TH raw data: {data}", flush=True)
                            if isinstance(data, dict):
                                if data.get("code") == 0 and "data" in data:
                                    price_data = data["data"]
                                    if isinstance(price_data, list):
                                        for item in price_data:
                                            if item.get("symbol") == symbol:
                                                return float(item.get("price"))
                                    elif isinstance(price_data, dict):
                                        return float(price_data.get("price"))
                                elif "price" in data:
                                    return float(data["price"])
            except Exception as e:
                print(f"⚠️ Binance TH attempt {attempt+1} error: {e}")

        # 2. Фоллбэк на Binance Global
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.binance.com/api/v3/ticker/price"
                params = {"symbol": "USDTTHB"}
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        print(f"DEBUG: Binance Global rate: {data.get('price')}")
                        return float(data['price'])
        except Exception as e:
            print(f"❌ Binance Global error: {e}")

        print(f"❌ Binance TH и Global недоступны — курс USDT/THB не получен")
        return None
    
    @staticmethod
    async def get_rapira_rate() -> float:
        """
        Курс RUB-USDT: топ ask стакана Рапиры × RAPIRA_MARKUP (сейчас 1.0, без наценки).

        Ask — потому что мы ПОКУПАЕМ USDT за рубли клиента; глубина топа
        обычно шестизначная в USDT, VWAP не нужен. Стакан отдаётся ТОЛЬКО
        на POST с form-data (28.07.2026 сменили контракт, GET → 500).
        Фоллбэк — публичный тикер /open/market/rates (askPrice).
        """
        # 1. Стакан (2 попытки)
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{ExchangeRateProvider.RAPIRA_API}/market/exchange-plate-mini"
                    async with session.post(url, data={'symbol': 'USDT/RUB'}, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            items = (data.get('ask') or {}).get('items') or []
                            if items:
                                top_ask = float(items[0]['price'])
                                rate = top_ask * ExchangeRateProvider.RAPIRA_MARKUP
                                print(f"DEBUG: Rapira ask {top_ask} × {ExchangeRateProvider.RAPIRA_MARKUP} = {rate:.4f}", flush=True)
                                return rate
            except Exception as e:
                print(f"⚠️ Rapira стакан attempt {attempt+1} error: {e}")

        # 2. Фоллбэк: тикер (без глубины)
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.RAPIRA_API}/open/market/rates"
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        for row in (data.get('data') or []):
                            if row.get('symbol') in ('USDT/RUB', 'USDTRUB'):
                                ask = float(row.get('askPrice') or 0)
                                if ask > 0:
                                    print(f"DEBUG: Rapira тикер askPrice {ask}", flush=True)
                                    return ask * ExchangeRateProvider.RAPIRA_MARKUP
        except Exception as e:
            print(f"⚠️ Rapira тикер error: {e}")

        print("❌ Rapira недоступна — курс RUB/USDT не получен")
        return None

    @staticmethod
    async def get_all_rates() -> Dict[str, float]:
        """
        Получить все необходимые курсы

        Returns:
            dict: {"usdt_thb": float, "rub_usdt": float}
        """
        usdt_thb = await ExchangeRateProvider.get_binance_rate("USDTTHB")
        rub_usdt = await ExchangeRateProvider.get_rapira_rate()

        return {
            "usdt_thb": usdt_thb,
            "rub_usdt": rub_usdt
        }

    @staticmethod
    async def get_precise_binance_rate(usdt_amount: float = None, thb_amount: float = None, direction: str = 'usdt_to_thb') -> dict:
        """
        Получить ТОЧНЫЙ курс от Binance Easy Buy/Sell через Playwright
        Поддерживает 4 режима:
        - usdt_to_thb: страница USDT/THB, вводим USDT в From → читаем THB из Receive
        - thb_to_usdt: страница THB/USDT, вводим THB в From → читаем USDT из Receive
        - usdt_to_thb_reverse: страница USDT/THB, вводим THB в Receive → читаем USDT из From
        - thb_to_usdt_reverse: страница THB/USDT, вводим USDT в Receive → читаем THB из From

        Returns: dict с полями direction, usdt, thb, rate (всегда USDT→THB), time
        """
        import time
        start_time = time.time()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',  # использовать /tmp вместо /dev/shm (критично в Docker)
                    '--disable-gpu',
                    '--disable-extensions',
                ])
                page = await browser.new_page()

                # Блокируем тяжёлые ресурсы (кроме CSS/JS — нужны для React)
                async def block_heavy(route):
                    if route.request.resource_type in ('image', 'media', 'font'):
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route('**/*', block_heavy)

                async def wait_for_nth_value(nth, max_ms=8000):
                    """Ждёт пока поле nth заполнится числом, не дольше max_ms"""
                    loc = page.locator('input').nth(nth)
                    for _ in range(max_ms // 150):
                        try:
                            val = await loc.input_value()
                            if val and val not in ('0', '0.00', '0.0', '', '--'):
                                return val
                        except Exception:
                            pass
                        await page.wait_for_timeout(150)
                    return await loc.input_value()

                async def goto_and_wait(url):
                    """Переходим и ждём появления первого инпута"""
                    await page.goto(url, timeout=60000, wait_until='domcontentloaded')
                    try:
                        await page.click('button:has-text("Accept")', timeout=2000)
                    except:
                        pass
                    # Ждём первый инпут — признак что React отрисовался
                    await page.locator('input').nth(0).wait_for(timeout=30000)

                if direction == 'thb_to_usdt':
                    # THB → USDT: страница THB/USDT, nth(0)=THB From, nth(1)=USDT Receive
                    await goto_and_wait('https://www.binance.th/en/convert/THB/USDT')
                    await page.locator('input').nth(0).fill(str(thb_amount))
                    usdt_text = await wait_for_nth_value(1)
                    usdt_received = float(usdt_text.replace(',', ''))

                    rate_usdt_thb = thb_amount / usdt_received

                    await browser.close()
                    elapsed = time.time() - start_time

                    return {
                        'direction': 'thb_to_usdt',
                        'thb': thb_amount,
                        'usdt': usdt_received,
                        'rate': rate_usdt_thb,
                        'time': round(elapsed, 2)
                    }

                elif direction == 'thb_to_usdt_reverse':
                    # Обратный ввод: THB/USDT, вводим USDT в Receive nth(1), читаем THB из From nth(0)
                    await goto_and_wait('https://www.binance.th/en/convert/THB/USDT')
                    await page.locator('input').nth(1).fill(str(usdt_amount))
                    thb_text = await wait_for_nth_value(0)
                    thb_needed = float(thb_text.replace(',', ''))

                    rate_usdt_thb = thb_needed / usdt_amount

                    await browser.close()
                    elapsed = time.time() - start_time

                    return {
                        'direction': 'thb_to_usdt_reverse',
                        'thb': thb_needed,
                        'usdt': usdt_amount,
                        'rate': rate_usdt_thb,
                        'time': round(elapsed, 2)
                    }

                elif direction == 'usdt_to_thb_reverse':
                    # Обратный ввод: USDT/THB, вводим THB в Receive nth(1), читаем USDT из From nth(0)
                    await goto_and_wait('https://www.binance.th/en/convert/USDT/THB')
                    await page.locator('input').nth(1).fill(str(thb_amount))
                    usdt_text = await wait_for_nth_value(0)
                    usdt_needed = float(usdt_text.replace(',', ''))

                    rate_usdt_thb = thb_amount / usdt_needed

                    await browser.close()
                    elapsed = time.time() - start_time

                    return {
                        'direction': 'usdt_to_thb_reverse',
                        'thb': thb_amount,
                        'usdt': usdt_needed,
                        'rate': rate_usdt_thb,
                        'time': round(elapsed, 2)
                    }

                else:
                    # USDT → THB: страница USDT/THB, nth(0)=USDT From, nth(1)=THB Receive
                    await goto_and_wait('https://www.binance.th/en/convert/USDT/THB')
                    await page.locator('input').nth(0).fill(str(usdt_amount))
                    thb_text = await wait_for_nth_value(1)
                    thb_received = float(thb_text.replace(',', ''))

                    rate = thb_received / usdt_amount

                    await browser.close()
                    elapsed = time.time() - start_time

                    return {
                        'direction': 'usdt_to_thb',
                        'usdt': usdt_amount,
                        'thb': thb_received,
                        'rate': rate,
                        'time': round(elapsed, 2)
                    }

        except Exception as e:
            print(f"❌ Playwright parsing error: {e}")
            return {
                'error': str(e),
                'time': round(time.time() - start_time, 2)
            }


# Комиссия площадки за выдачу бат. Зависит от того, где откупаем:
# Binance 0.25%, Bitazza 0.15%. Фикс за вывод одинаковый.
WITHDRAWAL_PCT_BINANCE = 0.0025
WITHDRAWAL_PCT_BITAZZA = 0.0015
WITHDRAWAL_FIXED_THB = 20


class CommissionCalculator:
    """Расчет комиссий по уровням сумм"""
    
    # После перехода RUB-USDT на Рапиру+2% (17.08.2026) бонуса Доверки нет:
    # профит целиком собирается комиссией USDT-THB. Чтобы фактический профит
    # равнялся целевому p, комиссия c = p/(1+p) — вывод: profit% = c/(1−c).
    LEVELS = {
        'до_500к': {
            'min': 0,
            'max': 500_000,
            'usdt_thb_commission': 0.047619,  # профит 5%: 0.05/1.05
            'rub_usdt_commission': 0.0,       # 0%
            'withdrawal_percent': 0.0025,     # 0.25%
            'withdrawal_fixed': 20,           # 20 THB
            'profit_percent': 0.05,           # 5%
            'bonus_percent': 0.0              # бонуса Доверки больше нет
        },
        '500к_1млн': {
            'min': 500_000,
            'max': 1_000_000,
            'usdt_thb_commission': 0.038462,  # профит 4%: 0.04/1.04
            'rub_usdt_commission': 0.0,       # 0%
            'withdrawal_percent': 0.0025,     # 0.25%
            'withdrawal_fixed': 20,           # 20 THB
            'profit_percent': 0.04,           # 4%
            'bonus_percent': 0.0
        },
        'от_1млн': {
            'min': 1_000_000,
            'max': float('inf'),
            'usdt_thb_commission': 0.029126,  # профит 3%: 0.03/1.03
            'rub_usdt_commission': 0.0,       # 0%
            'withdrawal_percent': 0.0025,     # 0.25%
            'withdrawal_fixed': 20,           # 20 THB
            'profit_percent': 0.03,           # 3%
            'bonus_percent': 0.0
        }
    }
    
    @staticmethod
    def get_level(rub_amount: float) -> Tuple[str, dict]:
        """
        Определить уровень комиссий по сумме в рублях
        
        Args:
            rub_amount: Сумма в рублях
            
        Returns:
            tuple: (название_уровня, параметры_комиссий)
        """
        for level_name, params in CommissionCalculator.LEVELS.items():
            if params['min'] <= rub_amount < params['max']:
                return level_name, params
        
        # По умолчанию - последний уровень
        return 'от_1млн', CommissionCalculator.LEVELS['от_1млн']


class ExchangeCalculator:
    """Калькулятор обмена валют для режима СБП (бывш. Doverka)"""
    
    def __init__(self, usdt_thb_rate: float, rub_usdt_rate: float,
                 withdrawal_percent: float = WITHDRAWAL_PCT_BINANCE,
                 withdrawal_fixed: float = WITHDRAWAL_FIXED_THB):
        """
        Args:
            usdt_thb_rate: Курс USDT-THB биржи, на которой откупаем баты
            rub_usdt_rate: Курс RUB-USDT
            withdrawal_percent: комиссия площадки за выдачу, доля (Binance 0.25%, Bitazza 0.15%)
            withdrawal_fixed: фикс за вывод, ฿
        """
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = rub_usdt_rate
        self.withdrawal_percent = withdrawal_percent
        self.withdrawal_fixed = withdrawal_fixed
    
    def _get_commissions(self, target_profit: float, rub_amount: float = 0):
        """Комиссии режима СБП: профит целиком в комиссии USDT-THB.

        Без бонуса Доверки связь точная: фактический профит = c/(1−c),
        поэтому под целевой p комиссия c = p/(1+p). Старый эмпирический
        мэппинг (5% → 2.72% и т.д.) был откалиброван под бонус 2.4% —
        с базой Рапира+2% он занижал бы профит.
        """
        _, default_comm = CommissionCalculator.get_level(rub_amount)
        bonus = default_comm['bonus_percent']  # 0.0 — оставлен для совместимости формул

        if target_profit is not None:
            p = target_profit / 100.0
            usdt_comm = p / (1 + p)
            return 0.0, usdt_comm, bonus, f"Индивидуальный ({target_profit}%)"
        else:
            return 0.0, default_comm['usdt_thb_commission'], bonus, "Стандартный"

    def rub_to_thb(self, rub_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 2: RUB → THB (amount)"""
        rub_comm, usdt_comm, bonus, level_name = self._get_commissions(custom_profit_margin, rub_amount)
        
        # 1. RUB-USDT
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        usdt_amount = rub_amount / rub_usdt_rate_sell
        
        # 2. USDT-THB
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        
        # 3. Выдача
        withdrawal_percent_fee = excel_round(thb_to_exchange * self.withdrawal_percent, 2)
        withdrawal_fixed = self.withdrawal_fixed
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)

        final_rate = safe_rate(rub_amount, thb_to_receive, 6)
        
        # Прибыль
        bonus_usdt = excel_round(usdt_amount * bonus, 2)
        incoming_usdt = excel_round(usdt_amount + bonus_usdt, 2)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0
        
        return {
            'scenario': 'RUB → THB',
            'direction': 'amount',
            'rub_amount': rub_amount,
            'rub_paid': rub_amount,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'usdt_amount': excel_round(usdt_amount, 2),
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'thb_to_exchange': excel_round(thb_to_exchange, 2),
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            'final_rate': final_rate,
            'bonus_usdt': bonus_usdt,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent,
            'commission_level': level_name
        }

    def rub_to_thb_target(self, thb_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 1: RUB → THB (target)"""
        # Прикидываем сумму для уровня
        estimated_rub = thb_target * (self.rub_usdt_rate / self.usdt_thb_rate) * 1.05
        rub_comm, usdt_comm, bonus, level_name = self._get_commissions(custom_profit_margin, estimated_rub)
        
        # 1. Выдача
        thb_to_exchange = (thb_target + self.withdrawal_fixed) / (1 - self.withdrawal_percent)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - self.withdrawal_fixed, 2)
        
        # 2. USDT-THB
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        
        # 3. RUB-USDT
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        rub_amount = excel_round(usdt_amount * rub_usdt_rate_sell, 2)

        final_rate = safe_rate(rub_amount, thb_target, 6)
        
        # Прибыль
        bonus_usdt = excel_round(usdt_amount * bonus, 2)
        incoming_usdt = excel_round(usdt_amount + bonus_usdt, 2)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent = excel_round((profit_usdt / outgoing_usdt) * 100, 2)
        
        return {
            'scenario': 'RUB → THB',
            'direction': 'target',
            'thb_target': thb_target,
            'thb_received': thb_target,
            'withdrawal_fixed': 20,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': excel_round(thb_to_exchange, 2),
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'usdt_amount': excel_round(usdt_amount, 2),
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'rub_amount': rub_amount,
            'rub_to_pay': rub_amount,
            'final_rate': final_rate,
            'bonus_usdt': bonus_usdt,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent,
            'commission_level': level_name
        }

    def thb_to_usdt(self, thb_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 4: THB → USDT (amount)"""
        # Для THB-USDT нет бонуса 2.4% (он только для RUB)
        target_profit = custom_profit_margin if custom_profit_margin is not None else 3.0
        usdt_comm = target_profit / 100.0
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + usdt_comm)
        usdt_before_commission = thb_amount / usdt_thb_rate_sell
        usdt_received = excel_round(usdt_before_commission - 1, 2)

        final_rate = safe_rate(thb_amount, usdt_received, 6)
        
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)
        outgoing_usdt = usdt_received
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
        return {
            'scenario': 'THB → USDT',
            'direction': 'amount',
            'thb_amount': thb_amount,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_amount': excel_round(usdt_before_commission, 2),
            'withdrawal_fixed': 1,
            'thb_received': usdt_received, # Для совместимости с UI
            'usdt_received': usdt_received,
            'final_rate': final_rate,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': target_profit,
            'commission_level': f"СБП ({target_profit}%)"
        }

    def thb_to_usdt_target(self, usdt_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 3: THB → USDT (target)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 3.0
        usdt_comm = target_profit / 100.0
        
        usdt_before_commission = usdt_target + 1
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + usdt_comm)
        thb_amount = excel_round(usdt_before_commission * usdt_thb_rate_sell, 2)

        final_rate = safe_rate(thb_amount, usdt_target, 6)
        
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)
        outgoing_usdt = usdt_target
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
        return {
            'scenario': 'THB → USDT',
            'direction': 'target',
            'usdt_target': usdt_target,
            'withdrawal_fixed': 1,
            'usdt_amount': usdt_before_commission,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_amount': thb_amount,
            'thb_to_pay': thb_amount,
            'final_rate': final_rate,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': target_profit,
            'commission_level': f"СБП ({target_profit}%)"
        }

    def usdt_to_thb(self, usdt_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 6: USDT → THB (amount)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 4.0
        usdt_comm = target_profit / 100.0
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        
        withdrawal_percent_fee = excel_round(thb_to_exchange * self.withdrawal_percent, 2)
        withdrawal_fixed = self.withdrawal_fixed
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)

        final_rate = safe_rate(thb_to_receive, usdt_amount, 4)
        
        incoming_usdt = usdt_amount
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
        return {
            'scenario': 'USDT → THB',
            'direction': 'amount',
            'usdt_amount': usdt_amount,
            'usdt_paid': usdt_amount,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_to_exchange': excel_round(thb_to_exchange, 2),
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            'final_rate': final_rate,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': target_profit,
            'commission_level': f"СБП ({target_profit}%)"
        }

    def usdt_to_thb_target(self, thb_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 5: USDT → THB (target)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 4.0
        usdt_comm = target_profit / 100.0
        
        thb_to_exchange = (thb_target + self.withdrawal_fixed) / (1 - self.withdrawal_percent)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - self.withdrawal_fixed, 2)
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        usdt_amount = excel_round(thb_to_exchange / usdt_thb_rate_sell, 2)

        final_rate = safe_rate(thb_target, usdt_amount, 4)
        
        incoming_usdt = usdt_amount
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
        return {
            'scenario': 'USDT → THB',
            'direction': 'target',
            'thb_target': thb_target,
            'thb_received': thb_target,
            'withdrawal_fixed': 20,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': excel_round(thb_to_exchange, 2),
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_amount': usdt_amount,
            'usdt_to_pay': usdt_amount,
            'final_rate': final_rate,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': target_profit,
            'commission_level': f"СБП ({target_profit}%)"
        }

    def rub_to_usdt_target(self, usdt_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 7: RUB → USDT (target) — хочу получить N USDT, сколько рублей заплатить"""
        # Тиры по сумме: оцениваем примерную сумму RUB для определения тира
        estimated_rub = usdt_target * self.rub_usdt_rate * 1.05
        _, default_comm = CommissionCalculator.get_level(estimated_rub)
        target_profit = custom_profit_margin if custom_profit_margin is not None else default_comm['profit_percent'] * 100
        bonus = default_comm["bonus_percent"]  # 0.0 — бонуса Доверки больше нет

        # Комиссия с учётом бонуса: если target_profit=5% и bonus=2.4%, то rub_comm=2.6%
        rub_comm = (target_profit - bonus * 100) / 100.0

        withdrawal_commission = 1  # 1 USDT
        usdt_before_commission = usdt_target + withdrawal_commission

        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        rub_amount = excel_round(usdt_before_commission * rub_usdt_rate_sell, 2)

        final_rate = safe_rate(rub_amount, usdt_target, 6)

        # Прибыль: USDT по рыночному курсу + бонус - выплата клиенту
        usdt_at_market = rub_amount / self.rub_usdt_rate
        bonus_usdt = excel_round(usdt_at_market * bonus, 2)
        incoming_usdt = excel_round(usdt_at_market + bonus_usdt, 2)
        outgoing_usdt = excel_round(usdt_before_commission, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0

        level_name = f"Индивидуальный ({target_profit}%)" if custom_profit_margin is not None else "Стандартный"

        return {
            'scenario': 'RUB → USDT',
            'direction': 'target',
            'usdt_target': usdt_target,
            'withdrawal_fixed': withdrawal_commission,
            'usdt_amount': usdt_before_commission,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'rub_amount': rub_amount,
            'rub_to_pay': rub_amount,
            'final_rate': final_rate,
            'bonus_usdt': bonus_usdt,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent,
            'commission_level': f"СБП ({target_profit}%)",
            'level_name': level_name
        }

    def rub_to_usdt_amount(self, rub_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 8: RUB → USDT (amount) — вношу N рублей, сколько USDT получу"""
        # Тиры по сумме рублей
        _, default_comm = CommissionCalculator.get_level(rub_amount)
        target_profit = custom_profit_margin if custom_profit_margin is not None else default_comm['profit_percent'] * 100
        bonus = default_comm["bonus_percent"]  # 0.0 — бонуса Доверки больше нет

        # Комиссия с учётом бонуса
        rub_comm = (target_profit - bonus * 100) / 100.0

        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        usdt_before_commission = rub_amount / rub_usdt_rate_sell

        withdrawal_commission = 1  # 1 USDT
        usdt_received = excel_round(usdt_before_commission - withdrawal_commission, 2)

        final_rate = safe_rate(rub_amount, usdt_received, 6)

        # Прибыль: USDT по рыночному курсу + бонус - выплата клиенту
        usdt_at_market = rub_amount / self.rub_usdt_rate
        bonus_usdt = excel_round(usdt_at_market * bonus, 2)
        incoming_usdt = excel_round(usdt_at_market + bonus_usdt, 2)
        outgoing_usdt = excel_round(usdt_before_commission, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0

        level_name = f"Индивидуальный ({target_profit}%)" if custom_profit_margin is not None else "Стандартный"

        return {
            'scenario': 'RUB → USDT',
            'direction': 'amount',
            'rub_amount': rub_amount,
            'rub_paid': rub_amount,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'usdt_amount': excel_round(usdt_before_commission, 2),
            'withdrawal_fixed': withdrawal_commission,
            'usdt_received': usdt_received,
            'final_rate': final_rate,
            'bonus_usdt': bonus_usdt,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent,
            'commission_level': f"СБП ({target_profit}%)",
            'level_name': level_name
        }

