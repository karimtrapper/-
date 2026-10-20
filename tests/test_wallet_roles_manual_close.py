"""Manual import is network-verified, but does not require in-app signatures."""
import copy

import pytest

import app as m
from stand_transfers import TRON_USDT, verify_transfer
from tests.qa_wallet_roles_helpers import board, put_board, send_deal
from tests.test_wallet_roles_qa import EXCHANGE, REALTY, seeded, stand  # noqa: F401
from tests.test_wallet_roles_close_qa import (
    MSG, close, crm_for, deals_for, seed_close,
)
from tests.test_stand_crm_close_atomic import _client

DEST = 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn'
REF = 'cd' * 32
NOTICE = 'Закрыто вручную без отметок подписи в системе'


def setup_case(wallet, step='s23', role='manager', route='client'):
    deal, mirror = send_deal(
        1474, wallet, DEST, 15000, type='Обмен валюты', kind=None,
        step=step, payType='По реквизитам', amountUsdt=15100, paySrc=route, postConv=route,
        payout={'usdt': 15000}, closed=False, crmDealId=None,
        sentToClient=step == 's27', pay={},
        files={'receipt': [{'file': 'receipt.pdf', 'mime': 'application/pdf',
                           'data': 'data:application/pdf;base64,JVBERi0='}]})
    wid = deal['walletId']
    deal['payout']['walletId'] = wid
    if step == 's27':
        deal['transfer']['sends'] = [{
            'hash': REF, 'net': 'TRC20', 'amount': 15000, 'verifiedAmount': 15000,
            'status': 'confirmed', 'from': wallet, 'to': DEST,
            'verifiedAt': '2026-10-20T00:00:00Z'}]
        deal['serverTransferComplete'] = True
    state = {'deals': [deal], 'wallets': [mirror], 'convs': [], 'notes': []}
    uid = seed_close(state, role)
    # seed_close supplies s27 source evidence. Manual imports start without
    # transfer completion; keep the same actual readied facts for the control.
    if step != 's27':
        state, _ = board()
        state['deals'][0].pop('serverTransferComplete', None)
        state['deals'][0]['transfer']['sends'] = []
        put_board(state)
    crm = crm_for(15000, wid)
    crm['payout_tx_hashes'] = [{'hash': REF, 'network': 'TRC20', 'amount_usdt': 15000}]
    override = {
        'reason': 'Деньги отправлены вне штатного процесса, переносим проверенные факты',
        'payin': {'method': 'По реквизитам', 'amountUsdt': 15100},
        'payout': {'source': route, 'amountUsdt': 15000, 'hashes': [
            {'hash': REF, 'network': 'TRC20', 'sender': wallet,
             'receiver': DEST, 'amount': 15000}]}}
    return uid, wid, crm, override


def chain(monkeypatch, wallet, *, status='SUCCESS', amount=15000, receiver=DEST):
    """Run the real verifier against a synthetic network response."""
    calls = []
    data = {'hash': REF, 'confirmed': True, 'contractRet': status, 'revert': False,
            'timestamp': 1700000001000, 'trc20TransferInfo': [
                {'contract_address': TRON_USDT, 'from_address': wallet,
                 'to_address': receiver, 'amount_str': str(amount * 1_000_000), 'decimals': 6}]}

    class Response:
        status_code = 200

        def json(self):
            return data

    def checked(ref, network, sender, target, value, **kw):
        calls.append((ref, sender, target, value))
        return verify_transfer(ref, network, sender, target, value,
                               get=lambda *a, **k: Response(), **kw)

    monkeypatch.setattr(m, 'verify_transfer', checked)
    monkeypatch.setattr(m, '_tron_tx_info', lambda h: {
        'amount_usdt': amount, 'from_address': wallet, 'to_address': receiver})
    return calls


