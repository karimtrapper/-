"""Независимая QA: legacy originMode=manual («Внести целиком») — приход USDT только по hash, сеть
наблюдает адреса и сумму, получатель — наш активный кошелёк реестра.

Настоящий `stand_transfers.verify_transfer` + фейковый `get` (TronScan), свой реестр кошельков,
никаких внешних сетей. После любого отказа: доска (сырой JSON), версия, Deal, StandCrmLink,
PayinTx/PayinTxUse и StandCloseEvidence не меняются. Повтор успешного закрытия — duplicate без
новой сверки по сети."""
import copy
import json
import secrets

import pytest

import app as m
from tests.test_stand_crm_close_atomic import _client, _manual_draft, _setup
from tests.test_payout_receipt_independent_qa import _qa_cleanup_created_rows  # noqa: F401
from tests.test_stand_manual_payin_hash_only_qa import (
    board_snapshot, install_native_verifier, make_wallet_flags, tron_address, tronscan)

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
AMOUNT = 100


def ledger_counts():
    db = m.get_session()
    try:
        return (db.query(m.Deal).count(), db.query(m.StandCrmLink).count(), db.query(m.PayinTx).count(),
                db.query(m.PayinTxUse).count(), db.query(m.StandCloseEvidence).count())
    finally:
        db.close()


def legacy_board(monkeypatch, entries, **deal_patch):
    uid = _setup(monkeypatch)
    deal = {'id': 1474, 'code': 'СД-1490', 'client': 'Synthetic Manual', 'type': 'Обмен валюты',
            'step': 'manual', 'closed': False, 'crmDealId': None, 'sentToClient': False, 'pay': {},
            'amountUsdt': AMOUNT, 'payout': {'usdt': 90}, 'files': {}, 'log': [], 'manual': True,
            'manualNew': False, 'isTask': False, 'originMode': 'manual', 'payType': 'Крипта',
            'payinHashes': entries}
    deal.update(deal_patch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [deal], 'notes': [], 'convs': []})
        row.version = 1
        db.commit()
    finally:
        db.close()
    for name, stub in (('_stand_deliver_notes', lambda: []), ('_stand_notify_deal_closed', lambda *_a: None),
                       ('_tx_info_by_network', lambda tx_hash, network: None),
                       ('_send_deal_telegram', lambda deal, sender=None: None)):
        monkeypatch.setattr(m, name, stub)
    return _client(uid)


def legacy_crm(tx, amount=AMOUNT, hash_amount=None):
    crm = {'deal_kind': 'exchange', 'client_name': 'Synthetic Manual', 'manager_name': 'Елизавета',
           'payin_method': 'crypto_direct', 'payin_amount_usdt': amount, 'payout_method': 'transfer',
           'payout_source': 'cash_batch', 'payout_amount_usdt': 90}
    if tx is not None:
        crm['payin_tx_hashes'] = [{'hash': tx, 'network': 'trc20',
                                   'amount_usdt': amount if hash_amount is None else hash_amount}]
    return crm


def close(client, crm):
    return client.post('/api/stand/deals/1474/crm-close', json={'version': 1, 'crm': crm})


CASES = [
    # (case, ok)
    ('ok-raw-hash-only-no-amount', True), ('ok-raw-with-board-amount', True),
    ('ok-explicit-from-and-to-strict', True), ('ok-only-from-given', True), ('ok-only-to-given', True),
    ('ok-deal-selected-wallet-matches', True),
    ('foreign-recipient-not-in-registry', False), ('inactive-registered-recipient', False),
    ('active-wallet-accepts-payin-false', False), ('only-from-mismatch', False),
    ('only-to-mismatch-other-registered-wallet', False), ('tron-to-case-changed', False),
    ('network-amount-differs-from-crm', False), ('board-amount-differs-from-network', False),
    ('crm-amount-within-tolerance-but-not-network-exact', False),
    ('pending-not-confirmed', False), ('multiple-recipients', False),
    ('deal-selected-wallet-is-another-ours', False), ('deal-selected-wallet-id-invalid', False),
    ('crm-hash-differs-from-board-hash', False), ('no-hash-at-all', False), ('empty-hash-string', False),
    ('invalid-hash-format', False), ('hash-of-another-deal', False),
]


