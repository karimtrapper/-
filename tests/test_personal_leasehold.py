"""The two personal leasehold payout modes post different accounting movements."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as crm

BUY_HASH = 'a' * 64
RETURN_HASH = 'b' * 64


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "personal-leasehold.db"}')
    crm.Base.metadata.create_all(engine)
    monkeypatch.setattr(crm, 'get_session', sessionmaker(bind=engine))
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    monkeypatch.setattr(crm, 'sync_realty_deal_to_gsheet', lambda *_: None)
    monkeypatch.setattr(crm, 'update_deal_in_gsheet', lambda *_: None)
    monkeypatch.setattr(crm, '_notify_reimbursed', lambda *_: None)
    monkeypatch.setattr(crm, '_send_deal_telegram', lambda *_: None)
    monkeypatch.setattr(crm, '_tx_info_by_network', lambda *_: {
        'amount_usdt': 1000, 'total_out_usdt': 1000, 'from_address': 'payer', 'to_address': 'broker',
    })
    monkeypatch.setattr(crm, '_tron_tx_amount', lambda *_: 1000)
    with crm.get_session() as db:
        card = crm.BankCard(bank_name='SCB', card_name='Личная', holder_name='Теодор', balance_thb=33000)
        card.topups.append(crm.CardTopup(amount_thb=33000, cost_usdt=1000, purchase_rate=33))
        ipps = crm.BankCard(bank_name='Другой', card_name=crm.IPPS_CARD_NAME, balance_thb=0)
        wallet = crm.Wallet(address='payer', label='Кошелёк QA')
        db.add_all([card, ipps, wallet])
        db.commit()
        ids = card.id, ipps.id, wallet.id
    try:
        with crm.app.test_client() as http:
            yield http, *ids
    finally:
        engine.dispose()


@pytest.fixture
def base():
    return dict(deal_kind='personal_realty', payin_method='crypto_direct', skip_sync=True,
                payin_amount_usdt=1100, payout_amount_thb=30000, realty_purpose='Юнит QA')


def test_existing_personal_balance_only_has_one_card_expense(ledger, base):
    http, card_id, ipps_id, _ = ledger
    data = dict(base, payout_source='bank_card', bank_card_id=card_id)
    assert http.post('/api/deals', json=data).status_code == 400
    assert http.patch(f'/api/cards/{ipps_id}/personal-owner', json={'personal_owner': 'andrey'}).status_code == 409
    assert http.patch(f'/api/cards/{card_id}/personal-owner', json={'personal_owner': 'theodor'}).status_code == 200
    preview = http.post('/api/deals/personal-preview', json=data)
    assert preview.status_code == 200, preview.json
    assert preview.json['result']['payout_amount_usdt'] == 909.09
    assert http.post('/api/deals', json={**data, 'payout_amount_thb': 33000.01}).status_code == 400
    created = http.post('/api/deals', json=data)
    assert created.status_code == 201, created.json
    row = created.json['deal']
    assert row['payout_amount_usdt'] == 909.09 and row['profit_usdt'] == 190.91
    assert row['needs_reimbursement'] is False
    deal_id = row['id']
    assert http.put(f'/api/deals/{deal_id}', json={'notes': 'Уточнение'}).status_code == 200
    assert http.put(f'/api/deals/{deal_id}', json={'payout_source': 'founder_personal'}).status_code == 400
    assert http.post('/api/reimbursements', json={
        'founder_name': 'Теодор', 'deal_ids': [deal_id], 'amount_usdt': 909.09,
    }).status_code == 409

    with crm.get_session() as db:
        assert db.get(crm.BankCard, card_id).balance_thb == 3000
        assert db.query(crm.CardAllocation).count() == 1
        assert db.query(crm.CardTopup).count() == 1
        assert db.query(crm.PayoutTxUse).count() == 0
        assert db.query(crm.WalletOperation).count() == 0
        assert crm.build_realty_rows(db.get(crm.Deal, deal_id))[0][10] == 909.09

    assert http.patch(f'/api/cards/{card_id}/personal-owner', json={'personal_owner': None}).status_code == 200
    assert http.put(f'/api/deals/{deal_id}', json={'notes': 'История сохранена'}).status_code == 200
    increased = http.put(f'/api/deals/{deal_id}', json={'payout_amount_thb': 30001})
    assert increased.status_code == 400, increased.json
    cancelled = http.put(f'/api/deals/{deal_id}', json={'status': 'cancelled'})
    assert cancelled.status_code == 200, cancelled.json
    revived = http.put(f'/api/deals/{deal_id}', json={'status': 'pending'})
    assert revived.status_code == 400, revived.json
    with crm.get_session() as db:
        assert db.get(crm.BankCard, card_id).balance_thb == 33000
        assert db.query(crm.CardAllocation).count() == 0


def test_direct_conversion_uses_existing_hash_and_full_reimbursement(ledger, base):
    http, card_id, _, wallet_id = ledger
    data = dict(base, payout_source='founder_personal', payout_founder_name='Теодор',
                payout_wallet_id=wallet_id, payout_tx_hashes=[{
                    'hash': BUY_HASH, 'network': 'trc20', 'amount_usdt': 1000,
                    'from_address': 'payer',
                }])
    assert http.post('/api/deals', json={**data, 'bank_card_id': card_id}).status_code == 400
    created = http.post('/api/deals', json=data)
    assert created.status_code == 201, created.json
    row = created.json['deal']
    assert row['payout_amount_usdt'] == 1000 and row['profit_usdt'] == 100
    assert row['needs_reimbursement'] is True
    deal_id = row['id']
    assert http.put(f'/api/deals/{deal_id}', json={'notes': 'Уточнение'}).status_code == 200
    with crm.get_session() as db:
        assert db.query(crm.PayoutTxUse).one().amount_usdt == 1000
        assert db.query(crm.CardAllocation).count() == 0
        assert db.query(crm.CardTopup).count() == 1
        assert db.query(crm.WalletOperation).count() == 0
        assert crm.build_realty_rows(db.get(crm.Deal, deal_id))[0][24] == BUY_HASH

    repay = {'founder_name': 'Теодор', 'deal_ids': [deal_id]}
    partial = http.post('/api/reimbursements', json={
        **repay, 'amount_usdt': 400, 'tx_uses': [{'tx_hash': RETURN_HASH, 'amount_usdt': 400}],
    })
    assert partial.status_code == 400, partial.json
    assert http.post('/api/reimbursements', json={**repay, 'amount_usdt': 1000}).status_code == 400
    full = http.post('/api/reimbursements', json={
        **repay, 'amount_usdt': 1000, 'tx_uses': [{'tx_hash': RETURN_HASH, 'amount_usdt': 1000}],
    })
    assert full.status_code == 200, full.json
    with crm.get_session() as db:
        deal = db.get(crm.Deal, deal_id)
        assert deal.payout_amount_usdt == 1000 and deal.profit_usdt == 100
        assert db.query(crm.ReimbursementTxUse).one().amount_usdt == 1000
    rejected = http.put(f'/api/deals/{deal_id}', json={'payout_amount_thb': 31000})
    assert rejected.status_code == 400, rejected.json


def test_direct_no_conversion_and_cancelled_debt_guards(ledger, base):
    http, _, _, wallet_id = ledger
    payload = dict(base, payout_source='founder_personal', payout_founder_name='Теодор',
                   payout_no_conversion=True, payout_wallet_id=wallet_id, payout_amount_usdt=1000)
    created = http.post('/api/deals', json=payload)
    assert created.status_code == 201, created.json
    deal_id = created.json['deal']['id']
    assert http.put(f'/api/deals/{deal_id}', json={'status': 'cancelled'}).status_code == 200
    pending = http.get('/api/reimbursements/pending').json['by_founder']
    assert not pending
    assert http.post('/api/reimbursements', json={
        'founder_name': 'Теодор', 'deal_ids': [deal_id], 'amount_usdt': 1000,
    }).status_code == 409


def test_settled_direct_deal_stays_out_of_reimbursements_after_notes_edit(ledger, base):
    http, _, _, wallet_id = ledger
    payload = dict(base, payout_source='founder_personal', payout_founder_name='Андрей',
                   payout_no_conversion=True, payout_wallet_id=wallet_id,
                   payout_amount_usdt=1000, needs_reimbursement=False)
    created = http.post('/api/deals', json=payload)
    assert created.status_code == 201, created.json
    deal_id = created.json['deal']['id']
    edited = http.put(f'/api/deals/{deal_id}', json={'notes': 'Поправка'})
    assert edited.status_code == 200, edited.json
    assert edited.json['deal']['needs_reimbursement'] is False
    assert http.get('/api/reimbursements/pending').json['by_founder'] == []
    assert http.post('/api/reimbursements', json={
        'founder_name': 'Андрей', 'deal_ids': [deal_id], 'amount_usdt': 1000,
    }).status_code == 409


def test_direct_disallows_incoming_unknown_and_wrong_wallet_hashes(ledger, base, monkeypatch):
    http, _, _, wallet_id = ledger
    data = dict(base, payout_source='founder_personal', payout_founder_name='Теодор',
                payout_wallet_id=wallet_id,
                payout_tx_hashes=[{'hash': BUY_HASH, 'network': 'trc20',
                                   'amount_usdt': 1000, 'from_address': 'payer'}])

    def proof(sender):
        return {'amount_usdt': 1000, 'from_address': sender, 'to_address': 'broker'}

    with crm.get_session() as db:
        incoming = crm.PayinTx(tx_hash='c' * 64, network='trc20', source='tronscan',
                               amount_usdt=1000, to_address='incoming')
        db.add(incoming)
        db.commit()
    incoming = http.post('/api/deals', json={**data, 'payout_tx_hashes': [
        {'hash': 'C' * 64, 'network': 'trc20', 'amount_usdt': 1000, 'from_address': 'payer'}]})
    assert incoming.status_code == 400 and 'входящего' in incoming.json['error']

    monkeypatch.setattr(crm, '_tx_info_by_network', lambda *_: proof('client'))
    mismatch = http.post('/api/deals', json=data)
    assert mismatch.status_code == 400 and 'другому кошельку' in mismatch.json['error']

    monkeypatch.setattr(crm, '_tx_info_by_network', lambda *_: None)
    unavailable = http.post('/api/deals', json=data)
    assert unavailable.status_code == 400 and 'подтвердить исходящий' in unavailable.json['error']
    with crm.get_session() as db:
        assert db.query(crm.Deal).count() == db.query(crm.PayoutTxUse).count() == 0

    monkeypatch.setattr(crm, '_tx_info_by_network', lambda *_: proof('payer'))
    created = http.post('/api/deals', json=data)
    assert created.status_code == 201, created.json
    deal_id = created.json['deal']['id']
    assert created.json['deal']['payout_amount_usdt'] == 1000
    monkeypatch.setattr(crm, '_tx_info_by_network',
                        lambda *_: pytest.fail('Запись заметки не должна перечитывать блокчейн'))
    same = http.put(f'/api/deals/{deal_id}', json={'notes': 'Без финансовых изменений'})
    assert same.status_code == 200, same.json
    for new_payin in (
        {'payin_tx_hash': BUY_HASH},
        {'payin_tx_hashes': [{'hash': '0x' + BUY_HASH.upper(), 'network': 'trc20', 'amount_usdt': 1000}]},
    ):
        conflict = http.put(f'/api/deals/{deal_id}', json=dict(new_payin, payin_amount_usdt=1000))
        assert conflict.status_code == 400 and 'прихода и выплаты' in conflict.json['error']
    with crm.get_session() as db:
        assert db.query(crm.PayinTxUse).count() == 0

    monkeypatch.setattr(crm, '_tx_info_by_network', lambda *_: proof('client'))
    edited = http.put(f'/api/deals/{deal_id}', json={
        'payout_tx_hashes': [{'hash': 'd' * 64, 'network': 'trc20', 'amount_usdt': 1000}],
    })
    assert edited.status_code == 400 and 'другому кошельку' in edited.json['error']
    with crm.get_session() as db:
        assert db.query(crm.PayoutTxUse).one().tx.tx_hash == BUY_HASH
