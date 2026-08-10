"""Комиссия за выдачу зависит от площадки, где откупаем баты.

Bitazza берёт 0.15% + 20 ฿, Binance — 0.25% + 20 ฿. До этого фикса ставка
0.25% была захардкожена во всех методах, и расчёт по Bitazza завышал расход
клиенту (карточка курса при этом честно писала «−0.15%» — расхождение видел Карим).

Здесь же проверяется, что источник курса доезжает в ответ (`rate_source`,
`withdrawal_percent_rate`) — по ним фронт подписывает строку «Комиссия за выдачу».

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_rate_source_fee.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import app as flask_app
from broker_detailed import BrokerCalculatorDetailed
from calculator import (ExchangeCalculator, WITHDRAWAL_PCT_BINANCE,
                        WITHDRAWAL_PCT_BITAZZA, WITHDRAWAL_FIXED_THB)

RATE_USDT_THB = 33.0
RATE_RUB_USDT = 90.0


@pytest.fixture
def pub():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def _mock_rates(usdt_thb=RATE_USDT_THB, rub_usdt=RATE_RUB_USDT):
    async def _f():
        return {'usdt_thb': usdt_thb, 'rub_usdt': rub_usdt}
    return _f


class TestWithdrawalFeeByVenue:
    """Ставка комиссии подставляется, а не берётся из хардкода."""

    def test_bitazza_fee_lower_than_binance(self):
        binance = ExchangeCalculator(RATE_USDT_THB, RATE_RUB_USDT)
        bitazza = ExchangeCalculator(RATE_USDT_THB, RATE_RUB_USDT,
                                     withdrawal_percent=WITHDRAWAL_PCT_BITAZZA)
        a = binance.rub_to_thb(100_000, custom_profit_margin=5.0)
        b = bitazza.rub_to_thb(100_000, custom_profit_margin=5.0)

        assert b['withdrawal_percent'] < a['withdrawal_percent']
        # 0.15% от той же базы = ровно 3/5 от 0.25%
        assert b['withdrawal_percent'] == pytest.approx(a['withdrawal_percent'] * 0.6, rel=1e-3)
        # клиент получает больше ровно на сэкономленную комиссию
        assert b['thb_received'] - a['thb_received'] == pytest.approx(
            a['withdrawal_percent'] - b['withdrawal_percent'], abs=0.02)

    def test_default_stays_binance(self):
        """Без явной ставки поведение прежнее — 0.25%, регресса нет."""
        calc = ExchangeCalculator(RATE_USDT_THB, RATE_RUB_USDT)
        res = calc.rub_to_thb(100_000, custom_profit_margin=5.0)
        assert res['withdrawal_percent'] == pytest.approx(
            res['thb_to_exchange'] * WITHDRAWAL_PCT_BINANCE, abs=0.02)
        assert res['withdrawal_fixed'] == WITHDRAWAL_FIXED_THB

    def test_target_direction_uses_same_rate(self):
        """Обратный ввод (клиенту нужна ровная сумма бат) — та же ставка."""
        bitazza = ExchangeCalculator(RATE_USDT_THB, RATE_RUB_USDT,
                                     withdrawal_percent=WITHDRAWAL_PCT_BITAZZA)
        res = bitazza.rub_to_thb_target(35_000, custom_profit_margin=5.0)
        base = 35_000 + WITHDRAWAL_FIXED_THB + res['withdrawal_percent']
        assert res['withdrawal_percent'] == pytest.approx(base * WITHDRAWAL_PCT_BITAZZA, abs=0.05)

    def test_broker_calculator_accepts_fee(self):
        broker = BrokerCalculatorDetailed(RATE_USDT_THB, 80.0, 4.0,
                                          withdrawal_percent=WITHDRAWAL_PCT_BITAZZA)
        res = broker.rub_to_thb_amount(100_000)
        assert res['withdrawal_percent'] == pytest.approx(
            res['thb_to_exchange'] * WITHDRAWAL_PCT_BITAZZA, abs=0.02)


class TestEstimateUsdtVolume:
    """Объём для VWAP: `amount` приходит в разной валюте — приводим к USDT."""

    RATES = {'usdt_thb': RATE_USDT_THB, 'rub_usdt': RATE_RUB_USDT}

    def test_rub_amount_converted(self):
        vol = appmod._estimate_usdt_volume('rub-to-thb', 'amount', 90_000, self.RATES)
        assert vol == pytest.approx(1000, rel=1e-6)

    def test_thb_target_converted(self):
        vol = appmod._estimate_usdt_volume('rub-to-thb', 'target', 33_000, self.RATES)
        assert vol == pytest.approx(1000, rel=1e-6)

    def test_usdt_passthrough(self):
        assert appmod._estimate_usdt_volume('usdt-to-thb', 'amount', 500, self.RATES) == 500

    def test_zero_rates_fall_back_to_nominal(self):
        vol = appmod._estimate_usdt_volume('rub-to-thb', 'amount', 90_000,
                                           {'usdt_thb': None, 'rub_usdt': None})
        assert vol == appmod.CALC_BITAZZA_QUOTE_VOLUME


class TestCalculateEndpoint:
    """Ответ /api/calculate несёт источник курса и применённую ставку."""

    def test_binance_source_reports_025(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates())
        resp = pub.post('/api/calculate', json={
            'scenario': 'rub-to-thb', 'direction': 'amount', 'amount': 100_000,
            'profit_margin': 5.0, 'rate_source': 'binance',
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['rate_source'] == 'binance'
        assert body['withdrawal_percent_rate'] == 0.25

    def test_bitazza_source_uses_book_and_015(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates())
        monkeypatch.setattr(appmod, '_bitazza_calc_quote',
                            lambda *a, **kw: {'raw_vwap': 34.0, 'effective': 33.949})
        resp = pub.post('/api/calculate', json={
            'scenario': 'rub-to-thb', 'direction': 'amount', 'amount': 100_000,
            'profit_margin': 5.0, 'rate_source': 'bitazza',
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['rate_source'] == 'bitazza'
        assert body['withdrawal_percent_rate'] == 0.15
        # курс взят из стакана Bitazza, а не из общих rates
        assert body['usdt_thb_rate'] == pytest.approx(34.0)

    def test_bitazza_unavailable_falls_back_to_binance(self, pub, monkeypatch):
        """Стакан молчит → считаем по Binance и честно говорим об этом."""
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates())
        monkeypatch.setattr(appmod, '_bitazza_calc_quote', lambda *a, **kw: None)
        resp = pub.post('/api/calculate', json={
            'scenario': 'rub-to-thb', 'direction': 'amount', 'amount': 100_000,
            'profit_margin': 5.0, 'rate_source': 'bitazza',
        })
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['rate_source'] == 'binance'
        assert body['withdrawal_percent_rate'] == 0.25
        assert body['usdt_thb_rate'] == pytest.approx(RATE_USDT_THB)
