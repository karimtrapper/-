"""QA 29.10: повторная загрузка документа после удаления и сохранение доски менеджером.

Раньше удалённый файл оставался в журнале deletedFiles: повторная загрузка давала 409,
а сохранение черновика падало. Журнала больше нет, удаление окончательное.
"""
from tests.test_stand_files_storage import board, pdf, upload, read_db, seed, clear_file_rows
from tests.test_stand_incoming_wallet_persist import api, fake_role_api, base_api


def _snapshot(api):
    body = api[0].get('/api/stand/state').json
    return body['version'], body['data']


def _manager_with_deleted_invoice(api):
    """Менеджер загружает паспорт и инвойс в черновик, затем удаляет инвойс насовсем."""
    api[1][0] = 'manager'
    seed(board('s5'))
    assert upload(api, b'%PDF-1.4\npassport', kind='pass', name='passport.pdf').status_code == 200
    invoice = upload(api, b'%PDF-1.4\ninvoice', kind='inv', name='invoice.pdf')
    assert invoice.status_code == 200, invoice.json
    item = invoice.json['data']['deals'][0]['_managerDraft']['files']['inv'][0]
    deleted = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}?draft=1", json={'action': 'delete'})
    assert deleted.status_code == 200, deleted.json
    return item


def test_reupload_after_delete_then_publish_is_not_blocked(api):
    """Сценарий QA/Codex 29.10: удалил, загрузил заново, передал операционисту — без 409 и 403."""
    _manager_with_deleted_invoice(api)
    again = upload(api, b'%PDF-1.4\ninvoice v2', kind='inv', name='invoice_v2.pdf')
    assert again.status_code == 200, again.json
    draft = again.json['data']['deals'][0]['_managerDraft']
    assert 'deletedFiles' not in draft
    new_item = draft['files']['inv'][0]
    _, state = read_db()
    state['deals'][0]['step'] = 's8'
    seed(state)
    version, current = _snapshot(api)
    deal = current['deals'][0]
    published_draft = deal['_managerDraft']
    deal.update(files=published_draft['files'], docs=published_draft['docs'],
                docMeta=published_draft['docMeta'], docComment=published_draft.get('comment', ''),
                step='s11')
    deal['_managerDraft'] = {}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.json
    published = read_db()[1]['deals'][0]
    assert [f['id'] for f in published['files']['inv']] == [new_item['id']]
    assert 'deletedFiles' not in published


def test_admin_save_after_delete_is_not_blocked(api):
    _manager_with_deleted_invoice(api)
    api[1][0] = 'admin'
    version, current = _snapshot(api)
    unchanged = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert unchanged.status_code == 200, unchanged.json
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft']['comment'] = 'после удаления'
    saved = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert saved.status_code == 200, saved.json


def test_stuck_journal_in_saved_draft_is_dropped_on_next_save(api):
    """Черновик, зависший со старой записью deletedFiles: сохранение проходит, запись уходит."""
    api[1][0] = 'manager'
    state = board('s5')
    state['deals'][0]['_managerDraft'] = {
        'files': {'pass': [pdf(b'stuck-pass', 'passport.pdf')]},
        'docs': {'pass': True},
        'docMeta': {'pass': {'file': 'passport.pdf', 'size': '1 КБ', 'at': '13.10'}},
        'deletedFiles': {'inv': [dict(pdf(b'stuck-inv', 'invoice.pdf'), id='sf_stuck_inv')]},
    }
    seed(state)
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft']['comment'] = 'сохранил после обновления'
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.json
    saved = read_db()[1]['deals'][0]['_managerDraft']
    assert 'deletedFiles' not in saved
    assert saved['comment'] == 'сохранил после обновления'


def test_client_deleted_files_are_ignored_not_rejected(api):
    """Поле deletedFiles от клиента молча стирается: ни на что не влияет и не даёт 409."""
    api[1][0] = 'manager'
    seed(board('s5'))
    version, current = _snapshot(api)
    current['deals'][0]['deletedFiles'] = {'inv': [{'id': 'sf_forged', 'file': 'x.pdf'}]}
    current['deals'][0]['_managerDraft'] = {'deletedFiles': {'inv': [{'id': 'sf_forged', 'file': 'x.pdf'}]}}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.json
    saved = read_db()[1]['deals'][0]
    assert 'deletedFiles' not in saved
    assert 'deletedFiles' not in saved['_managerDraft']


def test_draft_with_unknown_field_is_still_rejected(api):
    """Ослабление касается только deletedFiles: посторонние поля черновика по-прежнему отклоняются."""
    api[1][0] = 'manager'
    seed(board('s5'))
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft'] = {'junk': {}}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Некорректный черновик менеджера'
