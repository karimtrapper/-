"""Регресс-тесты guard-ов расчётного эндпоинта и parse_float.

Покрывает фиксы аудита 2026-07-02:
- None-курс от биржи → 503 (а не 500 через TypeError);
- слишком малая сумма → 400 floor-guard (а не ZeroDivisionError/бессмыслица);
- parse_float: '', запятая, None не роняют ручки.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_calculate_guards.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import app as flask_app, parse_float


@pytest.fixture
def pub():
    """Публичный клиент: /api/calculate не требует авторизации."""
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as c:
        yield c


def _mock_rates(usdt_thb, rub_usdt):
    async def _f():
        return {'usdt_thb': usdt_thb, 'rub_usdt': rub_usdt}
    return _f


class TestNoneRateGuard:
    """Недоступность биржи → 503, а не 500."""

    def test_usdt_thb_none_returns_503(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates(None, 92.5))
        resp = pub.post('/api/calculate', json={
            'scenario': 'usdt-to-thb', 'direction': 'amount', 'amount': 1000, 'profit_margin': 4.0
        })
        assert resp.status_code == 503

    def test_rub_usdt_none_returns_503(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates(34.5, None))
        resp = pub.post('/api/calculate', json={
            'scenario': 'rub-to-thb', 'direction': 'amount', 'amount': 100000, 'profit_margin': 3.0
        })
        assert resp.status_code == 503


class TestFloorGuard:
    """Слишком малая сумма → 400, без ZeroDivisionError."""

    def test_tiny_amount_returns_400(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates(34.5, 92.5))
        resp = pub.post('/api/calculate', json={
            'scenario': 'thb-to-usdt', 'direction': 'amount', 'amount': 33, 'profit_margin': 3.0
        })
        assert resp.status_code == 400

    def test_normal_amount_ok(self, pub, monkeypatch):
        monkeypatch.setattr(appmod.ExchangeRateProvider, 'get_all_rates', _mock_rates(34.5, 92.5))
        resp = pub.post('/api/calculate', json={
            'scenario': 'usdt-to-thb', 'direction': 'amount', 'amount': 1000, 'profit_margin': 4.0
        })
        assert resp.status_code == 200
        assert resp.get_json().get('final_rate', 0) > 0


class TestParseFloat:
    def test_empty_and_none(self):
        assert parse_float('') == 0.0
        assert parse_float(None) == 0.0
        assert parse_float('   ') == 0.0

    def test_comma_separator(self):
        assert parse_float('1,5') == 1.5
        assert parse_float('1 500,25') == 1500.25

    def test_plain_number(self):
        assert parse_float('42.5') == 42.5
        assert parse_float(42.5) == 42.5

    def test_garbage_returns_default(self):
        assert parse_float('abc') == 0.0
        assert parse_float('abc', default=7.0) == 7.0
