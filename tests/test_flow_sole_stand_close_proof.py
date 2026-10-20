"""The task board cannot turn an unproved Flow Sole draft into completed CRM."""
import json
import uuid

import pytest

import app as m
from tests.test_flow_sole_draft_proof import _tron_proof
from tests.test_stand_crm_close_atomic import _board, _client, _counts, _seed_evidence, _setup


pytestmark = pytest.mark.usefixtures('stand_demo_environment')


@pytest.fixture(autouse=True)
def clean_flow_close_artifacts():
    """The shared SQLite suite can reuse CRM IDs after another fixture resets it."""
    yield
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).first()
        if row:
            state = json.loads(row.data or '{}')
            origin = f'{row.generation}:1474'
            link = db.query(m.StandCrmLink).filter_by(origin=origin).first()
            if link:
                crm_id = link.crm_deal_id
                db.query(m.PayinTxUse).filter_by(deal_id=crm_id).delete()
                db.delete(link)
                db.query(m.Deal).filter_by(id=crm_id).delete()
            hashes = [h.get('hash') for d in state.get('deals') or [] if d.get('id') == 1474
                      for h in d.get('payinHashes') or []]
            if hashes:
                db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_(hashes)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _flow_board(monkeypatch, *, hash_amount=None):
    uid = _setup(monkeypatch)
    board = _board()
    deal = board['deals'][0]
    h = uuid.uuid4().hex + uuid.uuid4().hex
    deal.update(payType='По реквизитам', rubReceivingAccount={'mode': 'flowsole'},
                rubIsNet=True, amountRub=40000, amountUsdt=400,
                rates={'broker': 100}, payinHashes=([{'hash': h, 'net': 'TRC20',
                    'amount': hash_amount, 'verified': True}] if hash_amount else []))
    deal['payinParts'] = [{'incId': -1474, 'amountRub': 40000}]
    board['incomes'] = [{'id': -1474, 'source': 'sber', 'rub': 40000,
                         'grossRub': 40000, 'netRub': 40000,
                         'dealId': deal['id']}]
    if hash_amount:
        deal['cnvId'] = 1474
        board['convs'] = [{'id': 1474, 'status': 'received',
            'txs': [{'hash': h, 'net': 'TRC20', 'amount': hash_amount,
                     'status': 'confirmed', 'verifiedAt': '2026-10-20T00:00:00Z'}],
            'sources': [{'dealId': deal['id'], 'rub': 40000,
                         'usdtFact': hash_amount}]}]
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        _seed_evidence(db, row, board, actor_id=uid)
    finally:
        db.close()
    crm = {'deal_kind': 'exchange', 'client_name': deal['client'],
           'manager_name': 'Елизавета', 'payin_method': 'flow_sole_reqs',
           'payin_rub_is_net': True, 'payin_amount_rub': 40000,
           'payin_rate_rub_usdt': 100, 'payin_amount_usdt': 400,
           'payin_tx_hashes': ([{'hash': h, 'network': 'trc20',
                                'amount_usdt': hash_amount}] if hash_amount else []),
           'payout_source': 'cash_batch', 'payout_method': 'transfer',
           'payout_amount_usdt': 90, 'payout_amount_thb': 1}
    return _client(uid), crm, h


@pytest.mark.parametrize('network_state', ['missing', 'failed', 'pending', 'confirmed'])
def test_s27_close_requires_strict_payin_proof_and_rolls_back(monkeypatch, network_state):
    client, crm, h = _flow_board(monkeypatch, hash_amount=400)
    amounts = {h: 500}
    if network_state != 'missing':
        _tron_proof(monkeypatch, amounts, {h: network_state})
    else:
        _tron_proof(monkeypatch, {})
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    if network_state == 'confirmed':
        assert response.status_code == 201, response.json
        assert response.json['deal']['payin_tx_verified'] is True
        assert response.json['deal']['status'] == 'completed'
    else:
        assert response.status_code == 409, response.json
        assert response.json['error'] == 'Подтвердите сумму Pay-In хэшем сети'
        assert _counts() == before
        state = client.get('/api/stand/state').json['data']['deals'][0]
        assert state['closed'] is False and state['crmDealId'] is None


def test_s27_close_rejects_missing_hash(monkeypatch):
    client, crm, _ = _flow_board(monkeypatch)
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 409, response.json
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False


def test_s27_declared_400_is_not_replaced_by_hash_500(monkeypatch):
    client, crm, h = _flow_board(monkeypatch, hash_amount=500)
    _tron_proof(monkeypatch, {h: 500})
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'payin_amount_mismatch'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False


def test_manual_origin_close_cannot_skip_flow_proof(monkeypatch):
    client, crm, _ = _flow_board(monkeypatch)
    db = m.get_session()
    row = db.query(m.StandState).filter_by(id=1).one()
    state = json.loads(row.data)
    state['deals'][0].update(originMode='manual', manual=True, step='manual')
    row.data = json.dumps(state)
    db.commit(); db.close()
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Подтвердите сумму Pay-In хэшем сети'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False
