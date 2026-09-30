"""Private early manager inputs and explicit publication on the existing stand board."""
import copy
import json

import pytest

import app as appmod


@pytest.fixture
def board(monkeypatch):
    monkeypatch.setattr(appmod, 'STAND_MODE', True)
    monkeypatch.setenv('LOCAL_NO_AUTH', '1')
    role = {'value': 'manager'}
    monkeypatch.setattr(appmod, 'current_role', lambda: role['value'])
    monkeypatch.setattr(appmod, '_stand_deliver_notes', lambda: None)
    appmod._stand_migrate()

    def seed(deal):
        db = appmod.get_session()
        try:
            row = appmod._stand_row(db)
            state = (deal if 'deals' in deal else
                     {'deals': [deal], 'convs': [], 'wallets': [], 'notes': []})
            row.data = json.dumps(state)
            row.version = 1
            db.commit()
        finally:
            db.close()

    with appmod.app.test_client() as client:
        db = appmod.get_session()
        try:
            user = db.query(appmod.AdminUser).filter_by(username='t34_synthetic').first()
            if not user:
                user = appmod.AdminUser(username='t34_synthetic', role='manager',
                                        password_hash=appmod.AdminUser.hash_password('test'))
                db.add(user)
                db.commit()
            uid = user.id
        finally:
            db.close()
        with client.session_transaction() as session:
            session['user_id'] = uid
        yield client, role, seed


def _deal(step):
    return {'id': 3401, 'step': step, 'type': 'Оплата недвижимости',
            'kind': 'Лизхолд', 'payType': 'По реквизитам', 'log': [],
            'pay': {}, 'docs': {}, 'files': {}, 'docMeta': {}}


def _get(client):
    response = client.get('/api/stand/state')
    assert response.status_code == 200
    return response.json


def _put(client, current, deal, *, notes=None):
    data = copy.deepcopy(current['data'])
    data['deals'][0] = deal
    if notes is not None:
        data['notes'] = notes
    return client.put('/api/stand/state', json={'version': current['version'], 'data': data})


@pytest.mark.parametrize('step', ['s5', 's11'])
def test_early_requisites_are_private_until_native_manager_confirmation(board, step):
    client, role, seed = board
    seed(_deal(step))
    initial = _get(client)
    deal = copy.deepcopy(initial['data']['deals'][0])
    deal['_managerDraft'] = {'payTo': {'dev': 'PRIVATE_DEVELOPER', 'bank': 'PRIVATE_BANK',
                                     'acc': 'PRIVATE_ACCOUNT', 'purpose': 'PRIVATE_PURPOSE'}}
    saved = _put(client, initial, deal)
    assert saved.status_code == 200, saved.json
    assert saved.json['data']['deals'][0]['step'] == step
    assert saved.json['data']['deals'][0].get('reqTask') is None
    assert saved.json['data']['deals'][0].get('payTo') is None
    assert saved.json['data']['notes'] == []

    role['value'] = 'operator'
    hidden = _get(client)
    assert '_managerDraft' not in hidden['data']['deals'][0]
    assert 'PRIVATE_ACCOUNT' not in json.dumps(hidden)
    assert hidden['data']['notes'] == []
    own = copy.deepcopy(hidden['data']['deals'][0])
    own['log'].append({'text': 'оператор продолжает свой шаг'})
    operator_save = _put(client, hidden, own)
    assert operator_save.status_code == 200
    assert 'PRIVATE_ACCOUNT' not in operator_save.get_data(as_text=True)
    conflict = _put(client, hidden, own)
    assert conflict.status_code == 409
    assert 'PRIVATE_ACCOUNT' not in conflict.get_data(as_text=True)

    role['value'] = 'manager'
    resumed = _get(client)
    assert resumed['data']['deals'][0]['_managerDraft']['payTo']['acc'] == 'PRIVATE_ACCOUNT'
    spoof = copy.deepcopy(resumed['data']['deals'][0])
    spoof['step'] = 's22'
    denied = _put(client, resumed, spoof)
    assert denied.status_code == 409
    assert _get(client)['data']['deals'][0]['step'] == step
    payto = copy.deepcopy(resumed['data']['deals'][0])
    payto['payTo'] = payto['_managerDraft']['payTo']
    payto['payTo']['amount'] = 100
    assert _put(client, resumed, payto).status_code == 409
    fake_task = copy.deepcopy(resumed['data']['deals'][0])
    fake_task['reqTask'] = 'open'
    assert _put(client, resumed, fake_task).status_code == 409

    # The native afterPayin phase opens the existing manager task. It is a
    # synthetic fixture here; reqSave publication below uses real versioned HTTP.
    native = copy.deepcopy(resumed['data']['deals'][0])
    native.update(step='s22', reqTask='open')
    seed(native)
    opened = _get(client)
    leaked = copy.deepcopy(opened['data']['deals'][0])
    leaked['dev'] = 'PRIVATE_DEVELOPER'
    assert _put(client, opened, leaked).status_code == 409
    published = copy.deepcopy(opened['data']['deals'][0])
    published['payTo'] = {**published['_managerDraft']['payTo'], 'amount': 100}
    published['reqTask'] = 'done'
    published['_managerDraft'].pop('payTo')
    out = _put(client, opened, published)
    assert out.status_code == 200, out.json
    role['value'] = 'operator'
    visible = _get(client)
    assert visible['data']['deals'][0]['payTo']['acc'] == 'PRIVATE_ACCOUNT'
    assert visible['data']['deals'][0]['reqTask'] == 'done'
    assert '_managerDraft' not in visible['data']['deals'][0]


