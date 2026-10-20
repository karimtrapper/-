"""S27 closes once from current, trusted facts, including direct HTTP bypasses."""
import base64
import copy
import hashlib
import json
import secrets

import pytest
import app as m
from tests.test_stand_crm_close_atomic import _setup, _client, _crm, _counts, s26_legacy_trail

pytestmark = pytest.mark.usefixtures('stand_demo_environment')
STAMP = '2026-10-18T10:11:12+00:00'


def setup_verified(monkeypatch, *, property_deal=False, uploader_role='operator', invoice_paid=True):
    uid = _setup(monkeypatch)
    monkeypatch.setattr(m, '_tx_info_by_network', lambda *args, **kwargs: None)
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        deal = state['deals'][0]
        incoming = {'hash': 'a' * 64, 'network': 'TRC20', 'amount': 100,
                    'verified': True, 'verifiedAt': STAMP, 'from': 'sender', 'to': 'wallet'}
        outgoing = {'hash': 'b' * 64, 'net': 'TRC20', 'amount': 90,
                    'status': 'confirmed', 'verifiedAmount': 90,
                    'verifiedAt': STAMP, 'from': 'wallet', 'to': 'recipient'}
        deal.update(payType='Крипта', paySrc='client', payinHashes=[incoming],
                    serverTransferComplete=True, transfer={'amount': 90, 'sends': [outgoing]},
                    payout={'usdt': 90, 'hashes': [{'hash': 'b' * 64, 'net': 'TRC20', 'amount': 90}]})
        crm = {**_crm(), 'payin_method': 'crypto_direct', 'payout_source': 'binance',
               'payin_tx_hashes': [{'hash': 'a' * 64, 'network': 'trc20', 'amount_usdt': 100}],
               'payout_tx_hashes': [{'hash': 'b' * 64, 'network': 'trc20', 'amount_usdt': 90}]}
        deal['files']['receipt'][0]['data'] = 'data:application/pdf;base64,' + base64.b64encode(
            b'%PDF-' + secrets.token_bytes(16)).decode()
        uploader = m.AdminUser(username='s27-' + secrets.token_hex(6), role=uploader_role,
                               password_hash='unused')
        db.add(uploader); db.flush()
        if property_deal:
            deal.update(type='Оплата недвижимости', kind='Лизхолд', postConv='coins',
                        amountThb=3000, rates={'client': 30, 'usdtThb': 33.6666666667},
                        companyPct=1, mfPayout=[{'hash': 'b' * 64, 'net': 'TRC20', 'amount': 90}],
                        pay={'invoicePaid': invoice_paid, 'coinsNotified': True, 'coinsCredit': {'thb': 3030}})
            crm = {**crm, 'deal_kind': 'mf_realty', 'invoice_amount_thb': 3000,
                   'sell_rate_thb_usdt': 30, 'buy_rate_thb_usdt': 33.6666666667,
                   'company_percent': 1}
        row.generation = secrets.token_hex(16)  # No historical manager signoffs.
        m._stand_externalize_files(db, row, state, actor=uploader.id, previous={})
        row.data = json.dumps(state)
        db.commit()
        return _client(uid), uid, crm
    finally:
        db.close()


def complete_s26(deal):
    deal['log'] = (deal.get('log') or []) + s26_legacy_trail(deal)


def change_board(edit):
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        state = json.loads(row.data)
        edit(state['deals'][0])
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
        return row.version
    finally:
        db.close()


def test_verified_facts_close_with_one_snapshot_and_idempotent_retry(monkeypatch):
    client, uid, crm = setup_verified(monkeypatch)
    before = _counts()
    readiness = client.get('/api/stand/deals/1474/close-evidence').json
    assert readiness['missing'] == []
    assert all(f['ready'] for f in readiness['facts'])
    assert readiness['facts'][0]['checked_at'] == STAMP
    body = {'version': readiness['version'], 'crm': crm}
    result = client.post('/api/stand/deals/1474/crm-close', json=body)
    assert result.status_code == 201, result.json
    confirmation = result.json['data']['deals'][0]['closeConfirmation']
    assert confirmation['actor_id'] == uid
    assert confirmation['confirmed_at']
    snapshot = confirmation['snapshot']
    assert snapshot['crm'] == crm
    assert snapshot['deal']['payinHashes'][0]['hash'] == 'a' * 64
    assert snapshot['deal']['transfer']['sends'][0]['amount'] == 90
    assert hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest() == confirmation['fingerprint']
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        evidence = db.query(m.StandCloseEvidence).filter_by(generation=row.generation).all()
        assert len(evidence) == 1 and evidence[0].kind == 'summary'
        assert evidence[0].fingerprint == confirmation['fingerprint']
    finally:
        db.close()
    assert _counts() == (before[0] + 1, before[1] + 1)
    assert client.post('/api/stand/deals/1474/crm-close', json=body).json['duplicate'] is True
    assert _counts() == (before[0] + 1, before[1] + 1)


