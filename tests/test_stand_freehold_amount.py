"""Synthetic direct-amount and loss-risk admission for crypto freehold."""
import copy
import json
import secrets

import pytest

import app as m


WALLET = 'TKkeEVf2zySaWTLyX2qPwvi6kcdHRuPxkJ'


def board(amount=98800, step='s8', *, legacy=None, manual=False):
    deal = {
        'id': 9101, 'code': 'SYN-FH-9101', 'client': 'Synthetic Freehold',
        'type': 'Оплата недвижимости', 'kind': 'Фрихолд',
        'payType': 'Крипта', 'curBase': 'fhusd', 'step': 'manual' if manual else step,
        'manual': manual, 'originMode': 'manual' if manual else None,
        'invoiceUsd': 97500, 'ippsTariff': 'bank', 'amountUsdt': amount,
        'walletId': 'grusha', 'rates': {}, 'pay': {}, 'payout': {}, 'docs': {},
        'docFields': {'fio': 'Тестовый Клиент', 'passNo': '123456789',
                      'invNo': 'SYN-INV-1', 'amountThb': '97500',
                      'amountPay': str(amount or ''), 'rate': ''},
        'log': [], 'closed': False,
    }
    if legacy is not None:
        deal['freeholdMarkupPct'] = legacy
    return {'deals': [deal], 'wallets': [{'id': 'grusha', 'addr': WALLET,
                                        'owner': 'компания'}], 'convs': [], 'notes': []}


def seed(monkeypatch, state):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    db = m.get_session()
    try:
        user = m.AdminUser(username='fh-amount-' + secrets.token_hex(4),
                           role='admin', display_name='Synthetic Admin',
                           password_hash='unused')
        db.add(user)
        db.flush()
        row = m._stand_row(db)
        row.data = json.dumps(state)
        row.version = 17
        db.commit()
        uid = user.id
    finally:
        db.close()
    client = m.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    return client


def snapshot(client):
    response = client.get('/api/stand/state')
    assert response.status_code == 200
    return response.json


def put_step(client, step):
    before = snapshot(client)
    state = copy.deepcopy(before['data'])
    state['deals'][0]['step'] = step
    return client.put('/api/stand/state', json={'version': before['version'], 'data': state})


def test_exact_plan_contract_and_legacy_override(monkeypatch):
    state = board(98800, 's11', legacy=100475)
    deal = state['deals'][0]
    F = deal['docFields']
    req = m._stand_doc_request(state, deal, F)
    assert 'error' not in req, req
    assert req['money']['total_payin'] == '98800'
    assert req['money']['transfer_amount'] == '97500'
    assert not m._stand_freehold_absurd_doc(deal, F)
    assert m._stand_freehold_loss_fingerprint(deal) == '97500|98800|98330|bank'
    assert m._stand_freehold_plan_problem(deal) is None
    assert m._stand_freehold_plan_problem({**deal, 'amountUsdt': 98330}) is None
    assert m._stand_freehold_plan_problem({**deal, 'amountUsdt': 98000}) == 'freehold_loss_ack_required'


def test_legacy_percent_only_stopped_then_explicit_amount_allows_progression(monkeypatch):
    client = seed(monkeypatch, board(None, legacy=100475))
    initial = snapshot(client)
    blocked = put_step(client, 's11')
    assert blocked.status_code == 409
    assert blocked.json['error'] == 'freehold_amount_required'
    assert snapshot(client) == initial
    state = copy.deepcopy(initial['data'])
    state['deals'][0]['amountUsdt'] = 98800
    state['deals'][0]['docFields']['amountPay'] = '98800'
    saved = client.put('/api/stand/state', json={'version': initial['version'], 'data': state})
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][0]['freeholdMarkupPct'] == 100475
    moved = put_step(client, 's11')
    assert moved.status_code == 200, moved.json
    assert moved.json['data']['deals'][0]['amountUsdt'] == 98800


@pytest.mark.parametrize('amount,expected', [(98330, None), (98000, 'freehold_loss_ack_required')])
def test_equal_and_negative_step_guard(monkeypatch, amount, expected):
    client = seed(monkeypatch, board(amount))
    initial = snapshot(client)
    response = put_step(client, 's11')
    if expected:
        assert response.status_code == 409
        assert response.json['error'] == expected
        assert response.json['version'] == initial['version']
        assert response.json['data'] == initial['data']
        assert snapshot(client) == initial
    else:
        assert response.status_code == 200, response.json
        assert response.json['data']['deals'][0]['step'] == 's11'


def test_s11_amount_edit_role_lock_and_loss_ack_invalidation(monkeypatch):
    client = seed(monkeypatch, board(98800, step='s11'))
    before = snapshot(client)
    changed = copy.deepcopy(before['data'])
    changed['deals'][0]['amountUsdt'] = 98000
    monkeypatch.setattr(m, 'current_role', lambda: 'manager')
    denied = client.put('/api/stand/state', json={'version': before['version'], 'data': changed})
    assert denied.status_code == 409
    assert snapshot(client)['data'] == before['data']
    assert snapshot(client)['version'] == before['version']
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    allowed = client.put('/api/stand/state', json={'version': before['version'], 'data': changed})
    assert allowed.status_code == 200, allowed.json
    assert allowed.json['data']['deals'][0]['amountUsdt'] == 98000

    monkeypatch.setattr(m, 'current_role', lambda: 'admin')
    ack = client.post('/api/stand/deals/9101/freehold-loss-ack',
                      json={'version': allowed.json['version']})
    assert ack.status_code == 200, ack.json
    edit = copy.deepcopy(ack.json['data'])
    edit['deals'][0]['amountUsdt'] = 97900
    saved = client.put('/api/stand/state', json={'version': ack.json['version'], 'data': edit})
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][0]['freeholdLossAck'] == ack.json['data']['deals'][0]['freeholdLossAck']
    assert m._stand_freehold_plan_problem(saved.json['data']['deals'][0]) == 'freehold_loss_ack_required'

    for lock in ({'docVersion': 1}, {'docPack': {'version': 1}},
                 {'payinHashes': [{'hash': 'a' * 64, 'verified': True}]}):
        locked = board(98800, step='s11')
        locked['deals'][0].update(lock)
        guarded = seed(monkeypatch, locked)
        start = snapshot(guarded)
        attempt = copy.deepcopy(start['data'])
        attempt['deals'][0]['amountUsdt'] = 98900
        refused = guarded.put('/api/stand/state',
                              json={'version': start['version'], 'data': attempt})
        assert refused.status_code == 409, (lock, refused.json)
        assert snapshot(guarded) == start


