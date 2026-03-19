"""
Exchange Calculator Bot - Калькулятор обмена RUB-THB
Получает реальные курсы от Binance и Doverka API
"""

import aiohttp
import os
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
    DOVERKA_API = "https://api.doverkapay.com"
    
    # API ключи из переменных окружения
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    DOVERKA_API_KEY = os.getenv('DOVERKA_API_KEY', '')
    
    # Используем курс от Doverka API без маржи
    DOVERKA_MARGIN = 1.0  # Без маржи - чистый курс от API
    
    # Альтернативные источники для RUB-USDT, если Doverka API не работает
    FALLBACK_RUB_USDT = 92.50  # Фоллбэк курс (обновлен 20.01.2026)
    
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
    async def get_doverka_rate() -> float:
        """
        Получить курс RUB-USDT от Doverka API
        """
        if not ExchangeRateProvider.DOVERKA_API_KEY:
            print("⚠️ Doverka API key не найден")
            return None
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.DOVERKA_API}/v1/currencies"
                headers = {
                    'Authorization': f'Bearer {ExchangeRateProvider.DOVERKA_API_KEY}',
                    'accept': 'application/json'
                }
                
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        currencies = data if isinstance(data, list) else [data]
                        for currency in currencies:
                            symbol = currency.get('symbol', '').upper()
                            rate_to_rub = currency.get('rate_to_rub')
                            rate_from_rub = currency.get('rate_from_rub')
                            if symbol in ['USD', 'USDT']:
                                print(f"DEBUG: Doverka {symbol}: to_rub={rate_to_rub}, from_rub={rate_from_rub}", flush=True)
                                if rate_from_rub and float(rate_from_rub) > 80:
                                    return float(rate_from_rub)
                                if rate_to_rub:
                                    return float(rate_to_rub)
                        return None
                    else:
                        print(f"⚠️ Doverka API error status: {response.status}")
                        return None
        except Exception as e:
            print(f"⚠️ Doverka attempt 1 error: {e}")

        # Retry
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.DOVERKA_API}/v1/currencies"
                headers = {
                    'Authorization': f'Bearer {ExchangeRateProvider.DOVERKA_API_KEY}',
                    'accept': 'application/json'
                }
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        currencies = data if isinstance(data, list) else [data]
                        for currency in currencies:
                            symbol = currency.get('symbol', '').upper()
                            rate_to_rub = currency.get('rate_to_rub')
                            rate_from_rub = currency.get('rate_from_rub')
                            if symbol in ['USD', 'USDT']:
                                if rate_from_rub and float(rate_from_rub) > 80:
                                    return float(rate_from_rub)
                                if rate_to_rub:
                                    return float(rate_to_rub)
                        return None
        except Exception as e:
            print(f"⚠️ Doverka attempt 2 error: {e}")

        print(f"❌ Doverka недоступна — курс RUB/USDT не получен")
        return None
    
    @staticmethod
    async def get_all_rates() -> Dict[str, float]:
        """
        Получить все необходимые курсы
        
        Returns:
            dict: {"usdt_thb": float, "rub_usdt": float}
        """
        usdt_thb = await ExchangeRateProvider.get_binance_rate("USDTTHB")
        rub_usdt = await ExchangeRateProvider.get_doverka_rate()
        
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
                    '--single-process',          # без дочернего renderer-процесса, ~100MB меньше
                    '--no-zygote',
                    '--disable-extensions',
                ])
                page = await browser.new_page()

                if direction == 'thb_to_usdt':
                    # THB → USDT: страница THB/USDT, вводим THB в From
                    await page.goto('https://www.binance.th/en/convert/THB/USDT', timeout=30000)
                    try:
                        await page.click('button:has-text("Accept")', timeout=2000)
                    except:
                        pass

                    await page.fill('input[placeholder*="3248999"]', str(thb_amount))
                    await page.wait_for_timeout(2000)

                    usdt_text = await page.input_value('input[placeholder*="99999"]')
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
                    # Обратный ввод: страница THB/USDT, вводим USDT в поле Receive → читаем THB из From
                    # Используется когда клиент хочет получить N USDT и нужно узнать сколько THB платить
                    await page.goto('https://www.binance.th/en/convert/THB/USDT', timeout=30000)
                    try:
                        await page.click('button:has-text("Accept")', timeout=2000)
                    except:
                        pass

                    # Вводим USDT в поле Receive (второе поле)
                    await page.fill('input[placeholder*="99999"]', str(usdt_amount))
                    await page.wait_for_timeout(2000)

                    # Читаем THB из поля From (первое поле)
                    thb_text = await page.input_value('input[placeholder*="3248999"]')
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
                    # Обратный ввод: страница USDT/THB, вводим THB в поле Receive → читаем USDT из From
                    # Используется когда клиент хочет получить N бат и нужно узнать сколько USDT платить
                    await page.goto('https://www.binance.th/en/convert/USDT/THB', timeout=30000)
                    try:
                        await page.click('button:has-text("Accept")', timeout=2000)
                    except:
                        pass

                    # Вводим THB в поле Receive (второе поле)
                    await page.fill('input[placeholder*="3248999"]', str(thb_amount))
                    await page.wait_for_timeout(2000)

                    # Читаем USDT из поля From (первое поле)
                    usdt_text = await page.input_value('input[placeholder*="99999"]')
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
                    # USDT → THB: страница USDT/THB, вводим USDT в From
                    await page.goto('https://www.binance.th/en/convert/USDT/THB', timeout=30000)
                    try:
                        await page.click('button:has-text("Accept")', timeout=2000)
                    except:
                        pass

                    await page.fill('input[placeholder*="99999"]', str(usdt_amount))
                    await page.wait_for_timeout(2000)

                    thb_text = await page.input_value('input[placeholder*="3248999"]')
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


