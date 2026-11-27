"""Hotfix 6: real editor -> PUT -> every stored deal column, plus failed TronScan."""
import json
from datetime import datetime
from urllib.parse import urlsplit

import pytest
from sqlalchemy import select

import app as A
from tests.test_browser_crm import crm_server, chromium, ui  # real Flask/Chromium fixtures

CASES = [
    ('crypto', A.PayInMethod.CRYPTO_DIRECT, None),
    ('sbp', A.PayInMethod.SBER_WL, None),
    ('requisites', A.PayInMethod.SBER_REQS, None),
    ('flow_sole', A.PayInMethod.FLOW_SOLE_REQS, None),
    ('custom_flow_sole', A.PayInMethod.FLOW_SOLE_REQS, None),
    ('cash', A.PayInMethod.PARTNERS_CASH, A.PayOutSource.CASH_BATCH),
    ('card', A.PayInMethod.CRYPTO_DIRECT, A.PayOutSource.BANK_CARD),
    ('founder', A.PayInMethod.CRYPTO_DIRECT, A.PayOutSource.FOUNDER_PERSONAL),
    ('binance', A.PayInMethod.CRYPTO_DIRECT, A.PayOutSource.BINANCE),
    ('founder_no_conversion', A.PayInMethod.CRYPTO_DIRECT, A.PayOutSource.FOUNDER_PERSONAL),
    ('custom', A.PayInMethod.CRYPTO_DIRECT, None),
    ('null_methods', None, None),
]


def seed(case):
    name, method, source = case
    db = A.get_session()
    row = A.Deal(deal_type=A.DealType.PAY_IN, status=A.DealStatus.PENDING,
                 client_name='QA unchanged ' + name, manager_name='QA Manager',
                 payin_method=method, payout_source=source, payout_method=None,
                 created_at=datetime(2026, 9, 20, 13, 47, 28, 123456),
                 payin_amount_usdt=123.456789, payin_amount_rub=12345.67,
                 payout_amount_thb=3000, payout_amount_usdt=100.123456,
                 profit_usdt=23.333333, needs_reimbursement=False,
                 payout_founder_name='Теодор' if name.startswith('founder') else None,
                 is_custom=name.startswith('custom'),
                 custom_payin_amount=123.456789 if name.startswith('custom') else None,
                 custom_payout_amount=100.123456 if name.startswith('custom') else None,
                 custom_payin_currency='USDT' if name.startswith('custom') else None,
                 custom_payout_currency='USDT' if name.startswith('custom') else None)
    db.add(row)
    db.flush()
    if name in ('binance', 'founder_no_conversion'):
        wallet = A.Wallet(address='T_qa_hotfix6_' + name, label='QA wallet', active=True)
        db.add(wallet)
        db.flush()
        row.payout_wallet_id = wallet.id
        if name == 'founder_no_conversion':
            row.payout_no_conversion = True
        else:
            db.add(A.WalletOperation(wallet_id=wallet.id, deal_id=row.id, type='expense',
                                     amount=row.payout_amount_usdt, description='Original description'))
    if name == 'cash':
        batch = A.CashBatch(amount_thb=10000, remaining_thb=7000, cost_usdt=300, purchase_rate=33.3333)
        db.add(batch)
        db.flush()
        db.add(A.CashAllocation(deal_id=row.id, batch_id=batch.id, amount_thb=3000, cost_usdt=90, batch_rate=33.3333))
    if name == 'card':
        card = A.BankCard(bank_name='QA bank', balance_thb=7000)
        db.add(card)
        db.flush()
        row.bank_card_id = card.id
        db.add(A.CardAllocation(deal_id=row.id, card_id=card.id, amount_thb=3000, cost_usdt=90, card_rate=33.3333))
    if method == A.PayInMethod.FLOW_SOLE_REQS:
        receipt_uuid = 'crm-manual:qa-' + name
        row.payin_parts = json.dumps([{'uuid': receipt_uuid, 'amount_rub': row.payin_amount_rub}])
        db.add(A.SberIncome(uuid=receipt_uuid, account_key='flow_sole',
                            amount_rub=row.payin_amount_rub, claimed_deal_id=row.id,
                            operation_date='2026-09-20', claimed_at=datetime(2026, 9, 20, 13, 48)))
    db.commit()
    row_id = row.id
    db.close()
    return row_id


