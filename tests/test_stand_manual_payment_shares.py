"""Manual transfer through the actual close route and incoming ledger."""
import json
import secrets

import pytest

import app as m
import stand_transfers
from tests.test_payout_receipt_independent_qa import _qa_cleanup_created_rows  # noqa: F401
from tests.test_stand_legacy_manual_payin_hash_qa import legacy_board, legacy_crm, ledger_counts
from tests.test_stand_manual_close_route import _client, _crm, _early_board, _override, _post, _setup
from tests.test_stand_manual_payin_hash_only_qa import FakeResponse, board_snapshot, make_wallet, tron_address, tronscan


def _network(monkeypatch, transfers):
    def get(_url, params=None, **_kwargs):
        tx = params['hash']
        return FakeResponse(tronscan(tx, transfers[tx]))

    def verify(*args, **kwargs):
        return stand_transfers.verify_transfer(*args, **kwargs, get=get)

    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', verify)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])


def _preview(client, tx, **fields):
    return client.post('/api/stand/manual-close/verify-hash', json={
        'dealId': 1489, 'direction': 'payin', 'hash': tx, 'network': 'trc20',
        'checkShare': True, **fields,
    })


def test_shared_withdrawal_uses_free_ledger_balance(monkeypatch):
    tx, payer, receiver = secrets.token_hex(32), tron_address(), make_wallet()
    _network(monkeypatch, {tx: [(payer, receiver, 1941)]})
    uid = _setup(board_factory=lambda: _early_board(
        step='s8', payType='СБП', amountRub=45000, amountUsdt=505,
        rates={'broker': 45000 / 505}, payinHashes=[{'hash': tx, 'amount': 1941}]))
    db = m.get_session()
    try:
        earlier = m.Deal(client_name='Earlier closed deal', deal_type=m.DealType.PAY_IN,
                         doverka_status=m.DoverkaStatus.CONFIRMED, doverka_payout_hash=tx.upper())
        ledger = m.PayinTx(tx_hash=tx, network='trc20', amount_usdt=1941, source='tronscan',
                          notes='Retain this reconciliation note')
        db.add_all([earlier, ledger])
        db.flush()
        earlier_id, ledger_id = earlier.id, ledger.id
        db.commit()
    finally:
        db.close()
    client = _client(uid)
    assert _preview(client, tx).json['error'] == 'payin_hash_already_used'
    db = m.get_session()
    try:
        db.add(m.PayinTxUse(tx_id=ledger_id, deal_id=earlier_id, amount_usdt=1436))
        db.commit()
    finally:
        db.close()
    before = board_snapshot(), ledger_counts()
    preview = _preview(client, tx)
    assert preview.status_code == 200, preview.json
    assert (preview.json['verifiedAmount'], preview.json['freeAmount']) == (1941, 505)
    assert _preview(client, tx, amount=506).json['error'] == 'payin_share_unavailable'
    assert (board_snapshot(), ledger_counts()) == before

    def submit(share):
        override = _override(payin={'method': 'СБП (Доверка)', 'amountRub': 45000, 'amountUsdt': share,
            'rate': 45000 / 505, 'hashes': [{'hash': tx, 'network': 'trc20', 'shareAmount': share}]})
        crm = _crm(payin_method='spp_doverka', payin_amount_rub=45000, payin_amount_usdt=share,
                   payin_rate_rub_usdt=45000 / 505,
                   payin_tx_hashes=[{'hash': tx, 'network': 'trc20', 'amount_usdt': share}])
        return _post(client, crm=crm, override=override)

    overspend = submit(506)
    assert (overspend.status_code, overspend.json['error']) == (422, 'payin_share_unavailable')
    assert (board_snapshot(), ledger_counts()) == before
    closed = submit(505)
    assert closed.status_code == 201, closed.json
    assert closed.json['deal']['payin_method'] == 'spp_doverka'
    assert closed.json['deal']['payin_amount_usdt'] == 505
    assert closed.json['data']['deals'][0]['payinHashes'][0]['verifiedAmount'] == 1941
    assert submit(505).json['duplicate'] is True
    db = m.get_session()
    try:
        ledger = db.query(m.PayinTx).filter_by(tx_hash=tx).one()
        assert ledger.amount_usdt == 1941
        assert ledger.notes == 'Retain this reconciliation note'
        assert sorted(u.amount_usdt for u in ledger.uses) == [505, 1436]
    finally:
        db.close()


