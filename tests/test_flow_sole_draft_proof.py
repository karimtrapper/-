"""Flow Sole money remains a draft until the chain proves the Pay-In."""
import uuid

import app as m
import stand_transfers


def _hash():
    return uuid.uuid4().hex + uuid.uuid4().hex


def _tron_proof(monkeypatch, amounts, states=None):
    """Exercise the real strict TRC-20 parser with provider JSON, without HTTP."""
    monkeypatch.delenv('STAND_MODE', raising=False)
    states = states or {}
    calls = []

    def fake_get(url, *, params, **kwargs):
        h = params['hash']
        calls.append((url, h))
        amount = amounts.get(h)
        state = states.get(h, 'confirmed')
        payload = {'hash': h, 'confirmed': state != 'pending',
                   'contractRet': 'REVERT' if state == 'failed' else 'SUCCESS',
                   'revert': state == 'failed', 'timestamp': 1_760_000_000_000,
                   'trc20TransferInfo': [{'contract_address': m.USDT_TRC20_CONTRACT,
                       'amount_str': str(int((amount or 0) * 1_000_000)),
                       'decimals': 6, 'type': 'Transfer', 'status': 0,
                       'from_address': 'Tfrom', 'to_address': 'Tto'}] if amount else []}
        return type('Response', (), {'status_code': 200, 'json': lambda self: payload})()

    monkeypatch.setattr(m, 'verify_transfer', lambda ref, network, sender, receiver, amount, **kw:
        stand_transfers.verify_transfer(ref, network, sender, receiver, amount,
                                        get=fake_get, **kw))
    return calls


def test_flow_sole_draft_mismatch_and_confirmed_close(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_legacy_unverified_flow_problem', lambda *a, **kw: None)
    h = _hash()
    network = {h: None}
    monkeypatch.setattr(m, '_tron_tx_usdt_amount', lambda tx: network.get(tx))
    provider_calls = _tron_proof(monkeypatch, network)
    client = m.app.test_client()
    deal_id = None
    try:
        response = client.post('/api/deals', json={
            'client_name': 'flow-proof-' + h[:12], 'payin_method': 'flow_sole_reqs',
            'payin_rub_is_net': True, 'payin_amount_rub': 70000,
            'payin_amount_usdt': 700, 'payout_amount_usdt': 600,
            'needs_reimbursement': False, 'payout_source': 'binance',
            'payin_tx_verified': True, 'payin_confirmation': {'status': 'confirmed'},
        })
        assert response.status_code == 201, response.json
        first = response.json['deal']; deal_id = first['id']
        assert first['status'] == 'pending'
        assert first['payin_amount_usdt'] == 700
        assert first['profit_usdt'] == 100
        assert first['payin_tx_verified'] is False
        assert first['payin_confirmation']['status'] == 'unconfirmed'

        network[h] = 250
        mismatch = client.put(f'/api/deals/{deal_id}', json={
            'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': 700}],
            'payin_amount_usdt': 700, 'payin_tx_verified': True,
        })
        assert mismatch.status_code == 200, mismatch.json
        row = mismatch.json['deal']
        assert row['status'] == 'pending'
        assert row['payin_amount_usdt'] == 700
        assert row['payin_confirmation']['status'] == 'mismatch'
        assert row['payin_confirmation']['network_usdt'] == 250
        db = m.get_session()
        try:
            tx = db.query(m.PayinTx).filter_by(tx_hash=h).one()
            assert tx.amount_usdt == 250 and tx.source == 'tronscan'
            assert db.query(m.PayinTxUse).filter_by(tx_id=tx.id, deal_id=deal_id).count() == 0
        finally:
            db.close()
        assert client.put(f'/api/deals/{deal_id}', json={'status': 'completed'}).status_code == 409
        assert client.put(f'/api/deals/{deal_id}', json={'payout_tx_hash': _hash()}).status_code == 409

        matched = client.put(f'/api/deals/{deal_id}', json={
            'payin_amount_usdt': 250,
            'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': 250}],
        })
        assert matched.status_code == 200, matched.json
        row = matched.json['deal']
        assert row['payin_confirmation']['status'] == 'confirmed'
        assert row['payin_tx_verified'] is True
        assert row['status'] == 'completed'
        assert row['payin_amount_usdt'] == 250
        assert provider_calls and all('/api/transaction-info' in url for url, _ in provider_calls)
    finally:
        if deal_id:
            db = m.get_session()
            db.query(m.PayinTxUse).filter_by(deal_id=deal_id).delete()
            db.query(m.PayinTx).filter_by(tx_hash=h).delete()
            db.query(m.Deal).filter_by(id=deal_id).delete()
            db.commit(); db.close()


