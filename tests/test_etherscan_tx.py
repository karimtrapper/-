"""Проверка ERC-20 USDT через Etherscan API V2.

Регрессия для реальной Ethereum-транзакции 0x997ba2…: receipt содержит два
USDT Transfer одного отправителя — основной платёж 38 859,70 и отдельный
перевод 0,470111. В форме показываем основной, а потолок расхода хранит сумму.
"""
import pytest

import app as A
from app import (PayinTx, PayinTxUse, PayoutTx, PayoutTxUse,
                 TransactionVerificationError,
                 _etherscan_tx_info, _payin_tx_get_or_create,
                 _payout_tx_get_or_create, get_session)


TX_HASH = '0x997ba2b05e91560a958b7aa94e3f6c1298b5697fcab6765abedf2761320284fd'
SENDER = '68aea0f5386a57b48953f6fff2f22d29d00d9ba9'
MAIN_RECIPIENT = '52cfd61b4ae8a6de3d77bd013261de8e86944653'
FEE_RECIPIENT = '4337ff05c84b9a80ea0a78dbe7b8e102f66d4c08'


def _topic(address):
    return '0x' + ('0' * 24) + address


def _receipt(status='0x1', logs=None):
    if logs is None:
        logs = [
            {
                'address': A.USDT_ERC20_CONTRACT,
                'topics': [A.ERC20_TRANSFER_TOPIC, _topic(SENDER),
                           _topic(MAIN_RECIPIENT)],
                'data': '0x90c37f720',
            },
            {
                'address': A.USDT_ERC20_CONTRACT.upper(),
                'topics': [A.ERC20_TRANSFER_TOPIC, _topic(SENDER),
                           _topic(FEE_RECIPIENT)],
                'data': '0x72c5f',
            },
        ]
    return {'jsonrpc': '2.0', 'id': 1,
            'result': {'status': status, 'blockNumber': '0x18c5a04', 'logs': logs}}


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clean_ledgers():
    db = get_session()
    try:
        db.query(PayoutTxUse).delete()
        db.query(PayinTxUse).delete()
        db.query(PayoutTx).delete()
        db.query(PayinTx).delete()
        db.commit()
    finally:
        db.close()
    yield


def test_exact_etherscan_receipt_selects_main_and_total(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen.update({'url': url, **kwargs})
        return FakeResponse(_receipt())

    monkeypatch.setenv('ETHERSCAN_API_KEY', 'test-key')
    monkeypatch.setattr(A.requests, 'get', fake_get)
    info = _etherscan_tx_info(TX_HASH)

    assert seen['url'] == 'https://api.etherscan.io/v2/api'
    assert seen['params']['chainid'] == '1'
    assert seen['params']['action'] == 'eth_getTransactionReceipt'
    assert seen['params']['txhash'] == TX_HASH
    assert info['amount_usdt'] == 38859.7
    assert info['total_out_usdt'] == 38860.170111
    assert info['extra_out_usdt'] == 0.470111
    assert info['transfer_count'] == 2
    assert info['from_address'] == f'0x{SENDER}'
    assert info['to_address'] == f'0x{MAIN_RECIPIENT}'


def test_failed_or_non_usdt_receipt_is_rejected(monkeypatch):
    monkeypatch.setenv('ETHERSCAN_API_KEY', 'test-key')
    monkeypatch.setattr(A.requests, 'get', lambda *a, **k: FakeResponse(_receipt('0x0')))
    with pytest.raises(TransactionVerificationError, match='завершилась с ошибкой'):
        _etherscan_tx_info(TX_HASH)

    monkeypatch.setattr(A.requests, 'get', lambda *a, **k: FakeResponse(_receipt(logs=[])))
    with pytest.raises(TransactionVerificationError, match='USDT'):
        _etherscan_tx_info(TX_HASH)


def test_missing_key_keeps_manual_fallback(monkeypatch):
    monkeypatch.delenv('ETHERSCAN_API_KEY', raising=False)
    assert _etherscan_tx_info(TX_HASH) == {}

    db = get_session()
    try:
        tx = _payout_tx_get_or_create(
            db, TX_HASH, 1000, {'network': 'erc20', 'amount_usdt': 1000})
        assert tx.network == 'erc20'
        assert tx.source == 'manual'
        assert tx.amount_usdt == 1000
        assert 'не сверена' in tx.notes
    finally:
        db.rollback()
        db.close()


def test_erc_ledgers_use_verified_etherscan_amounts(monkeypatch):
    monkeypatch.setattr(A, '_etherscan_tx_info', lambda _hash: {
        'amount_usdt': 38859.7,
        'total_out_usdt': 38860.170111,
        'from_address': f'0x{SENDER}',
        'to_address': f'0x{MAIN_RECIPIENT}',
    })
    db = get_session()
    try:
        payin = _payin_tx_get_or_create(
            db, TX_HASH, 1000, {'network': 'erc20', 'amount_usdt': 1000})
        assert payin.source == 'etherscan'
        assert payin.amount_usdt == 38859.7
        assert payin.to_address == f'0x{MAIN_RECIPIENT}'
        db.rollback()

        payout = _payout_tx_get_or_create(
            db, TX_HASH, 1000, {'network': 'erc20', 'amount_usdt': 1000})
        assert payout.source == 'etherscan'
        assert payout.amount_usdt == 38860.170111
        assert payout.from_address == f'0x{SENDER}'
    finally:
        db.rollback()
        db.close()


def test_lookup_endpoint_reports_etherscan(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setenv('ETHERSCAN_API_KEY', 'test-key')
    monkeypatch.setattr(A, '_etherscan_tx_info', lambda _hash: {
        'amount_usdt': 38859.7,
        'total_out_usdt': 38860.170111,
        'from_address': f'0x{SENDER}',
        'to_address': f'0x{MAIN_RECIPIENT}',
    })
    with A.app.test_client() as client:
        response = client.get('/api/tx/lookup', query_string={
            'network': 'erc20', 'hash': TX_HASH})
    assert response.status_code == 200
    assert response.json['success'] is True
    assert response.json['source'] == 'etherscan'
    assert response.json['amount_usdt'] == 38859.7
