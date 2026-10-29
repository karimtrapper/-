"""Отдельные объекты, настоящие роли и долговечность ссылки после нового запроса."""
import base64
import copy
import io
import json

import pytest
import app as m
import stand_file_storage as storage
import stand_object_store as objects
from tests.test_stand_incoming_wallet_persist import api, fake_role_api, base_api
from tests.test_stand_prepay import seed
from scripts.verify_stand_files import verify


def board(step='s14'):
    return {'deals': [{'id': 1473, 'step': step, 'files': {}, 'docs': {}, 'log': [],
             'type': 'Оплата недвижимости', 'kind': 'Фрихолд', 'docsSent': True}]}


def pdf(data=b'test', name='invoice.pdf'):
    raw = b'%PDF-1.4\n' + data
    return dict(file=name, mime='application/pdf', bytes=len(raw), size='1 КБ',
                at='13.10', data='data:application/pdf;base64,'+base64.b64encode(raw).decode())


def upload(api, raw, kind='inv', name='invoice.pdf', mime='application/pdf'):
    return api[0].post('/api/stand/files', data={'dealId': '1473', 'kind': kind,
                       'file': (io.BytesIO(raw), name, mime)})


def read_db():
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        return row.version, json.loads(row.data)


@pytest.fixture(autouse=True)
def clear_file_rows():
    m._stand_migrate()
    with m.SessionLocal() as db:
        db.query(m.StandFile).delete()
        db.commit()


def test_15mb_pdf_upload_download_metadata_only_and_dedup(api):
    api[1][0] = 'manager'
    seed(board())
    raw = b'%PDF-1.4\n' + b'x' * (15*1024*1024)
    response = upload(api, raw)
    assert response.status_code == 200, response.json
    version, state = read_db()
    item = state['deals'][0]['files']['inv'][0]
    assert version == 2 and item['data'] == '__detached__' and 'object_key' not in item
    assert len(json.dumps(state)) < 5000
    assert api[0].get('/api/stand/file/1473/inv/0').data == raw
    duplicate = upload(api, raw)
    assert duplicate.json['duplicate'] and duplicate.json['version'] == 2
    assert len(read_db()[1]['deals'][0]['files']['inv']) == 1
    with m.SessionLocal() as db:
        assert db.query(m.StandFile).count() == 1
        row = db.get(m.StandFile, item['storageId'])
        assert row.sha256 == storage.digest(raw) and row.size == len(raw)
        assert 'data' not in m.StandFile.__table__.columns
        assert row.uploaded_by and row.uploaded_at


def test_no_configuration_rejects_upload_no_inline_fallback(api, monkeypatch):
    monkeypatch.delenv('STAND_FILES_LOCAL_DIR')
    api[1][0] = 'manager'
    seed(board())
    response = upload(api, b'%PDF-1.4\ntest')
    assert response.status_code == 400 and 'не настроено' in response.json['error']
    assert read_db()[0] == 1 and read_db()[1]['deals'][0]['files'] == {}
    with m.SessionLocal() as db:
        assert db.query(m.StandFile).count() == 0


@pytest.mark.parametrize('role,kind,step,pending,allowed', [
    ('operator','pass','s14',False,False), ('manager','pass','s5',False,True),
    ('teodor','receipt','s26',False,False), ('operator','receipt','s26',False,True),
    ('manager','clientPayinReceipt','s14',False,True),
    ('operator','clientPayinReceipt','s14',False,False),
    ('operator','bankCreditEvidence','s14',True,True),
    ('manager','bankCreditEvidence','s14',True,False),
    ('operator','bankCreditEvidence','s18',True,False),
])
def test_upload_preserves_roles_and_steps(api, role, kind, step, pending, allowed):
    api[1][0] = role
    state = board(step)
    if pending: state['deals'][0]['manualBankReceipt'] = {'status':'pending'}
    seed(state)
    response = upload(api, b'%PDF-1.4\npermissions', kind)
    assert (response.status_code == 200) == allowed, response.json
    if not allowed:
        assert read_db()[0] == 1
        with m.SessionLocal() as db: assert db.query(m.StandFile).count() == 0
    elif step == 's5':
        assert read_db()[1]['deals'][0]['_managerDraft']['files']['pass']
        api[1][0] = 'operator'
        assert api[0].get('/api/stand/file/1473/pass/0?draft=1').status_code == 403


