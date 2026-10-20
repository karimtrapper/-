"""Flow Sole is an account identity on the existing SBER_REQS payment method."""
import pytest

import app as module


@pytest.fixture
def tc(monkeypatch):
    module.app.config['TESTING'] = True
    # Capture sync calls locally; no Sheets connection is made by these tests.
    monkeypatch.setattr(module, 'sync_deals_to_gsheet', lambda deals: None)
    monkeypatch.setattr(module, 'sync_realty_deal_to_gsheet', lambda deal: None)
    monkeypatch.setattr(module, 'sync_referrer_reward_to_gsheet', lambda deal: None)
    db = module.get_session()
    try:
        admin = db.query(module.AdminUser).first()
        if admin is None:
            admin = module.AdminUser(username='flowsole_test_admin', display_name='Test',
                                     password_hash=module.AdminUser.hash_password('test'))
            db.add(admin)
            db.commit()
        admin_id = admin.id
    finally:
        db.close()
    with module.app.test_client() as client:
        with client.session_transaction() as session:
            session['user_id'] = admin_id
        yield client


def _exchange(**overrides):
    payload = {
        'client_name': 'Flow Sole regression', 'deal_type': 'pay_in',
        'payin_method': 'sber_reqs', 'payin_amount_rub': 85000,
        'payin_amount_usdt': 1000, 'payin_rate_rub_usdt': 85,
        'payout_amount_usdt': 970, 'payout_method': 'transfer',
    }
    payload.update(overrides)
    return payload


def _create(tc, payload):
    response = tc.post('/api/deals', json=payload)
    assert response.status_code == 201, response.json
    return response.json['deal']


def test_exchange_create_reload_update_reset_and_profit(tc):
    sber = _create(tc, _exchange(client_name='Sber comparison'))
    flow = _create(tc, _exchange(payin_account_key='flow_sole'))
    assert flow['payin_method'] == sber['payin_method'] == 'sber_reqs'
    assert flow['payin_account_key'] == 'flow_sole'
    assert sber['payin_account_key'] is None
    assert flow['profit_usdt'] == pytest.approx(sber['profit_usdt'])
    assert flow['net_profit_usdt'] == pytest.approx(sber['net_profit_usdt'])
    assert tc.get(f"/api/deals/{flow['id']}").json['deal']['payin_account_key'] == 'flow_sole'

    changed = tc.put(f"/api/deals/{flow['id']}", json={'payin_amount_rub': 170000,
                                                          'payin_amount_usdt': 2000,
                                                          'payout_amount_usdt': 1940}).json['deal']
    assert changed['payin_account_key'] == 'flow_sole'
    assert changed['profit_usdt'] == pytest.approx(60)
    switched = tc.put(f"/api/deals/{flow['id']}", json={'payin_method': 'crypto_direct'}).json['deal']
    assert switched['payin_account_key'] is None
    assert tc.get(f"/api/deals/{flow['id']}").json['deal']['payin_account_key'] is None
    assert tc.put(f"/api/deals/{flow['id']}", json={'payin_method': 'sber_reqs'}).json['deal']['payin_account_key'] is None
    assert tc.put(f"/api/deals/{sber['id']}", json={
        'payin_account_key': 'flow_sole', 'status': 'pending'
    }).json['deal']['payin_account_key'] == 'flow_sole'
    assert tc.put(f"/api/deals/{sber['id']}", json={'payin_account_key': None}).json['deal']['payin_account_key'] is None


