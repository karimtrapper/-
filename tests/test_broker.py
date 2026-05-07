"""
Тесты бизнес-логики калькулятора Broker.
Покрывает: BrokerCalculatorDetailed — все 8 операций, комиссии по уровням прибыли.
Запуск: cd Dev/CalcCRM && python -m pytest tests/test_broker.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_detailed import excel_round, BrokerCalculatorDetailed

# Фиксированные курсы
USDT_THB = 34.50
RUB_USDT = 92.50


# ── Инициализация комиссий по уровням ──────────────────────────────────────

class TestBrokerCommissions:
    """Проверяем что комиссии правильно инициализируются при разных target_profit"""

    def test_5_percent_commissions(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=5.0)
        assert b.rub_comm == 0.0256
        assert b.usdt_comm == 0.0257
        assert b.thb_usdt_comm == 0.0525
        assert b.usdt_thb_direct == 0.0500

    def test_4_percent_commissions(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=4.0)
        assert b.rub_comm == 0.0205
        assert b.usdt_comm == 0.0204

    def test_3_percent_commissions(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=3.0)
        assert b.rub_comm == 0.0155
        assert b.usdt_comm == 0.0150

    def test_1_5_percent_commissions(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=1.5)
        assert b.rub_comm == 0.0075
        assert b.usdt_comm == 0.0076

    def test_rub_usdt_direct_always_equals_target(self):
        for profit in [1.5, 3.0, 4.0, 5.0]:
            b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=profit)
            assert abs(b.rub_usdt_direct - profit / 100.0) < 0.0001

    def test_interpolated_commission(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=2.5)
        # Общая формула: rub_comm = target_profit / 100 / 2 = 0.0125
        assert abs(b.rub_comm - 0.0125) < 0.001

    def test_commission_name(self):
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=3.0)
        assert b.commission_name == 'Брокер (3.0%)'


# ── Fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(params=[1.5, 3.0, 4.0, 5.0], ids=['1.5%', '3%', '4%', '5%'])
def broker(request):
    return BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=request.param)


@pytest.fixture
def broker_default():
    return BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=4.0)


# ── Операция 1: RUB → THB (target) ────────────────────────────────────────

class TestBrokerRubToThbTarget:
    def test_thb_target_preserved(self, broker):
        r = broker.rub_to_thb_target(100_000)
        assert r['thb_target'] == 100_000

    def test_rub_amount_positive(self, broker):
        r = broker.rub_to_thb_target(100_000)
        assert r['rub_amount'] > 0

    def test_withdrawal_fixed_20(self, broker):
        r = broker.rub_to_thb_target(100_000)
        assert r['withdrawal_fixed'] == 20

    def test_scenario_label(self, broker):
        r = broker.rub_to_thb_target(100_000)
        assert r['scenario'] == 'RUB → THB'
        assert r['direction'] == 'target'


# ── Операция 2: RUB → THB (amount) ────────────────────────────────────────

class TestBrokerRubToThbAmount:
    def test_thb_received_positive(self, broker):
        r = broker.rub_to_thb_amount(1_000_000)
        assert r['thb_received'] > 0

    def test_thb_in_reasonable_range(self, broker_default):
        r = broker_default.rub_to_thb_amount(1_000_000)
        assert 200_000 < r['thb_received'] < 500_000

    def test_more_rub_more_thb(self, broker_default):
        r1 = broker_default.rub_to_thb_amount(500_000)
        r2 = broker_default.rub_to_thb_amount(1_000_000)
        assert r2['thb_received'] > r1['thb_received']

    def test_withdrawal_fees(self, broker_default):
        r = broker_default.rub_to_thb_amount(500_000)
        assert r['withdrawal_fixed'] == 20
        assert r['withdrawal_percent'] > 0


# ── Операция 3: THB → USDT (target) ───────────────────────────────────────

class TestBrokerThbToUsdtTarget:
    def test_usdt_target_preserved(self, broker):
        r = broker.thb_to_usdt_target(1000)
        assert r['usdt_target'] == 1000

    def test_thb_amount_positive(self, broker):
        r = broker.thb_to_usdt_target(1000)
        assert r['thb_amount'] > 0
        assert r['thb_amount'] > 34_000  # > 1000 * 34

    def test_withdrawal_1_usdt(self, broker):
        r = broker.thb_to_usdt_target(1000)
        assert r['withdrawal_commission'] == 1


# ── Операция 4: THB → USDT (amount) ───────────────────────────────────────

class TestBrokerThbToUsdtAmount:
    def test_usdt_received_positive(self, broker):
        r = broker.thb_to_usdt_amount(100_000)
        assert r['usdt_received'] > 0

    def test_withdrawal_1_usdt(self, broker):
        r = broker.thb_to_usdt_amount(100_000)
        assert r['withdrawal_commission'] == 1

    def test_more_thb_more_usdt(self, broker_default):
        r1 = broker_default.thb_to_usdt_amount(50_000)
        r2 = broker_default.thb_to_usdt_amount(100_000)
        assert r2['usdt_received'] > r1['usdt_received']


# ── Операция 5: USDT → THB (target) ───────────────────────────────────────

class TestBrokerUsdtToThbTarget:
    def test_thb_target_preserved(self, broker):
        r = broker.usdt_to_thb_target(100_000)
        assert r['thb_target'] == 100_000

    def test_usdt_amount_positive(self, broker):
        r = broker.usdt_to_thb_target(100_000)
        assert r['usdt_amount'] > 0

    def test_withdrawal_20_thb(self, broker):
        r = broker.usdt_to_thb_target(100_000)
        assert r['withdrawal_fixed'] == 20


# ── Операция 6: USDT → THB (amount) ───────────────────────────────────────

class TestBrokerUsdtToThbAmount:
    def test_thb_received_positive(self, broker):
        r = broker.usdt_to_thb_amount(1000)
        assert r['thb_received'] > 0

    def test_thb_in_reasonable_range(self, broker_default):
        r = broker_default.usdt_to_thb_amount(1000)
        assert 30_000 < r['thb_received'] < 35_000

    def test_withdrawal_fees(self, broker_default):
        r = broker_default.usdt_to_thb_amount(1000)
        assert r['withdrawal_fixed'] == 20
        assert r['withdrawal_percent'] > 0


# ── Операция 7: RUB → USDT (target) ───────────────────────────────────────

class TestBrokerRubToUsdtTarget:
    def test_usdt_target_preserved(self, broker):
        r = broker.rub_to_usdt_target(1000)
        assert r['usdt_target'] == 1000

    def test_rub_amount_positive(self, broker):
        r = broker.rub_to_usdt_target(1000)
        assert r['rub_amount'] > 0

    def test_uses_direct_commission(self, broker_default):
        r = broker_default.rub_to_usdt_target(1000)
        # rub_usdt_direct = 4.0 / 100 = 0.04 = 4.0%
        assert abs(r['rub_usdt_commission'] - 4.0) < 0.01

    def test_withdrawal_1_usdt(self, broker):
        r = broker.rub_to_usdt_target(1000)
        assert r['withdrawal_commission'] == 1


# ── Операция 8: RUB → USDT (amount) ───────────────────────────────────────

class TestBrokerRubToUsdtAmount:
    def test_usdt_received_positive(self, broker):
        r = broker.rub_to_usdt_amount(100_000)
        assert r['usdt_received'] > 0

    def test_withdrawal_1_usdt(self, broker):
        r = broker.rub_to_usdt_amount(100_000)
        assert r['withdrawal_commission'] == 1

    def test_more_rub_more_usdt(self, broker_default):
        r1 = broker_default.rub_to_usdt_amount(100_000)
        r2 = broker_default.rub_to_usdt_amount(500_000)
        assert r2['usdt_received'] > r1['usdt_received']


# ── Profit sanity ──────────────────────────────────────────────────────────

class TestBrokerProfit:
    """При стандартных маржах прибыль положительная"""

    def test_rub_thb_target_profit_positive(self, broker):
        r = broker.rub_to_thb_target(100_000)
        assert r['profit_usdt'] > 0

    def test_rub_thb_amount_profit_positive(self, broker):
        r = broker.rub_to_thb_amount(1_000_000)
        assert r['profit_usdt'] > 0

    def test_usdt_thb_profit_positive(self, broker):
        r = broker.usdt_to_thb_amount(1000)
        assert r['profit_usdt'] > 0

    def test_rub_usdt_profit_positive(self, broker):
        r = broker.rub_to_usdt_amount(500_000)
        assert r['profit_usdt'] > 0


# ── Симметрия amount ↔ target ──────────────────────────────────────────────

class TestBrokerSymmetry:
    """Target и amount-режимы должны давать согласованные результаты"""

    def test_rub_thb_symmetry(self, broker_default):
        # Сначала считаем сколько THB получим за 1M RUB
        r_amount = broker_default.rub_to_thb_amount(1_000_000)
        thb_got = r_amount['thb_received']
        # Потом — сколько RUB нужно заплатить за столько THB
        r_target = broker_default.rub_to_thb_target(thb_got)
        # Суммы RUB должны примерно совпасть
        assert abs(r_target['rub_amount'] - 1_000_000) < 100  # погрешность <100 RUB

    def test_usdt_thb_symmetry(self, broker_default):
        r_amount = broker_default.usdt_to_thb_amount(1000)
        thb_got = r_amount['thb_received']
        r_target = broker_default.usdt_to_thb_target(thb_got)
        assert abs(r_target['usdt_amount'] - 1000) < 1  # погрешность <1 USDT

    def test_thb_usdt_symmetry(self, broker_default):
        r_target = broker_default.thb_to_usdt_target(1000)
        thb_needed = r_target['thb_amount']
        r_amount = broker_default.thb_to_usdt_amount(thb_needed)
        assert abs(r_amount['usdt_received'] - 1000) < 1

    def test_rub_usdt_symmetry(self, broker_default):
        r_amount = broker_default.rub_to_usdt_amount(500_000)
        usdt_got = r_amount['usdt_received']
        r_target = broker_default.rub_to_usdt_target(usdt_got)
        assert abs(r_target['rub_amount'] - 500_000) < 100