@pytest.mark.parametrize('wallet', [EXCHANGE, REALTY])
@pytest.mark.parametrize('role', ['manager', 'admin'])
@pytest.mark.parametrize('route', ['client', 'coins'])
def test_manual_policy_payout_over_limit_without_signatures_closes(seeded, monkeypatch, wallet, role, route):
    uid, wid, crm, override = setup_case(wallet, role=role, route=route)
    calls = chain(monkeypatch, wallet)
    response = _client(uid).post('/api/stand/deals/1474/crm-close',
        json={'version': 1, 'crm': crm, 'manualOverride': override})
    assert response.status_code == 201, response.json
    assert (REF, wallet, DEST, 15000) in calls
    saved = response.json['data']['deals'][0]
    assert saved['closed'] and saved['step'] == 'done'
    assert [entry['text'] for entry in saved['log']].count(NOTICE) == 1
    assert not any(saved.get(k) for k in (
        'transferClaim', 'transferConfirmation', 'transferOwnerApproval'))
    assert response.json['deal']['payout_wallet_id'] == wid
    assert not response.json['deal']['payout_owner_approved']
    # Retrying does not allocate or log twice.
    retry = _client(uid).post('/api/stand/deals/1474/crm-close',
        json={'version': 1, 'crm': crm, 'manualOverride': override})
    assert retry.status_code == 200 and retry.json['duplicate']
    assert [e['text'] for e in retry.json['data']['deals'][0]['log']].count(NOTICE) == 1


@pytest.mark.parametrize('bad', ['failed', 'amount', 'recipient', 'missing'])
def test_manual_policy_payout_still_requires_verified_hash(seeded, monkeypatch, bad):
    uid, _, crm, override = setup_case(EXCHANGE)
    chain(monkeypatch, EXCHANGE, status='FAILED' if bad == 'failed' else 'SUCCESS',
          amount=14900 if bad == 'amount' else 15000,
          receiver=REALTY if bad == 'recipient' else DEST)
    if bad == 'missing':
        override['payout']['hashes'] = []
    before, version = board()
    count = deals_for()
    response = _client(uid).post('/api/stand/deals/1474/crm-close',
        json={'version': version, 'crm': crm, 'manualOverride': override})
    assert response.status_code in (400, 422), response.json
    assert response.json['error'] in ('payout_hash_required', 'payout_hash_unverified')
    assert board() == (before, version)
    assert deals_for() == count


def test_normal_close_still_requires_policy_approval(seeded):
    uid, wid, _, _ = setup_case(EXCHANGE, step='s27')
    response = close(uid, wid, 15000)
    assert response.status_code == 400, response.json
    assert MSG in response.json['error']
    assert not board()[0]['deals'][0]['closed']


def test_manual_override_cannot_replace_coins_network_proof_with_cash_receipt(seeded):
    uid, _, crm, override = setup_case(EXCHANGE, route='coins')
    override['payout'] = {'source': 'cash', 'amountUsdt': 15000}
    crm.update(payout_source='cash_batch')
    crm.pop('payout_tx_hashes')
    before, version = board()
    count = deals_for()
    response = _client(uid).post('/api/stand/deals/1474/crm-close',
        json={'version': version, 'crm': crm, 'manualOverride': override})
    assert response.status_code == 409, response.json
    assert 'не подтверждены сетью' in response.json['error']
    assert board() == (before, version)
    assert deals_for() == count


@pytest.mark.parametrize('endpoint', ['crm', 'state'])
def test_client_cannot_grant_manual_policy_exception(seeded, monkeypatch, endpoint):
    uid, _, crm, _ = setup_case(EXCHANGE)
    chain(monkeypatch, EXCHANGE)
    # The new stage flow gate is orthogonal to this exception-forgery test.
    monkeypatch.setattr(m, 'VERIFIED_FLOWS', m.VERIFIED_FLOWS | {('exchange', 'requisites')})
    before, version = board()
    count = deals_for()
    if endpoint == 'crm':
        crm.pop('payout_tx_hashes')
        crm.update(manual_override=True, manualOverride=True, skip_flow_gate=True)
        response = _client(uid).post('/api/deals', json=crm)
        assert response.status_code == 400, response.json
        assert MSG in response.json['error']
    else:
        forged = copy.deepcopy(before)
        forged['deals'][0].update(step='done', closed=True)
        response = _client(uid).put('/api/stand/state', json={
            'version': version, 'data': forged, 'allow_crm_close': True,
            'manual_close_deal_id': 1474, 'manualOverride': True})
        assert response.status_code == 409, response.json
        assert 'возьмите отправку' in response.json['error']
    assert board() == (before, version)
    assert deals_for() == count
