"""Независимые фикстуры QA для сетевого адаптера; внешних запросов нет."""

import pytest

from stand_transfers import ETH_TRANSFER_TOPIC, ETH_USDT, verify_transfer


SENDER = '0x' + '1' * 40
RECIPIENT = '0x' + '2' * 40
FOREIGN = '0x' + '3' * 40
HASH = '0x' + 'a' * 64


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def receipt(recipient=RECIPIENT, amount=600_000_000, status='0x1'):
    return {'transactionHash': HASH, 'status': status, 'blockNumber': '0x10', 'logs': [{
        'address': ETH_USDT, 'topics': [ETH_TRANSFER_TOPIC,
                                        '0x' + '0' * 24 + SENDER[2:],
                                        '0x' + '0' * 24 + recipient[2:]],
        'data': hex(amount),
    }]}


def mocked_get(result):
    calls = []

    def get(_url, *, params, timeout):
        calls.append((params['action'], timeout))
        if params['action'] == 'eth_getTransactionReceipt':
            return Response({'result': result})
        return Response({'result': {'timestamp': '0x6553f100'}})

    return get, calls


@pytest.mark.parametrize(('chain_receipt', 'expected'), [
    (receipt(), 'confirmed'),
    (receipt(recipient=FOREIGN), 'mismatch'),
    (receipt(amount=599_000_000), 'mismatch'),
    (receipt(status='0x0'), 'failed'),
    (None, 'pending'),
])
def test_erc20_requires_success_recipient_amount_and_receipt(chain_receipt, expected):
    get, calls = mocked_get(chain_receipt)
    result = verify_transfer(HASH, 'ERC-20', SENDER, RECIPIENT, 600,
                             get=get, etherscan_key='fixture-key')
    assert result['status'] == expected
    assert calls[0][0] == 'eth_getTransactionReceipt'
    if expected == 'confirmed':
        assert result['verifiedAmount'] == 600
        assert result['to'] == RECIPIENT


def test_invalid_explorer_link_never_calls_network():
    calls = []

    def get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError('Сеть не должна вызываться')

    result = verify_transfer('https://foreign.example/tx/' + HASH, 'ERC-20',
                             SENDER, RECIPIENT, 600, get=get, etherscan_key='fixture-key')
    assert result['status'] == 'mismatch'
    assert calls == []
