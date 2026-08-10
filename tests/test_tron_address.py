"""Адрес TRON: подменённые символы и контрольная сумма.

Живой кейс 10.08: в поле вставили `…pf5×5p` — знак умножения вместо латинской
`x` (автозамена «5x5» → «5×5»). Длина та же, начинается с T, поэтому старая
проверка пропускала, TronScan отвечал «не найден», и виноватым выглядел он.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_tron_address.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (Wallet, app as flask_app, get_session, normalize_tron_address,
                 tron_address_problem)

GOOD = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
WITH_TIMES = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5×5p'      # × вместо x — кейс 10.08


class TestNormalize:
    def test_multiplication_sign_becomes_x(self):
        addr, fixes = normalize_tron_address(WITH_TIMES)
        assert addr == GOOD
        assert fixes == [{'pos': 32, 'from': '×', 'to': 'x'}]

    def test_cyrillic_lookalikes(self):
        addr, fixes = normalize_tron_address('Т' + GOOD[1:])   # кириллическая Т
        assert addr == GOOD and fixes[0]['to'] == 'T'

    def test_spaces_are_stripped(self):
        addr, _ = normalize_tron_address(f'  {GOOD}  ')
        assert addr == GOOD

    def test_clean_address_untouched(self):
        addr, fixes = normalize_tron_address(GOOD)
        assert addr == GOOD and fixes == []


class TestProblem:
    def test_good_address_has_no_problem(self):
        assert tron_address_problem(GOOD) is None

    def test_typo_caught_by_checksum(self):
        """Один изменённый символ — длина та же, но контрольная сумма не сойдётся."""
        broken = GOOD[:-1] + ('q' if GOOD[-1] != 'q' else 'r')
        assert 'сумма' in tron_address_problem(broken)

    def test_foreign_symbol_named_with_position(self):
        p = tron_address_problem(WITH_TIMES)
        assert '×' in p and '32' in p

    def test_wrong_length(self):
        assert 'символ' in tron_address_problem(GOOD[:-2])

    def test_not_starting_with_t(self):
        assert tron_address_problem('X' + GOOD[1:]).startswith('Адрес TRON')

    def test_empty(self):
        assert 'введи адрес' in tron_address_problem('')


class TestEndpoints:
    @pytest.fixture
    def cli(self, monkeypatch):
        flask_app.config['TESTING'] = True
        monkeypatch.setenv('LOCAL_NO_AUTH', '1')
        with flask_app.test_client() as c:
            yield c

    @pytest.fixture(autouse=True)
    def clean(self):
        s = get_session()
        try:
            s.query(Wallet).delete(); s.commit()
        finally:
            s.close()
        yield

    def test_balance_repairs_address_and_reports_fix(self, cli, monkeypatch):
        monkeypatch.setattr(appmod, '_tron_balances', lambda a: (123.45, 1.0))
        r = cli.get(f'/api/tronscan/balance/{WITH_TIMES}')
        assert r.status_code == 200 and r.json['success']
        assert r.json['address'] == GOOD
        assert r.json['fixed'][0]['from'] == '×'
        assert r.json['usdt_balance'] == 123.45

    def test_balance_rejects_broken_checksum_without_network(self, cli, monkeypatch):
        def boom(_):
            raise AssertionError('в сеть ходить не должны — адрес заведомо кривой')
        monkeypatch.setattr(appmod, '_tron_balances', boom)
        broken = GOOD[:-1] + ('q' if GOOD[-1] != 'q' else 'r')
        r = cli.get(f'/api/tronscan/balance/{broken}')
        assert r.status_code == 400 and 'сумма' in r.json['error']

    def test_add_wallet_saves_repaired_address(self, cli):
        r = cli.post('/api/wallets', json={'address': WITH_TIMES, 'label': 'Тед',
                                           'is_balance': True, 'is_monitored': False})
        assert r.status_code == 200, r.json
        s = get_session()
        try:
            assert s.query(Wallet).filter(Wallet.address == GOOD).first() is not None
            assert s.query(Wallet).filter(Wallet.address == WITH_TIMES).first() is None
        finally:
            s.close()

    def test_add_wallet_rejects_bad_checksum(self, cli):
        broken = GOOD[:-1] + ('q' if GOOD[-1] != 'q' else 'r')
        r = cli.post('/api/wallets', json={'address': broken, 'label': 'кривой'})
        assert r.status_code == 400 and 'сумма' in r.json['error']

    def test_virtual_wallet_still_allowed(self, cli):
        """Имя вместо адреса — законный виртуальный кошелёк, не ломаем."""
        r = cli.post('/api/wallets', json={'address': 'Binance основной', 'label': 'вирт'})
        assert r.status_code == 200 and r.json['success']
