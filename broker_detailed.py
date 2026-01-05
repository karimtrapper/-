"""
Детальный калькулятор для брокера с полной информацией как в CSV
"""
from decimal import Decimal, ROUND_HALF_UP

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

class BrokerCalculatorDetailed:
    """Калькулятор брокера с детальными результатами и динамической прибылью"""
    
    def __init__(self, usdt_thb_rate: float, custom_rub_usdt_rate: float, target_profit: float = 4.0):
        """
        Args:
            usdt_thb_rate: Базовый курс USDT-THB (Binance)
            custom_rub_usdt_rate: Базовый курс RUB-USDT (Кастомный)
            target_profit: Желаемая чистая прибыль в % (например, 1.5, 2.0, 3.0, 5.0)
        """
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = custom_rub_usdt_rate
        self.target_profit = target_profit
        
        # Расчет комиссий для этапов на основе целевой прибыли (как в CSV)
        # Мы используем точные значения из CSV для основных шагов, 
        # а для остальных рассчитываем пропорционально.
        
        if abs(target_profit - 5.0) < 0.1:
            self.rub_comm = 0.0256
            self.usdt_comm = 0.0257
            self.thb_usdt_comm = 0.0525
            self.usdt_thb_direct = 0.0500
        elif abs(target_profit - 4.0) < 0.1:
            self.rub_comm = 0.0205
            self.usdt_comm = 0.0204
            self.thb_usdt_comm = 0.0416
            self.usdt_thb_direct = 0.0400
        elif abs(target_profit - 3.0) < 0.1:
            self.rub_comm = 0.0155
            self.usdt_comm = 0.0150
            self.thb_usdt_comm = 0.0308
            self.usdt_thb_direct = 0.0300
        elif abs(target_profit - 1.5) < 0.1:
            self.rub_comm = 0.0075
            self.usdt_comm = 0.0076
            self.thb_usdt_comm = 0.0151
            self.usdt_thb_direct = 0.0150
        else:
            # Общая формула для промежуточных значений (например, 2.5%, 3.5%)
            # Распределяем прибыль примерно пополам между двумя этапами
            self.rub_comm = (target_profit / 100.0) / 2.0
            self.usdt_comm = self.rub_comm
            self.thb_usdt_comm = (target_profit / 100.0) * 1.025
            self.usdt_thb_direct = target_profit / 100.0
            
        self.commission_name = f"Брокер ({target_profit}%)"

    def rub_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 1: RUB → THB (клиент хочет получить конкретную сумму THB)
        Соответствует операциям 1.1-1.3 в CSV
        """
        # Комиссии за выдачу
        withdrawal_fixed = 20
        thb_to_exchange = (thb_target + withdrawal_fixed) / (1 - 0.0025)
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - withdrawal_fixed, 2)
        
        # Курс продажи USDT-THB
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.usdt_comm)
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        # Курс продажи RUB-USDT
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.rub_comm)
        rub_amount = excel_round(usdt_amount * rub_usdt_rate_sell, 2)
        
        final_rate = excel_round(rub_amount / thb_target, 4)
        
        # Прибыльность
        incoming_usdt = excel_round(usdt_amount * (1 + self.rub_comm), 2)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0
        
        return {
            'operation': '1',
            'operation_name': 'Обменять сумму в рублях на конкретную сумму THB',
            'direction': 'target',
            'scenario': 'RUB → THB',
            'thb_target': thb_target,
            'withdrawal_fixed': withdrawal_fixed,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': thb_to_exchange_display,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(self.usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'usdt_amount': usdt_amount_display,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(self.rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 2),
            'rub_amount': rub_amount,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    
    def rub_to_thb_amount(self, rub_amount: float) -> dict:
        """
        Операция 2: RUB → THB (клиент вносит конкретную сумму RUB)
        Соответствует операциям 2.1-2.3 в CSV
        """
        # Для amount комиссии переставлены местами в CSV!
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.usdt_comm)
        usdt_amount = rub_amount / rub_usdt_rate_sell
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.rub_comm)
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        final_rate = excel_round(rub_amount / thb_to_receive, 4)
        
        incoming_usdt = excel_round(usdt_amount * (1 + self.usdt_comm), 2)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0
        
        return {
            'operation': '2',
            'operation_name': 'Обменять конкретную сумму в рублях на THB',
            'direction': 'amount',
            'scenario': 'RUB → THB',
            'rub_amount': rub_amount,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(self.usdt_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 2),
            'usdt_amount': usdt_amount_display,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(self.rub_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'thb_to_exchange': thb_to_exchange_display,
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def thb_to_usdt_target(self, usdt_target: float) -> dict:
        """
        Операция 3: THB → USDT (клиент хочет получить конкретную сумму USDT)
        """
        withdrawal_commission = 1
        usdt_before_commission = usdt_target + withdrawal_commission
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + self.thb_usdt_comm)
        thb_amount = excel_round(usdt_before_commission * usdt_thb_rate_sell, 2)
        
        final_rate = excel_round(thb_amount / usdt_target, 4)
        
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)
        outgoing_usdt = usdt_target
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '3',
            'operation_name': 'Обменять сумму в THB на конкретную сумму в USDT',
            'direction': 'target',
            'scenario': 'THB → USDT',
            'usdt_target': usdt_target,
            'withdrawal_commission': withdrawal_commission,
            'usdt_before_commission': usdt_before_commission,
            'usdt_thb_rate': self.usdt_thb_rate,
            'thb_usdt_commission': excel_round(self.thb_usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_amount': thb_amount,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def thb_to_usdt_amount(self, thb_amount: float) -> dict:
        """
        Операция 4: THB → USDT (клиент вносит конкретную сумму THB)
        """
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + self.thb_usdt_comm)
        usdt_before_commission = thb_amount / usdt_thb_rate_sell
        usdt_before_commission_display = excel_round(usdt_before_commission, 2)
        
        withdrawal_commission = 1
        usdt_to_receive = excel_round(usdt_before_commission - withdrawal_commission, 2)
        
        final_rate = excel_round(thb_amount / usdt_to_receive, 4)
        
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)
        outgoing_usdt = usdt_to_receive
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '4',
            'operation_name': 'Обменять конкретную сумму в THB на USDT',
            'direction': 'amount',
            'scenario': 'THB → USDT',
            'thb_amount': thb_amount,
            'usdt_thb_rate': self.usdt_thb_rate,
            'thb_usdt_commission': excel_round(self.thb_usdt_comm * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_before_commission': usdt_before_commission_display,
            'withdrawal_commission': withdrawal_commission,
            'usdt_received': usdt_to_receive,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def usdt_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 5: USDT → THB (клиент хочет получить конкретную сумму THB)
        """
        withdrawal_fixed = 20
        thb_to_exchange = (thb_target + withdrawal_fixed) / (1 - 0.0025)
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - withdrawal_fixed, 2)
        
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.usdt_thb_direct)
        usdt_amount = excel_round(thb_to_exchange / usdt_thb_rate_sell, 2)
        
        final_rate = excel_round(usdt_amount / thb_target, 6)
        
        incoming_usdt = usdt_amount
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '5',
            'operation_name': 'Обменять сумму в USDT на конкретную сумму THB',
            'direction': 'target',
            'scenario': 'USDT → THB',
            'thb_target': thb_target,
            'withdrawal_fixed': withdrawal_fixed,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': thb_to_exchange_display,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(self.usdt_thb_direct * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_amount': usdt_amount,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def usdt_to_thb_amount(self, usdt_amount: float) -> dict:
        """
        Операция 6: USDT → THB (клиент вносит конкретную сумму USDT)
        """
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - self.usdt_thb_direct)
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        final_rate = excel_round(usdt_amount / thb_to_receive, 6)
        
        incoming_usdt = usdt_amount
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '6',
            'operation_name': 'Обменять конкретную сумму в USDT на THB',
            'direction': 'amount',
            'scenario': 'USDT → THB',
            'usdt_amount': usdt_amount,
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(self.usdt_thb_direct * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_to_exchange': thb_to_exchange_display,
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def rub_to_usdt_target(self, usdt_target: float) -> dict:
        """
        Операция 7: RUB → USDT (клиент хочет получить конкретную сумму USDT)
        Соответствует операциям 1.1-1.4 (второй сет) в CSV
        """
        withdrawal_commission = 1 # 1 USDT фикс
        usdt_before_commission = usdt_target + withdrawal_commission
        
        # В CSV для 3% прибыли комиссия 1.55%, для 5% - 2.56%, для 4% - 2.05%
        # Мы используем self.rub_comm, который уже рассчитан в __init__
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.rub_comm)
        rub_amount = excel_round(usdt_before_commission * rub_usdt_rate_sell, 2)
        
        final_rate = excel_round(rub_amount / usdt_target, 4)
        
        incoming_usdt = excel_round(rub_amount / self.rub_usdt_rate, 2)
        outgoing_usdt = usdt_before_commission
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '7',
            'operation_name': 'Обменять сумму в рублях на конкретную сумму USDT',
            'direction': 'target',
            'scenario': 'RUB → USDT',
            'usdt_target': usdt_target,
            'withdrawal_commission': withdrawal_commission,
            'usdt_before_commission': usdt_before_commission,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(self.rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'rub_amount': rub_amount,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }

    def rub_to_usdt_amount(self, rub_amount: float) -> dict:
        """
        Операция 8: RUB → USDT (клиент вносит конкретную сумму RUB)
        Соответствует операциям 2.1-2.4 (второй сет) в CSV
        """
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + self.rub_comm)
        usdt_before_commission = rub_amount / rub_usdt_rate_sell
        usdt_before_commission_display = excel_round(usdt_before_commission, 2)
        
        withdrawal_commission = 1
        usdt_received = excel_round(usdt_before_commission - withdrawal_commission, 2)
        
        final_rate = excel_round(rub_amount / usdt_received, 4)
        
        incoming_usdt = excel_round(rub_amount / self.rub_usdt_rate, 2)
        outgoing_usdt = usdt_before_commission
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '8',
            'operation_name': 'Обменять конкретную сумму в рублях на USDT',
            'direction': 'amount',
            'scenario': 'RUB → USDT',
            'rub_amount': rub_amount,
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(self.rub_comm * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 4),
            'usdt_before_commission': usdt_before_commission_display,
            'withdrawal_commission': withdrawal_commission,
            'usdt_received': usdt_received,
            'final_rate': final_rate,
            'commission_level': self.commission_name,
            'profit_percent': self.target_profit,
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }



# Тестирование
if __name__ == '__main__':
    calc = BrokerCalculatorDetailed(usdt_thb_rate=31.12, custom_rub_usdt_rate=80.90, commission_level='high')
    
    print("Операция 2.1: RUB → THB (amount, 5%)")
    result = calc.rub_to_thb_amount(2741.18)
    print(f"THB received: {result['thb_received']} (expected: 979.21)")
    print(f"Final rate: {result['final_rate']}")
    print()
