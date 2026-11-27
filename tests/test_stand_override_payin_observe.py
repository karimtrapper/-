"""Ручной перенос: приход по одному hash. Настоящий stand_transfers.verify_transfer,
подменён только транспорт get (синтетический ответ TronScan, без сети)."""
import secrets

import pytest

import app as m
from stand_transfers import verify_transfer as real_verify, TRON_USDT

B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def _tron_address():
    """Уникальный валидный TRON-адрес: настоящие адреса уже посеяны другими тестами."""
    return 'T' + ''.join(secrets.choice(B58) for _ in range(33))


OURS, OTHER, PAYER = _tron_address(), _tron_address(), _tron_address()


class Response:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def native(tx, outputs, confirmed=True):
    data = {'hash': tx, 'confirmed': confirmed, 'contractRet': 'SUCCESS', 'revert': False,
            'timestamp': 1700000001000, 'trc20TransferInfo': [
                {'contract_address': TRON_USDT, 'from_address': frm, 'to_address': to,
                 'amount_str': str(int(amount * 1_000_000)), 'decimals': 6}
                for frm, to, amount in outputs]}
    return lambda *a, **k: real_verify(*a, get=lambda *x, **y: Response(data), **k)


def check(tx, outputs, sender=None, receiver=None, amount=None, confirmed=True):
    verify = m._stand_override_payin_verify(native(tx, outputs, confirmed))
    return verify(tx, 'trc20', sender, receiver, amount)


def test_hash_only_is_read_from_network_with_addresses_and_amount():
    tx = secrets.token_hex(32)
    result = check(tx, [(PAYER, OURS, 100)])
    assert result['status'] == 'confirmed' and result['from'] == PAYER and result['to'] == OURS
    assert result['verifiedAmount'] == 100


def test_ui_pool_shape_with_amount_but_no_addresses_works_within_one_cent():
    tx = secrets.token_hex(32)
    assert check(tx, [(PAYER, OURS, 100)], amount=100)['status'] == 'confirmed'
    assert check(tx, [(PAYER, OURS, 100)], amount=100.005)['status'] == 'confirmed'
    assert check(tx, [(PAYER, OURS, 100)], amount=100.5)['status'] == 'mismatch'


def test_explicit_addresses_are_checked_against_what_network_saw():
    tx = secrets.token_hex(32)
    chain = [(PAYER, OURS, 100)]
    assert check(tx, chain, sender=PAYER, receiver=OURS, amount=100)['status'] == 'confirmed'
    assert check(tx, chain, receiver=OURS, amount=100)['status'] == 'confirmed'
    assert check(tx, chain, sender=OTHER, receiver=OURS, amount=100)['status'] == 'mismatch'
    assert check(tx, chain, receiver=OTHER, amount=100)['status'] == 'mismatch'
    assert check(tx, chain, sender=OTHER)['status'] == 'mismatch'


def test_pending_and_multiple_recipients_are_not_accepted():
    tx = secrets.token_hex(32)
    assert check(tx, [(PAYER, OURS, 100)], confirmed=False)['status'] == 'pending'
    assert check(tx, [(PAYER, OURS, 50), (PAYER, OTHER, 50)])['status'] == 'mismatch'


@pytest.fixture
def registry():
    db = m.get_session()
    rows = {}
    try:
        for name, address, kwargs in (('ours', OURS, {}), ('inactive', PAYER, {'active': False}),
                                      ('no_payin', OTHER, {'accepts_payin': False})):
            row = m.Wallet(address=address, blockchain='TRON', label='test-payin-fixture',
                           active=kwargs.get('active', True),
                           accepts_payin=kwargs.get('accepts_payin', True), is_monitored=False)
            db.add(row)
            rows[name] = row
        db.commit()
        for row in rows.values():
            db.refresh(row)
        yield db, rows
    finally:
        db.close()


def entry(to):
    return [{'hash': secrets.token_hex(32), 'network': 'TRC20', 'to': to, 'amount': 100}]


