"""A Flow Sole draft can keep planned money without moving actual funds."""
import json
import uuid
from datetime import datetime

import app as m
from tests.test_flow_sole_draft_proof import _tron_proof


def _hash():
    return uuid.uuid4().hex + uuid.uuid4().hex


def test_pending_flow_draft_does_not_debit_wallet_or_card(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_legacy_unverified_flow_problem', lambda *args, **kwargs: None)
    wallet = m.Wallet(address='T' + uuid.uuid4().hex, label='Flow proof test', active=True)
    card = m.BankCard(bank_name='Flow proof test', balance_thb=33000,
                      status=m.CashBatchStatus.ACTIVE)
    db = m.get_session()
    db.add_all([wallet, card]); db.flush()
    topup = m.CardTopup(card_id=card.id, amount_thb=33000, cost_usdt=1000,
                        purchase_rate=33, source_type='separate', reference='flow-proof')
    db.add(topup); db.commit()
    wallet_id, card_id, topup_id = wallet.id, card.id, topup.id
    db.close()
    client = m.app.test_client()
    ids = []
    try:
        for payout in ({'payout_source': 'binance', 'payout_wallet_id': wallet_id,
                        'payout_amount_usdt': 90},
                       {'payout_source': 'bank_card', 'bank_card_id': card_id,
                        'payout_amount_thb': 3000, 'payout_amount_usdt': 90,
                        'agents': [{'name': 'Flow agent', 'tier': 1,
                                    'comp_model': 'revshare', 'percent': 10}]}):
            response = client.post('/api/deals', json={
                'client_name': 'flow-plan-' + _hash()[:8],
                'payin_method': 'flow_sole_reqs', 'payin_rub_is_net': True,
                'payin_amount_rub': 10000, 'payin_amount_usdt': 100,
                'status': 'pending', 'skip_sync': True, **payout})
            assert response.status_code == 201, response.json
            deal = response.json['deal']; ids.append(deal['id'])
            assert deal['status'] == 'pending'
            assert deal['payin_amount_usdt'] == 100
            assert deal['profit_usdt'] is not None
        db = m.get_session()
        assert db.query(m.WalletOperation).filter(
            m.WalletOperation.deal_id.in_(ids), m.WalletOperation.type == 'expense').count() == 0
        assert db.query(m.CardAllocation).filter(m.CardAllocation.deal_id.in_(ids)).count() == 0
        assert db.get(m.BankCard, card_id).balance_thb == 33000
        db.close()
        assert client.put(f'/api/deals/{ids[0]}', json={'status': 'completed'}).status_code == 409
        planned = client.put(f'/api/deals/{ids[0]}', json={'payout_amount_usdt': 85})
        assert planned.status_code == 200, planned.json
        assert planned.json['deal']['profit_usdt'] == 15
        db = m.get_session()
        assert db.query(m.WalletOperation).filter_by(deal_id=ids[0], type='expense').count() == 0
        db.close()

        h, card_hash = _hash(), _hash()
        _tron_proof(monkeypatch, {h: 100, card_hash: 100})
        verified = client.put(f'/api/deals/{ids[0]}', json={
            'payin_tx_hashes': [{'hash': h, 'network': 'trc20', 'amount_usdt': None}],
            'payin_amount_usdt': 100})
        assert verified.status_code == 200, verified.json
        assert verified.json['deal']['payin_tx_verified'] is True
        db = m.get_session()
        expense = db.query(m.WalletOperation).filter_by(deal_id=ids[0], type='expense').one()
        assert expense.amount == 85
        db.close()

        verified_card = client.put(f'/api/deals/{ids[1]}', json={
            'payin_tx_hashes': [{'hash': card_hash, 'network': 'trc20', 'amount_usdt': None}],
            'payin_amount_usdt': 100})
        assert verified_card.status_code == 200, verified_card.json
        assert verified_card.json['deal']['payin_tx_verified'] is True
        db = m.get_session()
        assert db.query(m.CardAllocation).filter_by(deal_id=ids[1]).count() == 1
        assert db.get(m.BankCard, card_id).balance_thb == 30000
        card_deal = db.get(m.Deal, ids[1])
        assert card_deal.profit_usdt == 9.09
        assert card_deal.agents[0].payout_usdt == 0.91
        assert card_deal.net_profit_usdt == 8.18
        db.close()
    finally:
        db = m.get_session()
        db.query(m.PayinTxUse).filter(m.PayinTxUse.deal_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.WalletOperation).filter(m.WalletOperation.deal_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.CardAllocation).filter(m.CardAllocation.deal_id.in_(ids)).delete(synchronize_session=False)
        db.query(m.Deal).filter(m.Deal.id.in_(ids)).delete(synchronize_session=False)
        db.query(m.PayinTx).filter(m.PayinTx.tx_hash.in_(
            [locals().get('h'), locals().get('card_hash')])).delete(synchronize_session=False)
        db.query(m.CardTopup).filter_by(id=topup_id).delete()
        db.query(m.BankCard).filter_by(id=card_id).delete()
        db.query(m.Wallet).filter_by(id=wallet_id).delete()
        db.commit(); db.close()


def test_reimbursement_requires_server_proof_for_flow(monkeypatch):
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(m, '_tron_tx_amount', lambda h: 10.0)
    monkeypatch.setattr(m, 'sync_deals_to_gsheet', lambda *a, **k: None)
    monkeypatch.setattr(m, '_send_deal_telegram', lambda *a, **k: None)
    h, payout_hash = _hash(), _hash()
    db = m.get_session()
    deal = m.Deal(client_name='flow-reimbursement-' + h[:8],
                  deal_type=m.DealType.PAY_IN, status=m.DealStatus.PENDING,
                  payin_method=m.PayInMethod.FLOW_SOLE_REQS,
                  payin_amount_usdt=100, payout_amount_thb=3000,
                  payout_source=m.PayOutSource.FOUNDER_PERSONAL,
                  payout_founder_name='Андрей', payout_amount_usdt=90)
    db.add(deal); db.commit(); deal_id = deal.id; db.close()
    client = m.app.test_client()
    body = {'founder_name': 'Андрей', 'deal_ids': [deal_id], 'amount_usdt': 10,
            'tx_uses': [{'tx_hash': payout_hash, 'amount_usdt': 10}]}
    try:
        missing = client.post('/api/reimbursements', json=body)
        assert missing.status_code == 409, missing.json
        db = m.get_session()
        assert db.query(m.Reimbursement).filter(m.Reimbursement.deals.any(id=deal_id)).count() == 0
        row = db.get(m.Deal, deal_id)
        row.payin_tx_hashes = json.dumps([{'hash': h, 'network': 'trc20', 'amount_usdt': None}])
        tx = m.PayinTx(tx_hash=h, network='trc20', amount_usdt=100,
                       source='tronscan', verified_at=datetime.utcnow())
        db.add(tx)
        row.payin_tx_verified = True
        db.commit(); db.close()
        _tron_proof(monkeypatch, {h: 100})
        approved = client.post('/api/reimbursements', json=body)
        assert approved.status_code == 200, approved.json
        assert approved.json['success'] is True
    finally:
        db = m.get_session()
        db.query(m.ReimbursementTxUse).filter(
            m.ReimbursementTxUse.reimbursement_id.in_(
                db.query(m.Reimbursement.id).filter(m.Reimbursement.deals.any(id=deal_id))
            )).delete(synchronize_session=False)
        row = db.get(m.Deal, deal_id)
        reimbursement_id = row.reimbursement_id if row else None
        if row:
            row.reimbursement_id = None
            db.flush()
        if reimbursement_id:
            db.query(m.Reimbursement).filter_by(id=reimbursement_id).delete()
        db.query(m.Deal).filter_by(id=deal_id).delete()
        db.query(m.PayinTx).filter_by(tx_hash=h).delete()
        db.query(m.ReimbursementTx).filter_by(tx_hash=payout_hash).delete()
        db.commit(); db.close()
