"""IPPS realty reuses the existing account, rate basis and card allocation."""
import json
import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as m
from tests.payin_registry import RECEIVER, ensure_payin_wallet
from tests.test_stand_crm_close_atomic import _client, _counts
from tests.test_wallet_roles_pg_qa import pg, start_app  # noqa: F401


THB = 34000.25
OPENING_THB = THB * 2
PAYIN = 1100
COST = 1000
PATH = '/api/stand/deals/7411/crm-close'


@pytest.fixture(autouse=True)
def sqlite_runtime(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "ipps.db"}'
    engine = create_engine(url)
    try:
        m.Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(m, 'engine', engine)
        monkeypatch.setattr(m, 'get_session', factory)
        monkeypatch.setattr(m, 'SessionLocal', factory)
        monkeypatch.setattr(m, 'DATABASE_URL', url)
        yield
    finally:
        engine.dispose()


def _network_payin(*args, **kwargs):
    return {'status': 'confirmed', 'verifiedAmount': PAYIN,
            'verifiedAt': '2026-11-20T12:00:00Z',
            'from': 'TSyntheticSenderForIPPS', 'to': RECEIVER}


def _accounts(db, balance=OPENING_THB):
    ipps = m.BankCard(bank_name='Другой', card_name='IPPS счет компании',
                      holder_name='Synthetic QA', balance_thb=balance)
    wrong = m.BankCard(bank_name='Другой', card_name='Different Company',
                       holder_name='Synthetic QA', balance_thb=100000)
    db.add_all([ipps, wrong])
    db.flush()
    db.add(m.CardTopup(card_id=ipps.id, amount_thb=OPENING_THB, cost_usdt=COST * 2,
                       purchase_rate=THB / COST, source_type='separate'))
    return ipps.id, wrong.id


def _draft(monkeypatch, balance=OPENING_THB, *, board_balance=True):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, 'verify_transfer', _network_payin)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    m._stand_migrate()
    ensure_payin_wallet()
    with m.get_session() as db:
        user = m.AdminUser(username='ipps-qa-' + secrets.token_hex(4),
                           display_name='IPPS QA Manager', role='manager', password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        card_id, wrong_id = _accounts(db, balance)
        row = db.get(m.StandState, 1) or m.StandState(id=1)
        state = {'deals': []}
        if board_balance:
            state['bal'] = {'ipps': 1250000, 'cash': 200, 'scb': 500, 'usdt': 900}
        row.data = json.dumps(state)
        row.notified = '[]'
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.add(row)
        db.commit()

    client = _client(uid)
    tx = secrets.token_hex(32)
    deal = {
        'id': 7411, 'code': 'QA-7411', 'client': 'Synthetic IPPS', 'managerUserId': uid,
        'type': 'Оплата недвижимости', 'kind': 'ИППС',
        'manual': True, 'step': 'manual', 'isTask': False, 'payType': 'Крипта',
        'amountUsdt': PAYIN, 'amountThb': THB, 'paySrc': 'ipps',
        'payinHashes': [{'hash': tx, 'network': 'trc20', 'amount': PAYIN,
                        'from': 'TSyntheticSenderForIPPS', 'to': RECEIVER}],
        'payout': {'thb': THB, 'usdt': 799, 'bankCardId': card_id},
        'rates': {'usdtThb': 4}, 'companyPct': 49,
        'unverified_flow_confirmation': ['ipps_realty', 'crypto'],
        'log': [],
    }
    snapshot = {**state, 'deals': [deal]}
    saved = client.put('/api/stand/state', json={'version': 1, 'data': snapshot})
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][0]['originMode'] == 'manual'
    with m.get_session() as db:
        assert db.get(m.BankCard, card_id).balance_thb == balance
        assert not db.query(m.CardAllocation).first()
    crm = {
        'deal_kind': 'ipps_realty', 'payin_method': 'crypto_direct', 'client_name': deal['client'],
        'payin_amount_usdt': PAYIN, 'payout_source': 'bank_card', 'bank_card_id': card_id,
        'payout_amount_thb': THB,
        'payin_tx_hashes': [{'hash': tx, 'network': 'trc20', 'amount_usdt': PAYIN}],
        'agents': [{'name': 'Synthetic Agent', 'tier': 1, 'comp_model': 'revshare', 'percent': 10}],
    }
    return client, {'version': saved.json['version'], 'crm': crm}, card_id, wrong_id