def test_missing_payout_is_explicit_and_direct_post_is_blocked(monkeypatch):
    client, _, crm = setup_verified(monkeypatch)
    version = change_board(lambda deal: deal['transfer'].update(sends=[]))
    status = client.get('/api/stand/deals/1474/close-evidence').json
    assert status['missing'] == ['payout']
    assert next(f for f in status['facts'] if f['kind'] == 'payout')['reason'] == 'network_payout_proof_missing'
    before = _counts()
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert result.status_code == 409 and result.json['missing'] == ['payout']
    assert _counts() == before


def test_version_of_shown_form_cannot_close_changed_board(monkeypatch):
    client, _, crm = setup_verified(monkeypatch)
    shown = client.get('/api/stand/deals/1474/close-evidence').json
    change_board(lambda deal: deal.update(client='Another manager changed this'))
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': shown['version'], 'crm': crm})
    assert result.status_code == 409 and result.json['error'] == 'conflict'
    assert 'обновите страницу' in result.json['detail']


@pytest.mark.parametrize('status', ['pending', 'mismatch', 'error'])
def test_failed_network_status_cannot_be_overridden_by_old_signoff(monkeypatch, status):
    client, uid, crm = setup_verified(monkeypatch)
    version = change_board(lambda deal: deal['transfer']['sends'][0].update(status=status))
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        deal = json.loads(row.data)['deals'][0]
        # Even a matching historical manager signoff never overrides current network facts.
        m._stand_upsert_close_evidence(db, row, deal, 'payout', uid, 'verified_network')
        db.commit()
    finally:
        db.close()
    before = _counts()
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert result.status_code == 409 and result.json['missing'] == ['payout']
    assert _counts() == before


def test_sent_true_needs_no_new_signoff_and_readiness_is_read_only(monkeypatch):
    client, _, _ = setup_verified(monkeypatch)
    first = client.get('/api/stand/deals/1474/close-evidence').json
    second = client.get('/api/stand/deals/1474/close-evidence').json
    assert first == second
    assert next(f for f in first['facts'] if f['kind'] == 'sent')['ready']
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        assert row.version == first['version']
        assert db.query(m.StandCloseEvidence).filter_by(generation=row.generation).count() == 0
    finally:
        db.close()


@pytest.mark.parametrize('role,ready', [('operator', True), ('manager', False)])
def test_only_operator_receipt_upload_is_automatic(monkeypatch, role, ready):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role=role)
    if ready:
        change_board(complete_s26)  # приёмку даёт завершённый s26, а не сама загрузка
    status = client.get('/api/stand/deals/1474/close-evidence').json
    fact = next(f for f in status['facts'] if f['kind'] == 'receipt')
    assert fact['ready'] is ready
    if ready:
        assert fact['system'] and fact['checked_at']
    else:
        assert fact['reason'] == 'operator_receipt_acceptance_missing'


def test_network_check_failure_then_direct_close_is_rejected(monkeypatch):
    client, _, crm = setup_verified(monkeypatch)
    calls = []
    def pending(*args, **kwargs):
        calls.append(args)
        return {'status': 'pending', 'checkError': 'Network has not confirmed this transfer'}
    monkeypatch.setattr(m, 'verify_transfer', pending)
    change_board(lambda d: d.update(step='s14', payinHashes=[], walletId='custom',
        payinCustom={'network': 'TRC-20', 'addr': 'T' + '1' * 33}))
    checked = client.post('/api/stand/payin/check', json={'dealId': 1474, 'hash': 'c' * 64})
    assert checked.status_code == 422 and checked.json['status'] == 'pending'
    assert len(calls) == 1
    # Simulate a legacy/malformed board arriving at s27. Closing must independently
    # reject it even though the normal step transition already blocks this case.
    version = change_board(lambda d: d.update(step='s27'))
    before = _counts()
    closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert closed.status_code == 409 and 'payin' in closed.json['missing']
    assert _counts() == before


def test_bank_credit_never_masks_unverified_conversion_hash(monkeypatch):
    client, _, crm = setup_verified(monkeypatch)
    version = change_board(lambda d: d.update(payType='По реквизитам',
        payinHashes=[{'hash': 'c' * 64, 'amount': 100, 'net': 'TRC20'}]))
    # setup's real server-owned Sber income remains present and matches the RUB
    # allocation. It does not establish that the USDT hash was confirmed.
    readiness = client.get('/api/stand/deals/1474/close-evidence').json
    assert 'payin' in readiness['missing']
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert result.status_code == 409 and 'payin' in result.json['missing']


