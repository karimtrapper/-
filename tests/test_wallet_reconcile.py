"""Сверка кошелька с блокчейном: что в сети было, а в CRM не отмечено.

Баланс кошелька в CRM складывается из операций, которые заводит человек.
Забыли отметить выдачу — CRM думает, что деньги на месте; пришёл приход,
которого никто не ждал, — он не виден вообще. Сверка ловит оба случая.

Запуск: cd Dev/CalcCRM && python -m pytest tests/test_wallet_reconcile.py -v
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['REESTR_SYNC_ENABLED'] = '0'

import pytest

import app as appmod
from app import (Wallet, WalletOperation, app as flask_app, get_session,
                 reconcile_wallet)

ADDR = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
OTHER = 'TNPLbPPHwJzSsbvoBqEn4zjUSyoNj1xohV'


def _ts(days_ago=0):
    return int((datetime.utcnow() - timedelta(days=days_ago)).timestamp() * 1000)


def _tx(hash_, type_, amount, days_ago=0):
    return {'tx_hash': hash_, 'type': type_, 'amount': amount, 'ts': _ts(days_ago),
            'date': None, 'counterparty': OTHER}


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(WalletOperation).delete()
        s.query(Wallet).delete()
        s.commit()
    finally:
        s.close()
    yield


@pytest.fixture
def wallet():
    """Кошелёк со стартовым остатком 1000, заведённым как операция."""
    s = get_session()
    w = Wallet(address=ADDR, label='Тестовый', is_balance=True,
               created_at=datetime.utcnow() - timedelta(days=30))
    s.add(w)
    s.commit()
    s.add(WalletOperation(wallet_id=w.id, type='income', amount=1000,
                          description='Начальный остаток'))
    s.commit()
    yield s, w
    s.close()


@pytest.fixture
def onchain(monkeypatch):
    """Подменяет баланс в сети: (usdt, trx)."""
    def _set(usdt):
        monkeypatch.setattr(appmod, '_tron_balances', lambda addr: (usdt, 5.0))
    return _set


class TestReconcile:
    def test_all_matched_by_hash(self, wallet, onchain):
        s, w = wallet
        s.add(WalletOperation(wallet_id=w.id, type='expense', amount=300,
                              tx_hash='AbC123', description='Сделка #1'))
        s.commit()
        onchain(700)
        r = reconcile_wallet(s, w, transfers=[_tx('abc123', 'expense', 300, days_ago=2)])
        assert r['ok'] and r['matched'] == 1
        assert r['unmatched'] == []
        assert r['crm_balance'] == 700 and r['onchain_balance'] == 700
        assert r['diff'] == 0

    def test_hash_match_is_case_insensitive(self, wallet, onchain):
        """TronScan отдаёт хэш в нижнем регистре, руками вставляют как придётся."""
        s, w = wallet
        s.add(WalletOperation(wallet_id=w.id, type='expense', amount=300, tx_hash='DEADBEEF'))
        s.commit()
        onchain(700)
        r = reconcile_wallet(s, w, transfers=[_tx('deadbeef', 'expense', 300)])
        assert r['matched'] == 1 and not r['unmatched']

    def test_unnoticed_income_is_flagged(self, wallet, onchain):
        """Пришли деньги, никто не завёл — главный кейс «алло, что за приход»."""
        s, w = wallet
        onchain(1500)
        r = reconcile_wallet(s, w, transfers=[_tx('newin', 'income', 500, days_ago=1)])
        assert len(r['unmatched']) == 1
        assert r['unmatched'][0]['type'] == 'income'
        assert r['unmatched_income'] == 500 and r['unmatched_expense'] == 0
        assert r['diff'] == 500, 'в сети денег больше, чем знает CRM'

    def test_unnoticed_expense_is_flagged(self, wallet, onchain):
        """Выдали и забыли отметить — CRM думает, что деньги на месте."""
        s, w = wallet
        onchain(600)
        r = reconcile_wallet(s, w, transfers=[_tx('newout', 'expense', 400)])
        assert r['unmatched_expense'] == 400 and r['unmatched_income'] == 0
        assert r['diff'] == -400

    def test_manual_operation_without_hash_matches_by_amount(self, wallet, onchain):
        """Операции заводят руками и без хэша — по сумме и типу они всё равно свои."""
        s, w = wallet
        s.add(WalletOperation(wallet_id=w.id, type='expense', amount=250,
                              description='выдача, хэш не вписали'))
        s.commit()
        onchain(750)
        r = reconcile_wallet(s, w, transfers=[_tx('h1', 'expense', 250)])
        assert r['matched'] == 1 and not r['unmatched']

    def test_one_loose_operation_covers_one_transfer(self, wallet, onchain):
        """Две одинаковые выдачи в сети, отмечена одна — вторая должна всплыть."""
        s, w = wallet
        s.add(WalletOperation(wallet_id=w.id, type='expense', amount=250))
        s.commit()
        onchain(500)
        r = reconcile_wallet(s, w, transfers=[_tx('h1', 'expense', 250),
                                              _tx('h2', 'expense', 250)])
        assert r['matched'] == 1 and len(r['unmatched']) == 1

    def test_type_must_agree(self, wallet, onchain):
        """Приход не закрывается расходом на ту же сумму."""
        s, w = wallet
        s.add(WalletOperation(wallet_id=w.id, type='expense', amount=250))
        s.commit()
        onchain(1250)
        r = reconcile_wallet(s, w, transfers=[_tx('h1', 'income', 250)])
        assert len(r['unmatched']) == 1 and r['unmatched'][0]['type'] == 'income'

    def test_tronscan_down_is_not_a_clean_bill(self, wallet, monkeypatch):
        """Сеть не ответила — говорим об этом, а не «неучтённых нет»."""
        s, w = wallet
        monkeypatch.setattr(appmod, '_tron_usdt_transfers', lambda *a, **kw: None)
        r = reconcile_wallet(s, w)
        assert r['ok'] is False and 'TronScan' in r['error']


class TestReconcileEndpoint:
    @pytest.fixture
    def cli(self, monkeypatch):
        flask_app.config['TESTING'] = True
        monkeypatch.setenv('LOCAL_NO_AUTH', '1')
        with flask_app.test_client() as c:
            yield c

    def test_endpoint_returns_unmatched(self, cli, wallet, onchain, monkeypatch):
        s, w = wallet
        onchain(1500)
        monkeypatch.setattr(appmod, '_tron_usdt_transfers',
                            lambda *a, **kw: [_tx('newin', 'income', 500)])
        r = cli.get(f'/api/wallets/{w.id}/reconcile')
        assert r.status_code == 200 and r.json['success']
        assert r.json['unmatched_income'] == 500

    def test_virtual_wallet_rejected(self, cli):
        s = get_session()
        try:
            w = Wallet(address='Binance основной', label='Виртуальный', is_balance=True)
            s.add(w); s.commit()
            wid = w.id
        finally:
            s.close()
        r = cli.get(f'/api/wallets/{wid}/reconcile')
        assert r.status_code == 400
        assert 'иртуальн' in r.json['error']

    def test_missing_wallet_404(self, cli):
        assert cli.get('/api/wallets/999999/reconcile').status_code == 404


class TestTronScanRetry:
    """429 у TronScan — штатная ситуация: по тому же IP стучится прогрев кэша."""

    class _R:
        def __init__(self, code, payload=None):
            self.status_code, self._p = code, payload or {}

        def json(self):
            return self._p

    def test_transfers_retry_on_429(self, monkeypatch):
        calls = []
        payload = {'token_transfers': [{
            'transaction_id': 'h1', 'from_address': ADDR, 'to_address': OTHER,
            'quant': '1000000', 'block_ts': _ts(1), 'finalResult': 'SUCCESS'}]}

        def fake_get(url, **kw):
            calls.append(url)
            return TestTronScanRetry._R(429) if len(calls) == 1 else TestTronScanRetry._R(200, payload)

        monkeypatch.setattr(appmod.requests, 'get', fake_get)
        monkeypatch.setattr(appmod.time, 'sleep', lambda *_: None)
        out = appmod._tron_usdt_transfers(ADDR, pages=1)
        assert len(calls) == 2, 'после 429 должен быть повтор'
        assert out and out[0]['type'] == 'expense' and out[0]['amount'] == 1.0

    def test_transfers_give_up_after_retries(self, monkeypatch):
        monkeypatch.setattr(appmod.requests, 'get', lambda url, **kw: TestTronScanRetry._R(429))
        monkeypatch.setattr(appmod.time, 'sleep', lambda *_: None)
        assert appmod._tron_usdt_transfers(ADDR, pages=1) is None

    def test_failed_transfer_is_ignored(self, monkeypatch):
        """Неудавшийся перевод денег не двигал — в сверку не берём."""
        payload = {'token_transfers': [{
            'transaction_id': 'bad', 'from_address': ADDR, 'to_address': OTHER,
            'quant': '5000000', 'block_ts': _ts(1), 'finalResult': 'FAILED'}]}
        monkeypatch.setattr(appmod.requests, 'get', lambda url, **kw: TestTronScanRetry._R(200, payload))
        assert appmod._tron_usdt_transfers(ADDR, pages=1) == []


class TestTruncation:
    def test_full_page_is_reported_as_truncated(self, wallet, onchain):
        """100 переводов = уперлись в лимит обхода, значит история неполная."""
        s, w = wallet
        onchain(1000)
        many = [_tx(f'h{i}', 'income', 1, days_ago=1) for i in range(appmod.TRON_RECONCILE_MAX_TRANSFERS)]
        r = reconcile_wallet(s, w, transfers=many)
        assert r['truncated'] is True

    def test_short_list_is_not_truncated(self, wallet, onchain):
        s, w = wallet
        onchain(1000)
        r = reconcile_wallet(s, w, transfers=[_tx('h1', 'income', 1)])
        assert r['truncated'] is False