def snapshot():
    # Raw database rows, not to_dict(): covers updated_at, nulls, JSON and links.
    with A.engine.connect() as conn:
        return {table.name: list(conn.execute(select(table)).mappings())
                for table in [A.Deal.__table__, A.WalletOperation.__table__,
                              A.CashAllocation.__table__, A.CardAllocation.__table__,
                              A.DealAgent.__table__, A.Wallet.__table__,
                              A.BankCard.__table__, A.CashBatch.__table__, A.SberIncome.__table__]}


@pytest.mark.parametrize('case', CASES, ids=[x[0] for x in CASES])
def test_empty_put_is_read_only(crm_server, case):
    row_id = seed(case)
    client = A.app.test_client()
    with client.session_transaction() as auth:
        auth['user_id'] = 1
        auth['username'] = 'qa_browser'
    before = snapshot()
    response = client.put(f'/api/deals/{row_id}', json={})
    assert response.status_code == 200, response.json
    assert response.json['success'] is True
    assert snapshot() == before


@pytest.mark.browser
@pytest.mark.parametrize('case', CASES, ids=[x[0] for x in CASES])
def test_editor_unchanged_preserves_all_stored_columns(ui, case):
    page, errors, _, _ = ui
    row_id = seed(case)
    before = snapshot()
    page.evaluate('(id) => openDealEditor(id)', row_id)
    page.wait_for_load_state('networkidle')
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {}
    if not case[0].startswith('custom'):
        assert page.locator('[name=payout_source]').input_value() == (case[2].value if case[2] else '')
        assert page.locator('[name=payout_founder_name]').input_value() == ('Теодор' if case[0].startswith('founder') else '')
    with page.expect_response(lambda r: urlsplit(r.url).path == f'/api/deals/{row_id}'
                              and r.request.method == 'PUT') as saved:
        if case[0].startswith('custom'):
            page.locator('#customDealSubmit').click()
        else:
            page.locator('#createDealForm button[type=submit]').click()
    assert saved.value.request.post_data_json == {}
    assert saved.value.status == 200, saved.value.text()
    assert snapshot() == before
    assert not errors, errors


@pytest.mark.browser
def test_editor_diff_supports_edit_revert_and_clear(ui):
    page, errors, _, base = ui
    row_id = seed(CASES[0])
    page.evaluate('(id) => openDealEditor(id)', row_id)
    page.wait_for_load_state('networkidle')
    notes = page.locator('#createDealForm [name=notes]')
    notes.fill('Only this changed')
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {'notes': 'Only this changed'}
    notes.fill('')
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {}
    page.locator('#dealDate').fill('2026-09-21')
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {'created_at': '2026-09-21'}
    page.locator('#dealDate').fill('2026-09-20')
    # Select changes, including explicit null, are represented in the diff.
    page.evaluate("document.querySelector('[name=payout_founder_name]').value = 'Андрей'")
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {'payout_founder_name': 'Андрей'}
    page.evaluate("document.querySelector('[name=payout_founder_name]').value = ''")
    assert page.evaluate('dealFormDiff(serializeDealEditor())') == {}
    notes.fill('Only this changed')
    with page.expect_response(lambda r: urlsplit(r.url).path == f'/api/deals/{row_id}'
                              and r.request.method == 'PUT') as saved:
        page.locator('#createDealForm button[type=submit]').click()
    assert saved.value.status == 200, saved.value.text()
    assert saved.value.request.post_data_json == {'notes': 'Only this changed'}
    state = page.request.get(base + f'/api/deals/{row_id}').json()['deal']
    assert state['created_at'] == '2026-09-20T13:47:28.123456'
    assert state['payout_source'] is None
    assert state['payout_founder_name'] is None
    assert state['needs_reimbursement'] is False
    page.evaluate('(id) => openDealEditor(id)', row_id)
    page.wait_for_load_state('networkidle')
    notes.fill('')
    with page.expect_response(lambda r: urlsplit(r.url).path == f'/api/deals/{row_id}'
                              and r.request.method == 'PUT') as cleared:
        page.locator('#createDealForm button[type=submit]').click()
    assert cleared.value.status == 200, cleared.value.text()
    assert cleared.value.request.post_data_json == {'notes': None}
    assert cleared.value.json()['deal']['notes'] is None
    assert not errors, errors