class CommissionCalculator:
    """Расчет комиссий по уровням сумм"""
    
    LEVELS = {
        'до_500к': {
            'min': 0,
            'max': 500_000,
            'usdt_thb_commission': 0.0272,  # 2.72%
            'rub_usdt_commission': 0.0,     # 0%
            'withdrawal_percent': 0.0025,    # 0.25%
            'withdrawal_fixed': 20,          # 20 THB
            'profit_percent': 0.05,          # 5%
            'bonus_percent': 0.024           # 2.4%
        },
        '500к_1млн': {
            'min': 500_000,
            'max': 1_000_000,
            'usdt_thb_commission': 0.017,   # 1.70%
            'rub_usdt_commission': 0.0,     # 0%
            'withdrawal_percent': 0.0025,   # 0.25%
            'withdrawal_fixed': 20,         # 20 THB
            'profit_percent': 0.04,         # 4%
            'bonus_percent': 0.024          # 2.4%
        },
        'от_1млн': {
            'min': 1_000_000,
            'max': float('inf'),
            'usdt_thb_commission': 0.0067,  # 0.67%
            'rub_usdt_commission': 0.0,     # 0%
            'withdrawal_percent': 0.0025,   # 0.25%
            'withdrawal_fixed': 20,         # 20 THB
            'profit_percent': 0.03,         # 3%
            'bonus_percent': 0.024          # 2.4%
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
    """Калькулятор обмена валют для режима Doverka (SBP)"""
    
    def __init__(self, usdt_thb_rate: float, rub_usdt_rate: float):
        """
        Args:
            usdt_thb_rate: Курс USDT-THB от Binance
            rub_usdt_rate: Курс RUB-USDT от Doverka
        """
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = rub_usdt_rate
    
    def _get_commissions(self, target_profit: float, rub_amount: float = 0):
        """Расчет комиссий для Doverka с фиксированными значениями"""
        _, default_comm = CommissionCalculator.get_level(rub_amount)
        bonus = default_comm['bonus_percent'] # 0.024
        
        if target_profit is not None:
            # Точный маппинг от пользователя: Прибыль -> Комиссия USDT-THB
            mapping = {
                5.0: 0.0272,
                4.5: 0.0225,
                4.0: 0.0170,
                3.5: 0.0120,
                3.0: 0.0067,
                2.4: 0.0,
                2.0: -0.003,
                1.5: -0.007
            }
            
            if target_profit in mapping:
                usdt_comm = mapping[target_profit]
            else:
                # Линейная интерполяция для промежуточных значений
                pts = sorted(mapping.items())
                for i in range(len(pts) - 1):
                    x1, y1 = pts[i]
                    x2, y2 = pts[i+1]
                    if x1 <= target_profit <= x2:
                        usdt_comm = y1 + (y2 - y1) * (target_profit - x1) / (x2 - x1)
                        break
                else:
                    usdt_comm = 0.0272 if target_profit > 5 else -0.007
                    
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
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        final_rate = excel_round(rub_amount / thb_to_receive, 6)
        
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
        thb_to_exchange = (thb_target + 20) / (1 - 0.0025)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - 20, 2)
        
        # 2. USDT-THB
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        
        # 3. RUB-USDT
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        rub_amount = excel_round(usdt_amount * rub_usdt_rate_sell, 2)
        
        final_rate = excel_round(rub_amount / thb_target, 6)
        
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
        
        final_rate = excel_round(thb_amount / usdt_received, 6)
        
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
            'commission_level': f"Doverka ({target_profit}%)"
        }

    def thb_to_usdt_target(self, usdt_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 3: THB → USDT (target)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 3.0
        usdt_comm = target_profit / 100.0
        
        usdt_before_commission = usdt_target + 1
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + usdt_comm)
        thb_amount = excel_round(usdt_before_commission * usdt_thb_rate_sell, 2)
        
        final_rate = excel_round(thb_amount / usdt_target, 6)
        
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
            'commission_level': f"Doverka ({target_profit}%)"
        }

    def usdt_to_thb(self, usdt_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 6: USDT → THB (amount)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 4.0
        usdt_comm = target_profit / 100.0
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        final_rate = excel_round(thb_to_receive / usdt_amount, 4)
        
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
            'commission_level': f"Doverka ({target_profit}%)"
        }

    def usdt_to_thb_target(self, thb_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 5: USDT → THB (target)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 4.0
        usdt_comm = target_profit / 100.0
        
        thb_to_exchange = (thb_target + 20) / (1 - 0.0025)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - 20, 2)
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_comm)
        usdt_amount = excel_round(thb_to_exchange / usdt_thb_rate_sell, 2)
        
        final_rate = excel_round(thb_target / usdt_amount, 4)
        
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
            'commission_level': f"Doverka ({target_profit}%)"
        }

    def rub_to_usdt_target(self, usdt_target: float, custom_profit_margin: float = None) -> dict:
        """Операция 7: RUB → USDT (target) — хочу получить N USDT, сколько рублей заплатить"""
        # Тиры по сумме: оцениваем примерную сумму RUB для определения тира
        estimated_rub = usdt_target * self.rub_usdt_rate * 1.05
        _, default_comm = CommissionCalculator.get_level(estimated_rub)
        target_profit = custom_profit_margin if custom_profit_margin is not None else default_comm['profit_percent'] * 100
        bonus = default_comm['bonus_percent']  # 0.024

        # Комиссия с учётом бонуса: если target_profit=5% и bonus=2.4%, то rub_comm=2.6%
        rub_comm = (target_profit - bonus * 100) / 100.0

        withdrawal_commission = 1  # 1 USDT
        usdt_before_commission = usdt_target + withdrawal_commission

        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        rub_amount = excel_round(usdt_before_commission * rub_usdt_rate_sell, 2)

        final_rate = excel_round(rub_amount / usdt_target, 6)

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
            'commission_level': f"Doverka ({target_profit}%)",
            'level_name': level_name
        }

    def rub_to_usdt_amount(self, rub_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 8: RUB → USDT (amount) — вношу N рублей, сколько USDT получу"""
        # Тиры по сумме рублей
        _, default_comm = CommissionCalculator.get_level(rub_amount)
        target_profit = custom_profit_margin if custom_profit_margin is not None else default_comm['profit_percent'] * 100
        bonus = default_comm['bonus_percent']  # 0.024

        # Комиссия с учётом бонуса
        rub_comm = (target_profit - bonus * 100) / 100.0

        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        usdt_before_commission = rub_amount / rub_usdt_rate_sell

        withdrawal_commission = 1  # 1 USDT
        usdt_received = excel_round(usdt_before_commission - withdrawal_commission, 2)

        final_rate = excel_round(rub_amount / usdt_received, 6)

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
            'commission_level': f"Doverka ({target_profit}%)",
            'level_name': level_name
        }