@pytest.mark.parametrize('case,ok', CASES)
def test_legacy_manual_payin_native_contract(monkeypatch, case, ok):
    tx, payer = secrets.token_hex(32), tron_address()
    ours, ours_id = make_wallet_flags(active=True, accepts_payin=True)
    other_ours, other_id = make_wallet_flags(active=True, accepts_payin=True)
    entry = {'hash': tx, 'network': 'trc20'}                       # «raw»: UI пишет hash и сеть
    transfers, confirmed, crm_args, patch = [(payer, ours, AMOUNT)], True, {}, {}
    if case == 'ok-raw-with-board-amount':
        entry['amount'] = AMOUNT
    elif case == 'ok-explicit-from-and-to-strict':
        entry.update(amount=AMOUNT, **{'from': payer}, to=ours)
    elif case == 'ok-only-from-given':
        entry['from'] = payer
    elif case == 'ok-only-to-given':
        entry['to'] = ours
    elif case == 'foreign-recipient-not-in-registry':
        transfers = [(payer, tron_address(), AMOUNT)]
    elif case == 'inactive-registered-recipient':
        transfers = [(payer, make_wallet_flags(active=False, accepts_payin=True)[0], AMOUNT)]
    elif case == 'active-wallet-accepts-payin-false':
        transfers = [(payer, make_wallet_flags(active=True, accepts_payin=False)[0], AMOUNT)]
    elif case == 'only-from-mismatch':
        entry['from'] = tron_address()
    elif case == 'only-to-mismatch-other-registered-wallet':
        entry['to'] = other_ours
    elif case == 'tron-to-case-changed':
        entry['to'] = ours.swapcase()
    elif case == 'network-amount-differs-from-crm':
        transfers = [(payer, ours, 50)]
    elif case == 'board-amount-differs-from-network':
        entry['amount'], transfers = AMOUNT, [(payer, ours, 50)]
    elif case == 'crm-amount-within-tolerance-but-not-network-exact':
        crm_args = {'amount': 103}
    elif case == 'pending-not-confirmed':
        confirmed = False
    elif case == 'multiple-recipients':
        transfers = [(payer, ours, AMOUNT / 2), (payer, other_ours, AMOUNT / 2)]
    elif case == 'deal-selected-wallet-is-another-ours':
        patch['walletId'] = other_id
    elif case == 'deal-selected-wallet-id-invalid':
        patch['walletId'] = 999999
    elif case == 'ok-deal-selected-wallet-matches':
        patch['walletId'] = ours_id
    elif case == 'crm-hash-differs-from-board-hash':
        crm_args = {'tx': secrets.token_hex(32)}
    elif case == 'no-hash-at-all':
        entry = None
    elif case == 'empty-hash-string':
        entry = {'hash': '', 'network': 'trc20'}
    elif case == 'invalid-hash-format':
        entry = {'hash': 'not-a-hash', 'network': 'trc20'}
    client = legacy_board(monkeypatch, [entry] if entry else [], **patch)
    if case == 'hash-of-another-deal':
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            state = json.loads(row.data)
            state['deals'].insert(0, {'id': 1, 'payinHashes': [{'hash': tx, 'network': 'TRC20', 'amount': AMOUNT}]})
            row.data = json.dumps(state)
            db.commit()
        finally:
            db.close()
    calls = install_native_verifier(monkeypatch, tronscan(tx, transfers, confirmed=confirmed))
    crm_tx = crm_args.get('tx', None if case == 'no-hash-at-all' else (entry or {}).get('hash', tx))
    if case in ('empty-hash-string', 'invalid-hash-format'):
        crm_tx = entry['hash']
    crm = legacy_crm(crm_tx, amount=crm_args.get('amount', AMOUNT))
    before, snap = ledger_counts(), board_snapshot()
    r = close(client, crm)
    if ok:
        assert calls, 'настоящий верификатор не дошёл до сети'
        assert r.status_code == 201, r.json
        saved = r.json['data']['deals'][0]['payinHashes'][0]
        assert saved['verified'] is True and saved['from'] == payer and float(saved['amount']) == AMOUNT, saved
        assert saved.get('verifiedAt')
        after = ledger_counts()
        assert (after[0], after[1]) == (before[0] + 1, before[1] + 1)
        return
    expected = {'pending-not-confirmed': (422, 'payin_hash_unverified'),
                'network-amount-differs-from-crm': (422, 'payin_amount_mismatch'),
                'board-amount-differs-from-network': (422, 'payin_amount_mismatch'),
                'hash-of-another-deal': (422, 'payin_hash_already_used'),
                'crm-hash-differs-from-board-hash': (409, 'payin_facts_mismatch'),
                'no-hash-at-all': (400, 'payin_hash_required'),
                'invalid-hash-format': (400, 'payin_hash_invalid')}.get(case)
    if expected:
        assert (r.status_code, r.json['error']) == expected, r.json
    else:
        assert r.status_code in (400, 409, 422) and r.json['success'] is False and r.json.get('error'), r.json
    assert ledger_counts() == before, 'отказ изменил Deal/CrmLink/PayinTx/PayinTxUse/evidence'
    assert board_snapshot() == snap, 'отказ изменил доску или версию'


