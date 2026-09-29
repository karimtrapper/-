"""Stand-only CRM close transaction and its retry/rollback guarantees."""
import copy
import json
import os
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import app as m
import requests
import pytest
from werkzeug.serving import make_server


def _board():
    return {'deals': [{'id': 1474, 'code': 'СД-1474', 'client': 'Synthetic T24',
                       'type': 'Обмен валюты', 'step': 's27', 'closed': False,
                       'crmDealId': None, 'sentToClient': True, 'pay': {},
                       'amountUsdt': 100, 'payout': {'usdt': 90},
                       'files': {'receipt': [{'file': 'receipt.pdf',
                           'mime': 'application/pdf',
                           'data': 'data:application/pdf;base64,JVBERi0='}]},
                       'log': []}], 'notes': []}


def _crm():
    return {'deal_kind': 'exchange', 'client_name': 'Synthetic T24',
            'manager_name': 'Марина', 'payin_method': 'sber_reqs',
            'payin_amount_usdt': 100, 'payout_method': 'transfer',
            'payout_source': 'cash_batch', 'payout_amount_usdt': 90}


def _setup(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='t24-' + secrets.token_hex(6), display_name='T24 Manager',
                           role='manager', password_hash='unused')
        db.add(user)
        db.flush()
        uid = user.id
        row = db.query(m.StandState).filter_by(id=1).first()
        if row is None:
            row = m.StandState(id=1)
            db.add(row)
        row.data = json.dumps(_board())
        row.version = 1
        row.generation = secrets.token_hex(16)
        db.commit()
        _seed_evidence(db, row, board=_board(), actor_id=uid)
        return uid
    finally:
        db.close()


def _seed_evidence(db, row, board, actor_id):
    """Synthetic preverified board for transaction tests; admission has its own tests."""
    deal = board['deals'][0]
    for kind in m._stand_close_required(deal):
        entry = db.query(m.StandCloseEvidence).filter_by(
            generation=row.generation, stand_deal_id=deal['id'], kind=kind).first()
        if entry is None:
            entry = m.StandCloseEvidence(generation=row.generation,
                stand_deal_id=deal['id'], kind=kind)
            db.add(entry)
        entry.fingerprint = m._stand_close_fingerprint(deal, kind)
        entry.actor_id = actor_id
        entry.provenance = 'synthetic_preverified_fixture'
    db.commit()


def _client(uid):
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def _post(client, version=1, crm=None):
    return client.post('/api/stand/deals/1474/crm-close',
                       json={'version': version, 'crm': _crm() if crm is None else crm})


def _counts():
    db = m.get_session()
    try:
        return db.query(m.Deal).count(), db.query(m.StandCrmLink).count()
    finally:
        db.close()


def test_atomic_close_and_lost_response_retry(monkeypatch):
    uid = _setup(monkeypatch)
    base_deals, base_links = _counts()
    client = _client(uid)
    first = _post(client)
    assert first.status_code == 201, first.json
    crm_id = first.json['deal']['id']
    assert first.json['data']['deals'][0]['closed'] is True
    assert first.json['data']['deals'][0]['crmDealId'] == crm_id
    assert _counts() == (base_deals + 1, base_links + 1)
    db = m.get_session()
    try:
        assert db.query(m.Deal).filter_by(id=crm_id).one().payin_extra is None
    finally:
        db.close()
    # Lost HTTP response, reload and retry with old version: same committed id.
    second = _post(_client(uid), version=1)
    assert second.status_code == 200, second.json
    assert second.json['duplicate'] is True
    assert second.json['deal']['id'] == crm_id
    assert _counts() == (base_deals + 1, base_links + 1)
    # A note/noop board save after close never creates another CRM row.
    state = client.get('/api/stand/state').json
    noop = client.put('/api/stand/state', json={'version': state['version'],
                                               'data': state['data']})
    assert noop.status_code == 200, noop.json
    assert _post(client, version=state['version']).json['deal']['id'] == crm_id
    assert _counts() == (base_deals + 1, base_links + 1)


def test_invalid_crm_rolls_back_board_link_and_money(monkeypatch):
    uid = _setup(monkeypatch)
    baseline = _counts()
    bad = _crm()
    bad['deal_kind'] = 'mf_freehold'
    response = _post(_client(uid), crm=bad)
    assert response.status_code == 400
    assert _counts() == baseline
    state = _client(uid).get('/api/stand/state').json
    assert state['data']['deals'][0]['step'] == 's27'
    assert state['data']['deals'][0]['crmDealId'] is None


def test_stale_version_and_forged_crm_id_rejected(monkeypatch):
    uid = _setup(monkeypatch)
    baseline = _counts()
    client = _client(uid)
    assert _post(client, version=0).status_code == 409
    assert client.post('/api/stand/deals/999999/crm-close',
                       json={'version': 1, 'crm': _crm()}).status_code == 404
    state = client.get('/api/stand/state').json
    forged = copy.deepcopy(state['data'])
    forged['deals'][0]['crmDealId'] = 999
    assert client.put('/api/stand/state', json={'version': state['version'],
                                              'data': forged}).status_code == 409
    forged_new = copy.deepcopy(state['data'])
    fake = copy.deepcopy(forged_new['deals'][0])
    fake.update(id=1475, code='СД-1475', crmDealId=777, closed=True,
                step='done', closeReason='Успешно завершена')
    forged_new['deals'].append(fake)
    assert client.put('/api/stand/state', json={'version': state['version'],
                                              'data': forged_new}).status_code == 409
    assert _counts() == baseline


def test_foreign_bitrix_origin_cannot_link_existing_crm(monkeypatch):
    uid = _setup(monkeypatch)
    client = _client(uid)
    unrelated = client.post('/api/deals', json={**_crm(), 'bitrix_deal_id': 456789,
                                                'status': 'completed', 'skip_sync': True})
    assert unrelated.status_code == 201, unrelated.json
    foreign_id = unrelated.json['deal']['id']
    before = _counts()
    crm = _crm()
    crm.update(bitrix_deal_id=456789, crmDealId=foreign_id)
    response = _post(client, crm=crm)
    assert response.status_code == 400
    assert response.json['error'] == 'foreign_origin_forbidden'
    assert _counts() == before
    assert client.get('/api/stand/state').json['data']['deals'][0]['crmDealId'] is None


def test_board_reset_rotates_origin_generation(monkeypatch):
    uid = _setup(monkeypatch)
    client = _client(uid)
    first = _post(client)
    assert first.status_code == 201
    first_id = first.json['deal']['id']
    db = m.get_session()
    try:
        admin = m.AdminUser(username='t24-' + secrets.token_hex(6),
                            display_name='T24 Admin', role='admin',
                            password_hash='unused')
        db.add(admin)
        db.commit()
        admin_id = admin.id
        prior_generation = db.query(m.StandState).filter_by(id=1).one().generation
    finally:
        db.close()
    admin_client = _client(admin_id)
    assert admin_client.post('/api/stand/reset').status_code == 200
    db = m.get_session()
    try:
        assert db.query(m.StandState).filter_by(id=1).one().generation != prior_generation
    finally:
        db.close()
    state = admin_client.get('/api/stand/state').json
    fresh = _board()
    fresh['deals'][0].update(step='s6', sentToClient=False)
    put = admin_client.put('/api/stand/state',
                           json={'version': state['version'], 'data': fresh})
    assert put.status_code == 200, put.json
    advanced = copy.deepcopy(put.json['data'])
    advanced['deals'][0].update(step='s27', sentToClient=True)
    saved = admin_client.put('/api/stand/state',
                             json={'version': put.json['version'], 'data': advanced})
    assert saved.status_code == 200, saved.json
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        _seed_evidence(db, row, saved.json['data'], uid)
    finally:
        db.close()
    second = _post(client, version=saved.json['version'])
    assert second.status_code == 201, second.json
    assert second.json['deal']['id'] != first_id