def test_operator_cannot_spoof_draft_and_s26_requires_confirmed_requisites(board):
    client, role, seed = board
    deal = _deal('s26')
    deal['_managerDraft'] = {'payTo': {'acc': 'PRIVATE_ACCOUNT'}}
    seed(deal)
    role['value'] = 'operator'
    state = _get(client)
    spoof = copy.deepcopy(state['data']['deals'][0])
    spoof['_managerDraft'] = {'payTo': {'acc': 'STEAL'}}
    assert _put(client, state, spoof).status_code == 409
    state = _get(client)
    advance = copy.deepcopy(state['data']['deals'][0])
    advance['step'] = 's27'
    assert _put(client, state, advance).status_code == 409
    assert _get(client)['data']['deals'][0]['step'] == 's26'


def test_crypto_freehold_draft_and_client_files_stay_private(board):
    client, role, seed = board
    deal = _deal('s5')
    deal.update(kind='Фрихолд', payType='Крипта', curBase='usdt',
                invoiceUsd=97500, ippsTariff='bank', amountUsdt=98800)
    seed(deal)
    state = _get(client)
    draft = copy.deepcopy(state['data']['deals'][0])
    draft['_managerDraft'] = {
        'payTo': {'dev': 'PRIVATE_IPPS', 'bank': 'PRIVATE_BANK',
                  'swift': 'PRIVATE_SWIFT', 'acc': 'PRIVATE_ACCOUNT',
                  'purpose': 'PRIVATE_PURPOSE'},
        'files': {'pass': [{'file': 'PRIVATE_PASSPORT.pdf'}],
                  'inv': [{'file': 'PRIVATE_INVOICE.pdf'}]},
        'docs': {'pass': True, 'inv': True},
        'comment': 'PRIVATE_COMMENT'}
    assert _put(client, state, draft).status_code == 200
    role['value'] = 'operator'
    hidden = _get(client)
    raw = json.dumps(hidden, ensure_ascii=False)
    assert all(marker not in raw for marker in ('PRIVATE_IPPS', 'PRIVATE_SWIFT',
                                                'PRIVATE_ACCOUNT', 'PRIVATE_PASSPORT',
                                                'PRIVATE_INVOICE', 'PRIVATE_COMMENT'))
    assert hidden['data']['deals'][0]['docs'] == {}
    role['value'] = 'manager'
    resumed = _get(client)
    assert resumed['data']['deals'][0]['_managerDraft']['comment'] == 'PRIVATE_COMMENT'
    illicit_money = copy.deepcopy(resumed['data']['deals'][0])
    illicit_money['amountUsdt'] = 1
    assert _put(client, resumed, illicit_money).status_code == 409
    illicit_doc = copy.deepcopy(resumed['data']['deals'][0])
    illicit_doc['_managerDraft']['files']['receipt'] = [{'file': 'FAKE_RECEIPT.pdf'}]
    assert _put(client, resumed, illicit_doc).status_code == 409