def test_legacy_manual_payin_retry_is_duplicate_without_new_network_check(monkeypatch):
    tx, payer = secrets.token_hex(32), tron_address()
    ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    client = legacy_board(monkeypatch, [{'hash': tx, 'network': 'trc20'}])
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(payer, ours, AMOUNT)]))
    before = ledger_counts()
    first = close(client, legacy_crm(tx))
    assert first.status_code == 201, first.json
    network_calls, after_first = len(calls), ledger_counts()
    again = close(client, legacy_crm(tx))
    assert again.status_code == 200 and again.json['duplicate'] is True, again.json
    assert again.json['deal']['id'] == first.json['deal']['id']
    assert len(calls) == network_calls, 'повтор не должен снова ходить в сеть'
    assert ledger_counts() == after_first
    assert (after_first[0], after_first[1]) == (before[0] + 1, before[1] + 1)


def test_legacy_manual_payin_rejection_after_valid_hash_does_not_persist_writeback(monkeypatch):
    """Hash сверен и записан бы на доску, но дальше CRM расходится (сумма выплаты) → ничего не сохранено."""
    tx, payer = secrets.token_hex(32), tron_address()
    ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    client = legacy_board(monkeypatch, [{'hash': tx, 'network': 'trc20'}])
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(payer, ours, AMOUNT)]))
    crm = legacy_crm(tx)
    crm['payout_amount_usdt'] = 999                      # не сойдётся с доской позже, чем сверка hash
    before, snap = ledger_counts(), board_snapshot()
    r = close(client, crm)
    assert calls, 'сеть опрошена до отказа'
    assert r.status_code in (400, 409, 422) and r.json['success'] is False, r.json
    assert ledger_counts() == before and board_snapshot() == snap, 'writeback verified/amount не должен сохраняться'
    saved = json.loads(board_snapshot()[1])['deals'][0]['payinHashes'][0]
    assert 'verified' not in saved and 'from' not in saved


# ---------- legacy ФРИХОЛД: verified ставит только сеть ----------
FREEHOLD_CRM = {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24', 'payin_method': 'crypto_direct',
                'payin_amount_usdt': 39533.77, 'invoice_amount_usd': 39010.91, 'transfer_fee_percent': .8,
                'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 39373,
                'doc_invoice_url': 'https://docs.invalid/invoice', 'doc_contract_url': 'https://docs.invalid/contract',
                'doc_payment_url': 'https://docs.invalid/payment'}


@pytest.mark.parametrize('case', ['raw-hash-no-verified-closes', 'verified-flag-but-network-pending',
                                  'payer-wallet-differs-from-network-sender',
                                  'forged-board-from-network-gives-no-sender'])
def test_legacy_freehold_payin_verified_only_by_network(monkeypatch, case):
    uid, _ = _manual_draft(monkeypatch, 'Фрихолд')
    for name, stub in (('_stand_deliver_notes', lambda: []), ('_stand_notify_deal_closed', lambda *_a: None),
                       ('_tx_info_by_network', lambda tx_hash, network: None),
                       ('_send_deal_telegram', lambda deal, sender=None: None)):
        monkeypatch.setattr(m, name, stub)
    tx, amount = secrets.token_hex(32), 39533.77
    payer, other = tron_address(), tron_address()
    ours, _ = make_wallet_flags(active=True, accepts_payin=True)
    entry = {'hash': tx, 'network': 'trc20', 'amount': amount}
    src, confirmed = payer, True
    if case == 'verified-flag-but-network-pending':
        entry.update(verified=True, verifiedAt='2026-10-18T12:00:00Z', **{'from': payer})
        confirmed = False
    elif case == 'payer-wallet-differs-from-network-sender':
        src = other
    elif case == 'forged-board-from-network-gives-no-sender':
        entry['from'] = payer
        src = None
    calls = install_native_verifier(monkeypatch, tronscan(tx, [(src, ours, amount)], confirmed=confirmed))
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        state['deals'][0].update(payType='Крипта', payerWallet=payer, payinHashes=[entry])
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
        version = row.version
    finally:
        db.close()
    crm = copy.deepcopy(FREEHOLD_CRM)
    crm['payin_tx_hashes'] = [{'hash': tx, 'network': 'trc20', 'amount_usdt': amount}]
    before, snap = ledger_counts(), board_snapshot()
    r = _client(uid).post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert calls, 'сеть не опрашивалась'
    if case == 'raw-hash-no-verified-closes':
        assert r.status_code == 201, r.json
        saved = r.json['data']['deals'][0]['payinHashes'][0]
        assert saved['verified'] is True and saved['from'] == payer and saved.get('verifiedAt'), saved
        return
    # введённый менеджером from, который сеть не подтвердила (или pending), отказывает уже при сверке hash;
    # расхождение payerWallet с сетевым отправителем ловит правило фрихолда.
    expected = ((422, 'payin_hash_unverified')
                if case in ('verified-flag-but-network-pending', 'forged-board-from-network-gives-no-sender')
                else (409, 'payin_basis_unverified'))
    assert (r.status_code, r.json['error']) == expected, r.json
    assert ledger_counts() == before and board_snapshot() == snap, 'отказ изменил доску/ledger'