def test_custom_exchange_uses_existing_crm_contract(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        board['deals'][0].update(custom=True, paySrc='coins',
            customData={'payinCurrency': 'RUB', 'payinAmount': 920000,
                        'payinRate': 92, 'payinUsdt': 10000,
                        'payoutCurrency': 'THB', 'payoutAmount': 343000,
                        'payoutRate': 35, 'payoutUsdt': 9800})
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    payload = {**_crm(), 'is_custom': True,
               'payin_amount_usdt': 10000, 'payout_amount_usdt': 9800,
               'payout_source': 'binance', 'payout_amount_thb': 343000,
               'custom_payin_currency': 'RUB', 'custom_payin_amount': 920000,
               'custom_payin_rate': 92,
               'custom_payout_currency': 'THB', 'custom_payout_amount': 343000,
               'custom_payout_rate': 35}
    payload.pop('deal_kind')  # CRM custom create sends is_custom, no deal_kind.
    before = _counts()
    invalid = {**payload, 'custom_payout_rate': None}
    assert _post(_client(uid), crm=invalid).status_code == 409
    assert _post(_client(uid), crm={**payload, 'custom_payin_amount': 1}).status_code == 409
    assert _post(_client(uid), crm={**payload, 'payin_amount_usdt': 1}).status_code == 409
    assert _counts() == before
    response = _post(_client(uid), crm=payload)
    assert response.status_code == 201, response.json
    deal = response.json['deal']
    assert deal['deal_kind'] == 'exchange' and deal['is_custom'] is True
    assert deal['custom_payin_currency'] == 'RUB'
    assert deal['custom_payout_currency'] == 'THB'
    assert deal['profit_usdt'] == 200


def test_freehold_locked_board_money_cannot_be_spoofed_in_crm_payload(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal.update(type='Оплата недвижимости', kind='Фрихолд', postConv='ipps_swift',
                    invoiceUsd=45000, ippsTariff='bank', serverTransferComplete=True,
                    amountUsdt=46000,
                    payTo={'purpose': 'Synthetic property'},
                    mfPayout=[{'hash': 'demo:fh:1', 'net': 'TRC20', 'amount': 45410}])
        deal['pay']['invoicePaid'] = True
        row.data = json.dumps(state)
        db.commit()
        _seed_evidence(db, row, state, uid)
    finally:
        db.close()
    before = _counts()
    valid = {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
             'payin_method': 'crypto_direct', 'payin_amount_usdt': 46000,
             'realty_purpose': 'Synthetic property',
             'invoice_amount_usd': 45000, 'transfer_fee_percent': .8,
             'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 45410,
             'payout_tx_hashes': [{'hash': 'demo:fh:1', 'network': 'trc20',
                                   'amount_usdt': 45410}]}
    for change in ({'invoice_amount_usd': 1}, {'transfer_fee_percent': 7},
                   {'transfer_fee_fixed_usd': 5}, {'transfer_sent_usd': 1},
                   {'invoice_amount_thb': 1}, {'buy_rate_thb_usdt': 30},
                   {'payout_tx_hashes': []},
                   {'payout_tx_hashes': [{'hash': 'demo:foreign', 'network': 'trc20',
                                          'amount_usdt': 45410}]},
                   {'payout_tx_hashes': [{'hash': 'demo:fh:1', 'network': 'trc20',
                                          'amount_usdt': 45410,
                                          'to_address': 'foreign-recipient'}]},
                   {'payin_amount_usdt': 1},
                   {'realty_purpose': 'foreign destination'},
                   {'payout_wallet_id': 999},
                   {'is_custom': True}):
        response = _post(_client(uid), crm={**valid, **change})
        assert response.status_code == 409, (change, response.json)
        assert _counts() == before
    good = _post(_client(uid), crm=valid)
    assert good.status_code == 201, good.json
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_crypto_freehold_plan_98800_closes_with_verified_98799_50_fact(monkeypatch):
    """Contract plan and verified Pay-In remain separate through final CRM close."""
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal.update(type='Оплата недвижимости', kind='Фрихолд', payType='Крипта',
                    postConv='ipps_swift', invoiceUsd=97500, ippsTariff='bank',
                    amountUsdt=98800, serverTransferComplete=True,
                    payerWallet='T' + '1' * 33,
                    payinHashes=[{'hash': 'synthetic-verified-in', 'amount': 98799.5,
                                  'net': 'TRC20', 'verified': True,
                                  'from': 'T' + '1' * 33}],
                    payTo={'purpose': 'Synthetic property'},
                    mfPayout=[{'hash': 'demo:fh:98800', 'net': 'TRC20', 'amount': 98330}])
        deal['pay']['invoicePaid'] = True
        row.data = json.dumps(state)
        db.commit()
        _seed_evidence(db, row, state, uid)
    finally:
        db.close()
    crm = {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
           'payin_method': 'crypto_direct', 'payin_amount_usdt': 98799.5,
           'payin_tx_hashes': [{'hash': 'synthetic-verified-in',
                                'network': 'trc20', 'amount_usdt': 98799.5}],
           'realty_purpose': 'Synthetic property',
           'invoice_amount_usd': 97500, 'transfer_fee_percent': .8,
           'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 98330,
           'payout_tx_hashes': [{'hash': 'demo:fh:98800',
                                 'network': 'trc20', 'amount_usdt': 98330}]}
    closed = _post(_client(uid), crm=crm)
    assert closed.status_code == 201, closed.json
    assert closed.json['deal']['payin_amount_usdt'] == 98799.5
    assert closed.json['data']['deals'][0]['amountUsdt'] == 98800
    assert closed.json['data']['deals'][0]['step'] == 'done'


def test_rates_and_company_sent_match_persisted_board(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(type='Оплата недвижимости', kind='Лизхолд',
            postConv='coins', payType='По реквизитам', amountThb=600000,
            incomeAmount=1932000, amountRub=1932000, amountUsdt=21000, companyPct=1,
            serverTransferComplete=True,
            rates={'broker': 92, 'client': 30, 'usdtThb': 32},
            transfer={'rate': 32, 'thb': 603000},
            payTo={'purpose': 'Synthetic property'})
        deal['pay'].update(usdt=21000, invoicePaid=True, coinsNotified=True,
                           coinsCredit={'thb': 603000})
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    crm = {'deal_kind': 'mf_realty', 'client_name': 'Synthetic T24',
           'payin_method': 'sber_reqs', 'payin_amount_rub': 1932000,
           'payin_amount_usdt': 21000, 'payin_rate_rub_usdt': 92,
           'realty_purpose': 'Synthetic property',
           'invoice_amount_thb': 600000, 'buy_rate_thb_usdt': 32,
           'sell_rate_thb_usdt': 30, 'company_sent_thb': 603000}
    baseline = _counts()
    for change in ({'payin_rate_rub_usdt': 1}, {'buy_rate_thb_usdt': 1},
                   {'sell_rate_thb_usdt': 1}, {'company_sent_thb': 600001},
                   {'company_sent_thb': None, 'company_percent': 1}):
        response = _post(_client(uid), crm={**crm, **change})
        assert response.status_code == 409, (change, response.json)
        assert _counts() == baseline
    accepted = _post(_client(uid), crm=crm)
    assert accepted.status_code == 201, accepted.json
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)


def _manual_draft(monkeypatch, kind='exchange'):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [], 'notes': []})
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    deal = copy.deepcopy(_board()['deals'][0])
    deal.update(manual=True, manualNew=False, step='manual', sentToClient=False,
                files={}, isTask=False,
                docLinks={'invoice': 'https://docs.invalid/invoice',
                          'contract': 'https://docs.invalid/contract',
                          'payment': 'https://docs.invalid/payment'})
    if kind != 'exchange':
        deal.update(type='Оплата недвижимости', kind=kind,
                    amountThb=622370 if kind != 'Фрихолд' else None,
                    invoiceUsd=39010.91 if kind == 'Фрихолд' else None,
                    amountUsdt=39533.77 if kind == 'Фрихолд' else 19929.17,
                    rates={'usdtThb': 33.22} if kind != 'Фрихолд' else {},
                    ippsTariff='bank' if kind == 'Фрихолд' else None)
    client = _client(uid)
    created = client.put('/api/stand/state', json={'version': 1,
                         'data': {'deals': [deal], 'notes': []}})
    assert created.status_code == 200, created.json
    assert created.json['data']['deals'][0]['originMode'] == 'manual'
    return uid, created.json['version']


