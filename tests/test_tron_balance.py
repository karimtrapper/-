"""Баланс адреса TRON для формы «Добавить кошелёк».

Менеджер вбивал начальный остаток руками — это лишний повод ошибиться, хотя
баланс USDT публичен. Эндпоинт отдаёт его по адресу ещё до создания кошелька.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_tron_balance.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import app as flask_app

ADDR = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'  # 34 символа, начинается с T


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    # эндпоинт под авторизацией — в тестах обходим гейт, как это делает локальный стенд
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with flask_app.test_client() as c:
        yield c


class _Resp:
    def __init__(self, payload, code=200):
        self._p, self.status_code = payload, code

    def json(self):
        return self._p


class TestTronBalanceEndpoint:
    def test_returns_usdt_and_trx(self, cli, monkeypatch):
        payload = {
            'address': ADDR,
            'balance': 12_500_000,  # 12.5 TRX в sun
            'trc20token_balances': [
                {'tokenId': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', 'balance': '1234560000'},
                {'tokenId': 'OTHER', 'balance': '999000000'},
            ],
        }
        monkeypatch.setattr(appmod.requests, 'get', lambda *a, **kw: _Resp(payload))
        resp = cli.get(f'/api/tronscan/balance/{ADDR}')
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['usdt_balance'] == 1234.56
        assert body['trx_balance'] == 12.5

    def test_zero_when_no_usdt_token(self, cli, monkeypatch):
        monkeypatch.setattr(appmod.requests, 'get',
                            lambda *a, **kw: _Resp({'address': ADDR, 'balance': 0,
                                                    'trc20token_balances': []}))
        body = cli.get(f'/api/tronscan/balance/{ADDR}').get_json()
        assert body['success'] is True
        assert body['usdt_balance'] == 0

    def test_rejects_non_tron_address(self, cli):
        """Виртуальный кошелёк («просто имя») в сеть не ходит."""
        resp = cli.get('/api/tronscan/balance/kassa-phuket')
        assert resp.status_code == 400
        assert resp.get_json()['success'] is False

    def test_unknown_address_reports_error(self, cli, monkeypatch):
        """Пустой ответ TronScan → 502, а не «баланс 0» (иначе учёт молча поедет)."""
        monkeypatch.setattr(appmod.requests, 'get', lambda *a, **kw: _Resp({}))
        resp = cli.get(f'/api/tronscan/balance/{ADDR}')
        assert resp.status_code == 502
        assert resp.get_json()['success'] is False

    def test_network_error_does_not_500(self, cli, monkeypatch):
        def _boom(*a, **kw):
            raise appmod.requests.exceptions.Timeout('timeout')
        monkeypatch.setattr(appmod.requests, 'get', _boom)
        resp = cli.get(f'/api/tronscan/balance/{ADDR}')
        assert resp.status_code == 502
