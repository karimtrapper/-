"""Shared CRM/stand incoming ledger; verification uses the real verifier and fake chain."""
import copy
import json
import uuid
from decimal import Decimal

import pytest
import app as m
from tests.test_stand_transfers import authenticated_stand_client, _put_board, chain, Response, FROM, TO
from stand_transfers import verify_transfer


@pytest.fixture
def split(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    h = uuid.uuid4().hex * 2
    state = {'wallets': [{'id': 'a', 'addr': TO}, {'id': 'b', 'addr': FROM}],
             'convs': [{'id': n, 'walletId': 'a', 'status': 'sent', 'sentTs': 1699999999999,
                        'sources': [{'dealId': n, 'rub': 10000}], 'txs': []} for n in (1, 2, 3)],
             'deals': [{'id': n, 'code': f'СД-{1483+n}', 'cnvId': n, 'step': 's18w',
                        'pay': {}, 'transfer': {'sends': []}, 'log': []} for n in (1, 2, 3)]}
    _put_board(state)
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: verify_transfer(
        *a, **kw, get=lambda *a, **kw: Response(200, dict(chain(amount='200000000'), hash=h))))
    cli = m.app.test_client()
    def check(n=1, **kw):
        return cli.post('/api/stand/incoming/check', json={'dealId': n, 'hash': h,
                                                        'network': 'TRC-20', **kw})
    return cli, check, h, state


def ledger(cli, h):
    r = cli.get('/api/payin-txs/' + h)
    assert r.status_code == 200, r.json
    return r.json['tx']


def test_split_200_and_unlink_returns_shared_remainder(split):
    cli, check, h, state = split
    preview = check(preview=True)
    assert preview.status_code == 200, preview.json
    assert preview.json['ledger']['free_usdt'] == 200
    assert check(amount=100).status_code == 200
    assert ledger(cli, h)['free_usdt'] == 100
    assert check(2, amount=100).status_code == 200
    assert ledger(cli, h)['free_usdt'] == 0
    denied = check(3, amount=101)
    assert denied.status_code == 409, denied.json
    assert 'свободно' in denied.json['error'] and '200' in denied.json['error']
    assert cli.post('/api/stand/incoming/unlink', json={
        'dealId': 1, 'hash': h, 'reason': 'перераспределение'}).status_code == 200
    assert ledger(cli, h)['free_usdt'] == 100
    assert check(3, amount=100).status_code == 200
    assert ledger(cli, h)['free_usdt'] == 0


def test_wallet_is_verified_for_each_batch(split):
    cli, check, h, state = split
    state['convs'][1]['walletId'] = 'b'
    _put_board(state)
    assert check(amount=100).status_code == 200
    denied = check(2, amount=100)
    assert denied.status_code == 422
    assert ledger(cli, h)['free_usdt'] == 100


@pytest.mark.parametrize('amount,ok', [('100.005', True), ('100.005001', False),
                                     ('100.004999', True), ('0', False), ('-1', False),
                                     ('NaN', False), ('Infinity', False)])
def test_tolerance_never_creates_negative_remainder(split, amount, ok):
    cli, check, h, state = split
    assert check(amount=100).status_code == 200
    r = check(2, amount=amount)
    assert (r.status_code == 200) == ok, r.json
    value = ledger(cli, h)
    assert value['free_usdt'] >= 0
    db = m.get_session()
    try:
        tx = db.query(m.PayinTx).filter_by(tx_hash=h).one()
        assert sum(Decimal(str(u.amount_usdt)) for u in tx.uses) <= Decimal('200')
    finally:
        db.close()


def test_old_full_hash_is_counted_without_rewriting_board(split):
    cli, check, h, state = split
    state['convs'][0]['txs'] = [{'hash': h, 'net': 'TRC20', 'amount': 200,
                                'status': 'confirmed', 'to': TO}]
    _put_board(state)
    r = check(2, preview=True)
    assert r.status_code == 200, r.json
    assert r.json['ledger']['free_usdt'] == 0
    assert check(2, amount=1).status_code == 409
    db = m.get_session()
    try:
        assert json.loads(m._stand_row(db).data)['convs'][0]['txs'] == state['convs'][0]['txs']
    finally:
        db.close()