def test_loss_ack_role_spoof_and_fingerprint_invalidation(monkeypatch):
    client = seed(monkeypatch, board(98000))
    before = snapshot(client)
    forged = copy.deepcopy(before['data'])
    forged['deals'][0]['freeholdLossAck'] = {'fingerprint': m._stand_freehold_loss_fingerprint(forged['deals'][0])}
    response = client.put('/api/stand/state', json={'version': before['version'], 'data': forged})
    assert response.status_code == 409
    assert response.json['error'] == 'freehold_loss_ack_server_only'
    assert snapshot(client) == before
    monkeypatch.setattr(m, 'current_role', lambda: 'operator')
    forbidden = client.post('/api/stand/deals/9101/freehold-loss-ack',
                            json={'version': before['version']})
    assert forbidden.status_code == 409
    assert forbidden.json['error'] == 'forbidden'
    assert snapshot(client)['data'] == before['data']
    assert snapshot(client)['version'] == before['version']
    monkeypatch.setattr(m, 'current_role', lambda: 'admin')
    ack = client.post('/api/stand/deals/9101/freehold-loss-ack', json={'version': before['version']})
    assert ack.status_code == 200, ack.json
    assert ack.json['data']['deals'][0]['freeholdLossAck']['fingerprint'] == '97500|98000|98330|bank'
    assert put_step(client, 's11').status_code == 200

    for key, value in (('amountUsdt', 97900), ('invoiceUsd', 97600), ('ippsTariff', 'soft')):
        separate = seed(monkeypatch, board(98000))
        start = snapshot(separate)
        confirmed = separate.post('/api/stand/deals/9101/freehold-loss-ack',
                                  json={'version': start['version']})
        assert confirmed.status_code == 200
        edited_state = copy.deepcopy(confirmed.json['data'])
        edited_state['deals'][0][key] = value
        edited = separate.put('/api/stand/state',
                              json={'version': confirmed.json['version'], 'data': edited_state})
        assert edited.status_code == 200, (key, edited.json)
        rejected = put_step(separate, 's11')
        assert rejected.status_code == 409, (key, rejected.json)
        assert rejected.json['error'] == 'freehold_loss_ack_required'
    # Before document prep, tariff edits invalidate the fingerprint and reopen the stop.
    client = seed(monkeypatch, board(98500))
    baseline = snapshot(client)
    changed = copy.deepcopy(baseline['data'])
    changed['deals'][0]['ippsTariff'] = 'soft'  # S rises from 98330 to 99012.50
    edited = client.put('/api/stand/state', json={'version': baseline['version'], 'data': changed})
    assert edited.status_code == 200, edited.json
    assert put_step(client, 's11').status_code == 409
    ack2 = client.post('/api/stand/deals/9101/freehold-loss-ack', json={'version': edited.json['version']})
    assert ack2.status_code == 200
    assert put_step(client, 's11').status_code == 200


def test_direct_doc_and_manual_close_refused_without_ack(monkeypatch):
    client = seed(monkeypatch, board(98000, step='s11'))
    before = snapshot(client)
    db = m.get_session()
    try:
        docs_before = db.query(m.AgreementDoc).count()
    finally:
        db.close()
    direct = client.post('/api/stand/docs/issue', json={'dealId': 9101,
                         'docFields': {'amountPay': '98000'}})
    assert direct.status_code == 409
    assert direct.json['error'] == 'freehold_loss_ack_required'
    assert snapshot(client) == before
    db = m.get_session()
    try:
        assert db.query(m.AgreementDoc).count() == docs_before
    finally:
        db.close()
    manual_client = seed(monkeypatch, board(98000, manual=True))
    initial = snapshot(manual_client)
    close = manual_client.post('/api/stand/deals/9101/crm-close',
        json={'version': initial['version'], 'crm': {'deal_kind': 'mf_freehold'}})
    assert close.status_code == 409
    assert close.json['error'] == 'freehold_loss_ack_required'
    assert snapshot(manual_client) == initial


def test_crm_fact_is_verified_hash_not_planned_amount():
    deal = board(98800)['deals'][0]
    crm = {'deal_kind': 'mf_freehold', 'payin_method': 'crypto_direct',
           'payin_amount_usdt': 98800, 'payout_wallet_id': None, 'bank_card_id': None}
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') == 'payin_basis_missing'
    deal['payinHashes'] = [{'hash': 'a' * 64, 'amount': 98799.5, 'verified': True,
                            'from': 'T' + '1' * 33}]
    deal['payerWallet'] = 'T' + '1' * 33
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') == 'payin_amount_mismatch'
    crm['payin_amount_usdt'] = 98799.5
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') != 'payin_amount_mismatch'
    deal['payinHashes'][0]['verified'] = False
    assert m._stand_crm_fact_problem(deal, crm, 'mf_freehold') == 'payin_basis_unverified'