def test_historical_completed_flow_sole_unrelated_edit_stays_completed(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    db = m.get_session()
    deal = m.Deal(client_name='old-flow-' + uuid.uuid4().hex,
        deal_type=m.DealType.PAY_IN, status=m.DealStatus.COMPLETED,
        payin_method=m.PayInMethod.FLOW_SOLE_REQS,
        payin_amount_usdt=700, payout_amount_usdt=600,
        payin_rub_is_net=None, payin_tx_verified=False)
    db.add(deal); db.commit(); deal_id = deal.id; db.close()
    try:
        client = m.app.test_client()
        monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError('unchanged completed deal must not reverify')))
        assert client.get(f'/api/deals/{deal_id}').json['deal']['status'] == 'completed'
        saved = client.put(f'/api/deals/{deal_id}', json={'notes': 'old record'})
        assert saved.status_code == 200, saved.json
        assert saved.json['deal']['status'] == 'completed'
        assert saved.json['deal']['payin_tx_verified'] is False
        full = client.put(f'/api/deals/{deal_id}', json={
            'payin_rub_is_net': False, 'payin_method': 'flow_sole_reqs',
            'status': 'completed', 'payin_amount_usdt': 700,
            'payout_amount_usdt': 600, 'payin_tx_hash': None,
            'payin_tx_hashes': [], 'payout_tx_hashes': [], 'notes': 'old record full form',
        })
        assert full.status_code == 200, full.json
        assert full.json['deal']['status'] == 'completed'
        assert full.json['deal']['payin_tx_verified'] is False
    finally:
        db = m.get_session(); db.query(m.Deal).filter_by(id=deal_id).delete()
        db.commit(); db.close()


def test_explicit_hash_share_uses_other_deals_remaining(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_legacy_unverified_flow_problem', lambda *a, **kw: None)
    h, full_h = _hash(), _hash()
    owner = m.Deal(client_name='share-owner-' + h[:8],
                   deal_type=m.DealType.PAY_IN, status=m.DealStatus.PENDING)
    db = m.get_session()
    db.add(owner); db.flush()
    tx = m.PayinTx(tx_hash=h, network='trc20', amount_usdt=2000, source='tronscan')
    full_tx = m.PayinTx(tx_hash=full_h, network='trc20', amount_usdt=2000, source='tronscan')
    db.add_all([tx, full_tx]); db.flush()
    db.add(m.PayinTxUse(tx_id=tx.id, deal_id=owner.id, amount_usdt=900))
    db.commit(); owner_id = owner.id; tx_id = tx.id; db.close()
    _tron_proof(monkeypatch, {h: 2000, full_h: 2000})
    ids = []
    client = m.app.test_client()
    try:
        base = {'client_name': 'flow-share-' + h[:8],
                'payin_method': 'flow_sole_reqs', 'payin_rub_is_net': True,
                'payin_amount_rub': 80000, 'payin_amount_usdt': 1000}
        explicit = client.post('/api/deals', json={**base,
            'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': 1000}]})
        assert explicit.status_code == 201, explicit.json
        ids.append(explicit.json['deal']['id'])
        assert explicit.json['deal']['payin_confirmation']['status'] == 'confirmed'
        db = m.get_session()
        db.query(m.PayinTxUse).filter_by(tx_id=tx_id, deal_id=owner_id).one().amount_usdt = 1200
        db.commit(); db.close()
        insufficient = client.put(f'/api/deals/{ids[0]}', json={'status': 'completed'})
        assert insufficient.status_code == 409
        assert insufficient.json['payin_confirmation']['status'] == 'mismatch'

        full = client.post('/api/deals', json={**base,
            'payin_tx_hashes': [{'hash': full_h, 'network': 'trc20', 'amount_usdt': None}]})
        assert full.status_code == 201, full.json
        ids.append(full.json['deal']['id'])
        assert full.json['deal']['payin_confirmation']['status'] == 'mismatch'
        assert full.json['deal']['payin_confirmation']['network_usdt'] == 2000
    finally:
        db = m.get_session()
        db.query(m.PayinTxUse).filter(m.PayinTxUse.deal_id.in_([owner_id] + ids)).delete(synchronize_session=False)
        db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_([h, full_h])).delete(synchronize_session=False)
        db.query(m.Deal).filter(m.Deal.id.in_([owner_id] + ids)).delete(synchronize_session=False)
        db.commit(); db.close()