@pytest.mark.parametrize('cached', [False, True])
def test_incoming_none_response_returns_structured_errors(monkeypatch, cached, crm_server):
    A.Base.metadata.create_all(A.engine)
    db = A.get_session()
    wallet = A.Wallet(address='T_hotfix6_none_response', label='QA', active=True, is_monitored=True)
    db.add(wallet)
    db.commit()
    address = wallet.address
    db.close()
    client = A.app.test_client()
    with client.session_transaction() as auth:
        auth['user_id'] = 1
        auth['username'] = 'qa_browser'
    monkeypatch.setattr(A, 'STAND_MODE', True)
    monkeypatch.setattr(A, '_stand_tronscan_get', lambda *a, **k: None)
    old_tx = dict(tx_hash='qa-cached', from_address='T_sender', to_address=address,
                  amount_usdt=12, timestamp='2026-09-20T10:00:00', is_incoming=True)
    monkeypatch.setitem(A.TRONSCAN_CACHE, 'incoming', {'data': [old_tx] if cached else [], 'timestamp': 0})
    response = client.get('/api/transactions/incoming', query_string={
        'wallet': address, 'force_refresh': 'true'})
    assert response.status_code == 200, response.json
    assert response.json['success'] is True
    assert response.json['wallets_errors'] == [{'address': address, 'error': 'TronScan returned no response'}]
    assert response.json['available'] == ([old_tx] if cached else [])
    db = A.get_session()
    db.query(A.Wallet).filter_by(address=address).delete()
    db.commit()
    db.close()


@pytest.mark.parametrize('patch', [{'notes': 'only notes'}, {'payin_amount_usdt': 200}])
def test_sparse_put_preserves_agent_cascade(crm_server, patch):
    row_id = seed(CASES[0])
    db = A.get_session()
    deal = db.query(A.Deal).filter_by(id=row_id).one()
    A._apply_deal_agents(db, deal, [
        {'name': 'QA first', 'tier': 1, 'comp_model': 'revshare', 'percent': 20},
        {'name': 'QA second', 'tier': 2, 'comp_model': 'revshare', 'percent': 50},
    ])
    db.commit()
    db.close()
    client = A.app.test_client()
    with client.session_transaction() as auth:
        auth['user_id'] = 1
        auth['username'] = 'qa_browser'
    response = client.put(f'/api/deals/{row_id}', json=patch)
    assert response.status_code == 200, response.json
    deal = response.json['deal']
    agents = sorted(deal['agents'], key=lambda a: a['tier'])
    assert [(a['name'], a['tier'], a['percent']) for a in agents] == [
        ('QA first', 1, 20), ('QA second', 2, 50)]
    gross = round(deal['payin_amount_usdt'] - deal['payout_amount_usdt'], 2)
    first = round(gross * .2, 2)
    second = round((gross - first) * .5, 2)
    assert [a['payout_usdt'] for a in agents] == [first, second]
    assert deal['net_profit_usdt'] == round(gross - first - second, 2)


@pytest.mark.browser
@pytest.mark.parametrize('custom', [False, True])
def test_flow_sole_sparse_edit_keeps_receipt_and_method(ui, custom):
    page, errors, _, base = ui
    case = next(c for c in CASES if c[0] == ('custom_flow_sole' if custom else 'flow_sole'))
    row_id = seed(case)
    before = page.request.get(base + f'/api/deals/{row_id}').json()['deal']
    incomes_before = snapshot()['sber_incomes']
    page.evaluate('(id) => openDealEditor(id)', row_id)
    page.wait_for_load_state('networkidle')
    selector = '#customPayinMethod' if custom else '#payinMethod'
    assert page.locator(selector).input_value() == 'flow_sole_reqs'
    assert page.locator(selector + ' option[value=""]').count() == 1
    assert page.locator(selector + ' option[value="flow_sole_reqs"]').count() == 1
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--coral').trim()") == '#C2410C'
    receipt_posts = []
    page.on('request', lambda r: receipt_posts.append(r.url)
            if r.method == 'POST' and '/manual-rub-income' in r.url else None)
    page.locator('#customNotes' if custom else '#createDealForm [name=notes]').fill('Flow note')
    with page.expect_response(lambda r: urlsplit(r.url).path == f'/api/deals/{row_id}'
                              and r.request.method == 'PUT') as saved:
        page.locator('#customDealSubmit' if custom else '#createDealForm button[type=submit]').click()
    assert saved.value.status == 200, saved.value.text()
    assert saved.value.request.post_data_json == {'notes': 'Flow note'}
    after = saved.value.json()['deal']
    for key in ('created_at', 'payin_method', 'payin_parts', 'payin_amount_rub', 'payin_amount_usdt'):
        assert after[key] == before[key], key
    assert snapshot()['sber_incomes'] == incomes_before
    assert receipt_posts == []
    assert not errors, errors
