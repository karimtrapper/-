"""
Контракт «бэкенд → фронт» для партнёрского markup.

Фронтовый applyPartnerMarkup (static/calculator/calculator.js) в target-режиме
умножает сумму к внесению ТОЛЬКО по алиасам rub_to_pay / thb_to_pay / usdt_to_pay,
а в amount-режиме — по thb_received / usdt_received. Сырые поля rub_amount /
thb_amount / usdt_amount он не трогает (в RUB-сценариях usdt_amount —
промежуточная сумма брокера, не клиентская).

Регресс 2026-07-13: broker_detailed.py не отдавал эти алиасы → фронт ухудшал
курс, но не пересчитывал сумму (рассинхрон на экране). Тесты фиксируют контракт
для ОБОИХ калькуляторов, чтобы новый бэкенд-путь снова его не потерял.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_partner_markup_contract.py -v
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_detailed import BrokerCalculatorDetailed
from calculator import ExchangeCalculator

USDT_THB = 34.50
RUB_USDT = 92.50

# Какой алиас суммы к внесению обязан присутствовать в каждом target-сценарии
TARGET_PAY_ALIAS = {
    'RUB → THB': ('rub_to_pay', 'rub_amount'),
    'THB → USDT': ('thb_to_pay', 'thb_amount'),
    'USDT → THB': ('usdt_to_pay', 'usdt_amount'),
    'RUB → USDT': ('rub_to_pay', 'rub_amount'),
}

# Какое поле «клиент получит» обязано присутствовать в каждом amount-сценарии
AMOUNT_RECEIVED_FIELD = {
    'RUB → THB': 'thb_received',
    'THB → USDT': 'usdt_received',
    'USDT → THB': 'thb_received',
    'RUB → USDT': 'usdt_received',
}


def broker_results():
    b = BrokerCalculatorDetailed(USDT_THB, RUB_USDT, target_profit=2.0)
    return {
        'target': [
            b.rub_to_thb_target(100_000),
            b.thb_to_usdt_target(5_000),
            b.usdt_to_thb_target(186_000),
            b.rub_to_usdt_target(5_000),
        ],
        'amount': [
            b.rub_to_thb_amount(500_000),
            b.thb_to_usdt_amount(186_000),
            b.usdt_to_thb_amount(5_733),
            b.rub_to_usdt_amount(500_000),
        ],
    }


def doverka_results():
    c = ExchangeCalculator(USDT_THB, RUB_USDT)
    return {
        'target': [
            c.rub_to_thb_target(100_000),
            c.thb_to_usdt_target(5_000),
            c.usdt_to_thb_target(186_000),
            c.rub_to_usdt_target(5_000),
        ],
        'amount': [
            c.rub_to_thb(500_000),
            c.thb_to_usdt(186_000),
            c.usdt_to_thb(5_733),
            c.rub_to_usdt_amount(500_000),
        ],
    }


@pytest.fixture(params=[broker_results, doverka_results], ids=['broker', 'doverka'])
def results(request):
    return request.param()


class TestTargetPayAlias:
    """target-режим: алиас *_to_pay присутствует и равен сырому полю суммы"""

    def test_alias_present_and_matches_raw(self, results):
        for r in results['target']:
            assert r['direction'] == 'target'
            alias, raw = TARGET_PAY_ALIAS[r['scenario']]
            assert alias in r, f"{r['scenario']}: нет алиаса {alias} — markup партнёра не применится к сумме"
            assert r[alias] == r[raw], f"{r['scenario']}: {alias} != {raw}"
            assert r[alias] > 0

    def test_no_foreign_pay_aliases(self, results):
        # Лишний алиас другой валюты заставил бы фронт умножить не ту сумму
        for r in results['target']:
            expected_alias = TARGET_PAY_ALIAS[r['scenario']][0]
            for alias in ('rub_to_pay', 'thb_to_pay', 'usdt_to_pay'):
                if alias != expected_alias:
                    assert alias not in r, f"{r['scenario']}: лишний алиас {alias}"


class TestAmountReceivedField:
    """amount-режим: поле *_received присутствует (его фронт уменьшает на markup)"""

    def test_received_present(self, results):
        for r in results['amount']:
            assert r['direction'] == 'amount'
            field = AMOUNT_RECEIVED_FIELD[r['scenario']]
            assert field in r, f"{r['scenario']}: нет {field}"
            assert r[field] > 0


class TestMarkupRateSumConsistency:
    """
    Порт применения markup из applyPartnerMarkup: после ухудшения курса
    и пересчёта суммы подразумеваемый курс (сумма/получение) обязан
    совпадать с final_rate. Именно этот инвариант был сломан на скрине
    2026-07-13 (курс 31.79 при сумме по курсу 32.44).
    """

    MARKUP = 0.02  # +2% к курсу клиента

    def _apply_markup_target(self, r):
        # Как в JS: сумма к внесению растёт, курс ухудшается
        inv = 1 + self.MARKUP
        alias = TARGET_PAY_ALIAS[r['scenario']][0]
        pay = r[alias] * inv
        if r['scenario'] == 'USDT → THB':
            rate = r['final_rate'] * (1 - self.MARKUP)  # ฿/USDT: клиенту меньше ฿
        else:
            rate = r['final_rate'] * inv
        return pay, rate

    def test_broker_all_target_scenarios(self):
        for r in broker_results()['target']:
            pay, rate = self._apply_markup_target(r)
            receive = r.get('thb_target') or r.get('usdt_target')
            if r['scenario'] == 'USDT → THB':
                implied = receive / pay          # ฿/USDT
            else:
                implied = pay / receive          # ₽/฿, ฿/USDT, ₽/USDT
            # 1e-3: JS умножает курс на (1-m), а сумму на (1+m) — не точные
            # обратные величины, расхождение ~m² (0.04% при 2%)
            assert abs(implied - rate) / rate < 1e-3, (
                f"{r['scenario']}: рассинхрон курс↔сумма после markup "
                f"(implied {implied:.4f} vs rate {rate:.4f})"
            )