def test_manual_draft_then_explicit_atomic_close_and_retry(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    before = _counts()
    state = client.get('/api/stand/state').json
    assert state['data']['deals'][0]['step'] == 'manual'
    crm = {**_crm(), 'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment',
           'notes': 'Allowed descriptive edit'}
    assert _post(client, version=version,
                 crm={**crm, 'doc_invoice_url': 'https://docs.invalid/foreign'}).status_code == 409
    assert _counts() == before
    first = _post(client, version=version, crm=crm)
    assert first.status_code == 201, first.json
    assert first.json['data']['deals'][0]['step'] == 'done'
    repeat = _post(_client(uid), version=version, crm=crm)
    assert repeat.status_code == 200 and repeat.json['deal']['id'] == first.json['deal']['id']
    assert _counts() == (before[0] + 1, before[1] + 1)
    assert first.json['deal']['doc_invoice_url'] == crm['doc_invoice_url']
    saved = client.get('/api/stand/state').json
    noop = client.put('/api/stand/state', json={'version': saved['version'],
                                                'data': saved['data']})
    assert noop.status_code == 200, noop.json
    assert _post(_client(uid), version=version, crm=crm).json['deal']['id'] == first.json['deal']['id']


def test_manual_draft_and_final_reject_wrong_role(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    db = m.get_session()
    try:
        operator = m.AdminUser(username='t24-' + secrets.token_hex(6),
                               display_name='T24 Operator', role='operator',
                               password_hash='unused')
        db.add(operator)
        db.commit()
        operator_id = operator.id
    finally:
        db.close()
    before = _counts()
    state = _client(uid).get('/api/stand/state').json
    copied = copy.deepcopy(state['data']['deals'][0])
    copied.update(id=1475, code='СД-1475', originMode=None)
    denied = _client(operator_id).put('/api/stand/state',
        json={'version': version, 'data': {'deals': [*state['data']['deals'], copied],
                                          'notes': state['data']['notes']}})
    assert denied.status_code == 409, denied.json
    assert _post(_client(operator_id), version=version).status_code == 403
    assert _counts() == before


@pytest.mark.parametrize('step', ['manual', 's27', 'done'])
def test_new_workflow_cannot_start_at_late_or_manual_stage(monkeypatch, step):
    uid = _setup(monkeypatch)
    client = _client(uid)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [], 'notes': []})
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    fake = copy.deepcopy(_board()['deals'][0])
    fake.update(step=step, manual=False)
    response = client.put('/api/stand/state', json={'version': 1,
                         'data': {'deals': [fake], 'notes': []}})
    assert response.status_code == 409
    assert client.get('/api/stand/state').json['data']['deals'] == []
    assert _post(client).status_code == 404


def test_legal_workflow_entry_can_advance_to_s27_then_close(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [], 'notes': []})
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    client = _client(uid)
    deal = copy.deepcopy(_board()['deals'][0])
    deal.update(step='s6', sentToClient=False)
    initial = client.put('/api/stand/state', json={'version': 1,
                         'data': {'deals': [deal], 'notes': []}})
    assert initial.status_code == 200, initial.json
    advanced = copy.deepcopy(initial.json['data'])
    advanced['deals'][0].update(step='s27', sentToClient=True)
    saved = client.put('/api/stand/state', json={'version': initial.json['version'],
                                                'data': advanced})
    assert saved.status_code == 200, saved.json
    closed = _post(client, version=saved.json['version'])
    assert closed.status_code == 409, closed.json
    assert closed.json['error'] == 'close_evidence_missing'