def test_realty_and_custom_roundtrip(tc):
    realty_payload = {
        'client_name': 'Flow Realty', 'deal_type': 'pay_in', 'deal_kind': 'mf_realty',
        'payin_method': 'sber_reqs', 'payin_account_key': 'flow_sole',
        'payin_amount_rub': 1693980, 'payin_amount_usdt': 19929.17,
        'realty_purpose': 'Unit', 'invoice_amount_thb': 622370,
        'buy_rate_thb_usdt': 33.22, 'company_percent': 1,
    }
    realty = _create(tc, realty_payload)
    ordinary_realty = _create(tc, {**realty_payload, 'client_name': 'Sber Realty',
                                   'payin_account_key': None})
    assert realty['payin_account_key'] == 'flow_sole'
    assert realty['profit_usdt'] == pytest.approx(ordinary_realty['profit_usdt'])
    assert realty['net_profit_usdt'] == pytest.approx(ordinary_realty['net_profit_usdt'])
    assert tc.get(f"/api/deals/{realty['id']}").json['deal']['payin_account_key'] == 'flow_sole'
    assert tc.put(f"/api/deals/{realty['id']}", json={'company_percent': 0.5}).json['deal']['payin_account_key'] == 'flow_sole'

    custom = _create(tc, _exchange(
        client_name='Flow Custom', payin_account_key='flow_sole', is_custom=True,
        custom_payin_currency='RUB', custom_payin_amount=85000, custom_payin_rate=85,
        custom_payout_currency='USDT', custom_payout_amount=970))
    assert custom['payin_account_key'] == 'flow_sole'
    assert tc.get(f"/api/deals/{custom['id']}").json['deal']['payin_account_key'] == 'flow_sole'
    assert tc.put(f"/api/deals/{custom['id']}", json={'notes': 'edited'}).json['deal']['payin_account_key'] == 'flow_sole'
    db = module.get_session()
    try:
        assert module.build_deal_rows(db.get(module.Deal, custom['id']), 1)[0][15] == 'Flow Sole (СГБ, реквизиты)'
    finally:
        db.close()


def test_labels_analytics_sheet_and_sber_pool_guard(tc, monkeypatch):
    synced_rows = []
    monkeypatch.setattr(module, 'sync_deals_to_gsheet',
                        lambda deals: synced_rows.extend(module.build_deal_rows(d, 1) for d in deals))
    monkeypatch.setattr(module, '_tron_confirmed_payin_amount', lambda hash_: 1000)
    flow = _create(tc, _exchange(payin_account_key='flow_sole', payin_tx_hash='flow-label-hash',
        payin_tx_hashes=[{'hash': 'flow-label-hash', 'network': 'trc20'}]))
    assert tc.post(f"/api/deals/{flow['id']}/verify-payin").status_code == 200
    flow = tc.put(f"/api/deals/{flow['id']}", json={'status': 'completed'}).json['deal']
    assert synced_rows and synced_rows[0][0][15] == 'Flow Sole (СГБ, реквизиты)'
    db = module.get_session()
    try:
        deal = db.get(module.Deal, flow['id'])
        assert deal.payin_method is module.PayInMethod.SBER_REQS
        assert module.build_deal_rows(deal, 1)[0][15] == 'Flow Sole (СГБ, реквизиты)'
        ledger = module._ledger_row(deal, {}, {})
        assert ledger['pay_in']['method_label'] == 'Flow Sole (СГБ, реквизиты)'
        totals = module._ledger_totals([ledger])
        assert totals['by_payin_method']['flow_sole_reqs']['label'] == 'Flow Sole (СГБ, реквизиты)'
    finally:
        db.close()
    dashboard = tc.get('/api/analytics/dashboard').json
    assert dashboard['dashboard']['charts']['methods']['flow_sole_reqs']['count'] >= 1
    assert tc.post('/api/deals', json=_exchange(payin_account_key='flow_sole',
               payin_parts=[{'uuid': 'sber-income', 'amount_rub': 85000}])).status_code == 400
    assert tc.put(f"/api/deals/{flow['id']}", json={'payin_parts': [
        {'uuid': 'sber-income', 'amount_rub': 85000}]}).status_code == 400


def test_legacy_method_and_invalid_key(tc):
    assert 'flow_sole_reqs' not in [method.value for method in module.PayInMethod]
    assert module.PAYIN_METHOD_LABELS['sber_reqs'] == 'сбер реквизиты'
    assert tc.post('/api/deals', json=_exchange(payin_account_key='unknown')).status_code == 400
    old = _create(tc, _exchange())
    assert old['payin_account_key'] is None
    assert tc.get(f"/api/deals/{old['id']}").json['deal']['payin_method'] == 'sber_reqs'
    assert module.Deal(payin_method=module.PayInMethod.SBER_REQS).payin_account_key is None


