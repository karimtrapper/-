"""Only final stand CRM close posts the personal leasehold payout."""
import pytest

import app as m
from tests.test_ipps_realty import COST, OPENING_THB, PATH, THB, _draft, sqlite_runtime  # noqa: F401


@pytest.mark.parametrize('source', ['bank_card', 'founder_personal'])
def test_manual_personal_leasehold_closes_once(monkeypatch, source):
    client, payload, ipps_id, personal_id = _draft(monkeypatch)
    current = client.get('/api/stand/state').json
    state = current['data']
    board = state['deals'][0]
    original_balance = state.get('bal')
    board.update(kind='Личный счёт', unverified_flow_confirmation=['personal_realty', 'crypto'])
    wallet_address = 'TLeaseholdSyntheticPayer'
    with m.get_session() as db:
        card = db.get(m.BankCard, personal_id)
        card.personal_owner = 'andrey'
        card.balance_thb = OPENING_THB
        topup = m.CardTopup(card_id=personal_id, amount_thb=OPENING_THB, cost_usdt=2 * COST,
                            purchase_rate=THB / COST)
        wallet = m.Wallet(address=wallet_address, label='Leasehold payer')
        db.add_all([topup, wallet])
        db.commit()
        wallet_id = wallet.id
        topups_before = db.query(m.CardTopup).count()
    crm = payload['crm']
    crm.update(deal_kind='personal_realty', payout_source=source)
    if source == 'bank_card':
        board.update(paySrc='scb', payout={'bankCardId': personal_id, 'thb': THB})
        crm['bank_card_id'] = personal_id
    else:
        payout_hash = 'a' * 64
        board.update(paySrc='founder', payout={
            'thb': THB, 'usdt': COST, 'founder': 'Андрей', 'walletId': wallet_id,
            'hashes': [{'hash': payout_hash, 'network': 'trc20', 'amount': COST,
                        'from_address': wallet_address, 'to_address': 'TLeaseholdSyntheticBroker'}],
        })
        crm.pop('bank_card_id')
        crm.update(payout_wallet_id=wallet_id, payout_founder_name='Андрей',
                   payout_amount_usdt=COST, needs_reimbursement=True,
                   payout_tx_hashes=[{'hash': payout_hash, 'network': 'trc20', 'amount_usdt': COST,
                                      'from_address': wallet_address, 'to_address': 'TLeaseholdSyntheticBroker'}])
        monkeypatch.setattr(m, '_tx_info_by_network', lambda *_: {
            'amount_usdt': COST, 'total_out_usdt': COST,
            'from_address': wallet_address, 'to_address': 'TLeaseholdSyntheticBroker',
        })

    saved = client.put('/api/stand/state', json={'version': current['version'], 'data': state})
    assert saved.status_code == 200, saved.json
    payload['version'] = saved.json['version']
    ready = client.post(PATH + '/check', json=payload)
    assert ready.status_code == 200 and ready.json['ready'], ready.json
    with m.get_session() as db:
        assert db.get(m.BankCard, personal_id).balance_thb == OPENING_THB
        assert db.query(m.CardAllocation).count() == db.query(m.PayoutTxUse).count() == 0

    closed = client.post(PATH, json=payload)
    assert closed.status_code == 201, closed.json
    result = closed.json
    assert result['deal']['payout_amount_usdt'] == COST
    assert result['deal']['profit_usdt'] == 100
    assert result['deal']['company_fee_usdt'] is None
    assert result['deal']['needs_reimbursement'] == (source == 'founder_personal')
    assert result['data'].get('bal') == original_balance
    assert result['data']['deals'][0]['payout']['usdt'] == COST
    replay = client.post(PATH, json=payload)
    assert replay.status_code == 200 and replay.json['duplicate'] is True, replay.json
    assert replay.json['deal']['id'] == result['deal']['id']
    with m.get_session() as db:
        assert db.get(m.BankCard, ipps_id).balance_thb == OPENING_THB
        assert db.get(m.BankCard, personal_id).balance_thb == (THB if source == 'bank_card' else OPENING_THB)
        assert db.query(m.CardAllocation).count() == int(source == 'bank_card')
        assert db.query(m.PayoutTxUse).count() == int(source == 'founder_personal')
        assert db.query(m.CardTopup).count() == topups_before
        assert db.query(m.StandCrmLink).count() == 1
