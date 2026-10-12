"""Чеки клиента — самостоятельное свидетельство отправки, не банковский приход."""
import base64
import copy
import json

import pytest

import app as m


PDF = 'data:application/pdf;base64,' + base64.b64encode(b'%PDF-1.4\nclient receipt').decode()


def receipt(file_id='cpr_123456789abc', actor_id=1):
    return {'id': file_id, 'file': 'client.pdf', 'size': '1 КБ', 'at': '12.10',
            'mime': 'application/pdf', 'bytes': 23, 'data': PDF, 'demo': False,
            'uploadedById': actor_id, 'uploadedBy': 'Елизавета', 'note': ''}


def deal(step='s14', sent=None):
    result = {'id': 1485, 'step': step, 'files': {}, 'log': [], 'docs': {},
              'type': 'Оплата недвижимости', 'kind': 'Лизхолд'}
    if sent:
        result['docsSent'] = {'at': '12.10', 'version': 3}
    return result


def changed(before, files):
    after = copy.deepcopy(before)
    after['files']['clientPayinReceipt'] = files
    return after


@pytest.mark.parametrize('step,sent,role,actor_id,allowed', [
    ('s12', False, 'manager', 1, False),
    ('s12', True, 'manager', 1, True),
    ('s14', False, 'manager', 1, True),  # старая сделка без нового поля и docsSent
    ('s14', False, 'operator', 2, False),
    ('s11', True, 'operator', 2, False),
    ('s12', False, 'admin', 3, True),
])
def test_upload_roles_and_old_deal(step, sent, role, actor_id, allowed):
    before = deal(step, sent)
    after = changed(before, [receipt(actor_id=actor_id)])
    assert (m._stand_client_payin_problem(before, after, role, actor_id) is None) == allowed
    assert 'clientPayinReceipt' not in before['files']


def test_operator_can_attach_during_verification():
    before = deal()
    before['manualBankReceipt'] = {'status': 'pending'}
    after = changed(before, [receipt(actor_id=2)])
    assert m._stand_client_payin_problem(before, after, 'operator', 2) is None
    assert m._stand_client_payin_only(before, after, {'files', 'log'})
    assert before.get('incomeAmount') == after.get('incomeAmount')
    assert before.get('manualBankReceipt') == after.get('manualBankReceipt')


def test_delete_and_note_permissions():
    before = changed(deal(), [receipt()])
    removed = changed(before, [])
    assert 'Удалить' in m._stand_client_payin_problem(before, removed, 'operator', 2)
    assert m._stand_client_payin_problem(before, removed, 'manager', 1) is None
    assert m._stand_client_payin_problem(before, removed, 'admin', 3) is None
    edited = changed(before, [dict(receipt(), note='50 000 ₽ · 12.10 · Иванов')])
    assert m._stand_client_payin_problem(before, edited, 'manager', 1) is None
    assert 'Заметку' in m._stand_client_payin_problem(before, edited, 'operator', 2)
    forged = changed(before, [dict(receipt(), uploadedById=2)])
    assert 'Файл чека' in m._stand_client_payin_problem(before, forged, 'admin', 3)


def test_file_validation_and_independent_kind():
    before = deal(sent=True)
    assert m._stand_client_payin_problem(before, changed(before, [receipt()]), 'manager', 1) is None
    wrong_type = changed(before, [dict(receipt(), mime='text/html')])
    assert 'Некорректные' in m._stand_client_payin_problem(before, wrong_type, 'manager', 1)
    other_kind = changed(before, [receipt()])
    other_kind['files']['receipt'] = [receipt()]
    assert not m._stand_client_payin_only(before, other_kind, {'files'})
    malformed = changed(before, [dict(receipt(), id=['bad'])])
    assert 'Некорректные' in m._stand_client_payin_problem(before, malformed, 'manager', 1)


def test_state_upload_show_download_delete(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: None)
    with m.get_session() as db:
        m._stand_migrate()
        for uid, role in [(1, 'manager'), (2, 'operator'), (3, 'admin')]:
            if not db.query(m.AdminUser).get(uid):
                db.add(m.AdminUser(id=uid, username=f'receipt_{uid}', display_name='Елизавета' if uid == 1 else role,
                                   role=role,
                                   password_hash=''))
        db.query(m.StandState).delete()
        db.add(m.StandState(id=1, version=1, data=json.dumps({'deals': [deal()]})))
        db.commit()

    def client(uid):
        result = m.app.test_client()
        with result.session_transaction() as session:
            session['user_id'] = uid
        return result

    manager, operator, admin = client(1), client(2), client(3)
    state = manager.get('/api/stand/state').json['data']
    state['deals'][0]['files']['clientPayinReceipt'] = [receipt()]
    no_log = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert no_log.status_code == 409
    assert 'журнал' in no_log.json['error']
    state['deals'][0]['log'].append({'text': 'Чек клиента прикреплён · client.pdf · Елизавета'})
    uploaded = manager.put('/api/stand/state', json={'version': 1, 'data': state})
    assert uploaded.status_code == 200, uploaded.json
    shown = operator.get('/api/stand/state').json['data']['deals'][0]
    assert shown['files']['clientPayinReceipt'][0]['data'] == '__detached__'
    assert shown['docs'] == {}
    assert operator.get('/api/stand/file/1485/clientPayinReceipt/0').data.startswith(b'%PDF-')
    shown['files']['clientPayinReceipt'] = []
    denied = operator.put('/api/stand/state', json={'version': 2, 'data': {'deals': [shown]}})
    assert denied.status_code == 409
    admin_state = admin.get('/api/stand/state').json['data']
    admin_state['deals'][0]['files']['clientPayinReceipt'] = []
    admin_state['deals'][0]['log'].append({'text': 'Чек клиента удалён · client.pdf · Елизавета'})
    removed = admin.put('/api/stand/state', json={'version': 2, 'data': admin_state})
    assert removed.status_code == 200, removed.json
    assert manager.get('/api/stand/state').json['data']['deals'][0]['files']['clientPayinReceipt'] == []