def test_flow_sole_draft_verification_and_closing(tc, monkeypatch):
    assert tc.post('/api/deals', json=_exchange(
        payin_account_key='flow_sole', status='completed')).status_code == 409
    assert tc.post('/api/deals', json=_exchange(
        payin_account_key='flow_sole', payout_tx_hash='new-payout')).status_code == 409
    assert tc.post('/api/deals', json=_exchange(
        payin_account_key='flow_sole',
        payout_tx_hashes=[{'hash': 'new-payout', 'amount_usdt': 970}])).status_code == 409
    draft = _create(tc, _exchange(payin_account_key='flow_sole',
                                   payin_tx_hash='flow-proof-hash',
                                   payin_tx_hashes=[{'hash': 'flow-proof-hash', 'network': 'trc20'}],
                                   payin_amount_usdt=700))
    deal_id = draft['id']
    assert draft['status'] == 'pending'
    assert draft['payin_amount_usdt'] == 700
    assert draft['profit_usdt'] == pytest.approx(-270)
    assert draft['payin_tx_verified'] is False
    assert tc.put(f'/api/deals/{deal_id}', json={'payout_tx_hash': 'new-payout'}).status_code == 409
    assert tc.put(f'/api/deals/{deal_id}', json={'payout_tx_hashes': [
        {'hash': 'new-payout', 'amount_usdt': 970}]}).status_code == 409
    assert tc.put(f'/api/deals/{deal_id}', json={'notes': 'still provisional'}).status_code == 200
    assert tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'}).status_code == 409
    blocked_reimbursement = tc.post('/api/reimbursements', json={
        'founder_name': 'QA Founder', 'deal_ids': [deal_id],
        'amount_usdt': 100, 'tx_hash': 'reimbursement-hash'})
    assert blocked_reimbursement.status_code == 409
    assert blocked_reimbursement.json['deal_ids'] == [deal_id]

    monkeypatch.setattr(module, '_tron_confirmed_payin_amount', lambda hash_: 250)
    mismatch = tc.post(f'/api/deals/{deal_id}/verify-payin')
    assert mismatch.status_code == 409
    assert mismatch.json['entered_usdt'] == 700
    assert mismatch.json['chain_usdt'] == 250
    assert mismatch.json['claimed_usdt'] == 250
    after = tc.get(f'/api/deals/{deal_id}').json['deal']
    assert after['payin_amount_usdt'] == 700
    assert after['profit_usdt'] == pytest.approx(-270)
    assert after['payin_tx_verified'] is False
    db = module.get_session()
    try:
        assert db.query(module.PayinTxUse).filter_by(deal_id=deal_id).count() == 0
    finally:
        db.close()

    monkeypatch.setattr(module, '_tron_confirmed_payin_amount', lambda hash_: 700)
    confirmed = tc.post(f'/api/deals/{deal_id}/verify-payin')
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['deal']['payin_amount_usdt'] == 700
    assert confirmed.json['deal']['payin_tx_verified'] is True
    completed = tc.put(f'/api/deals/{deal_id}', json={'status': 'completed'})
    assert completed.status_code == 200, completed.json
    assert completed.json['deal']['status'] == 'completed'


def test_flow_sole_existing_completed_compatibility_and_changed_proof(tc):
    db = module.get_session()
    try:
        old = module.Deal(client_name='Historic Flow', deal_type=module.DealType.PAY_IN,
                          payin_method=module.PayInMethod.SBER_REQS,
                          payin_account_key='flow_sole', payin_amount_usdt=400,
                          payin_tx_hash='historic-hash',
                          payout_amount_usdt=390, status=module.DealStatus.COMPLETED,
                          payin_tx_verified=False)
        db.add(old)
        db.commit()
        deal_id = old.id
    finally:
        db.close()
    unchanged = tc.put(f'/api/deals/{deal_id}', json={
        'notes': 'historic note', 'payin_amount_usdt': 400,
        'payin_tx_hash': 'historic-hash',
        'payin_tx_hashes': [{'hash': 'historic-hash', 'network': 'trc20',
                             'amount_usdt': None}]})
    assert unchanged.status_code == 200, unchanged.json
    assert unchanged.json['deal']['status'] == 'completed'
    assert unchanged.json['deal']['payin_amount_usdt'] == 400
    changed = tc.put(f'/api/deals/{deal_id}', json={'payin_amount_usdt': 500})
    assert changed.status_code == 409
    assert tc.get(f'/api/deals/{deal_id}').json['deal']['payin_amount_usdt'] == 400


