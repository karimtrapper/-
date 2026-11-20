"""Недвижимость через ИППС использует существующий карточный учёт."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as crm


def add_card(name, *, balance=66000, cost=2000):
    with crm.get_session() as db:
        card = crm.BankCard(bank_name='Другой', card_name=name, balance_thb=balance)
        card.topups.append(crm.CardTopup(amount_thb=balance, cost_usdt=cost, purchase_rate=balance / cost))
        db.add(card)
        db.commit()
        return card.id


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "ipps.db"}')
    crm.Base.metadata.create_all(engine)
    monkeypatch.setattr(crm, 'get_session', sessionmaker(bind=engine))
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    sent = []
    monkeypatch.setattr(crm, 'sync_realty_deal_to_gsheet',
                        lambda deal: sent.append(crm.build_realty_rows(deal)))
    monkeypatch.setattr(crm, '_send_deal_telegram', lambda deal: None)
    ipps = add_card(crm.IPPS_CARD_NAME)
    other = add_card('Обычная карта')
    try:
        with crm.app.test_client() as client:
            yield client, ipps, other, sent
    finally:
        engine.dispose()


@pytest.fixture
def payload():
    return {
        'deal_kind': 'ipps_realty', 'payin_method': 'crypto_direct',
        'payin_amount_usdt': 1100.76, 'payout_amount_thb': 33000,
        'realty_purpose': 'Оплата по счёту QA',
        'agents': [{'name': 'Агент QA ИППС', 'tier': 1, 'comp_model': 'revshare', 'percent': 10}],
    }


def card_state(card_id):
    with crm.get_session() as db:
        card = db.get(crm.BankCard, card_id)
        return card.balance_thb, [
            (allocation.amount_thb, allocation.cost_usdt, allocation.card_rate)
            for allocation in card.allocations
        ]


def test_ipps_crm_financial_lifecycle(client, payload):
    http, ipps, other, sheet = client
    cards = http.get('/api/cards/balance').json['cards']
    assert [card['id'] for card in cards if card['is_ipps']] == [ipps]
    preview = http.post('/api/deals/ipps-realty/preview', json=payload)
    assert preview.status_code == 200, preview.json
    assert preview.json['result']['payout_amount_usdt'] == 1000
    assert preview.json['result']['net_profit_usdt'] == 90.68
    assert card_state(ipps) == (66000, [])

    response = http.post('/api/deals', json=payload)
    assert response.status_code == 201, response.json
    deal = response.json['deal']
    deal_id = deal['id']
    path = f'/api/deals/{deal_id}'
    assert (deal['status'], deal['payout_method'], deal['payout_source']) == ('pending', 'transfer', 'bank_card')
    assert deal['bank_card_id'] == ipps
    assert deal['needs_reimbursement'] is False
    assert deal['profit_usdt'] == 100.76
    assert deal['net_profit_usdt'] == 90.68
    assert card_state(ipps) == (33000, [(33000, 1000, 33)])
    assert card_state(other) == (66000, [])

    topup = http.post(f'/api/cards/{ipps}/topup', json={
        'source_type': 'separate', 'amount_thb': 40000, 'cost_usdt': 1000,
    })
    assert topup.status_code in (200, 201), topup.json
    unchanged = http.put(path, json={'notes': 'Правка без изменения выплаты'})
    assert unchanged.status_code == 200, unchanged.json
    assert card_state(ipps) == (73000, [(33000, 1000, 33)])

    changed = http.put(path, json={'payout_amount_thb': '33033.00', 'status': 'completed'})
    assert changed.status_code == 200, changed.json
    deal = http.get(path).json['deal']
    assert crm.IPPS_CARD_NAME in deal['bank_card_name']
    assert deal['payout_amount_usdt'] == 1001
    assert deal['profit_usdt'] == 99.76
    assert deal['net_profit_usdt'] == 89.78
    assert deal['agents'][0]['payout_usdt'] == 9.98
    assert all(deal[field] is None for field in (
        'payout_wallet_id', 'payout_founder_name', 'company_fee_usdt',
    ))
    assert card_state(ipps) == (72967, [(33033, 1001, 33)])
    assert http.put(path, json={'payout_amount_thb': 33033}).status_code == 200
    assert card_state(ipps) == (72967, [(33033, 1001, 33)])

    ledger = http.get('/api/deals/ledger?deal_kind=ipps_realty').json
    entry = next(item for item in ledger['deals'] if item['id'] == deal_id)
    assert entry['pay_out']['source'] == 'bank_card'
    assert crm.IPPS_CARD_NAME in entry['pay_out']['source_name']
    assert entry['pay_out']['amount_thb'] == 33033
    assert entry['pay_out']['cost_usdt'] == 1001
    assert entry['realty']['purpose'] == payload['realty_purpose']
    including = http.get(f'/api/deals?deal_kind=realty&q={deal_id}').json
    excluding = http.get(f'/api/deals?deal_kind=exchange&q={deal_id}').json
    assert [item['id'] for item in including['deals']] == [deal_id]
    assert excluding['deals'] == []
    cashflow = http.get('/api/finance/cashflow?product=ipps_realty').json
    payment, = [event for event in cashflow['events'] if event['deal_id'] == deal_id]
    assert (payment['article'], payment['account'], payment['amount'], payment['currency']) == (
        'payout_developer', 'card_thb', 33033, 'THB',
    )
    assert payment['bank_card_id'] == ipps
    row, = sheet[-1]
    assert row[2] == 'usdt-thb · ИППС'
    assert (row[6], row[10], row[17], row[18], row[20]) == (33033, 1001, 99.76, 9.98, 89.78)
    assert all(row[i] == '' for i in (7, 8, 11, 12, 13, 14, 15, 16, 19))

    reimburse = http.post('/api/reimbursements', json={
        'founder_name': 'QA', 'deal_ids': [deal_id], 'amount_usdt': 1000,
    })
    assert reimburse.status_code == 409, reimburse.json
    assert reimburse.json['deal_ids'] == [deal_id]
    with crm.get_session() as db:
        for model in (crm.WalletOperation, crm.CashAllocation, crm.PayoutTxUse):
            assert db.query(model).filter_by(deal_id=deal_id).count() == 0
    assert http.put(path, json={'status': 'cancelled'}).status_code == 200
    assert card_state(ipps) == (106000, [])
    assert http.put(path, json={'status': 'pending'}).status_code == 200
    assert card_state(ipps)[0] == 72967
    assert http.delete(path).status_code == 200
    assert card_state(ipps) == (106000, [])


def test_ipps_rejects_invalid_amounts_and_hand_entered_usdt(client, payload):
    http, ipps, _, _ = client
    response = http.post('/api/deals', json=payload)
    assert response.status_code == 201, response.json
    deal_id = response.json['deal']['id']
    path = f'/api/deals/{deal_id}'
    for value in (None, True, -1, 0, 'NaN', float('inf'), '20.001', '1e12', []):
        invalid = payload | {'payout_amount_thb': value}
        assert http.post('/api/deals', json=invalid).status_code == 400, value
        assert http.post('/api/deals/ipps-realty/preview', json=invalid).status_code == 400, value
        assert http.put(path, json={'payout_amount_thb': value}).status_code == 400, value
    override = {'payout_amount_usdt': 999}
    assert http.post('/api/deals', json=payload | override).status_code == 400
    assert http.put(path, json=override).status_code == 400
    assert http.get(path).json['deal']['payout_amount_usdt'] == 1000
    assert card_state(ipps) == (33000, [(33000, 1000, 33)])


def test_ipps_selects_only_eligible_cards_and_preserves_link(client, payload):
    http, ipps, other, _ = client
    for override in ({'payout_source': 'binance'}, {'payout_method': 'office'},
                     {'needs_reimbursement': True}, {'payout_wallet_id': 1},
                     {'cash_batch_id': 1}, {'payout_tx_hash': 'qa'},
                     {'bank_card_id': other}):
        result = http.post('/api/deals', json=payload | override)
        assert result.status_code == 400, result.json
    second = add_card('  ipps счет компании ')
    missing_choice = http.post('/api/deals', json=payload)
    assert missing_choice.status_code == 400, missing_choice.json
    response = http.post('/api/deals', json=payload | {'bank_card_id': second})
    assert response.status_code == 201, response.json
    path = f"/api/deals/{response.json['deal']['id']}"
    assert http.put(path, json={'bank_card_id': ipps}).status_code == 400
    assert http.put(path, json={'deal_kind': 'exchange'}).status_code == 409
    assert card_state(ipps) == (66000, [])
    with crm.get_session() as db:
        for card_id in (ipps, second):
            db.get(crm.BankCard, card_id).status = crm.CashBatchStatus.ARCHIVED
        db.commit()
    assert http.post('/api/deals', json=payload).status_code == 400
    assert http.put(path, json={'notes': 'Отредактировано после архивации'}).status_code == 200
    assert http.get(path).json['deal']['bank_card_id'] == second
    assert card_state(second) == (33000, [(33000, 1000, 33)])


def test_ipps_uses_existing_negative_balance_warning(client, payload):
    http, ipps, _, _ = client
    response = http.post('/api/deals', json=payload | {
        'payout_amount_thb': 66000.25, 'payin_amount_usdt': None,
    })
    assert response.status_code == 201, response.json
    assert 'ушёл в минус' in response.json['warning']
    deal = response.json['deal']
    assert deal['payout_amount_usdt'] == 2000.01
    assert deal['profit_usdt'] is None
    assert deal['net_profit_usdt'] is None
    assert card_state(ipps) == (-0.25, [(66000.25, 2000.01, 33)])
