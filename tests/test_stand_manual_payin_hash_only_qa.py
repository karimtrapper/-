"""Независимая QA: manualOverride принимает приход USDT по одному hash, получатель — наш активный
кошелёк из реестра. Настоящий `stand_transfers.verify_transfer` + фейковый `get` (ответ TronScan),
без внешней сети; свой реестр кошельков, всё созданное чистится autouse-fixture ядра QA.

СД-1489-like аренда: приход наличными, расход THB банком 455000 с чеком менеджера."""
import json
import secrets

import pytest

import app as m
import stand_transfers
from tests.test_stand_crm_close_atomic import _client, _counts
from tests.test_payout_receipt_independent_qa import (  # noqa: F401  (fixture подключается по имени)
    CRM, _qa_cleanup_created_rows, override, rental_board, upload)

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
AMOUNT = 14500


def tron_address():
    return 'T' + ''.join(secrets.choice(B58) for _ in range(33))


def make_wallet(active=True):
    """Свой реестр: уникальный TRON-адрес; active=False — кошелёк в реестре, но выведен из работы."""
    address = tron_address()
    db = m.get_session()
    try:
        db.add(m.Wallet(address=address, blockchain='TRON', label='qa-payin', active=active,
                        accepts_payin=active, is_monitored=False))
        db.commit()
    finally:
        db.close()
    return address


class FakeResponse:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def tronscan(tx_hash, transfers, *, confirmed=True):
    """Ответ TronScan transaction-info: transfers = [(from, to, usdt), ...]."""
    return {'hash': tx_hash, 'confirmed': confirmed, 'contractRet': 'SUCCESS' if confirmed else None,
            'revert': False, 'timestamp': 1760950000000,
            'trc20TransferInfo': [{
                'contract_address': stand_transfers.TRON_USDT, 'from_address': src, 'to_address': dst,
                'amount_str': str(int(round(usdt * 1_000_000))), 'decimals': 6, 'type': 'Transfer', 'status': 0}
                for src, dst, usdt in transfers]}