def test_flow_sole_erc_proof_uses_etherscan_only(tc, monkeypatch):
    draft = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_tx_hash='0x' + 'e' * 64,
        payin_tx_hashes=[{'hash': '0x' + 'e' * 64, 'network': 'erc20', 'amount_usdt': 1000}]))
    monkeypatch.setattr(module, '_tron_confirmed_payin_amount',
                        lambda hash_: pytest.fail('ERC proof must not call TronScan'))
    monkeypatch.setattr(module, '_etherscan_tx_info', lambda hash_: {})
    offline = tc.post(f"/api/deals/{draft['id']}/verify-payin")
    assert offline.status_code == 409
    assert tc.get(f"/api/deals/{draft['id']}").json['deal']['payin_tx_verified'] is False
    monkeypatch.setattr(module, '_etherscan_tx_info', lambda hash_: {'amount_usdt': 1000})
    confirmed = tc.post(f"/api/deals/{draft['id']}/verify-payin")
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['deal']['payin_tx_verified'] is True


def test_flow_sole_explicit_partial_hash_respects_remaining_balance(tc, monkeypatch):
    monkeypatch.setattr(module, '_tron_confirmed_payin_amount', lambda hash_: 2000)
    partial = {'hash': 'shared-flow-hash', 'network': 'trc20',
               'amount_usdt': 1000}
    first = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_tx_hash='shared-flow-hash', payin_tx_hashes=[partial]))
    confirmed = tc.post(f"/api/deals/{first['id']}/verify-payin")
    assert confirmed.status_code == 200, confirmed.json
    assert confirmed.json['claimed_usdt'] == 1000
    assert confirmed.json['chain_usdt'] == 2000

    second = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_tx_hash='shared-flow-hash', payin_tx_hashes=[partial]))
    assert tc.post(f"/api/deals/{second['id']}/verify-payin").status_code == 200
    third = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_tx_hash='shared-flow-hash', payin_tx_hashes=[partial]))
    no_balance = tc.post(f"/api/deals/{third['id']}/verify-payin")
    assert no_balance.status_code == 409
    assert tc.get(f"/api/deals/{third['id']}").json['deal']['payin_tx_verified'] is False

    wrong_total = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_amount_usdt=900, payin_tx_hash='other-flow-hash',
        payin_tx_hashes=[{'hash': 'other-flow-hash', 'network': 'trc20',
                          'amount_usdt': 1000}]))
    mismatch = tc.post(f"/api/deals/{wrong_total['id']}/verify-payin")
    assert mismatch.status_code == 409
    assert mismatch.json['entered_usdt'] == 900
    assert mismatch.json['claimed_usdt'] == 1000
    assert tc.get(f"/api/deals/{wrong_total['id']}").json['deal']['payin_amount_usdt'] == 900

    implicit = _create(tc, _exchange(payin_account_key='flow_sole',
        payin_tx_hash='implicit-flow-hash',
        payin_tx_hashes=[{'hash': 'implicit-flow-hash', 'network': 'trc20',
                          'amount_usdt': None}]))
    full_required = tc.post(f"/api/deals/{implicit['id']}/verify-payin")
    assert full_required.status_code == 409
    assert full_required.json['claimed_usdt'] == 2000


def test_unverified_flow_draft_does_not_spend_card_balance(tc):
    db = module.get_session()
    try:
        card = module.BankCard(bank_name='Synthetic card', card_name='Synthetic',
                               balance_thb=50000, status=module.CashBatchStatus.ACTIVE)
        db.add(card)
        db.commit()
        card_id = card.id
    finally:
        db.close()
    draft = _create(tc, _exchange(payin_account_key='flow_sole',
        payout_source='bank_card', bank_card_id=card_id, payout_amount_thb=30000))
    assert draft['status'] == 'pending'
    assert draft['profit_usdt'] == pytest.approx(30)
    db = module.get_session()
    try:
        assert db.get(module.BankCard, card_id).balance_thb == 50000
        assert db.query(module.CardAllocation).filter_by(deal_id=draft['id']).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize('confirmed,revert,result,expected', [
    (True, False, 'SUCCESS', 500),
    (False, False, 'SUCCESS', None),
    (True, True, 'SUCCESS', None),
    (True, False, 'REVERT', None),
    (None, None, None, None),
])
def test_tron_proof_requires_confirmed_success(monkeypatch, confirmed, revert, result, expected):
    monkeypatch.delenv('PYTEST_CURRENT_TEST', raising=False)
    payload = {'hash': 'proof-hash', 'confirmed': confirmed, 'revert': revert,
               'contractRet': result, 'trc20TransferInfo': [{
                   'contract_address': module.USDT_TRC20_CONTRACT,
                   'decimals': 6, 'amount_str': '500000000'}]}

    class Response:
        status_code = 200
        def json(self):
            return payload

    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: Response())
    assert module._tron_confirmed_payin_amount('proof-hash') == expected
