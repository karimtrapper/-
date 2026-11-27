"""Чек выплаты получателю, приложенный любой ролью, сам принимает факт receipt/payout.

Без отдельного подтверждения операциониста; non-crypto выплата (банк THB, карта
фаундера, наличные) не требует blockchain hash, crypto — требует. СД-1489: аренда,
приход наличными, выплата банком 455 000 ฿, слип KBank→BBL от менеджера Лизы."""
import base64
import json
import secrets

import pytest
import app as m
from tests.test_stand_single_confirm import setup_verified, change_board
from tests.test_stand_s26_implicit_confirm import trail
from tests.test_stand_manual_close_realty import (
    _setup as realty_setup, _client as realty_client, _realty_board, _override, _crm, _post, REASON)

pytestmark = pytest.mark.usefixtures('stand_demo_environment')


@pytest.fixture(autouse=True)
def clean_created_crm_rows():
    """БД общая для всего прогона: CRM-сделки и связи, созданные тестом, не должны
    переживать его (иначе повторный id сделки ломает UNIQUE stand_crm_links)."""
    def snapshot():
        db = m.get_session()
        try:
            return ({row.id for row in db.query(m.Deal.id).all()},
                    {row.origin for row in db.query(m.StandCrmLink.origin).all()},
                    {row.id for row in db.query(m.PayinTx.id).all()},
                    {row.id for row in db.query(m.PayinTxUse.id).all()})
        finally:
            db.close()
    deals_before, links_before, txs_before, uses_before = snapshot()
    yield
    db = m.get_session()
    try:
        for link in db.query(m.StandCrmLink).all():
            if link.origin not in links_before:
                db.delete(link)
        for use in db.query(m.PayinTxUse).all():
            if use.id not in uses_before:
                db.delete(use)
        db.flush()
        for deal in db.query(m.Deal).all():
            if deal.id not in deals_before:
                db.delete(deal)
        db.flush()
        for tx in db.query(m.PayinTx).all():
            if tx.id not in txs_before:
                db.delete(tx)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
AT = 1760852000000


def pdf():
    return 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-' + secrets.token_bytes(16)).decode()


def receipt_name():
    db = m.get_session()
    try:
        return json.loads(m._stand_row(db).data)['deals'][0]['files']['receipt'][0]['file']
    finally:
        db.close()


def attach_log(name, role, at=AT, **extra):
    return {'at': at, 'ts': '19.10, 12:00', 'role': role, 'text': 'Приложен файл: receipt · ' + name, **extra}


def fact(client, kind, deal_id=1474):
    status = client.get(f'/api/stand/deals/{deal_id}/close-evidence').json
    return next(f for f in status['facts'] if f['kind'] == kind), status


# ---- факт receipt: приложил любой сотрудник --------------------------------

@pytest.mark.parametrize('role', ['manager', 'operator', 'admin'])
def test_receipt_attached_by_any_role_is_accepted_with_author_and_date(monkeypatch, role):
    client, _, crm = setup_verified(monkeypatch, property_deal=True, uploader_role=role)
    assert fact(client, 'receipt')[0]['reason'] == 'operator_receipt_acceptance_missing'
    name = receipt_name()
    version = change_board(lambda d: d.update(log=[attach_log(name, role)]))
    receipt, status = fact(client, 'receipt')
    assert receipt['ready'] and receipt['system'] and receipt['implicit']
    assert receipt['confirmed_role'] == role and receipt['confirmed_by']
    assert receipt['checked_at'] == '2025-10-19T05:33:20Z'  # at журнала, UTC
    assert 'receipt' not in status['missing']
    assert client.post('/api/stand/deals/1474/close-evidence',
                       json={'version': version, 'kind': 'receipt'}).status_code in (403, 409)