@pytest.mark.parametrize('role,step', [
    ('manager', 's5'), ('operator', 's23'), ('admin', 'done'),
])
def test_extra_document_upload_on_any_step(api, role, step):
    api[1][0] = role
    state = board(step)
    if step == 'done':
        state['deals'][0].update(closed=True, closeReason='Успешно завершена')
    seed(state)
    raw = b'%PDF-1.4\nextra'
    response = api[0].post('/api/stand/files', data={
        'dealId': '1473', 'kind': 'additional', 'documentType': 'inv', 'extra': '1',
        'file': (io.BytesIO(raw), 'extra.pdf', 'application/pdf')})
    assert response.status_code == 200, response.json
    deal = response.json['data']['deals'][0]
    assert deal['files']['additional'][0]['file'] == 'extra.pdf'
    assert deal['files']['additional'][0]['documentType'] == 'inv'
    assert not deal['docs'].get('inv')
    assert '_managerDraft' not in deal or not (deal['_managerDraft'].get('files') or {}).get('inv')
    assert api[0].get('/api/stand/file/1473/additional/0').data == raw


def test_other_manager_cannot_change_deal_documents(api):
    api[1][0] = 'manager'
    state = board('s14')
    state['deals'][0]['manager'] = 'Другой менеджер'
    seed(state)
    denied = api[0].post('/api/stand/files', data={
        'dealId': '1473', 'kind': 'additional', 'documentType': 'inv', 'extra': '1',
        'file': (io.BytesIO(b'%PDF-1.4\nother'), 'other.pdf', 'application/pdf')})
    assert denied.status_code == 403
    assert 'её менеджер' in denied.json['error']


def test_migrate_16_files_and_verify_byte_for_byte_and_idempotence(api):
    state = board()
    state['deals'].append(dict(id=1484, step='s23', files={}, _managerDraft={'files': {}}, docs={}))
    original = []
    kinds = ['pass', 'inv', 'spa', 'ipds', 'signed', 'receipt', 'clientPayinReceipt', 'bankCreditEvidence']
    for i in range(16):
        deal = state['deals'][i//8]
        target = deal['_managerDraft'] if i == 10 else deal
        item = pdf((str(i)*150000).encode())
        target['files'].setdefault(kinds[i%8], []).append(item)
        original.append((deal['id'], kinds[i%8], i == 10, storage.decode(item)))
    seed(state)
    assert m._stand_migrate_files() == 1
    assert m._stand_migrate_files() == 0
    assert read_db()[0] == 2
    api[1][0] = 'manager'
    for deal_id, kind, draft, raw in original:
        response = api[0].get(f'/api/stand/file/{deal_id}/{kind}/0?draft={int(draft)}')
        assert response.status_code == 200 and response.data == raw
    with m.engine.connect() as conn:
        result = verify(conn, state)
    assert result['ok'] and result['references'] == result['objects_verified'] == 16
    assert len(json.dumps(read_db()[1])) < 15000


def test_migration_failure_rolls_back_all_json_and_rows(api, monkeypatch):
    state = board(); state['deals'][0]['files']['pass'] = [pdf(b'a'), pdf(b'b')]
    seed(state)
    real = storage.read_verified
    calls = []
    def fail(key, size, sha):
        calls.append(key)
        if len(set(calls)) > 1: raise ValueError('SHA256 mismatch')
        return real(key,size,sha)
    monkeypatch.setattr(storage, 'read_verified', fail)
    with pytest.raises(ValueError): m._stand_migrate_files()
    assert read_db() == (1, state)
    with m.SessionLocal() as db: assert db.query(m.StandFile).count() == 0
    monkeypatch.setattr(storage, 'read_verified', real)
    assert m._stand_migrate_files() == 1


def test_stale_base64_and_missing_large_file_do_not_erase_references(api):
    api[1][0] = 'manager'
    state = board();state['deals'][0]['files']['inv'] = [pdf()]
    seed(state);m._stand_migrate_files()
    response = api[0].put('/api/stand/state', json={'version':2, 'data':state})
    assert response.status_code == 200, response.json
    item = read_db()[1]['deals'][0]['files']['inv'][0]
    old = response.json['data'];old['deals'][0]['files']['inv'] = []
    old['deals'][0]['docs']['inv'] = False
    response = api[0].put('/api/stand/state', json={'version':3,'data':old})
    assert response.status_code == 200, response.json
    assert read_db()[1]['deals'][0]['files']['inv'][0]['storageId'] == item['storageId']
    assert api[0].get('/api/stand/file/1473/inv/0').data == storage.decode(pdf())


def test_delete_soft_and_wrong_reference_forbidden(api):
    api[1][0] = 'manager';seed(board())
    response = upload(api, b'%PDF-1.4\ndelete')
    assert response.status_code == 200, response.json
    state = response.json['data']; item = state['deals'][0]['files']['inv'][0]
    forged = copy.deepcopy(state);forged['deals'][0]['files']['pass'] = [item]
    assert api[0].put('/api/stand/state',json={'version':2,'fileStorageVersion':1,'data':forged}).status_code == 409
    state['deals'][0]['files']['inv'] = []
    response = api[0].put('/api/stand/state',json={'version':2,'fileStorageVersion':1,'data':state})
    assert response.status_code == 409
    assert response.json['error'] == 'Удаляйте документы кнопкой «Удалить»'
    response = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}", json={'action': 'delete'})
    assert response.status_code == 200, response.json
    with m.SessionLocal() as db:
        row = db.get(m.StandFile, item['storageId'])
        assert row.deleted_at is not None
        assert objects.read_verified(row.object_key, row.size, row.sha256) == b'%PDF-1.4\ndelete'
    assert api[0].get('/api/stand/file/1473/inv/0').status_code == 404


