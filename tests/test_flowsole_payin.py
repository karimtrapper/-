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
    assert tc.put(f"/api/deals/{sber['id']}", json={'payin_account_key': 'flow_sole'}).json['deal']['payin_account_key'] == 'flow_sole'
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
    flow = _create(tc, _exchange(payin_account_key='flow_sole', status='completed'))
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
