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
    assert response.status_code == 200, response.json
    with m.SessionLocal() as db:
        row = db.get(m.StandFile, item['storageId'])
        assert row.deleted_at is not None
        assert objects.read_verified(row.object_key, row.size, row.sha256) == b'%PDF-1.4\ndelete'
    assert api[0].get('/api/stand/file/1473/inv/0').status_code == 404


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