def test_document_delete_and_admin_restore_keep_object_and_history(api):
    api[1][0] = 'manager'
    seed(board('s23'))
    raw = b'%PDF-1.4\nrecoverable'
    uploaded = upload(api, raw)
    assert uploaded.status_code == 200, uploaded.json
    item = uploaded.json['data']['deals'][0]['files']['inv'][0]
    url = f"/api/stand/files/1473/inv/{item['id']}"
    deleted = api[0].patch(url, json={'action': 'delete'})
    assert deleted.status_code == 200, deleted.json
    deal = deleted.json['data']['deals'][0]
    assert not deal['files']['inv']
    assert deal['deletedFiles']['inv'][0]['id'] == item['id']
    assert 'Удалён документ invoice.pdf' in deal['log'][-1]['text']
    with m.SessionLocal() as db:
        stored = db.get(m.StandFile, item['storageId'])
        assert stored.deleted_at is not None
        assert objects.read_verified(stored.object_key, stored.size, stored.sha256) == raw
    assert api[0].get('/api/stand/file/1473/inv/0').status_code == 404
    stale = api[0].get('/api/stand/state').json
    stale['data']['deals'][0].pop('deletedFiles')
    saved = api[0].put('/api/stand/state', json={
        'version': stale['version'], 'fileStorageVersion': 1, 'data': stale['data']})
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][0]['deletedFiles']['inv'][0]['id'] == item['id']
    assert api[0].patch(url, json={'action': 'restore'}).status_code == 403
    api[1][0] = 'admin'
    restored = api[0].patch(url, json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    assert restored.json['data']['deals'][0]['files']['inv'][0]['id'] == item['id']
    assert api[0].get('/api/stand/file/1473/inv/0').data == raw


def test_manager_draft_file_can_be_soft_deleted_and_restored(api):
    api[1][0] = 'manager'
    seed(board('s5'))
    uploaded = upload(api, b'%PDF-1.4\ndraft', kind='pass', name='passport.pdf')
    assert uploaded.status_code == 200, uploaded.json
    item = uploaded.json['data']['deals'][0]['_managerDraft']['files']['pass'][0]
    url = f"/api/stand/files/1473/pass/{item['id']}?draft=1"
    deleted = api[0].patch(url, json={'action': 'delete'})
    assert deleted.status_code == 200, deleted.json
    draft = deleted.json['data']['deals'][0]['_managerDraft']
    assert not draft['files']['pass']
    assert draft['deletedFiles']['pass'][0]['id'] == item['id']
    assert 'Удалён документ passport.pdf' in deleted.json['data']['deals'][0]['log'][-1]['text']
    api[1][0] = 'admin'
    restored = api[0].patch(url, json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    assert restored.json['data']['deals'][0]['_managerDraft']['files']['pass'][0]['id'] == item['id']


def test_closed_deal_rejects_non_admin_document_delete(api):
    api[1][0] = 'manager'
    state = board('done')
    state['deals'][0].update(closed=True, closeReason='Успешно завершена')
    seed(state)
    uploaded = upload(api, b'%PDF-1.4\nclosed')
    assert uploaded.status_code == 409  # legacy upload guard, tested separately
    state['deals'][0]['closed'] = False
    seed(state)
    uploaded = upload(api, b'%PDF-1.4\nclosed')
    assert uploaded.status_code == 200, uploaded.json
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        board_state = json.loads(row.data)
        board_state['deals'][0].update(closed=True, closeReason='Успешно завершена')
        row.data = json.dumps(board_state, ensure_ascii=False)
        db.commit()
    item = uploaded.json['data']['deals'][0]['files']['inv'][0]
    url = f"/api/stand/files/1473/inv/{item['id']}"
    denied = api[0].patch(url, json={'action': 'delete'})
    assert denied.status_code == 403
    assert denied.json['error'] == 'Сделка закрыта, удаление документов — только администратором'
    api[1][0] = 'admin'
    assert api[0].patch(url, json={'action': 'delete'}).status_code == 200
    assert api[0].patch(url, json={'action': 'restore'}).status_code == 200


def test_completed_crm_deal_blocks_delete_even_if_board_is_open(api):
    api[1][0] = 'manager'
    seed(board('s14'))
    uploaded = upload(api, b'%PDF-1.4\ncrm-completed')
    assert uploaded.status_code == 200, uploaded.json
    with m.SessionLocal() as db:
        crm = m.Deal(deal_type=m.DealType.PAY_IN, status=m.DealStatus.COMPLETED)
        db.add(crm)
        db.flush()
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        state['deals'][0]['crmDealId'] = crm.id
        row.data = json.dumps(state, ensure_ascii=False)
        db.commit()
    item = uploaded.json['data']['deals'][0]['files']['inv'][0]
    url = f"/api/stand/files/1473/inv/{item['id']}"
    denied = api[0].patch(url, json={'action': 'delete'})
    assert denied.status_code == 403
    assert 'только администратором' in denied.json['error']
    assert read_db()[1]['deals'][0]['files']['inv'][0]['id'] == item['id']
    forged = api[0].get('/api/stand/state').json
    forged['data']['deals'][0]['files']['inv'] = []
    bypass = api[0].put('/api/stand/state', json={
        'version': forged['version'], 'fileStorageVersion': 1, 'data': forged['data']})
    assert bypass.status_code == 403
    assert 'только администратором' in bypass.json['error']


def test_agreement_document_soft_delete_history_and_admin_restore(api):
    api[1][0] = 'manager'
    raw = b'%PDF-1.4\nissued'
    with m.SessionLocal() as db:
        agreement = m.Agreement(client_name='Документы QA', client_key='qa-docs',
                                route_key='legacy', deal_type='freehold', number='QA-DOC-1')
        db.add(agreement)
        db.flush()
        doc = m.AgreementDoc(agreement_id=agreement.id, kind='invoice', filename='issued.pdf',
                             mime='application/pdf', size=len(raw), data=raw, seq=1)
        db.add(doc)
        db.flush()
        agreement_id, doc_id = agreement.id, doc.id
        db.commit()
    state = board('s14')
    state['deals'][0].update(docPack={'agreementId': agreement_id, 'version': 1},
                             docsIssued=[{'kind':'bill', 'docId':doc_id, 'file':'issued.pdf',
                                          'version':1}])
    seed(state)
    url = f'/api/docs/file/{doc_id}'
    whole = api[0].delete(f'/api/docs/agreements/{agreement_id}')
    assert whole.status_code == 409
    assert 'связан со сделкой' in whole.json['error']
    deleted = api[0].patch(url, json={'action': 'delete'})
    assert deleted.status_code == 200, deleted.json
    with m.SessionLocal() as db:
        saved = db.get(m.AgreementDoc, doc_id)
        assert saved.deleted_at is not None and saved.data == raw
    deal = read_db()[1]['deals'][0]
    assert 'Удалён документ issued.pdf' in deal['log'][-1]['text']
    assert deal['docsIssued'][0]['deletedAt']
    assert api[0].get(url).status_code == 404
    assert not api[0].get(f'/api/docs/agreements/{agreement_id}').json['agreement']['docs']
    assert api[0].patch(url, json={'action': 'restore'}).status_code == 403
    api[1][0] = 'admin'
    assert api[0].get(f'/api/docs/agreements/{agreement_id}').json['agreement']['docs'][0]['deleted_at']
    restored = api[0].patch(url, json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    assert api[0].get(url).data == raw
    assert not read_db()[1]['deals'][0]['docsIssued'][0].get('deletedAt')
    with m.SessionLocal() as db:
        crm = m.Deal(deal_type=m.DealType.PAY_IN, status=m.DealStatus.COMPLETED)
        db.add(crm)
        db.flush()
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        state['deals'][0]['crmDealId'] = crm.id
        row.data = json.dumps(state, ensure_ascii=False)
        db.commit()
    api[1][0] = 'manager'
    denied = api[0].patch(url, json={'action': 'delete'})
    assert denied.status_code == 403
    assert denied.json['error'] == 'Сделка закрыта, удаление документов — только администратором'
    api[1][0] = 'admin'
    assert api[0].patch(url, json={'action': 'delete'}).status_code == 200
    assert api[0].patch(url, json={'action': 'restore'}).status_code == 200


def test_crm_additional_document_upload_uses_existing_kind(api):
    api[1][0] = 'operator'
    with m.SessionLocal() as db:
        agreement = m.Agreement(client_name='Загрузка QA', client_key='qa-upload',
                                route_key='legacy', deal_type='leasehold', number='QA-UP-1')
        db.add(agreement)
        db.commit()
        agreement_id = agreement.id
    raw = b'%PDF-1.4\nadditional-crm'
    url = f'/api/docs/agreements/{agreement_id}/upload'
    uploaded = api[0].post(url, data={'kind':'source_other',
        'files':(io.BytesIO(raw),'other.pdf','application/pdf')})
    assert uploaded.status_code == 200, uploaded.json
    doc = uploaded.json['agreement']['docs'][0]
    assert doc['kind'] == 'source_other'
    assert api[0].get(f"/api/docs/file/{doc['id']}").data == raw
    forbidden = api[0].post(url, data={'kind':'agreement',
        'files':(io.BytesIO(raw),'forged.pdf','application/pdf')})
    assert forbidden.status_code == 400
    signed = api[0].post(url, data={'kind':'signed', 'files':(
        io.BytesIO(b'PK\x03\x04legacy-signed-document'), 'signed.docx',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert signed.status_code == 200, signed.json


def test_crm_linked_document_rejects_another_manager(api):
    api[1][0] = 'manager'
    with m.SessionLocal() as db:
        agreement = m.Agreement(client_name='Чужая сделка', client_key='qa-owner',
                                route_key='legacy', deal_type='freehold', number='QA-OWNER-1')
        db.add(agreement)
        db.flush()
        doc = m.AgreementDoc(agreement_id=agreement.id, kind='invoice', filename='owner.pdf',
                             mime='application/pdf', size=8, data=b'%PDF-1.4', seq=1)
        db.add(doc)
        db.flush()
        agreement_id, doc_id = agreement.id, doc.id
        db.commit()
    state = board('s14')
    state['deals'][0].update(manager='Другой менеджер', docPack={'agreementId': agreement_id})
    seed(state)
    blocked = api[0].post(f'/api/docs/agreements/{agreement_id}/upload', data={
        'kind': 'source_other', 'files': (io.BytesIO(b'%PDF-1.4'), 'extra.pdf', 'application/pdf')})
    assert blocked.status_code == 403
    assert api[0].patch(f'/api/docs/file/{doc_id}', json={'action': 'delete'}).status_code == 403


def test_put_cannot_move_existing_file_to_another_document_type(api):
    api[1][0] = 'manager'
    seed(board())
    uploaded = upload(api, b'%PDF-1.4\nmove-me')
    assert uploaded.status_code == 200, uploaded.json
    state = uploaded.json['data']
    item = state['deals'][0]['files']['inv'].pop()
    state['deals'][0]['files']['spa'] = [item]
    moved = api[0].put('/api/stand/state', json={
        'fileStorageVersion': 1, 'version': uploaded.json['version'], 'data': state})
    assert moved.status_code == 409
    assert moved.json['error'] in ('invalid_file_marker', 'Удаляйте документы кнопкой «Удалить»')
    assert read_db()[1]['deals'][0]['files']['inv'][0]['id'] == item['id']


def test_bank_evidence_delete_keeps_step_and_role_rules(api):
    api[1][0] = 'operator'
    state = board('s14')
    state['deals'][0]['manualBankReceipt'] = {'status': 'pending'}
    seed(state)
    uploaded = upload(api, b'%PDF-1.4\ncredit', kind='bankCreditEvidence', name='credit.pdf')
    assert uploaded.status_code == 200, uploaded.json
    item = uploaded.json['data']['deals'][0]['files']['bankCreditEvidence'][0]
    url = f"/api/stand/files/1473/bankCreditEvidence/{item['id']}"
    api[1][0] = 'manager'
    assert api[0].patch(url, json={'action': 'delete'}).status_code == 403
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        later = json.loads(row.data)
        later['deals'][0]['step'] = 's18'
        row.data = json.dumps(later, ensure_ascii=False)
        db.commit()
    api[1][0] = 'operator'
    denied = api[0].patch(url, json={'action': 'delete'})
    assert denied.status_code == 403
    assert 'до подтверждения' in denied.json['error']
    api[1][0] = 'admin'
    assert api[0].patch(url, json={'action': 'delete'}).status_code == 200


def test_size_limits_and_no_total_board_limit(api, monkeypatch):
    api[1][0] = 'manager';seed(board())
    response = upload(api,b'%PDF-' + b'x'*(20*1024*1024))
    assert response.status_code == 400 and '20 МБ' in response.json['error']
    monkeypatch.setattr(storage,'DEAL_LIMIT',25)
    response = upload(api,b'%PDF-' + b'x'*21)
    assert response.status_code == 400 and '200 МБ' in response.json['error']
    assert read_db()[0] == 1


def test_new_base64_put_is_externalized(api):
    api[1][0] = 'manager';seed(board())
    state = board();state['deals'][0]['files']['inv'] = [pdf(b'old browser')]
    response = api[0].put('/api/stand/state', json={'version':1,'data':state})
    assert response.status_code == 200, response.json
    assert read_db()[1]['deals'][0]['files']['inv'][0]['storageId']
    assert api[0].get('/api/stand/file/1473/inv/0').data == storage.decode(pdf(b'old browser'))


def test_s3_configuration_and_private_calls_no_secret_errors(monkeypatch):
    from botocore.stub import Stubber
    monkeypatch.delenv('STAND_FILES_LOCAL_DIR')
    for key, value in {'ENDPOINT':'https://t3.storageapi.dev','BUCKET':'stand-files-test',
                       'REGION':'auto','ACCESS_KEY_ID':'synthetic-access',
                       'SECRET_ACCESS_KEY':'synthetic-secret','ADDRESSING':'virtual-host'}.items():
        monkeypatch.setenv('STAND_FILES_S3_'+key, value)
    backend = objects.storage()
    assert backend.client.meta.config.s3['addressing_style'] == 'virtual'
    assert backend.client.meta.config.proxies == {}
    with Stubber(backend.client) as stub:
        stub.add_response('put_object', {}, {'Bucket':'stand-files-test','Key':'object',
                          'Body':b'bytes','ContentType':'application/pdf'})
        backend.put('object',b'bytes','application/pdf')
        stub.add_response('get_object', {'Body':io.BytesIO(b'bytes')},
                          {'Bucket':'stand-files-test','Key':'object'})
        assert backend.open('object').read() == b'bytes'
        stub.add_client_error('put_object', 'Denied', 'synthetic-secret', expected_params={
            'Bucket':'stand-files-test','Key':'object','Body':b'bytes','ContentType':'application/pdf'})
        with pytest.raises(objects.StorageUnavailable) as exc:
            backend.put('object',b'bytes','application/pdf')
        assert 'synthetic-secret' not in str(exc.value)


def test_storage_egress_opens_only_exact_host_in_scope(monkeypatch):
    import stand_egress as guard
    monkeypatch.setenv('STAND_FILES_S3_ENDPOINT','https://t3.storageapi.dev')
    monkeypatch.setenv('STAND_FILES_S3_BUCKET','stand-files-test')
    monkeypatch.setenv('STAND_FILES_S3_ADDRESSING','virtual-host')
    host = 'stand-files-test.t3.storageapi.dev'
    assert not guard._hostname_allowed(host,443)
    with guard.storage_connection(host):
        assert guard._hostname_allowed(host,443)
        assert not guard._hostname_allowed(host,80)
        assert not guard._hostname_allowed('other.t3.storageapi.dev',443)
        assert not guard._hostname_allowed('grusha.up.railway.app',443)
    assert not guard._hostname_allowed(host,443)
    with pytest.raises(ValueError):
        with guard.storage_connection('other.t3.storageapi.dev'): pass


def test_large_image_browser_compression_and_pdf_untouched():
    import re
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    source = Path('static/stand/tasks.html').read_text()
    function = re.search(
        r'^async function fileOptimizeImage\([\s\S]*?^}',source,re.M).group()
    shells = list(Path('.browser-cache').glob('chromium_headless_shell-*/**/chrome-headless-shell'))
    with sync_playwright() as pw:
        if not shells and not Path(pw.chromium.executable_path).exists():
            pytest.skip('Установите Chromium: PLAYWRIGHT_BROWSERS_PATH=.browser-cache uvx --from playwright playwright install chromium --only-shell')
        browser = pw.chromium.launch(headless=True, executable_path=str(shells[0].resolve()) if shells else None)
        page = browser.new_page(viewport={'width':1300,'height':600})
        page.route('**/*', lambda route: route.abort())
        page.set_content('<body style="margin:0;background:white"></body>')
        page.add_script_tag(content=function)
        result = page.evaluate('''async () => {
          const c=document.createElement('canvas');c.width=3200;c.height=1300;
          const x=c.getContext('2d'), pixels=x.createImageData(3200,1300);
          let seed=17;
          for(let i=0;i<pixels.data.length;i+=4){seed=(Math.imul(seed,1664525)+1013904223)>>>0;
            pixels.data[i]=seed&255;pixels.data[i+1]=(seed>>>8)&255;pixels.data[i+2]=(seed>>>16)&255;pixels.data[i+3]=255;}
          x.putImageData(pixels,0,0);x.fillStyle='white';x.fillRect(0,0,3200,600);
          x.fillStyle='black';x.font='16px Arial';
          for(let i=0;i<14;i++)x.fillText('Выписка: 13.10.2026  Поступление 123 456,78 RUB  Счёт 40702810900000123456',30,30+i*30);
          const png=await new Promise(r=>c.toBlob(r,'image/png'));
          const original=new File([png],'statement.png',{type:'image/png'});
          const out=await fileOptimizeImage(original), decoded=await createImageBitmap(out);
          const shown=document.createElement('canvas');shown.width=1200;shown.height=450;
          shown.getContext('2d').drawImage(decoded,0,0);document.body.appendChild(shown);
          const pdf=new File(['%PDF-1.4'],'invoice.pdf',{type:'application/pdf'});
          return {input:original.size,output:out.size,width:decoded.width,height:decoded.height,
                  mime:out.type,pdfUntouched:(await fileOptimizeImage(pdf))===pdf};
        }''')
        page.screenshot(path='/tmp/calccrm-files-compressed-text.png')
        browser.close()
    assert 6*1024*1024 < result['input'] < 20*1024*1024
    assert result['output'] < result['input'] / 2
    assert max(result['width'], result['height']) == 2400
    assert result['mime'] == 'image/webp' and result['pdfUntouched']
    Path('/tmp/calccrm-files-compression.json').write_text(json.dumps(result))
    print('IMAGE_COMPRESSION',result)


def test_migration_preserves_existing_attestations_and_file_change_invalidates(api):
    api[1][0] = 'manager'
    state = board('s27');deal = state['deals'][0]
    deal.update(sentToClient=True, pay={'invoicePaid':True}, docs={'receipt':True})
    deal['files']['receipt'] = [pdf(b'old receipt')]
    seed(state)
    with m.SessionLocal() as db:
        row = db.get(m.StandState,1);row.generation = 'files-evidence-test'
        m._stand_upsert_close_evidence(db,row,deal,'sent',1,'manager_attestation')
        m._stand_upsert_close_evidence(db,row,deal,'receipt',1,'operator_attestation')
        db.commit()
    m._stand_migrate_files()
    with m.SessionLocal() as db:
        current = json.loads(db.get(m.StandState,1).data)['deals'][0]
        for kind in ('sent','receipt'):
            proof = db.query(m.StandCloseEvidence).filter_by(generation='files-evidence-test',kind=kind).one()
            assert proof.fingerprint == m._stand_close_fingerprint(current,kind)
            changed = copy.deepcopy(current)
            changed['files']['receipt'].append(pdf(b'new receipt'))
            assert proof.fingerprint != m._stand_close_fingerprint(changed,kind)


def test_migration_duplicates_share_object_and_sha_failure_detected(api):
    state=board();state['deals'][0]['files']['pass']=[pdf(b'duplicate'),pdf(b'duplicate')]
    seed(state);m._stand_migrate_files()
    with m.SessionLocal() as db:
        assert db.query(m.StandFile).count()==1
        row=db.query(m.StandFile).one()
        objects.storage().path(row.object_key).write_bytes(b'corrupted')
    with m.engine.connect() as conn:
        report=verify(conn,state)
    assert not report['ok'] and report['errors']


@pytest.mark.parametrize('duplicate', [False, True])
def test_parallel_uploads_keep_both_results_or_deduplicate(api, duplicate):
    from concurrent.futures import ThreadPoolExecutor
    api[1][0]='manager';seed(board())
    with api[0].session_transaction() as session:
        uid=session['user_id']
    def worker(index):
        client=m.app.test_client()
        with client.session_transaction() as session: session['user_id']=uid
        raw=b'%PDF-1.4\\n'+str(0 if duplicate else index).encode()
        return upload((client,None),raw)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(worker,[0,1]))
    assert all(r.status_code==200 for r in responses), [r.json for r in responses]
    version,state=read_db()
    assert version==(2 if duplicate else 3)
    assert len(state['deals'][0]['files']['inv'])==(1 if duplicate else 2)


def test_bad_legacy_receipt_does_not_hide_later_valid_receipt(api):
    state=board();bad=pdf(b'invalid');bad['data']='data:application/pdf;base64,eA=='
    state['deals'][0]['files']['receipt']=[bad,pdf(b'valid')]
    seed(state);m._stand_migrate_files()
    with m.app.test_request_context('/'):
        assert m._stand_valid_receipt(read_db()[1]['deals'][0])


def test_legacy_upload_author_comes_from_session(api):
    api[1][0]='manager';seed(board())
    state=board();item=pdf(b'author');item['uploadedById']=999999
    state['deals'][0]['files']['inv']=[item]
    response=api[0].put('/api/stand/state',json={'version':1,'data':state})
    assert response.status_code==200,response.json
    with api[0].session_transaction() as session: uid=session['user_id']
    with m.SessionLocal() as db:
        assert db.query(m.StandFile).one().uploaded_by==str(uid)


def test_manager_adds_file_through_board_save_on_deal_with_manager(api):
    """Сохранение доски менеджером с новым файлом в сделке, где указан менеджер,
    не должно падать 500 (баг 29.10: UnboundLocalError actor_id в stand_state_put)."""
    api[1][0] = 'manager'
    state = board('s5')
    state['deals'][0]['manager'] = 'Другой менеджер'
    seed(state)
    version, current = read_db()
    current['deals'][0]['files'] = {'pass': [dict(pdf(b'board-save', 'pass.pdf'))]}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code != 500, response.data[:300]
    assert response.status_code == 403
    assert 'её менеджер' in response.json['error']