@pytest.mark.parametrize('manual', [False, True])
def test_multiple_receipts_are_kept_in_crm_and_ledger(monkeypatch, manual):
    first, second = secrets.token_hex(32), secrets.token_hex(32)
    payer, receiver = tron_address(), make_wallet()
    _network(monkeypatch, {first: [(payer, receiver, 17000)], second: [(payer, receiver, 104)]})
    entries = [{'hash': tx, 'network': 'trc20', 'amount': amount}
               for tx, amount in ((first, 17000), (second, 104))]
    crm_entries = [{'hash': h['hash'], 'network': h['network'], 'amount_usdt': h['amount']}
                   for h in entries]
    if manual:
        client = legacy_board(monkeypatch, [{**h, 'isShare': True} for h in entries], amountUsdt=17104)
        crm = legacy_crm(None, amount=17104)
        response = client.post('/api/stand/deals/1474/crm-close', json={
            'version': 1, 'crm': {**crm, 'payin_tx_hashes': crm_entries}})
    else:
        uid = _setup(board_factory=lambda: _early_board(
            step='s8', payType='Крипта', amountUsdt=17000, payinHashes=[entries[0]]))
        client = _client(uid)
        override = _override(payin={'method': 'Крипта', 'amountUsdt': 17104,
            'hashes': [{**h, 'shareAmount': h['amount']} for h in entries]})
        duplicate = _override(payin={**override['payin'], 'hashes': [override['payin']['hashes'][0]] * 2})
        crm = _crm(payin_amount_usdt=17104, payin_tx_hashes=crm_entries)
        denied = _post(client, override=duplicate, crm=crm)
        assert (denied.status_code, denied.json['error']) == (422, 'payin_hash_already_used')
        response = _post(client, override=override, crm=crm)
    assert response.status_code == 201, response.json
    assert response.json['deal']['payin_amount_usdt'] == 17104
    assert response.json['deal']['payin_tx_hashes'] == crm_entries
    if not manual:
        logs = response.json['data']['deals'][0]['log']
        assert any('План прихода: 17000.00 USDT' in entry['text'] for entry in logs)
    db = m.get_session()
    try:
        rows = db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_((first, second))).all()
        assert sorted((row.amount_usdt, row.used_usdt()) for row in rows) == [(104, 104), (17000, 17000)]
    finally:
        db.close()


def test_new_manual_draft_can_preview_a_hash_without_creating_rows(monkeypatch):
    tx, sender, receiver = secrets.token_hex(32), tron_address(), make_wallet()
    _network(monkeypatch, {tx: [(sender, receiver, 320)]})
    client = _client(_setup())
    before = board_snapshot(), ledger_counts()
    preview = _preview(client, tx, dealId=9876, newDraft=True)
    assert (preview.status_code, preview.json['freeAmount']) == (200, 320)
    assert (board_snapshot(), ledger_counts()) == before


def test_two_open_manual_drafts_can_use_different_shares_of_the_same_hash(monkeypatch):
    tx, sender, receiver = secrets.token_hex(32), tron_address(), make_wallet()
    _network(monkeypatch, {tx: [(sender, receiver, 1941)]})
    client = legacy_board(monkeypatch, [
        {'hash': tx, 'network': 'trc20', 'amount': 505, 'isShare': True}], amountUsdt=505)
    db = m.get_session()
    try:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        first = state['deals'][0]
        state['deals'].append({**first, 'id': 1475, 'code': 'СД-1491', 'amountUsdt': 1436,
            'payinHashes': [{**first['payinHashes'][0], 'amount': 1436}]})
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    for version, (deal_id, amount) in enumerate(((1474, 505), (1475, 1436)), 1):
        preview = _preview(client, tx, dealId=deal_id)
        assert (preview.status_code, preview.json['freeAmount']) == (200, amount)
        closed = client.post(f'/api/stand/deals/{deal_id}/crm-close', json={
            'version': version, 'crm': legacy_crm(tx, amount=amount)})
        assert closed.status_code == 201, closed.json
        assert closed.json['deal']['payin_amount_usdt'] == amount
    db = m.get_session()
    try:
        ledger = db.query(m.PayinTx).filter_by(tx_hash=tx).one()
        assert ledger.amount_usdt == 1941
        assert sorted(u.amount_usdt for u in ledger.uses) == [505, 1436]
    finally:
        db.close()
