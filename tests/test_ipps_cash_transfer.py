"""Balance operation between the existing IPPS account and THB cash inventory."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app as crm


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "ipps-cash.db"}')
    crm.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(crm, 'get_session', factory)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    with factory() as db:
        source = crm.BankCard(bank_name='Другой', card_name=crm.IPPS_CARD_NAME,
                              holder_name='Теодор', balance_thb=71000)
        source.topups = [
            crm.CardTopup(amount_thb=33000, cost_usdt=1000, purchase_rate=33),
            crm.CardTopup(amount_thb=38000, cost_usdt=1000, purchase_rate=38),
        ]
        other = crm.BankCard(bank_name='SCB', card_name='Тестовый счёт', balance_thb=0)
        db.add_all((source, other))
        db.commit()
        ids = source.id, other.id
    try:
        with crm.app.test_client() as client:
            yield client, *ids, factory
    finally:
        engine.dispose()


@pytest.fixture
def payload():
    return {'amount_thb': '6500.25', 'request_id': str(uuid4()), 'reason': 'Перевод QA'}


def test_ipps_card_shows_balance_cost_and_latest_movements(ledger):
    http, source_id, _, factory = ledger
    purchase_at = datetime(2026, 11, 20, 10)
    with factory() as db:
        card = db.get(crm.BankCard, source_id)
        old_purchases = list(card.topups)
        for purchase in old_purchases:
            purchase.created_at = purchase_at - timedelta(days=1)
        latest_purchase = crm.CardTopup(
            created_at=purchase_at, amount_thb=36000, cost_usdt=1000, purchase_rate=36,
            source_type='separate',
        )
        card.topups.extend([
            latest_purchase,
            crm.CardTopup(created_at=purchase_at - timedelta(hours=1), amount_thb=-3550,
                          cost_usdt=-100, purchase_rate=35.5, source_type='adjustment'),
            crm.CardTopup(created_at=purchase_at + timedelta(hours=2), amount_thb=0,
                          cost_usdt=0, purchase_rate=0, source_type=crm.IPPS_CASH_CANCELLED),
        ])
        deal = crm.Deal(deal_type=crm.DealType.PAY_IN)
        card.allocations.append(crm.CardAllocation(
            deal=deal, created_at=purchase_at + timedelta(hours=1), amount_thb=35750,
            cost_usdt=1000, card_rate=35.75,
        ))
        card.balance_thb = 67700
        db.commit()
        purchase_id, deal_id = latest_purchase.id, deal.id

    cards = http.get('/api/cards').json['cards']
    listed = next(card for card in cards if card['id'] == source_id)
    assert listed['balance_thb'] == 67700
    assert listed['remaining_cost_usdt'] == 1900
    assert listed['avg_rate'] == round(67700 / 1900, 4)
    payout, purchase, adjustment = listed['recent_operations']
    assert (payout['deal_id'], payout['amount_thb'], payout['cost_usdt'], payout['purchase_rate']) == (
        deal_id, -35750, -1000, 35.75,
    )
    assert purchase['id'] == purchase_id
    assert adjustment['source_type'] == 'adjustment'


def test_ipps_cash_transfer_preserves_inventory_history_and_cancel(ledger, payload):
    http, source_id, _, factory = ledger
    source = f'/api/cards/{source_id}'
    response = http.post(source + '/transfer-to-cash', json=payload)
    assert response.status_code == 201, response.json
    transfer = response.json
    movement = transfer['transfer_out']
    batch = transfer['batch']
    batch_id = batch['id']
    cash = f'/api/cash/batches/{batch_id}/ipps-transfer'
    assert transfer['source_balance_thb'] == 64499.75
    assert batch['founder_name'] == 'Теодор'
    assert batch['amount_thb'] == batch['remaining_thb'] == 6500.25
    assert batch['cost_usdt'] == 183.11  # weighted balance rate 35.5, not the last top-up at 38
    assert batch['purchase_rate'] == 6500.25 / 183.11
    assert movement['source_batch_id'] == batch_id
    assert (movement['amount_thb'], movement['cost_usdt']) == (-6500.25, -183.11)
    assert transfer['reference'] == movement['reference']
    assert transfer['source_card_id'] == source_id

    cards = http.get('/api/cards').json
    assert [card['id'] for card in cards['cards'] if card['is_ipps']] == [source_id]
    assert cards['total_remaining_thb'] == 64499.75
    cash_list = http.get('/api/cash/batches').json
    assert cash_list['batches'][0]['is_ipps_transfer']
    assert cash_list['summary']['total_remaining_thb'] == 6500.25
    assert cash_list['summary']['total_cost_usdt'] == 183.11

    incoming = http.get(cash).json
    outgoing = next(row for row in http.get(source + '/history').json['topups'] if row['id'] == movement['id'])
    assert incoming['source_name'] == crm.IPPS_CARD_NAME
    assert incoming['reference'] == outgoing['reference']
    assert outgoing['cash_transfer']['id'] == batch_id

    events = http.get('/api/finance/cashflow').json['events']
    matched, = [row for row in events if row['ref'] == transfer['reference']]
    assert (matched['article'], matched['flow'], matched['account'], matched['to_account']) == (
        'ipps_cash_transfer', 'transfer', 'card_thb', 'cash_thb',
    )
    assert (matched['amount'], matched['to_amount'], matched['cost_usdt']) == (6500.25, 6500.25, 183.11)
    assert matched['bank_card_id'] == source_id and matched['cash_batch_id'] == batch_id
    assert not {f'card_topup:{movement["id"]}', f'cash_batch:{batch_id}'} & {row['ref'] for row in events}

    replay = http.post(source + '/transfer-to-cash', json=payload)
    assert replay.status_code == 200 and replay.json['duplicate']
    assert replay.json['batch']['id'] == batch_id
    assert http.post(source + '/transfer-to-cash', json=payload | {'amount_thb': 6500}).status_code == 409
    assert http.post(source + '/transfer-to-cash', json=payload | {'reason': 'другая операция'}).status_code == 409

    cancel = http.delete(cash)
    assert cancel.status_code == 200 and cancel.json['transfer_cancelled']
    assert cancel.json['source_balance_thb'] == 71000
    assert cancel.json['batch']['status'] == 'archived'
    assert cancel.json['batch']['amount_thb'] == 6500.25 and cancel.json['batch']['cost_usdt'] == 183.11
    assert cancel.json['batch']['remaining_thb'] == 0
    again = http.delete(source + f"/topup/{movement['id']}")
    assert again.status_code == 200 and again.json['duplicate']
    assert http.get(cash).json['transfer_cancelled']
    assert http.post(source + '/transfer-to-cash', json=payload).status_code == 409
    assert http.post(cash.replace('/ipps-transfer', '/adjust'), json={'new_remaining': 6500.25}).status_code == 409
    assert http.patch(source + f"/topup/{movement['id']}", json={'purchase_rate': 38}).status_code == 400
    assert not [row for row in http.get('/api/finance/cashflow').json['events'] if row['ref'] == transfer['reference']]
    with factory() as db:
        assert db.query(crm.CashBatch).count() == 1
        saved = db.get(crm.CardTopup, movement['id'])
        assert saved.source_type == crm.IPPS_CASH_CANCELLED and saved.amount_thb == saved.cost_usdt == 0


@pytest.mark.parametrize('use', ['card', 'cash_adjust', 'deal', 'allocation'])
def test_used_cash_batch_cannot_be_reversed(ledger, payload, use):
    http, source_id, other_id, factory = ledger
    path = f'/api/cards/{source_id}/transfer-to-cash'
    transfer = http.post(path, json=payload).json
    batch_id = transfer['batch']['id']
    if use == 'card':
        spent = http.post(f'/api/cards/{other_id}/topup', json={
            'source_type': 'cash_batch', 'source_batch_id': batch_id, 'amount_thb': 100,
        })
        assert spent.status_code == 200, spent.json
    elif use == 'cash_adjust':
        spent = http.post(f'/api/cash/batches/{batch_id}/adjust', json={'new_remaining': 6400.25})
        assert spent.status_code == 200, spent.json
    else:
        with factory() as db:
            deal = crm.Deal(deal_type=crm.DealType.PAY_IN)
            db.add(deal)
            db.flush()
            if use == 'allocation':
                db.add(crm.CashAllocation(deal_id=deal.id, batch_id=batch_id,
                                          amount_thb=100, cost_usdt=3, batch_rate=33))
            else:
                deal.cash_batch_id = batch_id
            db.commit()
    cancelled = http.delete(f'/api/cash/batches/{batch_id}/ipps-transfer')
    assert cancelled.status_code == 409, cancelled.json
    with factory() as db:
        assert db.get(crm.BankCard, source_id).balance_thb == 64499.75
        assert db.get(crm.CashBatch, batch_id).status == crm.CashBatchStatus.ACTIVE


def test_transfer_validation_and_atomic_rollback(ledger, payload):
    http, source_id, other_id, factory = ledger
    path = f'/api/cards/{source_id}/transfer-to-cash'
    for invalid in ('0', '-1', True, 'NaN', '22.001', '1e12'):
        assert http.post(path, json=payload | {'amount_thb': invalid}).status_code == 400
    assert http.post(path, json=payload | {'request_id': 'x'}).status_code == 400
    assert http.post(path, json=payload | {'amount_thb': '71000.01'}).status_code == 409
    assert http.post(path, json=payload | {'purchase_rate': 38}).status_code == 400
    assert http.post(f'/api/cards/{other_id}/transfer-to-cash', json=payload).status_code == 400
    assert http.post('/api/cash/batches', json={
        'purchase_method': crm.IPPS_CASH_BATCH, 'amount_thb': 12, 'cost_usdt': 1,
    }).status_code == 400
    assert http.post(f'/api/cards/{source_id}/topup', json={
        'source_type': crm.IPPS_CASH_OUT, 'amount_thb': 12, 'cost_usdt': 1,
    }).status_code == 400

    def fail_on_movement(session, *_):
        if any(isinstance(item, crm.CardTopup) for item in session.new):
            raise RuntimeError('simulated insert failure')

    event.listen(factory.class_, 'before_flush', fail_on_movement)
    try:
        failed = http.post(path, json=payload)
        assert failed.status_code == 500, failed.json
    finally:
        event.remove(factory.class_, 'before_flush', fail_on_movement)
    with factory() as db:
        assert db.get(crm.BankCard, source_id).balance_thb == 71000
        assert db.query(crm.CashBatch).count() == 0
        assert db.query(crm.CardTopup).count() == 2
    assert http.post(path, json=payload).status_code == 201