def _assert_financial_rows(deal_id, card_id, remaining=THB):
    with m.get_session() as db:
        for model in (m.CashAllocation, m.WalletOperation, m.PayoutTxUse):
            assert not db.query(model).filter_by(deal_id=deal_id).first()
        alloc = db.query(m.CardAllocation).filter_by(deal_id=deal_id).one()
        assert (alloc.card_id, alloc.amount_thb, alloc.cost_usdt) == (card_id, THB, COST)
        assert db.get(m.BankCard, card_id).balance_thb == remaining
        expenses = [ev for ev in m._finance_events(db)
                    if ev.get('deal_id') == deal_id and ev.get('flow') == 'out']
        assert [(ev['account'], ev['currency'], ev['amount'], ev['product']) for ev in expenses] == [
            ('card_thb', 'THB', THB, 'ipps_realty')]
        sheet = m.build_realty_rows(db.get(m.Deal, deal_id))[0]
        assert sheet[2] == 'usdt-thb · ИППС'
        assert [sheet[col] for col in (6, 10, 17, 18, 20)] == [THB, COST, 100, 10, 90]
        assert all(sheet[col] == '' for col in (7, 8, 11, 12, 13, 14, 15, 16, 19))


def _assert_close(client, payload, card_id, remaining=THB):
    before = _counts()
    balances = client.get('/api/stand/state').json['data'].get('bal')
    readiness = client.post(PATH + '/check', json=payload)
    assert readiness.status_code == 200 and readiness.json['ready'], readiness.json
    result = client.post(PATH, json=payload)
    assert result.status_code == 201, result.json
    result = result.json
    saved = result['deal']
    deal_id = saved['id']
    assert (saved['payout_source'], saved['bank_card_id']) == ('bank_card', card_id)
    assert (saved['payout_amount_thb'], saved['payout_amount_usdt']) == (THB, COST)
    assert (saved['profit_usdt'], saved['net_profit_usdt'], saved['referrer_payout_usdt']) == (100, 90, 10)
    assert saved['needs_reimbursement'] is False
    assert all(saved[k] is None for k in ('payout_wallet_id', 'payout_founder_name', 'company_fee_usdt'))
    assert result['data'].get('bal') == balances
    assert result['data']['deals'][0]['payout']['usdt'] == COST
    assert _counts() == (before[0] + 1, before[1] + 1)
    repeat = client.post(PATH, json=payload)
    assert repeat.status_code == 200 and repeat.json['duplicate'] is True, repeat.json
    assert repeat.json['deal']['id'] == deal_id
    assert _counts() == (before[0] + 1, before[1] + 1)

    path = f'/api/deals/{deal_id}'
    assert client.put(path, json={'notes': 'Synthetic note'}).status_code == 200
    reopened = client.get(path).json['deal']
    assert reopened['notes'] == 'Synthetic note'
    assert reopened['profit_usdt'] == 100 and reopened['net_profit_usdt'] == 90
    _assert_financial_rows(deal_id, card_id, remaining)
    return result


@pytest.mark.parametrize('board_balance', [True, False])
def test_ipps_manual_close_reopen_and_retry(monkeypatch, board_balance):
    client, payload, card_id, _ = _draft(monkeypatch, board_balance=board_balance)
    _assert_close(client, payload, card_id)


def test_ipps_follows_existing_card_warning_at_negative_balance(monkeypatch):
    client, payload, card_id, _ = _draft(monkeypatch, balance=15)
    result = _assert_close(client, payload, card_id, 15 - THB)
    assert 'ушёл в минус' in result['warning']


