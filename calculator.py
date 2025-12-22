"""
Exchange Calculator Bot - Калькулятор обмена RUB-THB
Получает реальные курсы от Binance и Doverka API
"""

import aiohttp
import os
from typing import Dict, Tuple
from dotenv import load_dotenv
from decimal import Decimal, ROUND_HALF_UP

# Загружаем переменные окружения
load_dotenv()

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
    DOVERKA_API_KEY = os.getenv('DOVERKA_API_KEY', '')
    
    # Используем курс от Doverka API без маржи
    DOVERKA_MARGIN = 1.0  # Без маржи - чистый курс от API
    
    # Альтернативные источники для RUB-USDT, если Doverka API не работает
    FALLBACK_RUB_USDT = 84.2271  # Фоллбэк курс
    
    @staticmethod
    async def get_binance_rate(symbol: str = "USDTTHB") -> float:
        """
        Получить курс от Binance Thailand API
        
        Args:
            symbol: Торговая пара (по умолчанию USDT-THB)
            
        Returns:
            float: Текущий курс
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.BINANCE_API}/ticker/price"
                params = {"symbol": symbol}
                
                # Заголовки с API ключом (если есть)
                headers = {}
                if ExchangeRateProvider.BINANCE_API_KEY:
                    headers['X-MBX-APIKEY'] = ExchangeRateProvider.BINANCE_API_KEY
                
                async with session.get(url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Формат 1: {"code": 0, "data": {"symbol": "USDTTHB", "price": "31.16"}}
                        if isinstance(data, dict) and data.get("code") == 0 and "data" in data:
                            price = data["data"].get("price")
                            if price:
                                print(f"✅ Binance API: {symbol} = {price}")
                                return float(price)
                        
                        # Формат 2: {"symbol": "USDTTHB", "price": "31.16"}
                        elif isinstance(data, dict) and "price" in data:
                            price = data["price"]
                            print(f"✅ Binance API: {symbol} = {price}")
                            return float(price)
                        
                        # Формат 3: Прямое значение цены
                        elif isinstance(data, (int, float, str)):
                            print(f"✅ Binance API: {symbol} = {data}")
                            return float(data)
                    
                    print(f"⚠️ Binance API error: {response.status}")
                    response_text = await response.text()
                    print(f"⚠️ Response: {response_text[:200]}")
                    return 31.16  # Фоллбэк
                    
        except Exception as e:
            print(f"❌ Ошибка получения курса Binance: {e}")
            return 31.16  # Фоллбэк
    
    @staticmethod
    async def get_doverka_rate() -> float:
        """
        Получить курс RUB-USDT от Doverka API
        
        Returns:
            float: Текущий курс RUB за 1 USDT
        """
        if not ExchangeRateProvider.DOVERKA_API_KEY:
            print("⚠️ Doverka API key не найден, используем фоллбэк")
            return ExchangeRateProvider.FALLBACK_RUB_USDT
        
        try:
            async with aiohttp.ClientSession() as session:
                # Правильный эндпоинт для получения валют
                url = f"{ExchangeRateProvider.DOVERKA_API}/v1/currencies"
                
                headers = {
                    'Authorization': f'Bearer {ExchangeRateProvider.DOVERKA_API_KEY}',
                    'accept': 'application/json'
                }
                
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # Ответ может быть списком или одним объектом
                        currencies = data if isinstance(data, list) else [data]
                        
                        # Ищем USD/USDT
                        for currency in currencies:
                            if isinstance(currency, dict):
                                symbol = currency.get('symbol', '').upper()
                                currency_name = currency.get('currency_name', '').upper()
                                
                                # USD или USDT
                                if symbol in ['USD', 'USDT'] or currency_name in ['USD', 'USDT']:
                                    rate_to_rub = currency.get('rate_to_rub')
                                    if rate_to_rub:
                                        rate_base = float(rate_to_rub)
                                        # Применяем маржу для курса продажи
                                        rate = rate_base * ExchangeRateProvider.DOVERKA_MARGIN
                                        print(f"✅ Doverka API: RUB-{symbol} = {rate_base:.4f} (базовый)")
                                        print(f"   С маржой {ExchangeRateProvider.DOVERKA_MARGIN}: {rate:.4f} ₽")
                                        return rate
                        
                        # Если не нашли USD/USDT, берем первую валюту с курсом
                        for currency in currencies:
                            if isinstance(currency, dict):
                                rate_to_rub = currency.get('rate_to_rub')
                                if rate_to_rub:
                                    rate_base = float(rate_to_rub)
                                    # Применяем маржу
                                    rate = rate_base * ExchangeRateProvider.DOVERKA_MARGIN
                                    symbol = currency.get('symbol', 'USD')
                                    print(f"✅ Doverka API: RUB-{symbol} = {rate_base:.4f} (используем как USD)")
                                    print(f"   С маржой: {rate:.4f} ₽")
                                    return rate
                        
                        print(f"⚠️ Doverka API: курс не найден в ответе")
                        print(f"   Response: {data}")
                        return ExchangeRateProvider.FALLBACK_RUB_USDT
                        
                    elif response.status == 401:
                        print(f"⚠️ Doverka API: Неверный API ключ (401)")
                        return ExchangeRateProvider.FALLBACK_RUB_USDT
                    else:
                        print(f"⚠️ Doverka API: {response.status}")
                        response_text = await response.text()
                        print(f"   Response: {response_text[:200]}")
                        return ExchangeRateProvider.FALLBACK_RUB_USDT
                    
        except asyncio.TimeoutError:
            print(f"⚠️ Doverka API: timeout")
            return ExchangeRateProvider.FALLBACK_RUB_USDT
        except Exception as e:
            print(f"⚠️ Ошибка Doverka API: {e}")
            return ExchangeRateProvider.FALLBACK_RUB_USDT
    
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
    """Калькулятор обмена валют"""
    
    def __init__(self, usdt_thb_rate: float, rub_usdt_rate: float):
        """
        Args:
            usdt_thb_rate: Курс USDT-THB от Binance
            rub_usdt_rate: Курс RUB-USDT от Doverka
        """
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = rub_usdt_rate
    
    def rub_to_thb(self, rub_amount: float) -> dict:
        """
        Сценарий: Клиент вносит конкретную сумму RUB → получает THB
        Использует Excel-округление для точного совпадения с таблицами
        
        Args:
            rub_amount: Сумма в рублях
            
        Returns:
            dict: Детальный расчет
        """
        # Определяем уровень комиссий
        level_name, comm = CommissionCalculator.get_level(rub_amount)
        
        # 1. Конвертация RUB → USDT (НЕ округляем для точности)
        usdt_amount = rub_amount / self.rub_usdt_rate
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        # 2. Курс продажи USDT-THB (с комиссией брокера) - НЕ округляем
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - comm['usdt_thb_commission'])
        
        # 3. Сумма THB к обмену - округляем
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        # 4. Комиссии за выдачу - округляем
        withdrawal_percent_fee = excel_round(thb_to_exchange * comm['withdrawal_percent'], 2)
        withdrawal_fixed = comm['withdrawal_fixed']
        
        # 5. Итоговая сумма THB к выдаче - округляем финальное значение
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        # 6. Итоговый курс для клиента
        final_rate = excel_round(rub_amount / thb_to_receive, 4)
        
        # 7. Расчет прибыли
        bonus_usdt = usdt_amount * comm['bonus_percent']
        incoming = usdt_amount + bonus_usdt
        outgoing = thb_to_exchange / self.usdt_thb_rate
        profit_usdt = excel_round(incoming - outgoing, 2)
        
        return {
            'scenario': 'RUB → THB',
            'level': level_name,
            'rub_paid': rub_amount,
            'thb_received': thb_to_receive,
            'final_rate': final_rate,
            'usdt_amount': usdt_amount_display,
            'commission_percent': comm['usdt_thb_commission'] * 100,
            'withdrawal_fees': withdrawal_percent_fee + withdrawal_fixed,
            'profit_usdt': profit_usdt,
            'details': {
                'usdt_thb_rate': self.usdt_thb_rate,
                'rub_usdt_rate': self.rub_usdt_rate,
                'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
                'thb_before_fees': thb_to_exchange_display
            }
        }
    
    def thb_to_rub(self, thb_target: float) -> dict:
        """
        Сценарий: Клиент хочет получить конкретную сумму THB → вносит RUB
        Использует Excel-округление для точного совпадения с таблицами
        
        Args:
            thb_target: Целевая сумма в батах
            
        Returns:
            dict: Детальный расчет
        """
        # Для определения уровня нужно сначала прикинуть сумму RUB
        # Делаем предварительный расчет
        estimated_rub = thb_target * 2.8  # Примерный курс
        level_name, comm = CommissionCalculator.get_level(estimated_rub)
        
        # 1. Комиссии за выдачу - округляем
        withdrawal_fixed = comm['withdrawal_fixed']
        withdrawal_percent_fee = excel_round(thb_target * comm['withdrawal_percent'], 2)
        
        # 2. Сумма THB к обмену (с учетом комиссий)
        thb_to_exchange = thb_target + withdrawal_fixed + withdrawal_percent_fee
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        # 3. Курс продажи USDT-THB (с комиссией брокера) - НЕ округляем
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - comm['usdt_thb_commission'])
        
        # 4. Сумма USDT - НЕ округляем для точности
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        # 5. Сумма RUB, вносимая клиентом - округляем финальное значение
        rub_amount = excel_round(usdt_amount * self.rub_usdt_rate, 2)
        
        # 6. Итоговый курс для клиента
        final_rate = excel_round(rub_amount / thb_target, 4)
        
        # 7. Расчет прибыли
        bonus_usdt = usdt_amount * comm['bonus_percent']
        incoming = usdt_amount + bonus_usdt
        outgoing = thb_to_exchange / self.usdt_thb_rate
        profit_usdt = excel_round(incoming - outgoing, 2)
        
        return {
            'scenario': 'THB ← RUB',
            'level': level_name,
            'thb_target': thb_target,
            'rub_to_pay': rub_amount,
            'final_rate': final_rate,
            'usdt_amount': usdt_amount_display,
            'commission_percent': comm['usdt_thb_commission'] * 100,
            'withdrawal_fees': withdrawal_percent_fee + withdrawal_fixed,
            'profit_usdt': profit_usdt,
            'details': {
                'usdt_thb_rate': self.usdt_thb_rate,
                'rub_usdt_rate': self.rub_usdt_rate,
                'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
                'thb_with_fees': thb_to_exchange_display
            }
        }


class BrokerCalculator:
    """Калькулятор для операций через брокера с кастомными курсами"""
    
    # Уровни комиссий для брокера
    COMMISSION_LEVELS = {
        'high': {  # 5% прибыли
            'name': 'Высокий (5%)',
            'usdt_thb_commission': 0.0257,  # 2.57%
            'rub_usdt_commission': 0.0256,   # 2.56%
            'thb_usdt_commission': 0.0525,   # 5.25%
            'usdt_thb_direct': 0.05,         # 5.00%
            'profit_percent': 0.05
        },
        'medium': {  # 4% прибыли
            'name': 'Средний (4%)',
            'usdt_thb_commission': 0.0204,  # 2.04%
            'rub_usdt_commission': 0.0205,   # 2.05%
            'thb_usdt_commission': 0.0416,   # 4.16%
            'usdt_thb_direct': 0.04,         # 4.00%
            'profit_percent': 0.04
        },
        'low': {  # 3% прибыли
            'name': 'Низкий (3%)',
            'usdt_thb_commission': 0.015,   # 1.50%
            'rub_usdt_commission': 0.0155,   # 1.55%
            'thb_usdt_commission': 0.0308,   # 3.08%
            'usdt_thb_direct': 0.03,         # 3.00%
            'profit_percent': 0.03
        }
    }
    
    def __init__(self, usdt_thb_rate: float, custom_rub_usdt_rate: float, commission_level: str = 'medium'):
        """
        Args:
            usdt_thb_rate: Курс USDT-THB от Binance
            custom_rub_usdt_rate: Кастомный курс RUB-USDT (задает менеджер)
            commission_level: Уровень комиссий ('high', 'medium', 'low')
        """
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = custom_rub_usdt_rate
        self.commission = self.COMMISSION_LEVELS.get(commission_level, self.COMMISSION_LEVELS['medium'])
    
    def rub_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 1: RUB → THB (клиент хочет получить конкретную сумму THB)
        """
        # Комиссии за выдачу
        withdrawal_fixed = 20  # THB
        withdrawal_percent_fee = thb_target * 0.0025
        
        # Сумма THB к обмену
        thb_to_exchange = thb_target + withdrawal_fixed + withdrawal_percent_fee
        
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.commission['usdt_thb_commission'])
        
        # Сумма USDT
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        
        # Курс продажи RUB-USDT (с комиссией)
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.commission['rub_usdt_commission'])
        
        # Сумма RUB
        rub_amount = usdt_amount * rub_usdt_rate_sell
        
        # Итоговый курс
        final_rate = rub_amount / thb_target
        
        return {
            'scenario': 'RUB → THB (целевая сумма)',
            'thb_target': thb_target,
            'rub_to_pay': round(rub_amount, 2),
            'final_rate': round(final_rate, 4),
            'usdt_amount': round(usdt_amount, 2),
            'commission_level': self.commission['name'],
            'withdrawal_fees': round(withdrawal_fixed + withdrawal_percent_fee, 2)
        }
    
    def rub_to_thb_amount(self, rub_amount: float) -> dict:
        """
        Операция 2: RUB → THB (клиент вносит конкретную сумму RUB)
        """
        # Курс продажи RUB-USDT (с комиссией)
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.commission['rub_usdt_commission'])
        
        # Сумма USDT
        usdt_amount = rub_amount / rub_usdt_rate_sell
        
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.commission['usdt_thb_commission'])
        
        # Сумма THB к обмену
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        
        # Комиссии за выдачу
        withdrawal_percent_fee = thb_to_exchange * 0.0025
        withdrawal_fixed = 20
        
        # Итоговая сумма THB
        thb_to_receive = thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed
        
        # Итоговый курс
        final_rate = rub_amount / thb_to_receive
        
        return {
            'scenario': 'RUB → THB (сумма RUB)',
            'rub_paid': rub_amount,
            'thb_received': round(thb_to_receive, 2),
            'final_rate': round(final_rate, 4),
            'usdt_amount': round(usdt_amount, 2),
            'commission_level': self.commission['name'],
            'withdrawal_fees': round(withdrawal_percent_fee + withdrawal_fixed, 2)
        }
    
    def thb_to_usdt_target(self, usdt_target: float) -> dict:
        """
        Операция 3: THB → USDT (клиент хочет получить конкретную сумму USDT)
        """
        # Комиссия за вывод
        withdrawal_commission = 1  # 1 USDT фикс
        
        # Сумма USDT до комиссии
        usdt_before_commission = usdt_target + withdrawal_commission
        
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + self.commission['thb_usdt_commission'])
        
        # Сумма THB
        thb_amount = usdt_before_commission * usdt_thb_rate_sell
        
        # Итоговый курс
        final_rate = thb_amount / usdt_target
        
        return {
            'scenario': 'THB → USDT (целевая сумма)',
            'usdt_target': usdt_target,
            'thb_to_pay': round(thb_amount, 2),
            'final_rate': round(final_rate, 4),
            'commission_level': self.commission['name'],
            'withdrawal_commission': withdrawal_commission
        }
    
    def thb_to_usdt_amount(self, thb_amount: float) -> dict:
        """
        Операция 4: THB → USDT (клиент вносит конкретную сумму THB)
        """
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + self.commission['thb_usdt_commission'])
        
        # Сумма USDT до комиссии
        usdt_before_commission = thb_amount / usdt_thb_rate_sell
        
        # Комиссия за вывод
        withdrawal_commission = 1  # 1 USDT
        
        # Итоговая сумма USDT
        usdt_to_receive = usdt_before_commission - withdrawal_commission
        
        # Итоговый курс
        final_rate = thb_amount / usdt_to_receive
        
        return {
            'scenario': 'THB → USDT (сумма THB)',
            'thb_paid': thb_amount,
            'usdt_received': round(usdt_to_receive, 2),
            'final_rate': round(final_rate, 4),
            'commission_level': self.commission['name'],
            'withdrawal_commission': withdrawal_commission
        }
    
    def usdt_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 5: USDT → THB (клиент хочет получить конкретную сумму THB)
        """
        # Комиссии за выдачу
        withdrawal_fixed = 20  # THB
        withdrawal_percent_fee = thb_target * 0.0025
        
        # Сумма THB к обмену
        thb_to_exchange = thb_target + withdrawal_fixed + withdrawal_percent_fee
        
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.commission['usdt_thb_direct'])
        
        # Сумма USDT
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        
        # Итоговый курс
        final_rate = usdt_amount / thb_target
        
        return {
            'scenario': 'USDT → THB (целевая сумма)',
            'thb_target': thb_target,
            'usdt_to_pay': round(usdt_amount, 2),
            'final_rate': round(final_rate, 6),
            'commission_level': self.commission['name'],
            'withdrawal_fees': round(withdrawal_fixed + withdrawal_percent_fee, 2)
        }
    
    def usdt_to_thb_amount(self, usdt_amount: float) -> dict:
        """
        Операция 6: USDT → THB (клиент вносит конкретную сумму USDT)
        """
        # Курс продажи USDT-THB (с комиссией)
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.commission['usdt_thb_direct'])
        
        # Сумма THB к обмену
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        
        # Комиссии за выдачу
        withdrawal_percent_fee = thb_to_exchange * 0.0025
        withdrawal_fixed = 20
        
        # Итоговая сумма THB
        thb_to_receive = thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed
        
        # Итоговый курс
        final_rate = usdt_amount / thb_to_receive
        
        return {
            'scenario': 'USDT → THB (сумма USDT)',
            'usdt_paid': usdt_amount,
            'thb_received': round(thb_to_receive, 2),
            'final_rate': round(final_rate, 6),
            'commission_level': self.commission['name'],
            'withdrawal_fees': round(withdrawal_percent_fee + withdrawal_fixed, 2)
        }


# Пример использования
async def test_calculator():
    """Тестовая функция"""
    print("🔄 Получаю актуальные курсы...")
    
    rates = await ExchangeRateProvider.get_all_rates()
    print(f"✅ Курс USDT-THB: {rates['usdt_thb']}")
    print(f"✅ Курс RUB-USDT: {rates['rub_usdt']}\n")
    
    calculator = ExchangeCalculator(
        usdt_thb_rate=rates['usdt_thb'],
        rub_usdt_rate=rates['rub_usdt']
    )
    
    # Тест 1: 100,000 рублей → THB
    print("=" * 60)
    print("ТЕСТ 1: Клиент вносит 100,000 рублей")
    print("=" * 60)
    result1 = calculator.rub_to_thb(100_000)
    print(f"Сценарий: {result1['scenario']}")
    print(f"Уровень комиссий: {result1['level']}")
    print(f"Клиент вносит: {result1['rub_paid']:,.2f} ₽")
    print(f"Клиент получает: {result1['thb_received']:,.2f} ฿")
    print(f"Курс для клиента: {result1['final_rate']:.4f} ₽/฿")
    print(f"Комиссия брокера USDT-THB: {result1['commission_percent']}%")
    print(f"Комиссия за выдачу: {result1['withdrawal_fees']:.2f} ฿")
    print(f"Прибыль (USDT): {result1['profit_usdt']:.2f}\n")
    
    # Тест 2: Хочет получить 150,000 батов
    print("=" * 60)
    print("ТЕСТ 2: Клиент хочет получить 150,000 батов")
    print("=" * 60)
    result2 = calculator.thb_to_rub(150_000)
    print(f"Сценарий: {result2['scenario']}")
    print(f"Уровень комиссий: {result2['level']}")
    print(f"Клиент хочет: {result2['thb_target']:,.2f} ฿")
    print(f"Клиент должен внести: {result2['rub_to_pay']:,.2f} ₽")
    print(f"Курс для клиента: {result2['final_rate']:.4f} ₽/฿")
    print(f"Комиссия брокера USDT-THB: {result2['commission_percent']}%")
    print(f"Комиссия за выдачу: {result2['withdrawal_fees']:.2f} ฿")
    print(f"Прибыль (USDT): {result2['profit_usdt']:.2f}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_calculator())