@pytest.mark.parametrize('property_deal,route', [
    (False, None), (True, 'ipps_swift'), (True, 'cash'), (True, None),
])
def test_staged_http_workflow_cannot_fabricate_completion(monkeypatch, property_deal, route):
    """A real HTTP client cannot invent all completion evidence in a later PUT."""
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        row.data = json.dumps({'deals': [], 'notes': []})
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    baseline = _counts()
    port = int(os.environ['CALCCRM_FENCE_PORT_START'])
    server = make_server('127.0.0.1', port, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
    base = f'http://127.0.0.1:{port}/api/stand'
    headers = {'Cookie': 'session=' + cookie}
    deal = copy.deepcopy(_board()['deals'][0])
    deal.update(step='s8' if property_deal else 's6', sentToClient=False)
    if property_deal:
        deal.update(type='Оплата недвижимости', kind='Фрихолд',
                    postConv=route, payType='Крипта', invoiceUsd=100)
        deal['pay'].update(usdt=120, invoicePaid=False)
        crm = {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
               'payin_method': 'crypto_direct', 'payin_amount_usdt': 120,
               'invoice_amount_usd': 100, 'transfer_fee_percent': .8,
               'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 150.8}
    else:
        crm = _crm()
    try:
        with requests.Session() as transport:
            start = transport.put(base + '/state',
                json={'version': 1, 'data': {'deals': [deal], 'notes': []}},
                headers=headers, timeout=10)
            assert start.status_code == 200, start.json()
            forged = start.json()['data']
            forged_deal = forged['deals'][0]
            forged_deal.update(step='s27', sentToClient=True)
            if property_deal:
                forged_deal['pay']['invoicePaid'] = True
            advanced = transport.put(base + '/state',
                json={'version': start.json()['version'], 'data': forged},
                headers=headers, timeout=10)
            assert advanced.status_code == 200, advanced.json()
            if property_deal and route != 'ipps_swift':
                attestation = transport.post(base + '/deals/1474/close-evidence',
                    json={'version': advanced.json()['version'], 'kind': 'payout'},
                    headers=headers, timeout=10)
                assert attestation.status_code == 409, attestation.json()
                assert attestation.json()['error'] == 'freehold_route_invalid'
            close = transport.post(base + '/deals/1474/crm-close',
                json={'version': advanced.json()['version'], 'crm': crm},
                headers=headers, timeout=10)
            print('STAGED_PROBE', 'freehold' if property_deal else 'exchange',
                  start.status_code, advanced.status_code, close.status_code,
                  close.json().get('error'))
            assert close.status_code == 409, close.json()
            assert _counts() == baseline
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize('kind,route,replacement', [
    ('Фрихолд', 'ipps_swift', 'cash'),
    ('Лизхолд', 'coins', 'cash'),
    ('Аренда', 'coins', 'scb'),
])
def test_real_http_verified_property_route_cannot_be_downgraded(
        monkeypatch, kind, route, replacement):
    """A client cannot turn a verified network send into human payout signoff."""
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        operator = m.AdminUser(username='t24-' + secrets.token_hex(6),
            role='operator', password_hash='unused')
        db.add(operator)
        db.flush()
        operator_id = operator.id
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(type='Оплата недвижимости', kind=kind, postConv=route,
            payType='Крипта', paySrc='coins', serverTransferComplete=True,
            payTo={'acc': 'Synthetic recipient', 'bank': 'Synthetic bank'},
            transfer={'amount': 100, 'sends': [{
                'ref': 'demo:verified', 'status': 'confirmed',
                'verifiedAmount': 100, 'from': 'Synthetic sender',
                'to': 'Synthetic recipient'}]})
        deal['pay']['invoicePaid'] = True
        row.data = json.dumps(board)
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    before = _counts()
    port = int(os.environ['CALCCRM_FENCE_PORT_START'])
    server = make_server('127.0.0.1', port, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    serializer = m.app.session_interface.get_signing_serializer(m.app)
    manager_headers = {'Cookie': 'session=' + serializer.dumps({'user_id': uid})}
    operator_headers = {'Cookie': 'session=' + serializer.dumps({'user_id': operator_id})}
    base = f'http://127.0.0.1:{port}/api/stand'
    try:
        with requests.Session() as transport:
            current = transport.get(base + '/state', headers=manager_headers,
                                    timeout=10).json()
            tampered = copy.deepcopy(current['data'])
            target = tampered['deals'][0]
            target.update(postConv=replacement, paySrc=replacement)
            changed = transport.put(base + '/state', headers=manager_headers,
                json={'version': current['version'], 'data': tampered}, timeout=10)
            assert changed.status_code == 409, changed.json()
            saved = transport.get(base + '/state', headers=manager_headers,
                                  timeout=10).json()
            assert saved['data']['deals'][0]['postConv'] == route
            signoff = transport.post(base + '/deals/1474/close-evidence',
                headers=operator_headers,
                json={'version': saved['version'], 'kind': 'payout'}, timeout=10)
            assert signoff.status_code == 200, signoff.json()
            assert signoff.json()['provenance'] == 'verified_network'
            attempt = transport.post(base + '/deals/1474/crm-close',
                headers=manager_headers,
                json={'version': signoff.json()['version'], 'crm': _crm()}, timeout=10)
            assert attempt.status_code == 409, attempt.json()
            assert _counts() == before
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_operator_evidence_has_role_origin_and_money_binding(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        operator = m.AdminUser(username='t24-' + secrets.token_hex(6),
            role='operator', password_hash='unused')
        db.add(operator)
        db.flush()
        operator_id = operator.id
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(payType='По реквизитам', incomeAmount=10000,
                    paySrc='cash', amountUsdt=100,
                    payout={'thb': 3000, 'usdt': 90})
        row.data = json.dumps(board)
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    manager = _client(uid)
    worker = _client(operator_id)
    path = '/api/stand/deals/1474/close-evidence'
    state = manager.get('/api/stand/state').json
    assert manager.get(path).json['missing'] == ['payin', 'payout', 'sent']
    assert worker.post(path, json={'version': 0, 'kind': 'payin'}).status_code == 409
    # A typed Sber amount without a server-owned income/verified conversion
    # cannot be approved as a cash receipt.
    fake_sber = worker.post(path, json={'version': 1, 'kind': 'payin'})
    assert fake_sber.status_code == 409
    assert fake_sber.json['error'] == 'verified_payin_missing'
    forged = copy.deepcopy(state['data'])
    forged['deals'][0]['closeEvidence'] = {'payin': True}
    assert manager.put('/api/stand/state', json={'version': 1,
        'data': forged}).status_code == 409
    cash = copy.deepcopy(state['data'])
    cash['deals'][0]['payType'] = 'Наличные'
    saved = manager.put('/api/stand/state', json={'version': 1, 'data': cash})
    assert saved.status_code == 200, saved.json
    version = saved.json['version']
    assert manager.post(path, json={'version': version,
        'kind': 'payin'}).status_code == 403
    first = worker.post(path, json={'version': version, 'kind': 'payin'})
    assert first.status_code == 200, first.json
    version = first.json['version']
    assert manager.post(path, json={'version': version,
        'kind': 'payout'}).status_code == 403
    second = worker.post(path, json={'version': version, 'kind': 'payout'})
    assert second.status_code == 200, second.json
    version = second.json['version']
    sent = manager.post(path, json={'version': version, 'kind': 'sent'})
    assert sent.status_code == 200, sent.json
    assert manager.get(path).json['missing'] == []
    note = copy.deepcopy(sent.json['data'])
    note['notes'].append({'id': 99, 'text': 'Unrelated note'})
    noted = manager.put('/api/stand/state', json={'version': sent.json['version'],
                                                  'data': note})
    assert noted.status_code == 200, noted.json
    assert manager.get(path).json['missing'] == []
    changed = copy.deepcopy(noted.json['data'])
    changed['deals'][0]['payout']['usdt'] = 91
    edited = manager.put('/api/stand/state', json={'version': noted.json['version'],
                                                  'data': changed})
    assert edited.status_code == 200, edited.json
    assert manager.get(path).json['missing'] == ['payout']
    before = _counts()
    crm = {**_crm(), 'payin_method': 'partners_cash', 'payin_amount_rub': 10000,
           'payout_amount_usdt': 91, 'payout_amount_thb': 3000}
    denied = _post(manager, version=edited.json['version'], crm=crm)
    assert denied.status_code == 409 and denied.json['error'] == 'close_evidence_missing'
    assert _counts() == before
    reattested = worker.post(path, json={'version': edited.json['version'],
                                         'kind': 'payout'})
    assert reattested.status_code == 200, reattested.json
    close = _post(manager, version=reattested.json['version'], crm=crm)
    assert close.status_code == 201, close.json
    assert _counts() == (before[0] + 1, before[1] + 1)
    retry = _post(_client(uid), version=reattested.json['version'], crm=crm)
    assert retry.status_code == 200 and retry.json['deal']['id'] == close.json['deal']['id']


def test_verified_network_marker_cannot_be_relabelled_or_human_attested(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        board['deals'][0].update(payType='Крипта', paySrc='coins',
            payinHashes=[{'hash': 'verified-hash', 'amount': 100,
                          'network': 'TRC20', 'verified': True,
                          'from': 'TSyntheticPayer', 'to': 'TSyntheticWallet'}])
        row.data = json.dumps(board)
        row.generation = secrets.token_hex(16)
        db.commit()
    finally:
        db.close()
    client = _client(uid)
    before = _counts()
    state = client.get('/api/stand/state').json
    forged = copy.deepcopy(state['data'])
    forged['deals'][0]['payinHashes'][0]['network'] = 'ERC20'
    denied = client.put('/api/stand/state', json={'version': state['version'],
                                                  'data': forged})
    assert denied.status_code == 200, denied.json
    assert denied.json['data']['deals'][0]['payinHashes'][0]['network'] == 'TRC20'
    assert client.get('/api/stand/state').json['data']['deals'][0]['payinHashes'][0]['network'] == 'TRC20'
    path = '/api/stand/deals/1474/close-evidence'
    payin = client.post(path, json={'version': denied.json['version'], 'kind': 'payin'})
    assert payin.status_code == 200, payin.json
    payout = client.post(path, json={'version': payin.json['version'],
                                     'kind': 'payout'})
    assert payout.status_code == 409
    assert payout.json['error'] == 'network_payout_proof_missing'
    assert _counts() == before


def test_accepted_conversion_pay_in_hash_identity_and_default_network():
    state = {'convs': [{'id': 2, 'sources': [{'dealId': 1474,
               'usdtFact': 120}], 'txs': [
               {'hash': 'source-one', 'amount': 100, 'net': 'TRC20',
                'status': 'confirmed'},
               {'hash': 'source-two', 'amount': 20, 'net': 'TRC20',
                'status': 'confirmed'}]}]}
    deal = {'id': 1474, 'cnvId': 2, 'payType': 'По реквизитам',
            'payinHashes': [{'hash': 'source-one', 'amount': 100,
                             'network': 'TRC20'},
                            {'hash': 'source-two', 'amount': 20,
                             'network': 'TRC20'}]}
    original = m._stand_close_fingerprint(deal, 'payin')
    assert m._stand_close_fact_source(state, deal, 'payin') == (
        'accepted_conversion', None)
    for item in deal['payinHashes']:
        item.pop('network')
    assert m._stand_close_fingerprint(deal, 'payin') == original
    assert m._stand_close_fact_source(state, deal, 'payin') == (
        'accepted_conversion', None)
    deal['payinHashes'][0]['hash'] = 'foreign-same-amount'
    assert m._stand_close_fingerprint(deal, 'payin') != original
    assert m._stand_close_fact_source(state, deal, 'payin')[1] == 'verified_payin_missing'
    deal['payinHashes'][0]['hash'] = 'source-one'
    deal['payinHashes'][0]['network'] = 'ERC20'
    assert m._stand_close_fact_source(state, deal, 'payin')[1] == 'verified_payin_missing'


def test_payin_extra_keeps_part_money_and_hash_provenance(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(payType='Крипта', amountUsdt=100,
                    payinHashes=[{'hash': 'main-hash', 'amount': 100, 'net': 'TRC20'}],
                    payinExtra=[{'label': 'наличные партнёров', 'partner': 'Synthetic',
                                 'amountUsdt': 20, 'hashes': [
                                     {'hash': 'extra-hash', 'amount': 20, 'net': 'TRC20'}]}])
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()


    crm = {**_crm(), 'payin_method': 'crypto_direct', 'payin_amount_usdt': 100,
           'payin_tx_hashes': [{'hash': 'main-hash', 'amount_usdt': 100,
                                'network': 'trc20'}],
           'payin_extra': [{'method': 'partners_cash', 'amount_usdt': 20,
                            'partner_name': 'Synthetic', 'tx_hashes': [
                                {'hash': 'extra-hash', 'amount_usdt': 20,
                                 'network': 'trc20'}]}]}
    baseline = _counts()
    for tamper in (
            lambda c: c.update(payin_amount_usdt=120),
            lambda c: c.update(payin_extra=[]),
            lambda c: c['payin_extra'][0].update(amount_usdt=40),
            lambda c: c['payin_extra'][0].update(method='sber_reqs'),
            lambda c: c['payin_extra'][0]['tx_hashes'][0].update(hash='other'),
            lambda c: c.update(payin_tx_hashes=c['payin_tx_hashes'] +
                c['payin_extra'][0]['tx_hashes'], payin_extra=[{
                    **c['payin_extra'][0], 'tx_hashes': []}])):
        wrong = copy.deepcopy(crm)
        tamper(wrong)
        assert _post(_client(uid), crm=wrong).status_code == 409
        assert _counts() == baseline
    response = _post(_client(uid), crm=crm)
    assert response.status_code == 201, response.json
    db = m.get_session()
    try:
        saved = db.query(m.Deal).filter_by(id=response.json['deal']['id']).one()
        assert saved.payin_amount_usdt == 120
        assert len(json.loads(saved.payin_extra or '[]')) == 1
        assert {h['hash'] for h in json.loads(saved.payin_tx_hashes)} == {
            'main-hash', 'extra-hash'}
    finally:
        db.close()


def test_payin_extra_rate_only_amount_is_not_dropped(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        board['deals'][0].update(payType='Крипта', amountUsdt=100,
            payinExtra=[{'method': 'partners_cash', 'amountRub': 2000,
                         'rate': 100, 'partner': 'Synthetic Cash'}])
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    crm = {**_crm(), 'payin_method': 'crypto_direct', 'payin_amount_usdt': 100,
           'payin_extra': [{'method': 'partners_cash', 'amount_rub': 2000,
                            'rate_rub_usdt': 100, 'amount_usdt': 20,
                            'partner_name': 'Synthetic Cash', 'tx_hashes': []}]}
    before = _counts()
    wrong = copy.deepcopy(crm)
    wrong['payin_extra'][0]['rate_rub_usdt'] = 99
    assert _post(_client(uid), crm=wrong).status_code == 409
    assert _counts() == before
    response = _post(_client(uid), crm=crm)
    assert response.status_code == 201, response.json
    assert response.json['deal']['payin_amount_usdt'] == 120


def test_multiple_payin_extras_replay_keeps_aggregate_once(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        board['deals'][0].update(payType='Крипта', amountUsdt=100,
            payinHashes=[{'hash': 'main', 'amount': 100, 'net': 'TRC20'}],
            payinExtra=[
                {'method': 'crypto_direct', 'amountUsdt': 20,
                 'hashes': [{'hash': 'extra-one', 'amount': 20, 'net': 'TRC20'}]},
                {'method': 'partners_cash', 'amountRub': 2000, 'rate': 100,
                 'partner': 'Cash desk'}])
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    crm = {**_crm(), 'payin_method': 'crypto_direct', 'payin_amount_usdt': 100,
           'payin_tx_hashes': [{'hash': 'main', 'amount_usdt': 100, 'network': 'trc20'}],
           'payin_extra': [
               {'method': 'crypto_direct', 'amount_usdt': 20,
                'tx_hashes': [{'hash': 'extra-one', 'amount_usdt': 20,
                               'network': 'trc20'}]},
               {'method': 'partners_cash', 'amount_rub': 2000,
                'rate_rub_usdt': 100, 'amount_usdt': 20,
                'partner_name': 'Cash desk', 'tx_hashes': []}]}
    before = _counts()
    first = _post(_client(uid), crm=crm)
    assert first.status_code == 201, first.json
    crm_id = first.json['deal']['id']
    assert first.json['deal']['payin_amount_usdt'] == 140
    retry = _post(_client(uid), version=1, crm=crm)
    assert retry.status_code == 200 and retry.json['deal']['id'] == crm_id
    assert _counts() == (before[0] + 1, before[1] + 1)
    db = m.get_session()
    try:
        saved = db.query(m.Deal).filter_by(id=crm_id).one()
        assert saved.payin_amount_usdt == 140
        assert len(json.loads(saved.payin_extra)) == 2
        assert {h['hash'] for h in json.loads(saved.payin_tx_hashes)} == {
            'main', 'extra-one'}
    finally:
        db.close()


def test_workflow_cannot_be_relabelled_manual_and_legacy_manual_stays_unlinked(monkeypatch):
    uid = _setup(monkeypatch)
    before = _counts()
    client = _client(uid)
    current = client.get('/api/stand/state').json
    forged = copy.deepcopy(current['data'])
    forged['deals'][0].update(manual=True, step='manual', originMode='manual',
                              sentToClient=False)
    assert client.put('/api/stand/state', json={'version': current['version'],
                                                'data': forged}).status_code == 409
    assert _counts() == before
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        legacy = json.loads(row.data)
        legacy['deals'][0].update(manual=True, step='manual')
        row.data = json.dumps(legacy)
        db.commit()
    finally:
        db.close()
    close = _post(client)
    assert close.status_code == 409 and close.json['error'] == 'legacy_manual_origin'
    assert _counts() == before


@pytest.mark.parametrize('kind,crm', [
    ('exchange', _crm()),
    ('Фрихолд', {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
                  'payin_method': 'crypto_direct', 'payin_amount_usdt': 39533.77,
                  'invoice_amount_usd': 39010.91, 'transfer_fee_percent': .8,
                  'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 39373}),
    ('Лизхолд', {'deal_kind': 'mf_realty', 'client_name': 'Synthetic T24',
                  'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
                  'invoice_amount_thb': 622370, 'buy_rate_thb_usdt': 33.22,
                  'company_percent': 1}),
    ('Аренда', {'deal_kind': 'mf_realty', 'client_name': 'Synthetic T24',
                 'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
                 'invoice_amount_thb': 622370, 'buy_rate_thb_usdt': 33.22,
                 'company_percent': 1}),
])
def test_manual_standard_types_close_once(monkeypatch, kind, crm):
    uid, version = _manual_draft(monkeypatch, kind)
    crm = {**crm, 'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    before = _counts()
    first = _post(_client(uid), version=version, crm=crm)
    assert first.status_code == 201, first.json
    assert _post(_client(uid), version=version, crm=crm).json['deal']['id'] == first.json['deal']['id']
    assert _counts() == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize('kind,missing,error', [
    ('exchange', 'payin', 'payin_basis_missing'),
    ('exchange', 'payout', 'payout_basis_missing'),
    ('Фрихолд', 'payin', 'payin_basis_missing'),
    ('Лизхолд', 'invoice', 'invoice_basis_missing'),
    ('Аренда', 'buy_rate', 'buy_rate_board_missing'),
])
def test_manual_close_requires_route_money_on_saved_board(monkeypatch, kind, missing, error):
    uid, version = _manual_draft(monkeypatch, kind)
    client = _client(uid)
    crm = {**_crm(), 'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    if kind == 'Фрихолд':
        crm.update(deal_kind='mf_freehold', payin_method='crypto_direct',
                   payin_amount_usdt=39533.77, invoice_amount_usd=39010.91,
                   transfer_fee_percent=.8, transfer_fee_fixed_usd=50,
                   transfer_sent_usd=39373)
    elif kind in ('Лизхолд', 'Аренда'):
        crm.update(deal_kind='mf_realty', payin_method='crypto_direct',
                   payin_amount_usdt=19929.17, invoice_amount_thb=622370,
                   buy_rate_thb_usdt=33.22, company_percent=1)
    control = _post(client, version=version, crm=crm)
    assert control.status_code == 201, control.json
    state = client.get('/api/stand/state').json
    board = copy.deepcopy(state['data'])
    deal = copy.deepcopy(board['deals'][0])
    deal.update(id=1475, code='СД-1475', originMode=None, step='manual',
                closed=False, crmDealId=None, sentToClient=False, log=[])
    for field in ('crmAt', 'closedAt', 'closeReason'):
        deal.pop(field, None)
    if missing == 'payin':
        deal.pop('amountUsdt', None)
    elif missing == 'payout':
        deal['payout'] = {}
    elif missing == 'invoice':
        deal.pop('amountThb', None)
    else:
        deal['rates'] = {}
    board['deals'].append(deal)
    saved = client.put('/api/stand/state', json={'version': state['version'], 'data': board})
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][1]['originMode'] == 'manual'
    version = saved.json['version']
    baseline = _counts()
    response = client.post('/api/stand/deals/1475/crm-close',
                           json={'version': version, 'crm': crm})
    assert response.status_code == 409 and response.json['error'] == error, response.json
    assert _counts() == baseline
    unchanged = client.get('/api/stand/state').json
    assert unchanged['version'] == version and unchanged['data'] == saved.json['data']


@pytest.mark.parametrize('missing_side', ['payin', 'payout'])
def test_manual_custom_requires_saved_usdt_basis(monkeypatch, missing_side):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    board = copy.deepcopy(client.get('/api/stand/state').json['data'])
    board['deals'][0].update(custom=True, customData={
        'payinCurrency': 'RUB', 'payinAmount': 92000, 'payinRate': 92,
        'payinUsdt': 1000,
        'payoutCurrency': 'THB', 'payoutAmount': 30000,
        'payoutRate': 31.5, 'payoutUsdt': 952.38})
    saved = client.put('/api/stand/state', json={'version': version, 'data': board})
    assert saved.status_code == 200, saved.json
    crm = {**_crm(), 'is_custom': True, 'payin_amount_usdt': 1000,
           'payout_amount_usdt': 952.38,
           'custom_payin_currency': 'RUB', 'custom_payin_amount': 92000,
           'custom_payin_rate': 92, 'custom_payout_currency': 'THB',
           'custom_payout_amount': 30000, 'custom_payout_rate': 31.5,
           'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    crm.pop('deal_kind')
    control = _post(client, version=saved.json['version'], crm=crm)
    assert control.status_code == 201, control.json
    state = client.get('/api/stand/state').json
    board = copy.deepcopy(state['data'])
    deal = copy.deepcopy(board['deals'][0])
    deal.update(id=1475, code='СД-1475', originMode=None, step='manual',
                closed=False, crmDealId=None, sentToClient=False, log=[])
    for field in ('crmAt', 'closedAt', 'closeReason'):
        deal.pop(field, None)
    deal['customData'].pop(missing_side + 'Usdt')
    board['deals'].append(deal)
    saved = client.put('/api/stand/state', json={'version': state['version'], 'data': board})
    assert saved.status_code == 200, saved.json
    baseline = _counts()
    response = client.post('/api/stand/deals/1475/crm-close',
                           json={'version': saved.json['version'], 'crm': crm})
    assert response.status_code == 409 and response.json['error'] == 'custom_facts_missing'
    assert _counts() == baseline


def test_manual_exchange_derived_payout_requires_saved_thb_and_buy_rate(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    board = copy.deepcopy(client.get('/api/stand/state').json['data'])
    board['deals'][0].update(payout={'thb': 3000}, rates={'usdtThb': 30})
    saved = client.put('/api/stand/state', json={'version': version, 'data': board})
    assert saved.status_code == 200, saved.json
    version = saved.json['version']
    crm = {**_crm(), 'payout_amount_usdt': 100, 'payout_amount_thb': 3000,
           'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    baseline = _counts()
    wrong = _post(client, version=version, crm={**crm, 'payout_amount_usdt': 999})
    assert wrong.status_code == 409 and wrong.json['error'] == 'payout_amount_mismatch'
    assert _counts() == baseline
    accepted = _post(client, version=version, crm=crm)
    assert accepted.status_code == 201, accepted.json
    assert accepted.json['deal']['payout_amount_usdt'] == 100


def test_manual_custom_uses_persisted_fields_and_rejects_invalid_money(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    state = client.get('/api/stand/state').json
    edited = copy.deepcopy(state['data'])
    edited['deals'][0].update(custom=True,
        customData={'payinCurrency': 'RUB', 'payinAmount': 92000,
                    'payinRate': 92, 'payinUsdt': 1000,
                    'payoutCurrency': 'THB', 'payoutAmount': 30000,
                    'payoutRate': 31.5, 'payoutUsdt': 952.38})
    put = client.put('/api/stand/state', json={'version': version, 'data': edited})
    assert put.status_code == 200, put.json
    version = put.json['version']
    crm = {**_crm(), 'is_custom': True, 'payin_amount_usdt': 1000,
           'payout_amount_usdt': 952.38,
           'custom_payin_currency': 'RUB', 'custom_payin_amount': 92000,
           'custom_payin_rate': 92, 'custom_payout_currency': 'THB',
           'custom_payout_amount': 30000, 'custom_payout_rate': 31.5,
           'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    crm.pop('deal_kind')
    before = _counts()
    for wrong in ({'custom_payout_rate': 0}, {'custom_payout_amount': 1},
                  {'payin_amount_usdt': 1}, {'is_custom': False}):
        assert _post(client, version=version, crm={**crm, **wrong}).status_code == 409
        assert _counts() == before
    first = _post(client, version=version, crm=crm)
    assert first.status_code == 201, first.json
    assert first.json['deal']['is_custom'] is True
    assert first.json['deal']['profit_usdt'] == 47.62
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_manual_custom_singular_incoming_hash_matches_t17_contract(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    current = client.get('/api/stand/state').json
    edited = copy.deepcopy(current['data'])
    hash_value = 'a' * 64
    edited['deals'][0].update(custom=True,
        customData={'payinCurrency': 'RUB', 'payinAmount': 92000,
                    'payinRate': 92, 'payinUsdt': 1000,
                    'payinTxHash': hash_value,
                    'payoutCurrency': 'THB', 'payoutAmount': 30000,
                    'payoutRate': 31.5, 'payoutUsdt': 952.38},
        payinHashes=[{'hash': hash_value, 'network': 'trc20',
                      'amount': 1000}])
    saved = client.put('/api/stand/state', json={'version': version,
                                                 'data': edited})
    assert saved.status_code == 200, saved.json
    version = saved.json['version']
    crm = {**_crm(), 'is_custom': True, 'payin_amount_usdt': 1000,
           'payout_amount_usdt': 952.38, 'payin_tx_hash': hash_value,
           'custom_payin_currency': 'RUB', 'custom_payin_amount': 92000,
           'custom_payin_rate': 92, 'custom_payout_currency': 'THB',
           'custom_payout_amount': 30000, 'custom_payout_rate': 31.5,
           'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    crm.pop('deal_kind')
    baseline = _counts()
    for change in ({'payin_tx_hash': 'b' * 64},
                   {'payin_tx_hash': None},
                   {'payin_amount_usdt': 999}):
        response = _post(client, version=version, crm={**crm, **change})
        assert response.status_code == 409, (change, response.json)
        assert _counts() == baseline
    first = _post(client, version=version, crm=crm)
    assert first.status_code == 201, first.json
    assert first.json['deal']['payin_tx_hash'] == hash_value
    assert _post(client, version=version, crm=crm).json['deal']['id'] == first.json['deal']['id']
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)


@pytest.mark.parametrize('mode', ['concurrent', 'lost_response'])
def test_manual_real_http_concurrent_and_lost_response(monkeypatch, mode):
    uid, version = _manual_draft(monkeypatch)
    before = _counts()
    port = int(os.environ['CALCCRM_FENCE_PORT_START'])
    server = make_server('127.0.0.1', port, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
    url = f'http://127.0.0.1:{port}/api/stand/deals/1474/crm-close'
    crm = {**_crm(), 'doc_invoice_url': 'https://docs.invalid/invoice',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    body = {'version': version, 'crm': crm}
    headers = {'Cookie': 'session=' + cookie}
    try:
        if mode == 'concurrent':
            barrier = threading.Barrier(2)
            def send(_):
                barrier.wait()
                with requests.Session() as transport:
                    return transport.post(url, json=body, headers=headers, timeout=10)
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(send, (1, 2)))
            assert sorted(r.status_code for r in responses) == [200, 201]
            assert len({r.json()['deal']['id'] for r in responses}) == 1
        else:
            encoded = json.dumps(body).encode()
            with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
                raw.sendall((f'POST /api/stand/deals/1474/crm-close HTTP/1.1\r\n'
                             f'Host: 127.0.0.1:{port}\r\nCookie: session={cookie}\r\n'
                             f'Content-Type: application/json\r\nContent-Length: {len(encoded)}\r\n'
                             'Connection: close\r\n\r\n').encode() + encoded)
            deadline = time.monotonic() + 5
            while _counts()[1] != before[1] + 1:
                assert time.monotonic() < deadline
                time.sleep(.02)
            with requests.Session() as transport:
                retry = transport.post(url, json=body, headers=headers, timeout=10)
            assert retry.status_code == 200 and retry.json()['duplicate'] is True
        assert _counts() == (before[0] + 1, before[1] + 1)
        board = _client(uid).get('/api/stand/state').json['data']['deals'][0]
        assert board['closed'] and board['step'] == 'done' and board['crmDealId']
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_two_concurrent_close_requests_share_one_id(monkeypatch):
    uid = _setup(monkeypatch)
    base_deals, base_links = _counts()
    def call(_):
        return _post(_client(uid))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(call, (1, 2)))
    assert sorted(r.status_code for r in responses) == [200, 201], [r.json for r in responses]
    assert len({r.json['deal']['id'] for r in responses}) == 1
    assert _counts() == (base_deals + 1, base_links + 1)


def test_failure_after_crm_flush_rolls_back_everything(monkeypatch):
    uid = _setup(monkeypatch)
    baseline = _counts()
    def fail_after_create(*args):
        raise RuntimeError('synthetic failure between CRM and board write')
    monkeypatch.setattr(m, '_stand_completion_notes', fail_after_create)
    response = _post(_client(uid))
    assert response.status_code == 500
    assert _counts() == baseline
    state = _client(uid).get('/api/stand/state').json
    assert state['data']['deals'][0]['crmDealId'] is None
    assert state['data']['deals'][0]['closed'] is False


def test_wrong_role_and_stale_note_edit(monkeypatch):
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        operator = m.AdminUser(username='t24-' + secrets.token_hex(6),
                               display_name='T24 Operator', role='operator',
                               password_hash='unused')
        db.add(operator)
        db.commit()
        operator_id = operator.id
    finally:
        db.close()
    assert _post(_client(operator_id)).status_code == 403
    client = _client(uid)
    board = client.get('/api/stand/state').json
    changed = copy.deepcopy(board['data'])
    changed['notes'].append({'id': 50, 'text': 'Synthetic concurrent note'})
    saved = client.put('/api/stand/state', json={'version': board['version'],
                                                'data': changed})
    assert saved.status_code == 200, saved.json
    conflict = _post(client, version=board['version'])
    assert conflict.status_code == 409
    assert conflict.json['error'] == 'conflict'
    assert conflict.json['data']['notes'][-1]['text'] == 'Synthetic concurrent note'
    assert _post(client, version=saved.json['version']).status_code == 201
    assert client.get('/api/stand/state').json['data']['notes'][-1]['text'] == 'Synthetic concurrent note'
    assert _post(_client(operator_id), version=saved.json['version']).status_code == 403


def test_overage_needs_confirmation_and_cancel_keeps_no_row(monkeypatch):
    uid = _setup(monkeypatch)
    baseline = _counts()
    tx_hash = 'a' * 64
    monkeypatch.setattr(m, '_tron_tx_info', lambda _: {
        'amount_usdt': 100.0, 'from_address': 'TWyLcjJzyQmiT1nt7gEn8BVoNSN94RGcHb',
        'to_address': 'TRgnccUBQo8yZXtra8gqBngBqeTV5aQz74'})
    crm = _crm()
    crm.update(payout_tx_hashes=[{'hash': tx_hash, 'network': 'trc20',
                                      'amount_usdt': 120}], payout_amount_usdt=120)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        board['deals'][0]['payout'] = {'hashes': [{'hash': tx_hash, 'net': 'TRC20', 'amount': 120}]}
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    first = _post(_client(uid), crm=crm)
    assert first.status_code == 409, first.json
    assert first.json['requires_confirmation'] is True
    assert _counts() == baseline
    assert _client(uid).get('/api/stand/state').json['data']['deals'][0]['closed'] is False
    crm['confirm_payout_tx_overage'] = True
    accepted = _post(_client(uid), crm=crm)
    assert accepted.status_code == 201, accepted.json
    assert accepted.json.get('warning')
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)


def test_two_real_http_connections_and_lost_response_retry(monkeypatch):
    uid = _setup(monkeypatch)
    baseline = _counts()
    port = int(os.environ['CALCCRM_FENCE_PORT_START'])
    server = make_server('127.0.0.1', port, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cookie = m.app.session_interface.get_signing_serializer(m.app).dumps({'user_id': uid})
    url = f'http://127.0.0.1:{port}/api/stand/deals/1474/crm-close'
    headers = {'Cookie': 'session=' + cookie}
    body = {'version': 1, 'crm': _crm()}
    try:
        barrier = threading.Barrier(2)
        def send(_):
            barrier.wait()
            with requests.Session() as transport:
                return transport.post(url, json=body, headers=headers, timeout=10)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(send, (1, 2)))
        assert sorted(r.status_code for r in responses) == [200, 201]
        assert len({r.json()['deal']['id'] for r in responses}) == 1
        assert _counts() == (baseline[0] + 1, baseline[1] + 1)

        # The response for a committed close can disappear at the transport.
        # A retry from a fresh HTTP connection still resolves the same origin.
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            row.data = json.dumps(_board())
            row.generation = secrets.token_hex(16)
            row.version = 1
            db.commit()
            _seed_evidence(db, row, _board(), uid)
        finally:
            db.close()
        with socket.create_connection(('127.0.0.1', port), timeout=5) as raw:
            encoded = json.dumps(body).encode()
            raw.sendall((f'POST /api/stand/deals/1474/crm-close HTTP/1.1\r\n'
                         f'Host: 127.0.0.1:{port}\r\nCookie: session={cookie}\r\n'
                         f'Content-Type: application/json\r\nContent-Length: {len(encoded)}\r\n'
                         'Connection: close\r\n\r\n').encode() + encoded)
            # No recv(): model a lost HTTP response after server processing.
        deadline = time.monotonic() + 5
        while _counts() != (baseline[0] + 2, baseline[1] + 2):
            assert time.monotonic() < deadline, 'server did not commit after transport closed'
            time.sleep(.02)
        retry = requests.post(url, json=body, headers=headers, timeout=10)
        assert retry.status_code == 200 and retry.json()['duplicate'] is True
        assert retry.json()['deal']['id'] != responses[0].json()['deal']['id']
        assert _counts() == (baseline[0] + 2, baseline[1] + 2)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize('kind,crm,expected', [
    ('Фрихолд', {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
                  'payin_method': 'crypto_direct', 'payin_amount_usdt': 39533.77,
                  'realty_purpose': 'Synthetic property', 'invoice_amount_usd': 39010.91,
                  'transfer_fee_percent': .8, 'transfer_fee_fixed_usd': 50,
                  'transfer_sent_usd': 39373.00}, 160.77),
    ('Лизхолд', {'deal_kind': 'mf_realty', 'client_name': 'Synthetic T24',
                  'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
                  'realty_purpose': 'Synthetic property', 'invoice_amount_thb': 622370,
                  'buy_rate_thb_usdt': 33.22, 'company_percent': 1}, 1194.37),
    ('Аренда', {'deal_kind': 'mf_realty', 'client_name': 'Synthetic T24',
                 'payin_method': 'crypto_direct', 'payin_amount_usdt': 19929.17,
                 'realty_purpose': 'Synthetic rent', 'invoice_amount_thb': 622370,
                 'buy_rate_thb_usdt': 33.22, 'company_percent': 1}, 1194.37),
])
def test_property_payloads_close_once_with_independent_money_check(monkeypatch, kind, crm, expected):
    from decimal import Decimal
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(type='Оплата недвижимости', kind=kind,
                    postConv='ipps_swift' if kind == 'Фрихолд' else 'coins',
                    serverTransferComplete=True,
                    amountUsdt=crm['payin_amount_usdt'])
        if kind == 'Фрихолд':
            deal.update(invoiceUsd=39010.91, ippsTariff='bank')
        else:
            deal.update(amountThb=622370, companyPct=1,
                        rates={'usdtThb': 33.22})
        deal['pay'].update(invoicePaid=True, coinsNotified=True,
                           coinsCredit={'thb': 622370})
        row.data = json.dumps(board)
        db.commit()
        _seed_evidence(db, row, board, uid)
    finally:
        db.close()
    before = _counts()
    first = _post(_client(uid), crm=crm)
    assert first.status_code == 201, first.json
    actual = Decimal(str(first.json['deal']['net_profit_usdt'])).quantize(Decimal('.01'))
    assert actual == Decimal(str(expected))
    second = _post(_client(uid), crm=crm)
    assert second.status_code == 200
    assert second.json['deal']['id'] == first.json['deal']['id']
    assert _counts() == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize('combined_batch', [False, True])
def test_freehold_ipps_server_settlement_receipt_sent_then_close(monkeypatch, combined_batch):
    """The freehold network route can satisfy signoffs without seeded evidence."""
    uid = _setup(monkeypatch)
    db = m.get_session()
    try:
        operator = m.AdminUser(username='t24-' + secrets.token_hex(6),
            role='operator', password_hash='unused')
        db.add(operator)
        signer = m.AdminUser(username='t24-' + secrets.token_hex(6),
            role='teodor', password_hash='unused')
        db.add(signer)
        db.flush()
        operator_id = operator.id
        signer_id = signer.id
        row = db.query(m.StandState).filter_by(id=1).one()
        board = json.loads(row.data)
        deal = board['deals'][0]
        deal.update(type='Оплата недвижимости', kind='Фрихолд', step='s24',
            postConv='ipps_swift', cnvId=1, walletId='synthetic',
            demoTransfers=True, invoiceUsd=39010.91, ippsTariff='bank',
            amountUsdt=39533.77,
            payinParts=[{'incId': 1474, 'amountRub': 3953377}],
            payType='Крипта',
            payinHashes=[{'hash': 'synthetic-in', 'amount': 39533.77,
                          'net': 'TRC20', 'verified': True}],
            transfer={'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso', 'amount': 39373,
                      'sends': [{'ref': 'demo:1474:one', 'hash': None,
                                 'net': 'TRC20', 'amount': 39373,
                                 'status': 'pending'}]})
        deal['pay'].update(usdt=39533.77, invoicePaid=True)
        board['wallets'] = [{'id': 'synthetic',
                             'addr': 'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                             'multisig': True}]
        board['incomes'] = [{'id': 1474, 'dealId': 1474, 'rub': 3953377,
                             'demo': True}]
        board['convs'] = [{'id': 1, 'walletId': 'synthetic',
                           'sources': [{'dealId': 1474, 'rub': 3953377}],
                           'txs': [{'hash': 'synthetic-in', 'net': 'TRC20',
                                    'status': 'confirmed', 'amount': 39533.77}]}]
        if combined_batch:
            # T23 owner comes from conv/sources despite a Coins side route.
            # T25 counts both outgoing sends and isolates a malformed neighbor.
            deal['conv'] = [1475]
            board['deals'].append({'id': 1475, 'cnvId': 1, 'conv': [], 'step': 'pack',
                'postConv': 'coins', 'demoTransfers': True,
                'payinParts': [{'incId': 1475, 'amountRub': 100}],
                'transfer': {'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso',
                    'amount': 10, 'sends': [{'ref': 'demo:1475:one', 'net': 'TRC20',
                                            'amount': 10, 'status': 'pending'}]},
                'pay': {}, 'log': []})
            board['incomes'].append({'id': 1475, 'dealId': 1475, 'rub': 100,
                                     'demo': True})
            board['convs'][0]['sources'].append({'dealId': 1475, 'rub': 100})
            board['deals'].append({'id': 1476, 'cnvId': 2, 'step': 's24',
                'postConv': 'coins', 'demoTransfers': True,
                'payinParts': [{'incId': 1476, 'amountRub': 100}],
                'transfer': {'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso',
                    'amount': 10, 'sends': [{'ref': 'demo:1476:one', 'net': 'TRC20',
                                            'amount': 10, 'status': 'pending'}]},
                'pay': {}, 'log': []})
            board['incomes'].append({'id': 1476, 'dealId': 1476, 'rub': 100,
                                     'demo': True})
            board['convs'].append({'id': 2, 'walletId': 'synthetic',
                'sources': [{'dealId': 1476, 'rub': 0}],
                'txs': [{'hash': 'bad-in', 'net': 'TRC20',
                         'status': 'confirmed', 'amount': 10}]})
        row.data = json.dumps(board)
        row.generation = secrets.token_hex(16)
        row.version = 1
        db.commit()
    finally:
        db.close()
    before = _counts()
    manager = _client(uid)
    worker = _client(operator_id)
    if combined_batch:
        snapshot = manager.get('/api/stand/state').json['data']
        assert m._stand_batch_main(snapshot, 1475)['id'] == 1474
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            changed = json.loads(row.data)
            changed['convs'][0]['txs'][0]['amount'] = 39382.99
            row.data = json.dumps(changed)
            db.commit()
        finally:
            db.close()
        assert m._stand_check_transfers(1474)['httpStatus'] == 409
        assert _post(manager).status_code == 409
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            changed = json.loads(row.data)
            changed['convs'][0]['txs'][0]['amount'] = 39533.77
            row.data = json.dumps(changed)
            db.commit()
        finally:
            db.close()
        def synthetic_verify(ref, net, sender, receiver, amount, **kwargs):
            return {'status': 'confirmed', 'verifiedAmount': amount,
                    'verifiedAt': '2026-09-28T12:00:00Z',
                    'from': sender, 'to': receiver}
        monkeypatch.setattr(m, 'verify_transfer', synthetic_verify)
        result = m._stand_check_transfers(poll=True)
        assert result['success'] is True
        assert next(d for d in result['data']['deals'] if d['id'] == 1476)['step'] == 's24'
        assert next(d for d in result['data']['deals'] if d['id'] == 1476)['transfer']['sends'][0]['status'] == 'pending'
        proved_deal = next(d for d in result['data']['deals'] if d['id'] == 1474)
    else:
        verified = _client(signer_id).post('/api/stand/transfers/demo',
            json={'dealId': 1474, 'ref': 'demo:1474:one', 'outcome': 'confirmed'})
        assert verified.status_code == 200, verified.json
        proved_deal = verified.json['data']['deals'][0]
    assert proved_deal['serverTransferComplete'] is True
    assert proved_deal['step'] == 's25'
    assert proved_deal['transfer']['sends'][0]['from']
    assert proved_deal['transfer']['sends'][0]['to']
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        advanced = json.loads(row.data)
        advanced['deals'][0].update(step='s27', sentToClient=True)
        row.data = json.dumps(advanced)
        db.commit()
        version = row.version
    finally:
        db.close()
    path = '/api/stand/deals/1474/close-evidence'
    for kind, actor, expected in (
            ('payin', manager, 'verified_network'),
            ('payout', manager, 'verified_network'),
            ('receipt', worker, 'operator_attestation'),
            ('sent', manager, 'manager_attestation')):
        signed = actor.post(path, json={'version': version, 'kind': kind})
        assert signed.status_code == 200, (kind, signed.json)
        assert signed.json['provenance'] == expected
        version = signed.json['version']
    assert manager.get(path).json['missing'] == []
    crm = {'deal_kind': 'mf_freehold', 'client_name': 'Synthetic T24',
           'payin_method': 'crypto_direct', 'payin_amount_usdt': 39533.77,
           'payin_tx_hashes': [{'hash': 'synthetic-in', 'network': 'trc20',
                                'amount_usdt': 39533.77}],
           'invoice_amount_usd': 39010.91, 'transfer_fee_percent': .8,
           'transfer_fee_fixed_usd': 50, 'transfer_sent_usd': 39373,
           'payout_tx_hashes': [{'hash': 'demo:1474:one', 'network': 'trc20',
                                 'amount_usdt': 39373}]}
    if combined_batch:
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            changed = json.loads(row.data)
            changed['convs'][0]['txs'][0]['amount'] = 39382.99
            row.data = json.dumps(changed)
            db.commit()
        finally:
            db.close()
        blocked = _post(manager, version=version, crm=crm)
        assert blocked.status_code == 409, blocked.json
        assert 'не хватает 0.01' in blocked.json['error']
        assert _counts() == before
        db = m.get_session()
        try:
            row = db.query(m.StandState).filter_by(id=1).one()
            changed = json.loads(row.data)
            changed['convs'][0]['txs'][0]['amount'] = 39533.77
            row.data = json.dumps(changed)
            db.commit()
        finally:
            db.close()
    created = _post(manager, version=version, crm=crm)
    assert created.status_code == 201, created.json
    assert created.json['data']['deals'][0]['closed'] is True
    assert _counts() == (before[0] + 1, before[1] + 1)
