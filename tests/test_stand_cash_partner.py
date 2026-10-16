"""Оплата наличными через партнёра на s14: права, документы и единый реестр USDT."""
import copy
import uuid

import pytest

import app as m
from tests.test_stand_transfers import authenticated_stand_client, _put_board, FROM


pytestmark = pytest.mark.usefixtures('stand_demo_environment')


def _state():
    return {'deals': [{'id': 1483, 'code': 'СД-1483', 'step': 's14',
        'type': 'Оплата недвижимости', 'kind': 'Лизхолд',
        'payType': 'По реквизитам', 'rubReceivingAccount': {'mode': 'flowsole'},
        'walletId': 'grusha', 'payinHashes': [], 'payinParts': [], 'pay': {},
        'docVersion': 2, 'docs': {'signed': [{'file': 'signed.pdf'}]},
        'docFields': {'payTo': 'Flow Sole'}, 'log': [{'at': 1700000000000, 'text': 'Заявка'}]}],
        'incomes': [], 'convs': [], 'wallets': []}


def _setup(monkeypatch, state=None):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    _put_board(state or _state())
    return m.app.test_client()


def test_cash_method_preserves_signed_docs_and_can_restore_before_receipt(monkeypatch):
    client = _setup(monkeypatch)
    original = client.get('/api/stand/state').json['data']['deals'][0]
    changed = client.post('/api/stand/payin/cash-method', json={'dealId': 1483})
    assert changed.status_code == 200, changed.json
    deal = changed.json['data']['deals'][0]
    assert deal['payType'] == 'Наличные' and deal['cashPartnerUsdt'] is True
    assert (deal['docs'], deal['docFields'], deal['docVersion']) == (
        original['docs'], original['docFields'], original['docVersion'])
    assert 'Flow Sole' in deal['log'][-1]['text']
    restored = client.post('/api/stand/payin/cash-method', json={'dealId': 1483, 'restore': True})
    assert restored.status_code == 200, restored.json
    assert restored.json['data']['deals'][0]['payType'] == 'По реквизитам'
    assert restored.json['data']['deals'][0]['docs'] == original['docs']


def test_cash_method_denied_after_bank_credit_and_for_manager(monkeypatch):
    state = _state()
    state['deals'][0]['payinParts'] = [{'incId': 1, 'amountRub': 1000}]
    client = _setup(monkeypatch, state)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 409
    state['deals'][0]['payinParts'] = []
    state['incomes'] = [{'id': 1, 'dealId': 1483, 'rub': 1000}]
    _put_board(state)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 409
    _put_board(_state())
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 403