def test_attachment_author_wins_over_s26_completion(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    old_s26 = trail(name)  # операционист Артём, 2025-10-19 05:49:42Z
    change_board(lambda d: d.update(log=old_s26 + [attach_log(name, 'manager', at=1760853000000)]))
    receipt, _ = fact(client, 'receipt')
    assert receipt['ready'] and receipt['confirmed_role'] == 'manager'
    # автор файла главнее даты: чек менеджера не прячется за оператором, позже завершившим s26
    change_board(lambda d: d.update(log=old_s26 + [attach_log(name, 'manager', at=1760851000000)]))
    receipt, _ = fact(client, 'receipt')
    assert receipt['ready'] and receipt['confirmed_role'] == 'manager'
    # без записи о приложении (старая сделка) остаётся приёмка по завершённому s26
    change_board(lambda d: d.update(log=old_s26))
    receipt, _ = fact(client, 'receipt')
    assert receipt['ready'] and receipt['confirmed_role'] == 'operator' and receipt['confirmed_by'] == 'Артём'


def test_receipt_acceptance_requires_server_authorship(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    cases = {
        'no journal entry': [],
        'role of someone else': [attach_log(name, 'operator')],
        'client-claimed author': [attach_log(name, 'manager', kind='comment', author='Лиза')],
        'other file name': [attach_log('other-' + name, 'manager')],
        'bad time': [attach_log(name, 'manager', at=0)],
    }
    for label, log in cases.items():
        change_board(lambda d: d.update(log=log))
        assert not fact(client, 'receipt')[0]['ready'], label


def test_attached_receipt_confirms_payment_without_operator_invoice_paid_flag(monkeypatch):
    client, _, crm = setup_verified(monkeypatch, property_deal=True, uploader_role='manager',
                                    invoice_paid=False)
    name = receipt_name()
    version = change_board(lambda d: d.update(log=[attach_log(name, 'manager')]))
    receipt, status = fact(client, 'receipt')
    assert receipt['ready'] and receipt['implicit'] and receipt['confirmed_role'] == 'manager'
    assert status['missing'] == []
    # маршрут Coins: guard закрытия тоже принимает приложенный чек вместо invoicePaid
    closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert closed.status_code == 201, closed.json


def test_unpaid_invoice_without_attached_receipt_stays_blocked(monkeypatch):
    client, _, crm = setup_verified(monkeypatch, property_deal=True, uploader_role='manager',
                                    invoice_paid=False)
    version = change_board(lambda d: d.update(log=[]))  # чек без серверной записи об авторе
    receipt, _ = fact(client, 'receipt')
    assert not receipt['ready'] and receipt['reason'] == 'invoice_payment_or_receipt_missing'
    closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert closed.status_code == 409
    name = receipt_name()
    change_board(lambda d: d.update(log=[attach_log(name, 'manager')], files={'receipt': []}))
    assert not fact(client, 'receipt')[0]['ready']


def test_crypto_network_fact_still_required_when_receipt_is_attached(monkeypatch):
    client, _, crm = setup_verified(monkeypatch, property_deal=True, uploader_role='manager',
                                    invoice_paid=False)
    name = receipt_name()
    version = change_board(lambda d: d.update(log=[attach_log(name, 'manager')],
                                              serverTransferComplete=False))
    assert not fact(client, 'payout')[0]['ready']
    closed = client.post('/api/stand/deals/1474/crm-close', json={'version': version, 'crm': crm})
    assert closed.status_code == 409


def test_migrated_receipt_never_backfills_acceptance(monkeypatch):
    client, uid, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal['files']['receipt'] = [{'file': 'old.pdf', 'mime': 'application/pdf',
                                     'uploadedById': uid, 'at': '18.10, 10:00', 'data': pdf()}]
        m._stand_externalize_files(db, row, state, migration=True)
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    assert not fact(client, 'receipt')[0]['ready']


# ---- факт payout: недвижимость без отдельной подписи ------------------------

def test_realty_payout_confirmed_by_attached_receipt_without_operator_signoff(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    change_board(lambda d: d.update(postConv=None, paySrc=None, payTo={'bank': 'BBL', 'acc': '123'},
                                    transfer={'amount': 90}))
    payout, _ = fact(client, 'payout')
    assert not payout['ready'] and payout['reason'] == 'operator_confirmation_missing'
    change_board(lambda d: d.update(log=[attach_log(name, 'manager')]))
    payout, _ = fact(client, 'payout')
    assert payout['ready'] and payout['system'] and payout['implicit']
    assert payout['confirmed_role'] == 'manager' and payout['checked_at']


def test_realty_noncrypto_payout_needs_amount_recipient_and_receipt_not_hash(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    base = dict(postConv=None, paySrc=None, mfPayout=[], transfer={}, amountThb=455000,
                payTo={'bank': 'BBL', 'acc': '123-4-56789-0'})
    change_board(lambda d: d.update(base))
    payout, _ = fact(client, 'payout')
    assert not payout['ready'] and payout['reason'] == 'payout_receipt_missing'
    change_board(lambda d: d.update(log=[attach_log(name, 'manager')]))
    assert fact(client, 'payout')[0]['ready']
    change_board(lambda d: d.update(payTo={'bank': 'BBL'}))
    assert fact(client, 'payout')[0]['reason'] == 'payout_fact_missing'
    change_board(lambda d: d.update(payTo=base['payTo'], amountThb=0))
    assert fact(client, 'payout')[0]['reason'] == 'payout_fact_missing'


def test_crypto_payout_keeps_hash_requirement(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    change_board(lambda d: d.update(log=[attach_log(name, 'manager')], amountThb=455000,
                                    payTo={'bank': 'BBL', 'acc': '123'}, serverTransferComplete=False))
    payout, _ = fact(client, 'payout')
    assert not payout['ready'] and payout['reason'] == 'network_payout_proof_missing'


def test_payin_without_network_hash_never_closes_and_asks_for_hash_not_operator(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    version = change_board(lambda d: d.update(log=[attach_log(name, 'manager')], payType='Наличные',
                                              payinHashes=[], incomeAmount=1400))
    payin, status = fact(client, 'payin')
    assert not payin['ready'] and payin['reason'] == 'verified_payin_missing'
    assert payin['required_role'] != 'operator' and 'payin' in status['missing']
    # подписать приход человеком нельзя
    signed = client.post('/api/stand/deals/1474/close-evidence', json={'version': version, 'kind': 'payin'})
    assert signed.status_code == 409 and signed.json['error'] == 'payin_hash_required'


def test_exchange_deal_manual_sources_do_not_replace_payin_hash(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, uploader_role='manager')
    change_board(lambda d: d.update(payType='По реквизитам', payinHashes=[], payinParts=[{'incId': -1, 'amountRub': 1}]))
    payin, _ = fact(client, 'payin')
    assert not payin['ready'] and payin['reason'] == 'verified_payin_missing'


# ---- manualOverride «Перенести в CRM», СД-1489 -------------------------------

def rental_board(*, with_log=True, role='manager', receipt=True):
    board = _realty_board(mfPayout=[], payTo={'purpose': 'Оплата аренды виллы, авг 2026',
                                              'bank': 'Bangkok Bank', 'acc': '123-4-56789-0'})
    deal = board['deals'][0]
    deal['files'] = {'receipt': [{'file': 'kbank-bbl.pdf', 'mime': 'application/pdf', 'data': pdf()}]
                     if receipt else []}
    deal['_attach_log'] = with_log
    return board


def realty_client_with_receipt(monkeypatch, *, with_log=True, role='manager', receipt=True):
    board = rental_board(with_log=with_log, role=role, receipt=receipt)
    uid = realty_setup(monkeypatch, board=board, role=role)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal.pop('_attach_log')
        m._stand_externalize_files(db, row, state, actor=uid, previous={})
        if with_log and receipt:
            deal['log'] = [attach_log('kbank-bbl.pdf', role)]
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    return realty_client(uid)


def bank_override(**payout):
    body = {'route': 'bank', 'amountThb': 455000, 'recipient': {'name': 'Villa Owner Co'}}
    body.update(payout)
    return _override(payout=body)


def bank_crm():
    return _crm(payout_tx_hashes=[])


@pytest.mark.parametrize('role', ['manager', 'admin'])  # закрывает manager/admin, не operator
def test_override_bank_thb_payout_closes_without_hash(monkeypatch, role):
    client = realty_client_with_receipt(monkeypatch, role=role)
    resp = _post(client, bank_override(), bank_crm())
    assert resp.status_code == 201, resp.json
    db = m.get_session()
    try:
        deal = json.loads(m._stand_row(db).data)['deals'][0]
    finally:
        db.close()
    fact_ = deal['payoutFact']
    assert fact_['route'] == 'bank' and fact_['amountThb'] == 455000
    assert fact_['receiptRole'] == role and fact_['receiptAt'] == AT
    assert not deal.get('mfPayout')


@pytest.mark.parametrize('route', ['founder', 'cash'])
def test_override_founder_and_cash_payout_close_without_hash(monkeypatch, route):
    client = realty_client_with_receipt(monkeypatch)
    resp = _post(client, bank_override(route=route), bank_crm())
    assert resp.status_code == 201, resp.json


@pytest.mark.parametrize('label,kwargs,payout,error', [
    ('payment below invoice', {}, dict(amountThb=40000), 'payout_amount_below_invoice'),
    ('no receipt file', dict(receipt=False), {}, 'payout_receipt_required'),
    ('receipt without server journal', dict(with_log=False), {}, 'payout_receipt_required'),
    ('zero amount', {}, dict(amountThb=0), 'payout_amount_required'),
    ('no recipient', {}, dict(recipient={}), 'payout_recipient_required'),
    ('unknown route', {}, dict(route='wire'), 'payout_route_invalid'),
])
def test_override_noncrypto_payout_negative(monkeypatch, label, kwargs, payout, error):
    client = realty_client_with_receipt(monkeypatch, **kwargs)
    board_payto = payout.get('recipient') == {}
    if board_payto:
        db = m.get_session()
        try:
            row = m._stand_row(db)
            state = json.loads(row.data)
            state['deals'][0]['payTo'] = {'purpose': 'Оплата аренды виллы, авг 2026'}
            row.data = json.dumps(state)
            db.commit()
        finally:
            db.close()
    resp = _post(client, bank_override(**payout), bank_crm())
    assert resp.status_code == 400, (label, resp.json)
    assert resp.json['error'] == error


def test_override_crypto_payout_keeps_hash_requirement(monkeypatch):
    client = realty_client_with_receipt(monkeypatch)
    resp = _post(client, _override(payout={'route': 'crypto', 'amountUsdt': 1388.89}), bank_crm())
    assert resp.status_code == 400 and resp.json['error'] == 'payout_hash_required'
    # маршрут не указан = прежнее крипто-поведение
    resp = _post(client, _override(payout={'amountUsdt': 1388.89}), bank_crm())
    assert resp.status_code == 400 and resp.json['error'] == 'payout_hash_required'



def test_override_bank_route_needs_bank_and_account_but_cash_may_be_name_only(monkeypatch):
    client = realty_client_with_receipt(monkeypatch)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        state['deals'][0]['payTo'] = {'purpose': 'Оплата аренды виллы, авг 2026'}
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    resp = _post(client, bank_override(), bank_crm())
    assert resp.status_code == 400 and resp.json['error'] == 'payout_recipient_required'
    resp = _post(client, bank_override(route='cash'), bank_crm())
    assert resp.status_code == 201, resp.json


def test_override_bank_route_cannot_mask_crypto_route(monkeypatch):
    client = realty_client_with_receipt(monkeypatch)
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        state['deals'][0]['postConv'] = 'coins'
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()
    resp = _post(client, bank_override(), bank_crm())
    assert resp.status_code == 400 and resp.json['error'] == 'payout_route_conflict'


def test_forged_payout_fact_does_not_confirm_payout(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    name = receipt_name()
    change_board(lambda d: d.update(log=[attach_log(name, 'manager')], mfPayout=[], transfer={},
                                    postConv=None, paySrc=None, payTo={}, payoutFact={'route': 'bank', 'amountThb': 1}))
    payout, _ = fact(client, 'payout')
    assert not payout['ready'] and payout['reason'] == 'payout_fact_missing'


# ---- второй путь загрузки: «+ Загрузить ещё» (files.additional, documentType=receipt) ----

def move_receipt_to_additional(*, native=True, document_type='receipt', journal=None):
    """Чек лежит только в files.additional, как после «+ Загрузить ещё» в документах."""
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        uploader = int(db.get(m.StandFile, deal['files']['receipt'][0]['storageId']).uploaded_by)
        user = db.get(m.AdminUser, uploader)
        author = user.display_name or user.username
        previous = json.loads(json.dumps(state))
        item = {'id': 'sf_' + secrets.token_hex(8), 'file': 'extra-slip.pdf', 'mime': 'application/pdf',
                'documentType': document_type, 'data': pdf()}
        if native:
            item.update(uploadedById=uploader, uploadedBy=author, demo=False)
        deal['files'] = {'additional': [item]}
        deal['docs'] = {'inv': True}
        if journal is not None:
            deal['log'] = [journal(author, user.role)]
        m._stand_externalize_files(db, row, state, actor=uploader, previous=previous)
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
        return author
    finally:
        db.close()


def additional_log(author, role, at=AT):
    return {'at': at, 'role': role, 'text': 'Приложен документ extra-slip.pdf · ' + author}


@pytest.mark.parametrize('role', ['manager', 'operator', 'admin'])
def test_additional_receipt_is_accepted_like_receipt_slot(monkeypatch, role):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role=role)
    author = move_receipt_to_additional(journal=additional_log)
    receipt, status = fact(client, 'receipt')
    assert receipt['ready'] and receipt['implicit'] and receipt['confirmed_role'] == role
    assert receipt['confirmed_by'] == author and receipt['checked_at'] == '2025-10-19T05:33:20Z'
    assert 'receipt' not in status['missing']


def test_additional_receipt_native_marks_work_without_journal(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    move_receipt_to_additional(native=True)
    receipt, _ = fact(client, 'receipt')
    assert receipt['ready'] and receipt['confirmed_role'] == 'manager' and receipt['checked_at']


def test_additional_receipt_without_native_marks_or_journal_is_not_accepted(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    move_receipt_to_additional(native=False)
    assert not fact(client, 'receipt')[0]['ready']


def test_additional_document_of_other_type_is_not_a_receipt(monkeypatch):
    client, _, _ = setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    move_receipt_to_additional(document_type='other', journal=additional_log)
    receipt, _ = fact(client, 'receipt')
    assert not receipt['ready'] and receipt['reason'] == 'invoice_payment_or_receipt_missing'


def test_additional_receipt_counts_as_valid_receipt_and_content_id(monkeypatch):
    setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    move_receipt_to_additional()
    db = m.get_session()
    try:
        deal = json.loads(m._stand_row(db).data)['deals'][0]
        assert m._stand_valid_receipt(deal)
        assert len(m._stand_receipt_content_ids(deal)) == 1
    finally:
        db.close()


def test_override_accepts_additional_receipt_for_bank_payout(monkeypatch):
    client = realty_client_with_receipt(monkeypatch)
    move_receipt_to_additional_realty()
    resp = _post(client, bank_override(), bank_crm())
    assert resp.status_code == 201, resp.json


def move_receipt_to_additional_realty():
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        uploader = int(db.get(m.StandFile, deal['files']['receipt'][0]['storageId']).uploaded_by)
        user = db.get(m.AdminUser, uploader)
        previous = json.loads(json.dumps(state))
        deal['files'] = {'additional': [{
            'id': 'sf_x', 'file': 'extra-slip.pdf', 'mime': 'application/pdf', 'documentType': 'receipt',
            'uploadedById': uploader, 'uploadedBy': user.display_name or user.username,
            'demo': False, 'data': pdf()}]}
        deal['docs'] = {'inv': True}  # docs.receipt «+ Загрузить ещё» не выставляет
        m._stand_externalize_files(db, row, state, actor=uploader, previous=previous)
        row.data = json.dumps(state)
        db.commit()
    finally:
        db.close()


def test_override_docs_receipt_flag_without_real_file_is_blocked(monkeypatch):
    """mfPayout уже на доске и docs.receipt=true, но файла чека нет — закрыть нельзя."""
    board = _realty_board(files={})
    uid = realty_setup(monkeypatch, board=board)
    resp = _post(realty_client(uid))
    assert resp.status_code == 400 and resp.json['error'] == 'realty_docs_missing'
    board = _realty_board(files={'receipt': [{'file': 'x.pdf', 'mime': 'application/pdf', 'data': 'not-a-file'}]})
    uid = realty_setup(monkeypatch, board=board)
    resp = _post(realty_client(uid))
    assert resp.status_code == 400 and resp.json['error'] == 'realty_docs_missing'


def test_receipt_upload_guard_allows_any_role_on_any_step_but_only_receipts(monkeypatch):
    setup_verified(monkeypatch, property_deal=True, uploader_role='manager')
    before = {'step': 's26', 'files': {'receipt': [{'id': 'a'}]}, 'docs': {}}
    ok = {'step': 's26', 'files': {'receipt': [{'id': 'a'}, {'id': 'b'}]}, 'docs': {'receipt': True}}
    assert m._stand_receipt_upload_only(before, ok, {'files', 'docs'})
    extra_receipt = {'step': 's26', 'files': {'receipt': [{'id': 'a'}],
                     'additional': [{'id': 'c', 'documentType': 'receipt'}]}}
    assert m._stand_receipt_upload_only(before, extra_receipt, {'files'})
    other_type = {'step': 's26', 'files': {'receipt': [{'id': 'a'}],
                  'additional': [{'id': 'c', 'documentType': 'inv'}]}}
    assert not m._stand_receipt_upload_only(before, other_type, {'files'})
    replaced = {'step': 's26', 'files': {'receipt': [{'id': 'z'}]}}
    assert not m._stand_receipt_upload_only(before, replaced, {'files'})
    other_slot = {'step': 's26', 'files': {'receipt': [{'id': 'a'}], 'pass': [{'id': 'p'}]}}
    assert not m._stand_receipt_upload_only(before, other_slot, {'files'})
    assert not m._stand_receipt_upload_only(before, ok, {'files', 'payTo'})
    pass_doc = {'step': 's26', 'files': ok['files'], 'docs': {'receipt': True, 'pass': True}}
    assert not m._stand_receipt_upload_only(before, pass_doc, {'files', 'docs'})


def test_manual_close_resolves_pending_bank_receipt_and_logs_without_notes():
    state = {'deals': [{'id': 1489, 'log': [], 'manualBankReceipt': {'status': 'pending', 'actualAmount': 1217600}}],
             'notes': [{'dealId': 1489, 'role': 'operator', 'read': False},
                       {'dealId': 7, 'role': 'operator', 'read': False}]}
    m._stand_manual_close_resolve_tasks(state, 1489, 'Лиза')
    deal = state['deals'][0]
    receipt = deal['manualBankReceipt']
    assert receipt['status'] == 'cancelled' and receipt['previousStatus'] == 'pending'
    assert receipt['resolvedBy'] == 'Лиза' and receipt['actualAmount'] == 1217600
    assert state['notes'][0]['read'] and 'вне задачника' in state['notes'][0]['resolved']
    assert not state['notes'][1]['read']
    text = deal['log'][-1]['text']
    assert 'вне задачника' in text and 'без подтверждений операциониста' in text and 'Лиза' in text
    # без нот история всё равно пишется
    state = {'deals': [{'id': 5, 'log': []}], 'notes': []}
    m._stand_manual_close_resolve_tasks(state, 5, 'Лиза')
    assert 'вне задачника' in state['deals'][0]['log'][-1]['text']


def test_rub_deal_with_accepted_broker_conversion_hash_is_ready_without_signoff(monkeypatch):
    """Рублёвая сделка остаётся RUB: приход принимает хеш USDT брокера (accepted_conversion)."""
    client, _, _ = setup_verified(monkeypatch, uploader_role='manager')
    tx = {'hash': secrets.token_hex(32), 'net': 'TRC20', 'amount': 100, 'status': 'confirmed',
          'verifiedAt': '2026-10-18T12:00:00Z'}
    db = m.get_session()
    try:
        row = m._stand_row(db)
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal.update(payType='По реквизитам', cnvId=777, payinHashes=[dict(tx, network='TRC20')])
        state['convs'] = [{'id': 777, 'status': 'received', 'txs': [tx],
                           'sources': [{'dealId': deal['id'], 'rub': 9000, 'usdtFact': 100}]}]
        row.data = json.dumps(state)
        row.version += 1
        db.commit()
    finally:
        db.close()
    payin, _ = fact(client, 'payin')
    assert payin['ready'] and payin['source'] == 'accepted_conversion'
    assert payin['required_role'] != 'operator'
