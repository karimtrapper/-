"""The task board cannot turn an unproved Flow Sole draft into completed CRM."""
import json
import uuid

import pytest

import app as m
from tests.test_flow_sole_draft_proof import _tron_proof
from tests.test_stand_crm_close_atomic import _board, _client, _counts, _seed_evidence, _setup


pytestmark = pytest.mark.usefixtures('stand_demo_environment')


@pytest.fixture(autouse=True)
def clean_flow_close_artifacts(stand_demo_environment, monkeypatch):
    """Remove only links/ledger rows created here, even if SQLite IDs reset."""
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        prior_links = {(link.origin, link.crm_deal_id)
                       for link in db.query(m.StandCrmLink).all()}
    finally:
        db.close()
    yield
    db = m.get_session()
    try:
        new_links = [link for link in db.query(m.StandCrmLink).all()
                     if (link.origin, link.crm_deal_id) not in prior_links]
        for link in new_links:
            crm_id = link.crm_deal_id
            db.query(m.PayinTxUse).filter_by(deal_id=crm_id).delete()
            db.delete(link)
            db.query(m.Deal).filter_by(id=crm_id).delete()
        row = db.query(m.StandState).filter_by(id=1).first()
        if row:
            state = json.loads(row.data or '{}')
            hashes = [h.get('hash') for d in state.get('deals') or [] if d.get('id') == 1474
                      for h in d.get('payinHashes') or []]
            if hashes:
                tx_ids = [tx_id for (tx_id,) in db.query(m.PayinTx.id).filter(
                    m.PayinTx.tx_hash.in_(hashes)).all()]
                if tx_ids:
                    db.query(m.PayinTxUse).filter(m.PayinTxUse.tx_id.in_(tx_ids)).delete(
                        synchronize_session=False)
                db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_(hashes)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _flow_board(monkeypatch, *, hash_amount=None, declared_amount=400):
    uid = _setup(monkeypatch)
    board = _board()
    deal = board['deals'][0]
    h = uuid.uuid4().hex + uuid.uuid4().hex
    deal.update(payType='По реквизитам', rubReceivingAccount={'mode': 'flowsole'},
                rubIsNet=True, amountRub=40000, amountUsdt=declared_amount,
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
           'payin_rate_rub_usdt': 100, 'payin_amount_usdt': declared_amount,
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
    assert response.json['error'] == 'Подтвердите сумму Pay-In хэшем сети'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False


def test_flow_manual_hash_without_share_matches_full_network_transfer(monkeypatch):
    client, crm, h = _flow_board(monkeypatch, hash_amount=500, declared_amount=500)
    # Task manual/pool auto amounts are deliberately null: strict Flow Sole
    # proof interprets that as the full confirmed transfer, without inventing
    # a numeric CRM share during board fact validation.
    db = m.get_session()
    row = db.query(m.StandState).filter_by(id=1).one()
    state = json.loads(row.data)
    state['deals'][0]['payinHashes'][0]['amount'] = None
    row.data = json.dumps(state)
    db.commit(); db.close()
    crm['payin_tx_hashes'][0]['amount_usdt'] = None
    _tron_proof(monkeypatch, {h: 500})
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 201, response.json
    assert response.json['deal']['payin_amount_usdt'] == 500
    assert response.json['deal']['payin_tx_verified'] is True


def test_flow_explicit_pool_share_is_preserved_and_must_match_declared(monkeypatch):
    client, crm, h = _flow_board(monkeypatch, hash_amount=100, declared_amount=100)
    _tron_proof(monkeypatch, {h: 500})
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 201, response.json
    assert response.json['deal']['payin_amount_usdt'] == 100
    assert response.json['deal']['payin_tx_verified'] is True


def test_flow_explicit_pool_share_mismatch_is_rejected_before_close(monkeypatch):
    client, crm, h = _flow_board(monkeypatch, hash_amount=100, declared_amount=100)
    _tron_proof(monkeypatch, {h: 500})
    crm['payin_amount_usdt'] = 90
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'payin_amount_mismatch'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False


@pytest.mark.parametrize(('board_share', 'payload_share'), [(100, None), (None, 100)])
def test_flow_hash_amount_null_and_explicit_share_cannot_be_swapped(
        monkeypatch, board_share, payload_share):
    client, crm, _ = _flow_board(monkeypatch, hash_amount=100, declared_amount=100)
    db = m.get_session()
    row = db.query(m.StandState).filter_by(id=1).one()
    state = json.loads(row.data)
    state['deals'][0]['payinHashes'][0]['amount'] = board_share
    row.data = json.dumps(state)
    db.commit(); db.close()
    crm['payin_tx_hashes'][0]['amount_usdt'] = payload_share
    before = _counts()
    response = client.post('/api/stand/deals/1474/crm-close',
                           json={'version': 1, 'crm': crm})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'payin_facts_mismatch'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['closed'] is False


@pytest.mark.parametrize(('share', 'declared'), [(None, 500), (100, 100)])
def test_custom_flow_scalar_payload_preserves_board_hash_amount(share, declared):
    h = uuid.uuid4().hex + uuid.uuid4().hex
    board = {'custom': True, 'type': 'Обмен валюты', 'kind': '',
        'payType': 'По реквизитам', 'amountUsdt': declared,
        'payinHashes': [{'hash': h, 'network': 'trc20', 'amount': share}],
        'customData': {'payinMethod': 'flow_sole_reqs', 'payinTxHash': h,
            'payinCurrency': 'RUB', 'payinAmount': declared * 100,
            'payinRate': 100, 'payinUsdt': declared,
            'payoutCurrency': 'USDT', 'payoutAmount': 90,
            'payoutRate': None, 'payoutUsdt': 90}}
    crm = {'is_custom': True, 'deal_kind': 'exchange',
        'client_name': 'custom flow', 'payin_method': 'flow_sole_reqs',
        'payin_amount_usdt': declared, 'payin_tx_hash': h,
        'payin_tx_hashes': ([{'hash': h, 'network': 'trc20', 'amount_usdt': share}]
                            if share is not None else None),
        'custom_payin_currency': 'RUB', 'custom_payin_amount': declared * 100,
        'custom_payin_rate': 100, 'custom_payout_currency': 'USDT',
        'custom_payout_amount': 90, 'custom_payout_rate': None,
        'payout_amount_usdt': 90, 'payout_wallet_id': None, 'bank_card_id': None,
        'payout_source': 'cash_batch', 'payout_method': 'transfer',
        'payout_amount_thb': 1, 'payin_rate_rub_usdt': None,
        'payin_parts': [], 'payin_extra': [], 'payout_tx_hashes': []}
    assert m._stand_crm_fact_problem(board, crm, 'exchange') is None
    crm['payin_tx_hashes'] = [{'hash': h, 'network': 'trc20',
                               'amount_usdt': 100 if share is None else None}]
    assert m._stand_crm_fact_problem(board, crm, 'exchange') == 'payin_facts_mismatch'


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