def test_receiver_must_be_our_active_payin_wallet(registry):
    db, rows = registry
    deal = {}
    assert m._stand_payin_wallet_problem(db, deal, entry(OURS)) is None
    # TRON-адреса чувствительны к регистру
    assert m._stand_payin_wallet_problem(db, deal, entry(OURS.lower())) == 'payin_wallet_not_registered'
    assert m._stand_payin_wallet_problem(db, deal, entry(PAYER)) == 'payin_wallet_not_registered'
    assert m._stand_payin_wallet_problem(db, deal, entry(OTHER)) == 'payin_wallet_not_registered'
    assert m._stand_payin_wallet_problem(db, deal, entry('T' + '1' * 33)) == 'payin_wallet_not_registered'
    assert m._stand_payin_wallet_problem(db, deal, entry(None)) == 'payin_receiver_unknown'


def test_selected_wallet_on_the_deal_must_be_the_receiver(registry):
    db, rows = registry
    other = m.Wallet(address='T' + 'B' * 33, blockchain='TRON', label='test-payin-fixture',
                     active=True, accepts_payin=True, is_monitored=False)
    db.add(other)
    db.commit()
    assert m._stand_payin_wallet_problem(db, {'walletId': rows['ours'].id}, entry(OURS)) is None
    assert m._stand_payin_wallet_problem(
        db, {'walletId': other.id}, entry(OURS)) == 'payin_wallet_mismatch'


def test_bad_selected_wallet_blocks_instead_of_becoming_no_selection(registry):
    db, rows = registry
    for bad in ('ghost', rows['inactive'].id, rows['no_payin'].id, 999999):
        assert m._stand_payin_wallet_problem(
            db, {'walletId': bad}, entry(OURS)) == 'payin_selected_wallet_invalid', bad


def test_custom_wallet_keeps_explicit_address_and_still_needs_registry(registry):
    db, rows = registry
    custom = lambda addr, net='TRC-20': {'walletId': 'custom', 'payinCustom': {'network': net, 'addr': addr}}
    assert m._stand_payin_wallet_problem(db, custom(OURS), entry(OURS)) is None
    assert m._stand_payin_wallet_problem(db, custom(OTHER), entry(OURS)) == 'payin_wallet_mismatch'
    assert m._stand_payin_wallet_problem(db, custom(OURS, 'ERC-20'), entry(OURS)) == 'payin_wallet_mismatch'
    # адрес совпал со своим, но в реестре его нет — не принимаем
    assert m._stand_payin_wallet_problem(db, custom(PAYER), entry(PAYER)) == 'payin_wallet_not_registered'
    assert m._stand_payin_wallet_problem(
        db, {'walletId': 'custom', 'payinCustom': {}}, entry(OURS)) == 'payin_selected_wallet_invalid'


def test_amount_mismatch_has_its_own_code_through_the_hash_helper():
    tx = secrets.token_hex(32)
    verify = m._stand_override_payin_verify(native(tx, [(PAYER, OURS, 100)]))
    entries, error = m._stand_manual_close_verify_hashes(
        {}, [{'hash': tx, 'network': 'trc20', 'amount': 90}], 90, verify, set(), 'payin')
    assert entries is None and error == 'payin_amount_mismatch'
    entries, error = m._stand_manual_close_verify_hashes(
        {}, [{'hash': tx, 'network': 'trc20'}], 100, verify, set(), 'payin')
    assert error is None and entries[0]['to'] == OURS and entries[0]['from'] == PAYER


@pytest.mark.parametrize('bad', [0, -5, '0', 'abc'])
def test_explicit_non_positive_amount_is_rejected_not_treated_as_missing(bad):
    tx = secrets.token_hex(32)
    result = check(tx, [(PAYER, OURS, 100)], amount=bad)
    assert result['status'] == 'mismatch', bad
    assert check(tx, [(PAYER, OURS, 100)], amount=None)['status'] == 'confirmed'