def test_reserve_moves_to_crm_share_once_and_rollback_restores(split):
    cli, check, h, state = split
    assert check(amount=100).status_code == 200
    db = m.get_session()
    try:
        row = m._stand_row(db)
        before = db.query(m.PayinTxUse).join(m.PayinTx).filter(m.PayinTx.tx_hash == h).one()
        reserve_id = before.id
        deal = m.Deal(client_name='split close', deal_type=m.DealType.PAY_IN)
        db.add(deal); db.flush()
        db.info['stand_payin_origin'] = (row.generation, '1')
        for _ in range(2):
            m._sync_payin_tx_uses(db, deal, [{'hash': h, 'amount_usdt': 100, 'network': 'trc20'}])
        uses = db.query(m.PayinTxUse).filter_by(tx_id=before.tx_id).all()
        assert len(uses) == 1 and uses[0].id == reserve_id
        assert uses[0].deal_id == deal.id
        assert uses[0].amount_usdt == 100
        assert db.query(m.PayinTx).filter_by(tx_hash=h).one().free_usdt() == 100
        db.rollback()
        restored = db.query(m.PayinTxUse).filter_by(id=reserve_id).one()
        assert restored.deal_id is None and restored.amount_usdt == 100
    finally:
        db.info.pop('stand_payin_origin', None)
        db.close()


def test_crm_cannot_spend_reserved_money(split):
    cli, check, h, state = split
    assert check(amount=150).status_code == 200
    db = m.get_session()
    try:
        deal = m.Deal(client_name='other CRM', deal_type=m.DealType.PAY_IN)
        db.add(deal); db.flush()
        with pytest.raises(ValueError, match='свободно'):
            m._sync_payin_tx_uses(db, deal, [{'hash': h, 'amount_usdt': 100}])
    finally:
        db.rollback(); db.close()


def test_two_concurrent_requests_cannot_spend_same_remainder(split, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    cli, check, h, state = split
    clients = [m.app.test_client(), m.app.test_client()]
    real = m.verify_transfer
    barrier = threading.Barrier(2)
    def verified(*args, **kwargs):
        result = real(*args, **kwargs)
        barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(m, 'verify_transfer', verified)
    def claim(index):
        return clients[index].post('/api/stand/incoming/check', json={
            'dealId': index + 1, 'hash': h, 'network': 'TRC-20', 'amount': 150}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (0, 1))) == [200, 409]
    assert ledger(cli, h)['free_usdt'] == 50


def test_partial_close_leaves_rest_of_batch_reserved(split):
    cli, check, h, state = split
    assert check(amount=200).status_code == 200
    db = m.get_session()
    try:
        row = m._stand_row(db)
        db.info['stand_payin_origin'] = (row.generation, '1')
        for amount in (80, 120):
            deal = m.Deal(client_name='batch member', deal_type=m.DealType.PAY_IN)
            db.add(deal); db.flush()
            m._sync_payin_tx_uses(db, deal, [{'hash': h, 'amount_usdt': amount}])
            tx = db.query(m.PayinTx).filter_by(tx_hash=h).one()
            assert tx.used_usdt() == 200 and tx.free_usdt() == 0
        assert db.query(m.PayinTxUse).filter_by(tx_id=tx.id, deal_id=None).count() == 0
        assert db.query(m.PayinTxUse).filter_by(tx_id=tx.id).count() == 2
    finally:
        db.info.pop('stand_payin_origin', None)
        db.rollback(); db.close()


def test_actual_crm_close_moves_reserve_and_retry_keeps_same_use(monkeypatch):
    from tests.test_stand_crm_close_atomic import _setup, _seed_evidence, _client, _post, _crm
    uid = _setup(monkeypatch)
    h = uuid.uuid4().hex * 2
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        d = state['deals'][0]
        d.update(cnvId=1, payinHashes=[{'hash': h, 'net': 'TRC20', 'amount': 100, 'verified': True}])
        d['pay']['usdt'] = 100
        d['payinParts'] = [{'incId': 'test-close', 'amountRub': 10000}]
        state['incomes'] = [{'id': 'test-close', 'source': 'sber', 'dealId': d['id'], 'rub': 10000}]
        state['convs'] = [{'id': 1, 'sources': [{'dealId': d['id'], 'rub': 10000, 'usdtFact': 100}],
                           'txs': [{'hash': h, 'net': 'TRC20', 'amount': 100, 'status': 'confirmed'}]}]
        row.data = json.dumps(state)
        db.commit()
        _seed_evidence(db, row, state, uid)
        m._stand_import_legacy_payins(db, row, state)
        tx = db.query(m.PayinTx).filter_by(tx_hash=h).one()
        reserve_id = db.query(m.PayinTxUse).filter_by(tx_id=tx.id).one().id
        db.commit()
    finally:
        db.close()
    crm = {**_crm(), 'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': 100}]}
    client = _client(uid)
    real_apply = m._stand_apply_prepay_fees_to_crm
    def fail_after_transfer(*args, **kwargs):
        raise RuntimeError('injected failure after reserve transfer')
    monkeypatch.setattr(m, '_stand_apply_prepay_fees_to_crm', fail_after_transfer)
    assert _post(client, crm=crm).status_code == 500
    db = m.get_session()
    try:
        use = db.query(m.PayinTxUse).filter_by(id=reserve_id).one()
        assert use.deal_id is None and use.amount_usdt == 100
    finally:
        db.close()
    monkeypatch.setattr(m, '_stand_apply_prepay_fees_to_crm', real_apply)
    closed = _post(client, crm=crm)
    assert closed.status_code == 201, closed.json
    assert _post(client, crm=crm).json['duplicate'] is True
    db = m.get_session()
    try:
        use = db.query(m.PayinTxUse).filter_by(id=reserve_id).one()
        assert use.deal_id == closed.json['deal']['id']
        assert use.amount_usdt == 100
        assert db.query(m.PayinTxUse).filter_by(tx_id=use.tx_id).count() == 1
    finally:
        db.close()