def test_erc_hash_cannot_use_tron_proof_on_stage(monkeypatch):
    h = _hash()
    db = m.get_session()
    deal = m.Deal(client_name='erc-proof-' + h[:8],
        deal_type=m.DealType.PAY_IN, status=m.DealStatus.PENDING,
        payin_method=m.PayInMethod.FLOW_SOLE_REQS, payin_amount_usdt=250,
        payin_tx_hashes=m.json.dumps([{'hash': h, 'network': 'erc20', 'amount_usdt': 250}]))
    tx = m.PayinTx(tx_hash=h, network='trc20', amount_usdt=250, source='tronscan')
    db.add_all([deal, tx]); db.flush()
    try:
        assert m._flow_sole_payin_confirmation(db, deal)['status'] == 'unconfirmed'
        tx.network = 'erc20'
        db.flush()
        monkeypatch.setattr(m, 'STAND_MODE', True)
        assert m._flow_sole_payin_confirmation(db, deal)['status'] == 'unconfirmed'
    finally:
        db.rollback(); db.close()


def test_failed_and_pending_tron_transfer_info_never_proves_payin(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_legacy_unverified_flow_problem', lambda *a, **kw: None)
    hashes = [_hash(), _hash()]
    amounts = {h: 250 for h in hashes}
    _tron_proof(monkeypatch, amounts, {hashes[0]: 'failed', hashes[1]: 'pending'})
    monkeypatch.setattr(m, '_tron_tx_usdt_amount', lambda h: amounts.get(h))
    ids = []
    client = m.app.test_client()
    try:
        for h in hashes:
            response = client.post('/api/deals', json={
                'client_name': 'unproved-' + h[:8], 'payin_method': 'flow_sole_reqs',
                'payin_rub_is_net': True, 'payin_amount_rub': 20000,
                'payin_amount_usdt': 250,
                'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': None}],
                'payin_tx_verified': True,
            })
            assert response.status_code == 201, response.json
            ids.append(response.json['deal']['id'])
            assert response.json['deal']['payin_confirmation']['status'] == 'unconfirmed'
            assert response.json['deal']['payin_tx_verified'] is False
            assert client.put(f'/api/deals/{ids[-1]}', json={'status': 'completed'}).status_code == 409
    finally:
        db = m.get_session()
        db.query(m.PayinTxUse).filter(m.PayinTxUse.deal_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_(hashes)).delete(synchronize_session=False)
        db.query(m.Deal).filter(m.Deal.id.in_(ids)).delete(synchronize_session=False)
        db.commit(); db.close()