def test_confirmation_cannot_be_forged_and_failed_create_leaves_no_audit(monkeypatch):
    client, _, crm = setup_verified(monkeypatch)
    state = client.get('/api/stand/state').json
    state['data']['deals'][0]['closeConfirmation'] = {'actor_id': 999, 'fingerprint': 'forged'}
    forged = client.put('/api/stand/state', json={'version': state['version'], 'data': state['data']})
    assert forged.status_code == 409
    before = _counts()
    monkeypatch.setattr(m, '_create_deal_impl', lambda *args, **kwargs:
        (m.jsonify(success=False, error='synthetic_create_rejected'), 409))
    failed = client.post('/api/stand/deals/1474/crm-close', json={'version': state['version'], 'crm': crm})
    assert failed.status_code == 409 and failed.json['error'] == 'synthetic_create_rejected'
    assert _counts() == before
    db = m.get_session()
    try:
        row = db.query(m.StandState).filter_by(id=1).one()
        assert not json.loads(row.data)['deals'][0].get('closeConfirmation')
        assert db.query(m.StandCloseEvidence).filter_by(generation=row.generation, kind='summary').count() == 0
    finally:
        db.close()


def test_realty_bank_credit_without_any_usdt_hash_cannot_close(monkeypatch):
    client, _, crm = setup_verified(monkeypatch, property_deal=True)
    version = change_board(lambda d: d.update(payType='По реквизитам', payinHashes=[], cnvId=None))
    status = client.get('/api/stand/deals/1474/close-evidence').json
    assert 'payin' in status['missing']
    before = _counts()
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert result.status_code == 409 and 'payin' in result.json['missing']
    assert _counts() == before


def test_migration_cannot_claim_authenticated_operator_acceptance(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        prior = db.query(m.StandCloseEvidence).filter_by(generation=row.generation, kind='receipt').one()
        claimed_operator = prior.actor_id
        db.delete(prior); db.flush()
        deal['files']['receipt'] = [{'file': 'migrated.pdf', 'mime': 'application/pdf',
            'uploadedById': claimed_operator, 'at': '18.10, 10:00',
            'data': 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-' + secrets.token_bytes(16)).decode()}]
        m._stand_externalize_files(db, row, state, migration=True)
        stored = db.get(m.StandFile, deal['files']['receipt'][0]['storageId'])
        assert stored.uploaded_by == str(claimed_operator)  # Existing migration behavior.
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    fact = next(f for f in client.get('/api/stand/deals/1474/close-evidence').json['facts'] if f['kind'] == 'receipt')
    assert not fact['ready'] and not fact['checked_at']
    assert fact['reason'] == 'operator_receipt_acceptance_missing'


def test_native_file_acceptance_timestamp_survives_invoice_paid(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, invoice_paid=False)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        before = copy.deepcopy(state)
        evidence = db.query(m.StandCloseEvidence).filter_by(generation=row.generation, kind='receipt').one()
        stamp, operator = evidence.confirmed_at, evidence.actor_id
        assert evidence.provenance == 'operator_upload'
        payer = m.AdminUser(username='s27-payer-' + secrets.token_hex(6),
                            role='operator', password_hash='unused')
        db.add(payer); db.flush()
        assert payer.id != operator
        state['deals'][0]['pay']['invoicePaid'] = True
        m._stand_externalize_files(db, row, state, actor=payer.id, previous=before)
        row.data = json.dumps(state)
        db.commit()
        assert evidence.confirmed_at == stamp
        assert evidence.actor_id == operator  # Actor and time remain one upload event.
    finally:
        db.close()
    change_board(complete_s26)
    fact = next(f for f in client.get('/api/stand/deals/1474/close-evidence').json['facts'] if f['kind'] == 'receipt')
    assert fact['ready'] and fact['system']
    assert fact['checked_at'] == '2025-10-19T05:49:42Z'  # время завершения s26, а не поздней записи


def test_realty_closes_with_one_manager_confirmation_after_operator_upload(monkeypatch):
    client, uid, crm = setup_verified(monkeypatch, property_deal=True)
    change_board(complete_s26)
    status = client.get('/api/stand/deals/1474/close-evidence').json
    assert status['missing'] == []
    assert all(f['system'] for f in status['facts'] if f['kind'] != 'sent')
    result = client.post('/api/stand/deals/1474/crm-close', json={'version': status['version'], 'crm': crm})
    assert result.status_code == 201, result.json
    db = m.get_session()
    try:
        row = m._stand_row(db)
        records = db.query(m.StandCloseEvidence).filter_by(generation=row.generation).all()
        assert [r.kind for r in records if r.actor_id == uid] == ['summary']
        assert next(r for r in records if r.kind == 'receipt').provenance == 'operator_upload'
    finally:
        db.close()
