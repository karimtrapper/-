"""Совместимость сетевой сверки: прежнее поведение с адресным получателем не меняется.

Хеш с несколькими получателями USDT, среди которых ожидаемый кошелёк, засчитывает
ТОЛЬКО сумму ожидаемого кошелька (как до изменений). Наблюдение «кто получатель»
включается только явным observe_recipient и не ослабляет сверку исходящих.
Проверяется настоящий разбор ответа сети, а не подмена результата verify_transfer.
"""
import pytest

import app as m
import stand_egress
from stand_transfers import verify_transfer, TRON_USDT
from tests.qa_wallet_roles_helpers import make_user, client_for, put_board, board
from tests.test_wallet_roles_qa import REALTY, EXCHANGE, seeded, stand  # noqa: F401

OTHER = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
SENDER = 'TVmgzMQ2zwV2DVPscBf98WRRdhrcpf5x5p'
REF = 'ab' * 32
TS = 1700000001000


class Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def payload(outputs):
    return {'hash': REF, 'confirmed': True, 'contractRet': 'SUCCESS', 'revert': False,
            'timestamp': TS, 'trc20TransferInfo': [
                {'contract_address': TRON_USDT, 'from_address': SENDER, 'to_address': to,
                 'amount_str': str(int(amount * 1_000_000)), 'decimals': 6}
                for to, amount in outputs]}


def verify(outputs, receiver, sender=None, amount=None, **kw):
    return verify_transfer(REF, 'trc20', sender, receiver, amount,
                           get=lambda *a, **k: Resp(payload(outputs)), **kw)


def test_targeted_verification_credits_only_expected_wallet_sum():
    r = verify([(REALTY, 60), (OTHER, 40)], REALTY)
    assert r['status'] == 'confirmed' and r['verifiedAmount'] == 60
    assert r['to'] == REALTY
    r = verify([(REALTY, 60), (OTHER, 40)], OTHER)
    assert r['verifiedAmount'] == 40 and r['to'] == OTHER


def test_targeted_verification_with_sender_and_amount_unchanged():
    r = verify([(REALTY, 60), (OTHER, 40)], REALTY, sender=SENDER, amount=60)
    assert r['status'] == 'confirmed' and r['verifiedAmount'] == 60
    r = verify([(REALTY, 60), (OTHER, 40)], REALTY, sender=SENDER, amount=100)
    assert r['status'] == 'mismatch'      # сумма считается только по ожидаемому получателю


def test_targeted_verification_without_expected_recipient_in_outputs_is_mismatch():
    r = verify([(OTHER, 100)], REALTY)
    assert r['status'] == 'mismatch'


def test_missing_receiver_is_rejected_unless_observation_is_explicit():
    assert verify([(REALTY, 100)], None)['status'] == 'mismatch'
    assert verify([(REALTY, 100)], None, observe_recipient=False)['status'] == 'mismatch'
    # исходящие всегда с известным отправителем и суммой: наблюдение там запрещено
    assert verify([(REALTY, 100)], None, sender=SENDER, amount=100,
                  observe_recipient=True)['status'] == 'mismatch'
    assert verify([(REALTY, 100)], None, amount=100, observe_recipient=True)['status'] == 'mismatch'


def test_observation_reports_single_actual_recipient():
    r = verify([(OTHER, 100)], None, observe_recipient=True)
    assert r['status'] == 'confirmed' and r['to'] == OTHER and r['verifiedAmount'] == 100


@pytest.fixture
def tron_chain(monkeypatch):
    """Подменяется только сеть: настоящий verify_transfer разбирает этот ответ."""
    monkeypatch.setenv('STAND_MODE', '1')
    box = {'outputs': []}

    def read(operation, params):
        assert operation == 'tron_tx_info', operation
        return 200, payload(box['outputs']), None
    monkeypatch.setattr(stand_egress, 'read_get', read)
    return box


def crypto_board(wallet_address):
    wid = m.get_session().query(m.Wallet).filter_by(address=wallet_address).one().id
    m.get_session().close()
    put_board({'deals': [{'id': 7, 'payType': 'Крипта', 'step': 's14', 'walletId': wid,
                          'type': 'Оплата недвижимости', 'kind': 'Лизхолд', 'payinHashes': [],
                          'log': [{'at': 1700000000000, 'text': 'заведена'}]}],
               'convs': [], 'wallets': []})


def test_payin_endpoint_multi_output_credits_only_expected_wallet(seeded, tron_chain):
    crypto_board(REALTY)
    tron_chain['outputs'] = [(REALTY, 60), (OTHER, 40)]
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                               json={'dealId': 7, 'hash': REF})
    assert r.status_code == 200, r.get_json()
    deal = board()[0]['deals'][0]
    assert [(h['amount'], h['to']) for h in deal['payinHashes']] == [(60.0, REALTY)]
    assert not deal.get('recipientWarnings')


def test_payin_endpoint_all_outputs_elsewhere_is_warning_not_credit(seeded, tron_chain):
    crypto_board(REALTY)
    tron_chain['outputs'] = [(EXCHANGE, 100)]
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                               json={'dealId': 7, 'hash': REF})
    assert r.status_code == 409 and r.get_json()['warning']['actual'] == EXCHANGE
    assert board()[0]['deals'][0]['payinHashes'] == []


def test_payin_endpoint_ambiguous_wrong_recipients_neither_credited_nor_guessed(seeded, tron_chain):
    crypto_board(REALTY)
    tron_chain['outputs'] = [(EXCHANGE, 50), (OTHER, 50)]
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                               json={'dealId': 7, 'hash': REF})
    assert r.status_code in (409, 422), r.get_json()
    deal = board()[0]['deals'][0]
    assert deal['payinHashes'] == []
    assert not any(w.get('actual') in (EXCHANGE, OTHER) and w.get('acknowledgedById')
                   for w in deal.get('recipientWarnings') or [])


def test_payin_endpoint_expected_among_many_with_wrong_extra_has_no_warning(seeded, tron_chain):
    crypto_board(REALTY)
    tron_chain['outputs'] = [(OTHER, 30), (REALTY, 70), (EXCHANGE, 5)]
    r = client_for(make_user('operator')).post('/api/stand/payin/check',
                                               json={'dealId': 7, 'hash': REF})
    assert r.status_code == 200, r.get_json()
    deal = board()[0]['deals'][0]
    assert deal['payinHashes'][0]['amount'] == 70.0 and not deal.get('recipientWarnings')