def install_native_verifier(monkeypatch, chain):
    """Настоящий verify_transfer; сеть подменена фейковым `get`. Вызовы пишутся в calls."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        return FakeResponse(chain)

    monkeypatch.setattr(stand_transfers, '_stand_get', fake_get)

    def native(ref, network, sender, receiver, amount, **kw):
        kw.pop('get', None)
        return stand_transfers.verify_transfer(ref, network, sender, receiver, amount, get=fake_get, **kw)

    monkeypatch.setattr(m, 'verify_transfer', native)
    return calls


def board_snapshot():
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        return row.version, row.data
    finally:
        db.close()


def submit(client, tx_hash, payin_hash_entry):
    ov = override()
    ov['payin'] = {'method': 'Наличные', 'amountRub': 1217600, 'amountUsdt': AMOUNT, 'hashes': [payin_hash_entry]}
    crm = {**CRM, 'payin_tx_hashes': [{'hash': tx_hash, 'network': 'trc20', 'amount_usdt': AMOUNT}]}
    version = client.get('/api/stand/state').json['version']
    return client.post('/api/stand/deals/1474/crm-close',
                       json={'version': version, 'crm': crm, 'manualOverride': ov})


CASES = ['ok-raw-hash-only', 'ok-pool-shape-empty-strings', 'ok-explicit-correct-sender-receiver',
         'wrong-registered-recipient-inactive', 'foreign-recipient-not-in-registry',
         'explicit-sender-mismatch', 'explicit-receiver-mismatch-other-registered-wallet',
         'amount-mismatch', 'pending-not-confirmed', 'multiple-recipients']


@pytest.mark.parametrize('case', CASES)
def test_manual_override_payin_hash_only_registered_recipient(monkeypatch, case):
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200           # чек выплаты bank остаётся обязательным
    tx = secrets.token_hex(32)
    ours, other_ours = make_wallet(), make_wallet()
    inactive, foreign, payer = make_wallet(active=False), tron_address(), tron_address()
    entry = {'hash': tx, 'network': 'trc20'}                        # «raw»: только hash и сеть
    transfers, confirmed, ok = [(payer, ours, AMOUNT)], True, case.startswith('ok-')
    if case == 'ok-pool-shape-empty-strings':                       # так UI кладёт hash из пула
        entry.update(amount=AMOUNT, receiver='', sender='')
    elif case == 'ok-explicit-correct-sender-receiver':
        entry.update(amount=AMOUNT, receiver=ours, sender=payer)
    elif case == 'wrong-registered-recipient-inactive':
        transfers = [(payer, inactive, AMOUNT)]
    elif case == 'foreign-recipient-not-in-registry':
        transfers = [(payer, foreign, AMOUNT)]
    elif case == 'explicit-sender-mismatch':
        entry.update(amount=AMOUNT, receiver=ours, sender=tron_address())
    elif case == 'explicit-receiver-mismatch-other-registered-wallet':
        entry.update(amount=AMOUNT, receiver=other_ours, sender=payer)
    elif case == 'amount-mismatch':
        transfers = [(payer, ours, 100)]
    elif case == 'pending-not-confirmed':
        confirmed = False
    elif case == 'multiple-recipients':
        transfers = [(payer, ours, AMOUNT / 2), (payer, other_ours, AMOUNT / 2)]
    calls = install_native_verifier(monkeypatch, tronscan(tx, transfers, confirmed=confirmed))
    before, snap = _counts(), board_snapshot()
    r = submit(client, tx, entry)
    assert calls, 'настоящий верификатор не дошёл до сети (отказ ДО сети маскирует реальный контракт)'
    if ok:
        assert r.status_code == 201, r.json
        deal = r.json['data']['deals'][0]
        assert deal['closed'] is True
        saved = deal['payinHashes'][0]
        assert saved['hash'] == tx and saved['verified'] is True and saved['to'] == ours, saved
        assert saved['from'] == payer
        assert _counts() == (before[0] + 1, before[1] + 1)
        return
    expected = (422, 'payin_hash_unverified') if case == 'pending-not-confirmed' else None
    if case == 'amount-mismatch':
        expected = (422, 'payin_amount_mismatch')
    if expected:
        assert (r.status_code, r.json['error']) == expected, r.json
    else:
        # код ошибки реестра/получателя определяет реализация: важен отказ, не его имя
        assert r.status_code in (400, 409, 422) and r.json['success'] is False and r.json.get('error'), r.json
    assert _counts() == before
    assert board_snapshot() == snap, 'отказ изменил доску или версию'


def test_manual_override_payin_hash_only_operator_still_cannot_close(monkeypatch):
    """Роль operator закрывать по-прежнему не может, даже с идеальным hash."""
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    tx, ours, payer = secrets.token_hex(32), make_wallet(), tron_address()
    install_native_verifier(monkeypatch, tronscan(tx, [(payer, ours, AMOUNT)]))
    db = m.get_session()
    try:
        op = m.AdminUser(username='op-' + secrets.token_hex(4), role='operator', password_hash='unused')
        db.add(op)
        db.flush()
        op_id = op.id
        db.commit()
    finally:
        db.close()
    before = _counts()
    r = submit(_client(op_id), tx, {'hash': tx, 'network': 'trc20'})
    assert r.status_code == 403, r.json
    assert _counts() == before


# ---------- дополнительные независимые контракты: частичные ограничения, реестр, walletId, регистр TRON ----------
def make_wallet_flags(*, active, accepts_payin, address=None):
    address = address or tron_address()
    db = m.get_session()
    try:
        w = m.Wallet(address=address, blockchain='TRON', label='qa-payin', active=active,
                     accepts_payin=accepts_payin, is_monitored=False)
        db.add(w)
        db.commit()
        return address, w.id
    finally:
        db.close()


def select_wallet_on_deal(wallet_id):
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        state['deals'][0]['walletId'] = wallet_id
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
    finally:
        db.close()


def preview(client, tx, entry):
    """Предпросмотр /api/stand/manual-close/verify-hash — тот же контракт, что у закрытия."""
    r = client.post('/api/stand/manual-close/verify-hash', json={
        'dealId': 1474, 'direction': 'payin', 'network': 'trc20', 'hash': tx,
        'sender': entry.get('sender') or None, 'receiver': entry.get('receiver') or None,
        'amount': entry.get('amount')})
    return r


EXTRA_CASES = [
    ('ok-only-sender-given', True), ('ok-only-receiver-given', True),
    ('ok-deal-selected-wallet-matches', True),
    ('only-sender-given-mismatch', False), ('only-receiver-given-mismatch-other-ours', False),
    ('active-wallet-accepts-payin-false', False),
    ('deal-selected-wallet-is-another-ours', False), ('deal-selected-wallet-id-invalid', False),
    ('tron-explicit-receiver-case-changed', False), ('tron-registry-address-differs-by-case', False),
]


@pytest.mark.parametrize('case,ok', EXTRA_CASES)
def test_manual_override_payin_hash_only_partial_constraints_registry_and_case(monkeypatch, case, ok):
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    tx, payer = secrets.token_hex(32), tron_address()
    ours, ours_id = make_wallet_flags(active=True, accepts_payin=True)
    other_ours, other_id = make_wallet_flags(active=True, accepts_payin=True)
    chain_to = ours
    entry = {'hash': tx, 'network': 'trc20', 'amount': AMOUNT}
    if case == 'ok-only-sender-given':
        entry['sender'] = payer
    elif case == 'ok-only-receiver-given':
        entry['receiver'] = ours
    elif case == 'ok-deal-selected-wallet-matches':
        select_wallet_on_deal(ours_id)
    elif case == 'only-sender-given-mismatch':
        entry['sender'] = tron_address()
    elif case == 'only-receiver-given-mismatch-other-ours':
        entry['receiver'] = other_ours
    elif case == 'active-wallet-accepts-payin-false':
        chain_to, _ = make_wallet_flags(active=True, accepts_payin=False)
    elif case == 'deal-selected-wallet-is-another-ours':
        select_wallet_on_deal(other_id)
    elif case == 'deal-selected-wallet-id-invalid':
        select_wallet_on_deal(999999)
    elif case == 'tron-explicit-receiver-case-changed':
        entry['receiver'] = ours.swapcase()          # TRON base58 регистрозависим: это другой адрес
    elif case == 'tron-registry-address-differs-by-case':
        chain_to = tron_address()
        make_wallet_flags(active=True, accepts_payin=True, address=chain_to.swapcase())
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(payer, chain_to, AMOUNT)]))
    before, snap = _counts(), board_snapshot()
    shown = preview(client, tx, entry)              # предпросмотр и закрытие обязаны согласоваться
    assert calls, 'настоящий верификатор не дошёл до сети'
    assert (shown.status_code == 200 and shown.json['success'] is True) == ok, (shown.status_code, shown.json)
    assert board_snapshot() == snap, 'предпросмотр изменил доску'
    r = submit(client, tx, entry)
    if ok:
        assert r.status_code == 201, r.json
        saved = r.json['data']['deals'][0]['payinHashes'][0]
        assert saved['verified'] is True and saved['to'] == chain_to and saved['from'] == payer, saved
        assert _counts() == (before[0] + 1, before[1] + 1)
        return
    assert r.status_code in (400, 409, 422) and r.json['success'] is False and r.json.get('error'), r.json
    assert _counts() == before
    assert board_snapshot() == snap, 'отказ изменил доску или версию'


# ---------- кнопка «проверить hash» (preview) на настоящем верификаторе ----------
PREVIEW_CASES = [('ok-single-hash-only', True), ('foreign-receiver-by-network', False),
                 ('explicit-foreign-receiver', False), ('amount-mismatch', False),
                 ('pending-not-confirmed', False)]


@pytest.mark.parametrize('case,ok', PREVIEW_CASES)
def test_preview_verify_hash_native_single_hash_button(monkeypatch, case, ok):
    client = rental_board(monkeypatch)
    tx, payer = secrets.token_hex(32), tron_address()
    ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    entry, chain_to, confirmed, chain_amount = {'hash': tx}, ours, True, AMOUNT
    if case == 'foreign-receiver-by-network':
        chain_to = tron_address()
    elif case == 'explicit-foreign-receiver':
        entry['receiver'] = tron_address()
    elif case == 'amount-mismatch':
        entry['amount'], chain_amount = AMOUNT, 100
    elif case == 'pending-not-confirmed':
        confirmed = False
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(payer, chain_to, chain_amount)], confirmed=confirmed))
    snap = board_snapshot()
    r = preview(client, tx, entry)
    assert calls, 'настоящий верификатор не дошёл до сети'
    assert board_snapshot() == snap, 'предпросмотр ничего не пишет'
    if ok:
        assert r.status_code == 200 and r.json['success'] is True, r.json
        assert r.json['to'] == ours and r.json['from'] == payer and float(r.json['verifiedAmount']) == AMOUNT, r.json
    else:
        assert r.status_code == 422 and r.json['success'] is False and r.json.get('error'), (r.status_code, r.json)


# ---------- walletId='custom' + payinCustom: ограничение сохраняется, нужна реальная запись реестра ----------
CUSTOM_CASES = [('custom-addr-registered-and-matches-chain', True),
                ('custom-addr-not-in-registry', False),
                ('custom-addr-registered-but-chain-pays-other-ours', False),
                ('custom-addr-registered-but-inactive', False)]


@pytest.mark.parametrize('case,ok', CUSTOM_CASES)
def test_manual_override_payin_custom_wallet_keeps_registry_constraint(monkeypatch, case, ok):
    client = rental_board(monkeypatch)
    assert upload(client, extra=True).status_code == 200
    tx, payer = secrets.token_hex(32), tron_address()
    ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    other_ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    unregistered = tron_address()
    inactive, _ = make_wallet_flags(active=False, accepts_payin=True)
    custom_addr, chain_to = ours, ours
    if case == 'custom-addr-not-in-registry':
        custom_addr = chain_to = unregistered              # сеть платит ровно на «свой» адрес, но его нет в реестре
    elif case == 'custom-addr-registered-but-chain-pays-other-ours':
        chain_to = other_ours                              # выбранный кошелёк — ours, перевод ушёл на другой наш
    elif case == 'custom-addr-registered-but-inactive':
        custom_addr = chain_to = inactive
    select_wallet_on_deal('custom')
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        state['deals'][0]['payinCustom'] = {'network': 'TRC-20', 'addr': custom_addr}
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
    finally:
        db.close()
    entry = {'hash': tx, 'network': 'trc20'}
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(payer, chain_to, AMOUNT)]))
    before, snap = _counts(), board_snapshot()
    shown = preview(client, tx, entry)
    assert calls
    assert (shown.status_code == 200 and shown.json['success'] is True) == ok, (shown.status_code, shown.json)
    r = submit(client, tx, entry)
    if ok:
        assert r.status_code == 201, r.json
        assert _counts() == (before[0] + 1, before[1] + 1)
        return
    assert r.status_code in (400, 409, 422) and r.json['success'] is False and r.json.get('error'), r.json
    assert _counts() == before
    assert board_snapshot() == snap, 'отказ изменил доску или версию'
