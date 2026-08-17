"""
Тесты бизнес-логики калькулятора Doverka.
Покрывает: excel_round, тиры комиссий, все 8 сценариев обмена.
Запуск: cd Dev/CalcCRM && python -m pytest tests/test_calculator.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculator import excel_round, CommissionCalculator, ExchangeCalculator

# Фиксированные курсы — не зависят от API
USDT_THB = 34.50
RUB_USDT = 92.50


# ── excel_round ────────────────────────────────────────────────────────────

class TestExcelRound:
    """Коммерческое округление: 0.5 всегда вверх"""

    def test_half_rounds_up_zero_decimals(self):
        assert excel_round(0.5, 0) == 1.0
        assert excel_round(1.5, 0) == 2.0
        assert excel_round(2.5, 0) == 3.0

    def test_half_rounds_up_two_decimals(self):
        assert excel_round(2.345, 2) == 2.35
        assert excel_round(2.335, 2) == 2.34

    def test_rounds_down_when_below_half(self):
        assert excel_round(2.344, 2) == 2.34
        assert excel_round(0.4, 0) == 0.0

    def test_zero(self):
        assert excel_round(0, 2) == 0.0
        assert excel_round(0, 0) == 0.0

    def test_large_number(self):
        assert excel_round(1_000_000.555, 2) == 1_000_000.56

    def test_negative(self):
        assert excel_round(-2.345, 2) == -2.35


# ── CommissionCalculator.get_level ─────────────────────────────────────────

class TestGetLevel:
    """Тиры комиссий: границы и параметры"""

    def test_zero_is_first_tier(self):
        name, _ = CommissionCalculator.get_level(0)
        assert name == 'до_500к'

    def test_just_below_500k(self):
        name, _ = CommissionCalculator.get_level(499_999)
        assert name == 'до_500к'

    def test_exactly_500k(self):
        name, _ = CommissionCalculator.get_level(500_000)
        assert name == '500к_1млн'

    def test_just_below_1m(self):
        name, _ = CommissionCalculator.get_level(999_999)
        assert name == '500к_1млн'

    def test_exactly_1m(self):
        name, _ = CommissionCalculator.get_level(1_000_000)
        assert name == 'от_1млн'

    def test_large_amount(self):
        name, _ = CommissionCalculator.get_level(50_000_000)
        assert name == 'от_1млн'

    def test_bonus_removed(self):
        """Бонуса Доверки нет с 17.08.2026 — база RUB-USDT = Рапира+2%."""
        for amount in [100_000, 500_000, 700_000, 1_000_000, 5_000_000]:
            _, params = CommissionCalculator.get_level(amount)
            assert params['bonus_percent'] == 0.0

    def test_commission_decreases_with_amount(self):
        _, p1 = CommissionCalculator.get_level(100_000)
        _, p2 = CommissionCalculator.get_level(700_000)
        _, p3 = CommissionCalculator.get_level(2_000_000)
        assert p1['usdt_thb_commission'] > p2['usdt_thb_commission'] > p3['usdt_thb_commission']

    def test_profit_percent_decreases_with_amount(self):
        _, p1 = CommissionCalculator.get_level(100_000)
        _, p2 = CommissionCalculator.get_level(700_000)
        _, p3 = CommissionCalculator.get_level(2_000_000)
        assert p1['profit_percent'] > p2['profit_percent'] > p3['profit_percent']


# ── Doverka: ExchangeCalculator ────────────────────────────────────────────

@pytest.fixture
def calc():
    return ExchangeCalculator(usdt_thb_rate=USDT_THB, rub_usdt_rate=RUB_USDT)


# -- RUB → THB --

class TestDoverkaRubToThb:
    """Сценарий 1-2: RUB → THB (amount и target)"""

    def test_amount_returns_positive_thb(self, calc):
        r = calc.rub_to_thb(1_000_000)
        assert r['scenario'] == 'RUB → THB'
        assert r['thb_received'] > 0

    def test_amount_thb_in_reasonable_range(self, calc):
        r = calc.rub_to_thb(1_000_000)
        # 1M RUB ~ 10800 USDT ~ 370k THB при базовых курсах
        assert 200_000 < r['thb_received'] < 500_000

    def test_amount_withdrawal_fees_applied(self, calc):
        r = calc.rub_to_thb(500_000)
        assert r['withdrawal_fixed'] == 20
        assert r['withdrawal_percent'] > 0
        assert r['thb_received'] < r['thb_to_exchange']

    def test_target_delivers_exact_thb(self, calc):
        r = calc.rub_to_thb_target(100_000)
        assert r['thb_received'] == 100_000

    def test_target_rub_is_positive(self, calc):
        r = calc.rub_to_thb_target(100_000)
        assert r['rub_amount'] > 0

    def test_custom_profit_margin(self, calc):
        r = calc.rub_to_thb(1_000_000, custom_profit_margin=3.0)
        assert r['commission_level'] == 'Индивидуальный (3.0%)'

    def test_more_rub_means_more_thb(self, calc):
        r1 = calc.rub_to_thb(500_000)
        r2 = calc.rub_to_thb(1_000_000)
        assert r2['thb_received'] > r1['thb_received']

    def test_target_more_thb_costs_more_rub(self, calc):
        r1 = calc.rub_to_thb_target(50_000)
        r2 = calc.rub_to_thb_target(100_000)
        assert r2['rub_amount'] > r1['rub_amount']


# -- THB → USDT --

class TestDoverkaThbToUsdt:
    """Сценарий 3-4: THB → USDT"""

    def test_amount_1_usdt_withdrawal(self, calc):
        r = calc.thb_to_usdt(100_000)
        assert r['withdrawal_fixed'] == 1

    def test_amount_commission_applied(self, calc):
        r = calc.thb_to_usdt(100_000, custom_profit_margin=3.0)
        assert r['profit_percent_actual'] == 3.0

    def test_target_delivers_target_usdt(self, calc):
        r = calc.thb_to_usdt_target(1000)
        assert r['usdt_target'] == 1000

    def test_target_thb_is_positive(self, calc):
        r = calc.thb_to_usdt_target(1000)
        assert r['thb_amount'] > 0
        # 1000 USDT ~ 34500 THB + комиссии
        assert r['thb_amount'] > 34_000

    def test_more_thb_means_more_usdt(self, calc):
        r1 = calc.thb_to_usdt(50_000)
        r2 = calc.thb_to_usdt(100_000)
        assert r2['usdt_received'] > r1['usdt_received']


# -- USDT → THB --

class TestDoverkaUsdtToThb:
    """Сценарий 5-6: USDT → THB"""

    def test_amount_withdrawal_fees(self, calc):
        r = calc.usdt_to_thb(1000)
        assert r['withdrawal_fixed'] == 20
        assert r['withdrawal_percent'] > 0

    def test_amount_thb_received_positive(self, calc):
        r = calc.usdt_to_thb(1000)
        assert r['thb_received'] > 0
        # 1000 USDT ~ 34500 THB минус комиссии
        assert 30_000 < r['thb_received'] < 35_000

    def test_target_delivers_exact_thb(self, calc):
        r = calc.usdt_to_thb_target(100_000)
        assert r['thb_received'] == 100_000

    def test_target_usdt_is_positive(self, calc):
        r = calc.usdt_to_thb_target(100_000)
        assert r['usdt_amount'] > 0

    def test_more_usdt_means_more_thb(self, calc):
        r1 = calc.usdt_to_thb(500)
        r2 = calc.usdt_to_thb(1000)
        assert r2['thb_received'] > r1['thb_received']


# -- RUB → USDT --

class TestDoverkaRubToUsdt:
    """Сценарий 7-8: RUB → USDT. Без бонуса rub_comm = profit напрямую."""

    def test_rub_comm_formula_at_5_percent(self, calc):
        r = calc.rub_to_usdt_target(1000, custom_profit_margin=5.0)
        # rub_comm = (5.0 - 0) / 100 = 5.0%
        assert abs(r['rub_usdt_commission'] - 5.0) < 0.01

    def test_rub_comm_formula_at_3_percent(self, calc):
        r = calc.rub_to_usdt_target(1000, custom_profit_margin=3.0)
        assert abs(r['rub_usdt_commission'] - 3.0) < 0.01

    def test_rub_comm_formula_at_2_4_percent(self, calc):
        r = calc.rub_to_usdt_target(1000, custom_profit_margin=2.4)
        assert abs(r['rub_usdt_commission'] - 2.4) < 0.01

    def test_target_1_usdt_withdrawal(self, calc):
        r = calc.rub_to_usdt_target(1000)
        assert r['withdrawal_fixed'] == 1

    def test_amount_deducts_1_usdt(self, calc):
        r = calc.rub_to_usdt_amount(100_000)
        # usdt_received = usdt_before_commission - 1
        assert r['withdrawal_fixed'] == 1
        assert abs(r['usdt_received'] - (r['usdt_amount'] - 1)) < 0.01

    def test_target_rub_is_positive(self, calc):
        r = calc.rub_to_usdt_target(1000)
        assert r['rub_amount'] > 0
        # 1001 USDT * 92.50 * (1 + comm) ~ 95k-100k RUB
        assert r['rub_amount'] > 90_000

    def test_amount_usdt_received_positive(self, calc):
        r = calc.rub_to_usdt_amount(500_000)
        assert r['usdt_received'] > 0

    def test_more_rub_means_more_usdt(self, calc):
        r1 = calc.rub_to_usdt_amount(100_000)
        r2 = calc.rub_to_usdt_amount(500_000)
        assert r2['usdt_received'] > r1['usdt_received']


# -- Profit sanity checks --

class TestDoverkaProfit:
    """Прибыль должна быть положительной при стандартных маржах"""

    def test_rub_thb_profit_positive(self, calc):
        r = calc.rub_to_thb(1_000_000, custom_profit_margin=3.0)
        assert r['profit_usdt'] > 0

    def test_thb_usdt_profit_positive(self, calc):
        r = calc.thb_to_usdt(100_000, custom_profit_margin=3.0)
        assert r['profit_usdt'] > 0

    def test_usdt_thb_profit_positive(self, calc):
        r = calc.usdt_to_thb(1000, custom_profit_margin=4.0)
        assert r['profit_usdt'] > 0

    def test_rub_usdt_profit_positive(self, calc):
        r = calc.rub_to_usdt_amount(500_000, custom_profit_margin=5.0)
        assert r['profit_usdt'] > 0


# ── Регресс: защита от деления на ноль (safe_rate) ──────────────────────────

from calculator import safe_rate


class TestSafeRate:
    """final_rate не должен ронять расчёт при нулевой выдаче (ZeroDivisionError)"""

    def test_zero_denominator_returns_zero(self):
        assert safe_rate(100, 0) == 0.0
        assert safe_rate(100, 0, 4) == 0.0

    def test_normal_division(self):
        assert safe_rate(100, 4) == 25.0

    def test_tiny_amounts_no_crash(self, calc):
        # Слишком маленькие суммы: выдача округляется в 0 → раньше ZeroDivisionError
        for amount in (1, 5, 10, 20, 33, 34):
            r = calc.thb_to_usdt(amount, custom_profit_margin=3.0)
            assert 'final_rate' in r  # не упало
            r2 = calc.rub_to_thb(amount, custom_profit_margin=3.0)
            assert 'final_rate' in r2

    def test_broker_tiny_amounts_no_crash(self):
        from broker_detailed import BrokerCalculatorDetailed
        b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, 4.0)
        for amount in (1, 10, 34):
            assert 'final_rate' in b.thb_to_usdt_amount(amount)


# -- Профит-мэппинг после перехода на Рапиру+2% (17.08.2026) --

class TestProfitHitsTargetWithoutBonus:
    """Комиссия c = p/(1+p): фактический профит RUB→THB равен целевому.

    Раньше мэппинг (5% → 2.72%) был откалиброван под бонус Доверки 2.4% —
    без бонуса он давал заниженный профит (5% → фактических 2.8%).
    """

    @pytest.fixture
    def calc(self):
        return ExchangeCalculator(usdt_thb_rate=32.87, rub_usdt_rate=89.97)

    @pytest.mark.parametrize('rub,target', [
        (100_000, 5.0),      # тир до 500к
        (700_000, 4.0),      # тир 500к-1млн
        (1_500_000, 3.0),    # тир от 1млн
    ])
    def test_standard_tiers(self, calc, rub, target):
        r = calc.rub_to_thb(rub)
        assert abs(r['profit_percent_actual'] - target) < 0.05

    @pytest.mark.parametrize('target', [1.5, 2.0, 2.4, 3.5, 4.5, 5.0])
    def test_custom_margin(self, calc, target):
        r = calc.rub_to_thb(300_000, custom_profit_margin=target)
        assert abs(r['profit_percent_actual'] - target) < 0.05

    def test_bonus_is_zero_in_result(self, calc):
        r = calc.rub_to_thb(100_000)
        assert r['bonus_usdt'] == 0
