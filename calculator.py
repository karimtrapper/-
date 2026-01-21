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
        Получить курс от Binance (сначала Global, потом TH как фоллбэк)
        """
        # 1. Пробуем Binance Global (обычно точнее для USDTTHB)
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.binance.com/api/v3/ticker/price"
                params = {"symbol": "USDTTHB"}
                async with session.get(url, params=params, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        rate = float(data['price'])
                        print(f"DEBUG: Binance Global rate: {rate}", flush=True)
                        return rate
        except Exception as e:
            print(f"❌ Binance Global error: {e}", flush=True)

        # 2. Фоллбэк на Binance Thailand
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{ExchangeRateProvider.BINANCE_API}/ticker/price"
                params = {"symbol": symbol}
                async with session.get(url, params=params, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, dict) and "price" in data:
                            return float(data["price"])
        except Exception as e:
            print(f"⚠️ Binance TH error: {e}", flush=True)
            
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
                
                async with session.get(url, headers=headers, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        currencies = data if isinstance(data, list) else [data]
                        print(f"DEBUG: Doverka currencies raw: {currencies}", flush=True)
                        for currency in currencies:
                            symbol = currency.get('symbol', '').upper()
                            # Пытаемся найти наиболее подходящий курс для продажи USDT за RUB
                            # Часто это rate_from_rub или просто поле с самым большим значением
                            rate_to_rub = currency.get('rate_to_rub')
                            rate_from_rub = currency.get('rate_from_rub')
                            
                            if symbol in ['USD', 'USDT']:
                                print(f"DEBUG: Found {symbol}. to_rub: {rate_to_rub}, from_rub: {rate_from_rub}", flush=True)
                                # Если есть rate_from_rub и он больше 85, скорее всего это то, что нам нужно
                                if rate_from_rub and float(rate_from_rub) > 80:
                                    return float(rate_from_rub)
                                if rate_to_rub:
                                    return float(rate_to_rub)
                        return None
                    else:
                        print(f"⚠️ Doverka API error status: {response.status}")
                        return None
        except Exception as e:
            print(f"⚠️ Ошибка Doverka API: {e}")
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
        """Операция 7: RUB → USDT (target)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 3.0
        rub_comm = target_profit / 100.0
        bonus = 0.024
        
        withdrawal_commission = 1
        usdt_before_commission = usdt_target + withdrawal_commission
        
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        rub_amount = excel_round(usdt_before_commission * rub_usdt_rate_sell, 2)
        
        final_rate = excel_round(rub_amount / usdt_target, 6)
        
        bonus_usdt = excel_round(usdt_before_commission * bonus, 2)
        incoming_usdt = excel_round(usdt_before_commission + bonus_usdt, 2)
        outgoing_usdt = usdt_before_commission
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
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
            'profit_percent_actual': target_profit,
            'commission_level': f"Doverka ({target_profit}%)"
        }

    def rub_to_usdt_amount(self, rub_amount: float, custom_profit_margin: float = None) -> dict:
        """Операция 8: RUB → USDT (amount)"""
        target_profit = custom_profit_margin if custom_profit_margin is not None else 3.0
        rub_comm = target_profit / 100.0
        bonus = 0.024
        
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_comm)
        usdt_before_commission = rub_amount / rub_usdt_rate_sell
        
        withdrawal_commission = 1
        usdt_received = excel_round(usdt_before_commission - withdrawal_commission, 2)
        
        final_rate = excel_round(rub_amount / usdt_received, 6)
        
        bonus_usdt = excel_round(usdt_before_commission * bonus, 2)
        incoming_usdt = excel_round(usdt_before_commission + bonus_usdt, 2)
        outgoing_usdt = usdt_before_commission
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        
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
            'profit_percent_actual': target_profit,
            'commission_level': f"Doverka ({target_profit}%)"
        }

    # Псевдонимы для обратной совместимости
    def thb_to_rub(self, thb_target: float, custom_profit_margin: float = None) -> dict:
        return self.rub_to_thb_target(thb_target, custom_profit_margin)


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