def test_board_save_and_funding_accept_server_owned_split(split):
    import stand_funding
    cli, check, h, state = split
    first = check(amount=100).json
    second = check(2, amount=100).json
    assert stand_funding.check_state(second['data'], second['data']) is None
    # Merely repeating a hash without a real reservation remains forbidden.
    forged = copy.deepcopy(second['data'])
    forged['convs'][1]['txs'][0].pop('ledgerUseId')
    assert stand_funding.check_state(forged, forged)


def test_six_decimal_share_can_fund_and_close_batch(split):
    import stand_funding
    cli, check, h, state = split
    result = check(amount='100.123456').json
    state = result['data']
    d, c = state['deals'][0], state['convs'][0]
    d['payinParts'] = [{'incId': 'fractional', 'amountRub': 10000}]
    state['incomes'] = [{'id': 'fractional', 'source': 'sber', 'dealId': 1, 'rub': 10000}]
    c['sources'][0]['usdtFact'] = 100.123456
    assert stand_funding.check_batch(state, c, dispatch=True) is None


def test_existing_crm_uppercase_hash_counts_towards_remainder(split):
    cli, check, h, state = split
    db = m.get_session()
    try:
        deal = m.Deal(client_name='legacy uppercase', deal_type=m.DealType.PAY_IN)
        tx = m.PayinTx(tx_hash=h.upper(), amount_usdt=200, source='tronscan')
        db.add_all([deal, tx]); db.flush()
        db.add(m.PayinTxUse(tx_id=tx.id, deal_id=deal.id, amount_usdt=150))
        db.commit()
    finally:
        db.close()
    result = check(preview=True)
    assert result.status_code == 200, result.json
    assert result.json['ledger']['free_usdt'] == 50
    assert check(amount=51).status_code == 409


def test_100_transfer_then_101_at_zero_is_rejected(split, monkeypatch):
    cli, check, h, state = split
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: verify_transfer(
        *a, **kw, get=lambda *a, **kw: Response(200, dict(chain(amount='100000000'), hash=h))))
    assert check(amount=100).status_code == 200
    denied = check(2, amount=101)
    assert denied.status_code == 409
    assert 'разнесено $100.00' in denied.json['error']
    assert 'свободно $0.00' in denied.json['error']


def test_recalculation_preserves_other_batch_reservation(split):
    cli, check, h, state = split
    assert check(amount=100).status_code == 200
    assert check(2, amount=100).status_code == 200
    db = m.get_session()
    try:
        row = m._stand_row(db)
        tx = db.query(m.PayinTx).filter_by(tx_hash=h).one()
        other = db.query(m.PayinTxUse).filter_by(tx_id=tx.id, stand_cnv_id='2').one()
        other_id = other.id
        crm = m.Conversion(status=m.ConversionStatus.RECEIVED)
        deal = m.Deal(client_name='CRM source', deal_type=m.DealType.PAY_IN)
        db.add_all([crm, deal]); db.flush()
        income = m.SberIncome(uuid=uuid.uuid4().hex, amount_rub=10000, claimed_deal_id=deal.id)
        db.add(income); db.flush()
        db.add_all([m.ConversionSource(conversion_id=crm.id, sber_income_id=income.id, amount_rub=10000),
                    m.ConversionTx(conversion_id=crm.id, payin_tx_id=tx.id, amount_usdt=100)])
        db.flush()
        for _ in range(2):
            m._apply_conversion_shares(db, crm, stand_origin=(row.generation, '1'))
        assert db.query(m.PayinTxUse).filter_by(id=other_id).one().amount_usdt == 100
        assert other.deal_id is None
        assert tx.used_usdt() == 200 and tx.free_usdt() == 0
    finally:
        db.rollback(); db.close()


def test_new_hash_preview_keeps_full_six_decimal_remainder(split, monkeypatch):
    cli, check, h, state = split
    monkeypatch.setattr(m, 'verify_transfer', lambda *a, **kw: verify_transfer(
        *a, **kw, get=lambda *a, **kw: Response(200, dict(chain(amount='200123456'), hash=h))))
    preview = check(preview=True)
    assert preview.json['ledger']['free_usdt'] == 200.123456
    assert preview.json['ledger']['amount_usdt'] == 200.123456
    assert check().json['tx']['amount'] == 200.123456
