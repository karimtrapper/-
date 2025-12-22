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
    """Калькулятор брокера с детальными результатами"""
    
    # Уровни комиссий
    COMMISSION_LEVELS = {
        'high': {  # 5% - для сумм > 1M RUB
            'name': 'Высокий (5%)',
            'rub_usdt_commission': 0.0256,   # 2.56% (RUB-USDT)
            'usdt_thb_commission': 0.0257,   # 2.57% (USDT-THB)
            'thb_usdt_commission': 0.0525,   # 5.25%
            'usdt_thb_direct': 0.0500,       # 5.00%
            'profit_percent': 0.05
        },
        'medium': {  # 4% - для сумм 500k-1M RUB
            'name': 'Средний (4%)',
            'rub_usdt_commission': 0.0205,   # 2.05% (RUB-USDT) - ИСПРАВЛЕНО!
            'usdt_thb_commission': 0.0204,   # 2.04% (USDT-THB)
            'thb_usdt_commission': 0.0416,   # 4.16%
            'usdt_thb_direct': 0.0400,       # 4.00%
            'profit_percent': 0.04
        },
        'low': {  # 3% - для сумм < 500k RUB
            'name': 'Низкий (3%)',
            'rub_usdt_commission': 0.0155,   # 1.55% (RUB-USDT)
            'usdt_thb_commission': 0.0150,   # 1.50% (USDT-THB) - ИСПРАВЛЕНО!
            'thb_usdt_commission': 0.0308,   # 3.08%
            'usdt_thb_direct': 0.0300,       # 3.00%
            'profit_percent': 0.03
        }
    }
    
    def __init__(self, usdt_thb_rate: float, custom_rub_usdt_rate: float, commission_level: str = 'medium'):
        self.usdt_thb_rate = usdt_thb_rate
        self.rub_usdt_rate = custom_rub_usdt_rate
        self.commission = self.COMMISSION_LEVELS.get(commission_level, self.COMMISSION_LEVELS['medium'])
        self.commission_level = commission_level
    
    def rub_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 1: RUB → THB (клиент хочет получить конкретную сумму THB)
        Соответствует операциям 1.1-1.3 в CSV
        Использует Excel-округление для точного совпадения
        """
        # Комиссии за выдачу - процентная комиссия берется от ИТОГОВОЙ суммы!
        withdrawal_fixed = 20
        # Формула: thb_to_exchange = (thb_target + fixed) / (1 - percent)
        thb_to_exchange = (thb_target + withdrawal_fixed) / (1 - 0.0025)
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - withdrawal_fixed, 2)
        
        # Курс продажи USDT-THB (с комиссией) - НЕ округляем для точности
        usdt_thb_commission_value = self.commission['usdt_thb_commission']
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_thb_commission_value)
        
        # Сумма USDT - округляем для отображения
        usdt_amount = thb_to_exchange / usdt_thb_rate_sell
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        # Курс продажи RUB-USDT (с комиссией) - НЕ округляем для точности
        rub_usdt_commission_value = self.commission['rub_usdt_commission']
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_usdt_commission_value)
        
        # Сумма RUB - округляем финальное значение
        rub_amount = excel_round(usdt_amount * rub_usdt_rate_sell, 2)
        
        # Итоговый курс
        final_rate = excel_round(rub_amount / thb_target, 4)
        
        # Расчет прибыли (БЕЗ бонуса 2.4% - это только для Doverka!)
        # Поступление = Сумма USDT × (1 + Комиссия RUB-USDT)
        incoming_usdt = excel_round(usdt_amount * (1 + rub_usdt_commission_value), 2)
        # Выплата = THB к обмену / Базовый курс USDT-THB (без комиссии)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0
        
        return {
            'operation': '1',
            'operation_name': 'Обменять сумму в рублях на конкретную сумму THB',  # Точно как в CSV
            'direction': 'target',
            'scenario': 'RUB → THB',
            
            # Входные данные
            'thb_target': thb_target,
            
            # Комиссии за выдачу
            'withdrawal_fixed': withdrawal_fixed,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': thb_to_exchange_display,
            
            # Курсы и комиссии USDT-THB
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_thb_commission_value * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'usdt_amount': usdt_amount_display,
            
            # Курсы и комиссии RUB-USDT
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_usdt_commission_value * 100, 2),
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 2),
            'rub_amount': rub_amount,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
            'incoming_usdt': incoming_usdt,  # Поступление
            'outgoing_usdt': outgoing_usdt,  # Выплата
            'profit_usdt': profit_usdt,      # Прибыль
            'profit_percent_actual': profit_percent_actual  # % прибыли фактический
        }
    
    def rub_to_thb_amount(self, rub_amount: float) -> dict:
        """
        Операция 2: RUB → THB (клиент вносит конкретную сумму RUB)
        Соответствует операциям 2.1-2.3 в CSV
        Использует округление как в Excel для точного совпадения
        
        ВАЖНО: Для операции amount комиссии ПЕРЕСТАВЛЕНЫ местами относительно target!
        """
        # Курс продажи RUB-USDT (с комиссией) - для amount берём usdt_thb_commission!
        rub_usdt_commission_value = self.commission['usdt_thb_commission']  # ПЕРЕСТАВЛЕНО!
        rub_usdt_rate_sell = self.rub_usdt_rate * (1 + rub_usdt_commission_value)
        
        # Сумма USDT - округляем для отображения
        usdt_amount = rub_amount / rub_usdt_rate_sell
        usdt_amount_display = excel_round(usdt_amount, 2)
        
        # Курс продажи USDT-THB (с комиссией) - для amount берём rub_usdt_commission!
        usdt_thb_commission_value = self.commission['rub_usdt_commission']  # ПЕРЕСТАВЛЕНО!
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_thb_commission_value)
        
        # Сумма THB к обмену - округляем для отображения
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        # Комиссии за выдачу - округляем
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        
        # Итоговая сумма THB - округляем финальное значение
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        # Итоговый курс
        final_rate = excel_round(rub_amount / thb_to_receive, 4)
        
        # Расчет прибыли (как в CSV)
        # Прибыль (БЕЗ бонуса 2.4% - это только для Doverka!)
        # Используем актуальную комиссию RUB-USDT для расчёта поступления
        incoming_usdt = excel_round(usdt_amount * (1 + rub_usdt_commission_value), 2)
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / outgoing_usdt) * 100, 2) if outgoing_usdt > 0 else 0
        
        return {
            'operation': '2',
            'operation_name': 'Обменять конкретную сумму в рублях на THB',
            'direction': 'amount',
            'scenario': 'RUB → THB',
            
            # Входные данные
            'rub_amount': rub_amount,
            
            # Курсы и комиссии RUB-USDT (для amount комиссии переставлены!)
            'rub_usdt_rate': self.rub_usdt_rate,
            'rub_usdt_commission': excel_round(rub_usdt_commission_value * 100, 2),  # Актуальная комиссия
            'rub_usdt_rate_sell': excel_round(rub_usdt_rate_sell, 2),
            'usdt_amount': usdt_amount_display,
            
            # Курсы и комиссии USDT-THB (для amount комиссии переставлены!)
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_thb_commission_value * 100, 2),  # Актуальная комиссия
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 4),
            'thb_to_exchange': thb_to_exchange_display,
            
            # Комиссии за выдачу
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }
    
    def thb_to_usdt_target(self, usdt_target: float) -> dict:
        """
        Операция 3: THB → USDT (клиент хочет получить конкретную сумму USDT)
        Соответствует операциям 3.1-3.3 в CSV
        Использует Excel-округление для точного совпадения
        """
        # Комиссия за вывод
        withdrawal_commission = 1
        
        # Сумма USDT до комиссии
        usdt_before_commission = usdt_target + withdrawal_commission
        
        # Курс продажи USDT-THB (с комиссией) - НЕ округляем для точности
        thb_usdt_commission_value = self.commission['thb_usdt_commission']
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + thb_usdt_commission_value)
        
        # Сумма THB - округляем финальное значение
        thb_amount = excel_round(usdt_before_commission * usdt_thb_rate_sell, 2)
        
        # Итоговый курс
        final_rate = excel_round(thb_amount / usdt_target, 4)
        
        # Расчет прибыли для THB → USDT
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)  # THB в USDT по базовому курсу
        outgoing_usdt = usdt_target  # Выдаем клиенту
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '3',
            'operation_name': 'Обменять сумму в THB на конкретную сумму в USDT',  # Точно как в CSV
            'direction': 'target',
            'scenario': 'THB → USDT',
            
            # Входные данные
            'usdt_target': usdt_target,
            
            # Комиссия за вывод
            'withdrawal_commission': withdrawal_commission,
            'usdt_before_commission': usdt_before_commission,
            
            # Курсы и комиссии
            'usdt_thb_rate': self.usdt_thb_rate,
            'thb_usdt_commission': excel_round(thb_usdt_commission_value * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_amount': thb_amount,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }
    
    def thb_to_usdt_amount(self, thb_amount: float) -> dict:
        """
        Операция 4: THB → USDT (клиент вносит конкретную сумму THB)
        Соответствует операциям 4.1-4.3 в CSV
        Использует Excel-округление для точного совпадения
        """
        # Курс продажи USDT-THB (с комиссией) - НЕ округляем для точности
        thb_usdt_commission_value = self.commission['thb_usdt_commission']
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 + thb_usdt_commission_value)
        
        # Сумма USDT до комиссии - округляем
        usdt_before_commission = thb_amount / usdt_thb_rate_sell
        usdt_before_commission_display = excel_round(usdt_before_commission, 2)
        
        # Комиссия за вывод
        withdrawal_commission = 1
        
        # Итоговая сумма USDT - округляем финальное значение
        usdt_to_receive = excel_round(usdt_before_commission - withdrawal_commission, 2)
        
        # Итоговый курс
        final_rate = excel_round(thb_amount / usdt_to_receive, 4)
        
        # Расчет прибыли для THB → USDT
        incoming_usdt = excel_round(thb_amount / self.usdt_thb_rate, 2)
        outgoing_usdt = usdt_to_receive
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '4',
            'operation_name': 'Обменять конкретную сумму в THB на USDT',  # Точно как в CSV
            'direction': 'amount',
            'scenario': 'THB → USDT',
            
            # Входные данные
            'thb_amount': thb_amount,
            
            # Курсы и комиссии
            'usdt_thb_rate': self.usdt_thb_rate,
            'thb_usdt_commission': excel_round(thb_usdt_commission_value * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_before_commission': usdt_before_commission_display,
            
            # Комиссия за вывод
            'withdrawal_commission': withdrawal_commission,
            'usdt_received': usdt_to_receive,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }
    
    def usdt_to_thb_target(self, thb_target: float) -> dict:
        """
        Операция 5: USDT → THB (клиент хочет получить конкретную сумму THB)
        Соответствует операциям 5.1-5.3 в CSV
        Использует Excel-округление для точного совпадения
        """
        # Комиссии за выдачу - процентная комиссия берется от ИТОГОВОЙ суммы!
        withdrawal_fixed = 20
        # Формула: thb_to_exchange = (thb_target + fixed) / (1 - percent)
        thb_to_exchange = (thb_target + withdrawal_fixed) / (1 - 0.0025)
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        withdrawal_percent_fee = excel_round(thb_to_exchange - thb_target - withdrawal_fixed, 2)
        
        # Курс продажи USDT-THB (с комиссией) - НЕ округляем для точности
        usdt_thb_direct_commission = self.commission['usdt_thb_direct']
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_thb_direct_commission)
        
        # Сумма USDT - округляем финальное значение
        usdt_amount = excel_round(thb_to_exchange / usdt_thb_rate_sell, 2)
        
        # Итоговый курс
        final_rate = excel_round(usdt_amount / thb_target, 6)
        
        # Расчет прибыли для USDT → THB
        incoming_usdt = usdt_amount  # USDT от клиента
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)  # THB в USDT по базовому курсу
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '5',
            'operation_name': 'Обменять сумму в USDT на конкретную сумму THB',  # Точно как в CSV
            'direction': 'target',
            'scenario': 'USDT → THB',
            
            # Входные данные
            'thb_target': thb_target,
            
            # Комиссии за выдачу
            'withdrawal_fixed': withdrawal_fixed,
            'withdrawal_percent': withdrawal_percent_fee,
            'thb_to_exchange': thb_to_exchange_display,
            
            # Курсы и комиссии
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_thb_direct_commission * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'usdt_amount': usdt_amount,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
            'incoming_usdt': incoming_usdt,
            'outgoing_usdt': outgoing_usdt,
            'profit_usdt': profit_usdt,
            'profit_percent_actual': profit_percent_actual
        }
    
    def usdt_to_thb_amount(self, usdt_amount: float) -> dict:
        """
        Операция 6: USDT → THB (клиент вносит конкретную сумму USDT)
        Соответствует операциям 6.1-6.3 в CSV
        Использует Excel-округление для точного совпадения
        """
        # Курс продажи USDT-THB (с комиссией) - НЕ округляем для точности
        usdt_thb_direct_commission = self.commission['usdt_thb_direct']
        usdt_thb_rate_sell = self.usdt_thb_rate * (1 - usdt_thb_direct_commission)
        
        # Сумма THB к обмену - округляем
        thb_to_exchange = usdt_amount * usdt_thb_rate_sell
        thb_to_exchange_display = excel_round(thb_to_exchange, 2)
        
        # Комиссии за выдачу - округляем
        withdrawal_percent_fee = excel_round(thb_to_exchange * 0.0025, 2)
        withdrawal_fixed = 20
        
        # Итоговая сумма THB - округляем финальное значение
        thb_to_receive = excel_round(thb_to_exchange - withdrawal_percent_fee - withdrawal_fixed, 2)
        
        # Итоговый курс
        final_rate = excel_round(usdt_amount / thb_to_receive, 6)
        
        # Расчет прибыли для USDT → THB
        incoming_usdt = usdt_amount  # USDT от клиента
        outgoing_usdt = excel_round(thb_to_exchange / self.usdt_thb_rate, 2)  # THB в USDT по базовому курсу
        profit_usdt = excel_round(incoming_usdt - outgoing_usdt, 2)
        profit_percent_actual = excel_round((profit_usdt / incoming_usdt) * 100, 2) if incoming_usdt > 0 else 0
        
        return {
            'operation': '6',
            'operation_name': 'Обменять конкретную сумму в USDT на THB',  # Точно как в CSV
            'direction': 'amount',
            'scenario': 'USDT → THB',
            
            # Входные данные
            'usdt_amount': usdt_amount,
            
            # Курсы и комиссии
            'usdt_thb_rate': self.usdt_thb_rate,
            'usdt_thb_commission': excel_round(usdt_thb_direct_commission * 100, 2),
            'usdt_thb_rate_sell': excel_round(usdt_thb_rate_sell, 2),
            'thb_to_exchange': thb_to_exchange_display,
            
            # Комиссии за выдачу
            'withdrawal_percent': withdrawal_percent_fee,
            'withdrawal_fixed': withdrawal_fixed,
            'thb_received': thb_to_receive,
            
            # Итоговый курс
            'final_rate': final_rate,
            'commission_level': self.commission['name'],
            'profit_percent': self.commission['profit_percent'] * 100,
            
            # Прибыльность
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