def test_ipps_failure_after_allocation_rolls_back_debit(monkeypatch):
    client, payload, card_id, _ = _draft(monkeypatch)
    counts = _counts()
    with monkeypatch.context() as failure:
        def fail_after_deal_flush(*args):
            raise RuntimeError('synthetic failure before close commit')
        failure.setattr(m, '_stand_capture_close_outbox', fail_after_deal_flush)
        refused = client.post(PATH, json=payload)
    assert refused.status_code == 500 and refused.json['error'] == 'close_failed'
    assert _counts() == counts
    with m.get_session() as db:
        assert db.get(m.BankCard, card_id).balance_thb == OPENING_THB
        assert not db.query(m.CardAllocation).first()
    _assert_close(client, payload, card_id)


@pytest.mark.parametrize('patch', [
    {'payout_amount_thb': 0}, {'payout_amount_thb': 1.001}, {'payout_amount_thb': '1e30'},
    {'payout_amount_usdt': 999}, {'payout_source': 'founder_personal'},
    {'needs_reimbursement': True}, {'payout_wallet_id': 93},
    {'payout_tx_hashes': [{'hash': 'would-be-wallet-expense'}]},
])
def test_ipps_rejects_forged_close(monkeypatch, patch):
    client, payload, card_id, _ = _draft(monkeypatch)
    counts = _counts()
    payload['crm'].update(patch)
    result = client.post(PATH, json=payload)
    assert result.status_code in (400, 409), result.json
    assert _counts() == counts
    with m.get_session() as db:
        assert db.get(m.BankCard, card_id).balance_thb == OPENING_THB
        assert not db.query(m.CardAllocation).first()


def test_board_and_crm_cannot_disguise_another_account_as_ipps(monkeypatch):
    client, payload, card_id, wrong_id = _draft(monkeypatch)
    state = client.get('/api/stand/state').json
    state['data']['deals'][0]['payout']['bankCardId'] = wrong_id
    edited = client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
    assert edited.status_code == 200, edited.json
    payload['version'] = edited.json['version']
    payload['crm']['bank_card_id'] = wrong_id
    checked = client.post(PATH + '/check', json=payload)
    assert not checked.json['ready']
    assert client.post(PATH, json=payload).status_code == 400
    with m.get_session() as db:
        assert db.get(m.BankCard, card_id).balance_thb == OPENING_THB
        assert db.get(m.BankCard, wrong_id).balance_thb == 100000


def test_ipps_postgres_concurrent_retry_books_one_card_allocation(pg, monkeypatch):
    _, url = pg
    start_app(url, stand=True)
    engine = create_engine(url)
    try:
        factory = sessionmaker(bind=engine)
        with monkeypatch.context() as local:
            local.setattr(m, 'engine', engine)
            local.setattr(m, 'get_session', factory)
            local.setattr(m, 'SessionLocal', factory)
            local.setattr(m, 'DATABASE_URL', url)
            client, payload, card_id, _ = _draft(local)
            with client.session_transaction() as login:
                uid = login['user_id']
            with ThreadPoolExecutor(2) as executor:
                results = list(executor.map(lambda _: _client(uid).post(PATH, json=payload), range(2)))
            assert sorted(result.status_code for result in results) == [200, 201], [r.json for r in results]
            deal_ids = {result.json['deal']['id'] for result in results}
            assert len(deal_ids) == 1
            _assert_financial_rows(deal_ids.pop(), card_id)
    finally:
        engine.dispose()