def test_ipps_application_requires_published_requisites_at_s25(board):
    client, role, seed = board
    deal = _deal('s25')
    deal.update(kind='Фрихолд', payType='Крипта', curBase='usdt',
                invoiceUsd=97500, amountUsdt=98800, ippsTariff='bank',
                postConv='ipps_swift', serverTransferComplete=True,
                transfer={'addr': 'TQgQCBXkewuW4RoieDKFP9Ko2SopBh8jso',
                          'net': 'TRC-20', 'amount': 98330, 'sends': []},
                payTo={})
    seed(deal)
    role['value'] = 'operator'
    before = _get(client)
    send = copy.deepcopy(before['data']['deals'][0])
    send['step'] = 's26'
    send['pay']['ippsSent'] = True
    denied = _put(client, before, send)
    assert denied.status_code == 409
    assert 'реквизиты' in denied.json['error'].lower()
    assert _get(client) == before

    role['value'] = 'manager'
    opened = _get(client)
    draft = copy.deepcopy(opened['data']['deals'][0])
    draft['reqTask'] = 'open'
    seed(draft)  # native afterPayin fixture: the manager task is now open
    opened = _get(client)
    confirmed = copy.deepcopy(opened['data']['deals'][0])
    confirmed['payTo'] = {'dev': 'Developer', 'bank': 'Bank', 'swift': 'TESTTHBK',
                          'acc': '123', 'purpose': 'invoice INV-1'}
    confirmed['reqTask'] = 'done'
    assert _put(client, opened, confirmed).status_code == 200
    role['value'] = 'operator'
    ready = _get(client)
    send = copy.deepcopy(ready['data']['deals'][0])
    send['step'] = 's26'
    send['pay']['ippsSent'] = True
    assert _put(client, ready, send).status_code == 200


def test_client_documents_publish_at_s8_and_later_correction_remains_available(board):
    client, role, seed = board
    deal = _deal('s5')
    deal['_managerDraft'] = {'files': {'pass': [{'file': 'PRIVATE_PASS.pdf'}],
                                       'inv': [{'file': 'PRIVATE_INV.pdf'}]},
                             'docs': {'pass': True, 'inv': True},
                             'comment': 'PRIVATE_DOC_COMMENT'}
    seed(deal)
    early = _get(client)
    illicit = copy.deepcopy(early['data']['deals'][0])
    illicit['files'] = {'pass': [{'file': 'PRIVATE_PASS.pdf'}]}
    assert _put(client, early, illicit).status_code == 409
    role['value'] = 'operator'
    assert 'PRIVATE_PASS' not in json.dumps(_get(client))
    role['value'] = 'manager'
    deal['step'] = 's8'
    seed(deal)
    ready = _get(client)
    published = copy.deepcopy(ready['data']['deals'][0])
    published['files'] = published['_managerDraft']['files']
    published['docs'] = published['_managerDraft']['docs']
    published['docComment'] = published['_managerDraft']['comment']
    published['_managerDraft'] = {}
    published['step'] = 's11'
    assert _put(client, ready, published).status_code == 200
    role['value'] = 'operator'
    shown = _get(client)
    assert shown['data']['deals'][0]['files']['pass'][0]['file'] == 'PRIVATE_PASS.pdf'
    assert shown['data']['deals'][0]['docComment'] == 'PRIVATE_DOC_COMMENT'
    illicit_operator = copy.deepcopy(shown['data']['deals'][0])
    illicit_operator['files']['pass'] = [{'file': 'FORGED_PASS.pdf'}]
    assert _put(client, shown, illicit_operator).status_code == 409
    role['value'] = 'manager'
    late = _get(client)
    corrected = copy.deepcopy(late['data']['deals'][0])
    corrected['files']['inv'].append({'file': 'REVISED_INV.pdf'})
    corrected['log'].append({'text': 'Добавлен исправленный инвойс'})
    assert _put(client, late, corrected).status_code == 200