def test_two_partner_hashes_use_shared_ledger_and_block_duplicate(monkeypatch):
    client = _setup(monkeypatch)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 200
    first, second = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    def verified(ref, network, sender, receiver, amount):
        return {'status': 'confirmed', 'verifiedAmount': 120 if ref == first else 80,
            'verifiedAt': 'now', 'timestampMs': 1700000000001, 'from': FROM, 'to': receiver}
    monkeypatch.setattr(m, 'verify_transfer', verified)
    for ref in (first, second):
        result = client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': ref})
        assert result.status_code == 200, result.json
    deal = client.get('/api/stand/state').json['data']['deals'][0]
    assert [h['amount'] for h in deal['payinHashes']] == [120, 80]
    assert all(h['verified'] and h['ledgerUseId'] for h in deal['payinHashes'])
    assert client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': first}).status_code == 409
    ledger = client.get('/api/payin-txs/' + first).json['tx']
    assert ledger['free_usdt'] == 0 and ledger['used_usdt'] == 120
    forged = copy.deepcopy(client.get('/api/stand/state').json)
    forged['data']['deals'][0]['payinHashes'].pop()
    rejected = client.put('/api/stand/state', json={'version': forged['version'], 'data': forged['data']})
    assert rejected.status_code == 409
    advancing = copy.deepcopy(client.get('/api/stand/state').json)
    advancing['data']['deals'][0]['step'] = 's22'
    advancing['data']['deals'][0]['amountUsdt'] = 200
    advancing['data']['deals'][0]['pay']['usdt'] = 200
    routed = client.put('/api/stand/state', json={
        'version': advancing['version'], 'data': advancing['data']})
    assert routed.status_code == 200, routed.json
    assert routed.json['data']['deals'][0]['step'] == 's22'
    db = m.get_session()
    try:
        stand = m._stand_row(db)
        original_uses = {u.tx.tx_hash: u.id for u in db.query(m.PayinTxUse).filter_by(
            stand_generation=stand.generation, stand_cnv_id='cash:1483').all()}
        crm = m.Deal(client_name='cash partner', deal_type=m.DealType.PAY_IN)
        db.add(crm); db.flush()
        db.info['stand_payin_origin'] = (stand.generation, 'cash:1483')
        db.info['stand_payin_hashes'] = {first, second}
        m._sync_payin_tx_uses(db, crm, [
            {'hash': first, 'network': 'trc20', 'amount_usdt': 120},
            {'hash': second, 'network': 'trc20', 'amount_usdt': 80}])
        uses = db.query(m.PayinTxUse).filter_by(deal_id=crm.id).all()
        assert {u.id for u in uses} == set(original_uses.values())
        assert all(u.tx.used_usdt() == u.amount_usdt for u in uses)
    finally:
        db.info.pop('stand_payin_origin', None)
        db.info.pop('stand_payin_hashes', None)
        db.rollback(); db.close()


def test_partner_hash_already_allocated_in_crm_is_rejected(monkeypatch):
    client = _setup(monkeypatch)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 200
    ref = uuid.uuid4().hex * 2
    db = m.get_session()
    try:
        tx = m.PayinTx(tx_hash=ref, network='trc20', amount_usdt=100, source='tronscan')
        db.add(tx); db.flush()
        db.add(m.PayinTxUse(tx_id=tx.id, stand_generation='another-board',
                            stand_cnv_id='another-conversion', amount_usdt=100))
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(m, 'verify_transfer', lambda ref, network, sender, receiver, amount: {
        'status': 'confirmed', 'verifiedAmount': 100, 'verifiedAt': 'now',
        'timestampMs': 1700000000001, 'from': FROM, 'to': receiver})
    result = client.post('/api/stand/payin/check', json={'dealId': 1483, 'hash': ref})
    assert result.status_code == 409, result.json
    assert client.get('/api/stand/state').json['data']['deals'][0]['payinHashes'] == []


def test_incoming_list_shows_available_wallet_transfers(monkeypatch):
    client = _setup(monkeypatch)
    assert client.post('/api/stand/payin/cash-method', json={'dealId': 1483}).status_code == 200
    available, occupied = uuid.uuid4().hex * 2, uuid.uuid4().hex * 2
    db = m.get_session()
    try:
        tx = m.PayinTx(tx_hash=occupied, network='trc20', amount_usdt=50, source='tronscan')
        db.add(tx); db.flush()
        db.add(m.PayinTxUse(tx_id=tx.id, stand_generation='another-board',
                            stand_cnv_id='other', amount_usdt=50))
        db.commit()
    finally:
        db.close()
    import stand_transfer_discovery
    seen = {}
    def discover(**kwargs):
        seen.update(kwargs)
        return {'status': 'complete', 'candidates': [
            {'hash': ref, 'amount': amount, 'from': FROM, 'timestamp_ms': 1700000000001}
            for ref, amount in ((available, 100), (occupied, 50))]}
    monkeypatch.setattr(stand_transfer_discovery, 'discover_transfers', discover)
    result = client.get('/api/stand/payin/cash-incoming?dealId=1483')
    assert result.status_code == 200, result.json
    assert [x['hash'] for x in result.json['incoming']] == [available]
    assert seen['wallet_addr'] == 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'
    assert seen['direction'] == 'incoming'