def test_direct_ipps_crm_preserves_historical_cost_and_returns_card_funds(monkeypatch):
    client, _payload, card_id, _ = _draft(monkeypatch)
    with m.get_session() as db:
        user = m.AdminUser(username='ipps-crm-qa-' + secrets.token_hex(4), role='admin',
                           display_name='IPPS CRM QA', password_hash='unused')
        db.add(user)
        db.commit()
        admin = _client(user.id)
    before = client.get('/api/stand/state').json
    crm = {'deal_kind': 'ipps_realty', 'payin_method': 'partners_cash', 'payin_amount_usdt': PAYIN,
           'payout_source': 'bank_card', 'payout_amount_thb': THB,
           'status': 'completed', 'client_name': 'Synthetic CRM IPPS', 'skip_sync': True,
           'unverified_confirmed': True}
    result = admin.post('/api/deals', json=crm)
    assert result.status_code == 201, result.json
    saved = result.json['deal']
    assert saved['bank_card_id'] == card_id
    assert saved['profit_usdt'] == 100
    path = f'/api/deals/{saved["id"]}'
    with m.get_session() as db:
        card = db.get(m.BankCard, card_id)
        card.balance_thb += 34000
        db.add(m.CardTopup(card_id=card_id, amount_thb=34000, cost_usdt=2000,
                          purchase_rate=17, source_type='separate'))
        db.commit()
    edited = admin.put(path, json={'payout_amount_thb': THB / 5})
    assert edited.status_code == 200, edited.json
    assert edited.json['deal']['payout_amount_usdt'] == 200
    assert admin.delete(path).status_code == 200
    with m.get_session() as db:
        assert db.get(m.BankCard, card_id).balance_thb == OPENING_THB + 34000
        assert not db.query(m.CardAllocation).first()
    after = client.get('/api/stand/state').json
    assert (after['version'], after['data']['bal']) == (before['version'], before['data']['bal'])


def test_closed_ipps_cannot_be_explicitly_included_in_a_reimbursement(monkeypatch):
    client, payload, card_id, _ = _draft(monkeypatch)
    done = client.post(PATH, json=payload)
    assert done.status_code == 201, done.json
    deal_id = done.json['deal']['id']

    def unexpected_tx_lookup(*args):
        pytest.fail('Reject IPPS before looking up any reimbursement transaction')
    monkeypatch.setattr(m, '_tron_tx_amount', unexpected_tx_lookup)
    rejected = client.post('/api/reimbursements', json={
        'deal_ids': [deal_id], 'founder_name': 'Synthetic founder', 'amount_usdt': 1015,
        'tx_hashes': ['aa' * 32], 'force': True,
    })
    assert rejected.status_code == 409, rejected.json
    assert rejected.json['deal_ids'] == [deal_id]
    with m.get_session() as db:
        assert all(not db.query(model).first() for model in
                   (m.Reimbursement, m.ReimbursementTx, m.ReimbursementTxUse))
        saved = db.get(m.Deal, deal_id)
        assert saved.reimbursement_id is None and saved.net_profit_usdt == 90
        assert db.get(m.BankCard, card_id).balance_thb == THB


def test_ipps_closes_at_current_account_rate_after_draft(monkeypatch):
    client, payload, card_id, _ = _draft(monkeypatch)
    with m.get_session() as db:
        card = db.get(m.BankCard, card_id)
        card.balance_thb += OPENING_THB
        db.add(m.CardTopup(card_id=card.id, amount_thb=OPENING_THB, cost_usdt=4000,
                          purchase_rate=OPENING_THB / 4000, source_type='separate'))
        db.commit()
    assert client.post(PATH + '/check', json=payload).json['ready']
    closed = client.post(PATH, json=payload)
    assert closed.status_code == 201, closed.json
    crm = closed.json['deal']
    assert (crm['payout_amount_usdt'], crm['profit_usdt']) == (1500, -400)
    persisted = client.get('/api/stand/state').json['data']['deals'][0]['payout']
    assert (persisted['bankCardId'], persisted['usdt'], persisted['rate']) == (
        card_id, 1500, crm['cash_batch_rate'])
    with m.get_session() as db:
        allocation = db.query(m.CardAllocation).filter_by(deal_id=crm['id']).one()
        assert (allocation.cost_usdt, allocation.card_rate) == (1500, crm['cash_batch_rate'])
