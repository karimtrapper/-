"""QA 29.10: удаление документа в черновике менеджера блокировало все последующие сохранения сделки."""
import pytest

from tests.test_stand_files_storage import board, pdf, upload, read_db, seed, clear_file_rows
from tests.test_stand_incoming_wallet_persist import api, fake_role_api, base_api


def _manager_with_deleted_invoice(api):
    """Менеджер загружает паспорт и инвойс в черновик, удаляет инвойс (как в QA)."""
    api[1][0] = 'manager'
    seed(board('s5'))
    assert upload(api, b'%PDF-1.4\npassport', kind='pass', name='passport.pdf').status_code == 200
    invoice = upload(api, b'%PDF-1.4\ninvoice', kind='inv', name='invoice.pdf')
    assert invoice.status_code == 200, invoice.json
    item = invoice.json['data']['deals'][0]['_managerDraft']['files']['inv'][0]
    deleted = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}?draft=1", json={'action': 'delete'})
    assert deleted.status_code == 200, deleted.json
    return item


def _publish_as_client(api):
    """Публикация черновика так, как её отправляет клиент: файлы и комментарий переезжают в сделку.

    Журнал deletedFiles клиент не переносит (сервер ведёт его сам), поэтому он остаётся в черновике.
    """
    version, current = _snapshot(api)
    deal = current['deals'][0]
    draft = deal['_managerDraft']
    deal['files'], deal['docs'], deal['docMeta'] = draft['files'], draft['docs'], draft['docMeta']
    deal['docComment'] = draft.get('comment', '')
    deal['_managerDraft'] = {'deletedFiles': draft.get('deletedFiles', {})}
    deal['step'] = 's11'
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.json


def test_qa_publish_then_admin_restore_puts_invoice_into_deal(api):
    """QA Codex 29.10: удалил, загрузил заново, передал операционисту, админ восстановил первый инвойс."""
    first = _manager_with_deleted_invoice(api)
    assert upload(api, b'%PDF-1.4\npassport', kind='pass', name='passport.pdf').status_code == 200
    again = upload(api, b'%PDF-1.4\ninvoice v2', kind='inv', name='invoice_v2.pdf')
    assert again.status_code == 200, again.json
    _, state = read_db()
    state['deals'][0]['step'] = 's8'
    seed(state)
    _publish_as_client(api)
    _, published = read_db()
    deal = published['deals'][0]
    assert deal['step'] == 's11'
    assert not (deal['_managerDraft'].get('deletedFiles') or {}).get('inv'), 'журнал должен уйти из черновика'
    assert [f['id'] for f in deal['deletedFiles']['inv']] == [first['id']]
    api[1][0] = 'admin'
    restored = api[0].patch(f"/api/stand/files/1473/inv/{first['id']}", json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    _, state = read_db()
    deal = state['deals'][0]
    ids = [f['id'] for f in deal['files']['inv']]
    assert sorted(ids) == sorted([first['id'], again.json['data']['deals'][0]['_managerDraft']['files']['inv'][0]['id']])
    assert len(set(ids)) == len(ids), 'дублей быть не должно'
    draft_ids = [f['id'] for f in (deal['_managerDraft'].get('files') or {}).get('inv', [])]
    assert first['id'] not in draft_ids, 'восстановленный файл не должен уйти в черновик'
    assert not (deal.get('deletedFiles') or {}).get('inv')


def test_restore_before_publish_returns_invoice_to_manager_draft(api):
    item = _manager_with_deleted_invoice(api)
    api[1][0] = 'admin'
    restored = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}?draft=1", json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    deal = read_db()[1]['deals'][0]
    assert [f['id'] for f in deal['_managerDraft']['files']['inv']] == [item['id']]
    assert not (deal.get('files') or {}).get('inv')
    assert not (deal['_managerDraft'].get('deletedFiles') or {}).get('inv')


def test_stuck_deal_restore_finds_journal_in_draft_and_puts_file_into_documents(api):
    """Сделка, зависшая до фикса: опубликована, но старая запись удаления осталась в черновике."""
    api[1][0] = 'admin'
    state = board('s11')
    deal = state['deals'][0]
    deal['docs'] = {'inv': True}
    deal['files'] = {'inv': [dict(pdf(b'current', 'invoice_v2.pdf'), id='sf_current_inv')]}
    deal['_managerDraft'] = {'deletedFiles': {'inv': [dict(pdf(b'stuck', 'invoice.pdf'), id='sf_stuck_inv')]}}
    seed(state)
    restored = api[0].patch('/api/stand/files/1473/inv/sf_stuck_inv?draft=1', json={'action': 'restore'})
    assert restored.status_code == 200, restored.json
    deal = read_db()[1]['deals'][0]
    assert [f['id'] for f in deal['files']['inv']] == ['sf_current_inv', 'sf_stuck_inv']
    assert not (deal['_managerDraft'].get('deletedFiles') or {}).get('inv')
    assert not (deal['_managerDraft'].get('files') or {}).get('inv')


def test_client_cannot_move_draft_journal_into_deal_by_put(api):
    """Журнал сделки пишет только сервер: клиент не переносит его сам (deleted_files_server_only)."""
    api[1][0] = 'manager'
    state = board('s8')
    state['deals'][0]['_managerDraft'] = {'deletedFiles': {'inv': [dict(pdf(b'old', 'old.pdf'), id='sf_old_inv')]}}
    seed(state)
    version, current = _snapshot(api)
    deal = current['deals'][0]
    deal['deletedFiles'] = {'inv': [{'id': 'sf_old_inv', 'file': 'old.pdf'}]}
    deal['_managerDraft'] = {}
    deal['step'] = 's11'
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'deleted_files_server_only'


def _snapshot(api):
    """Состояние так, как его получает клиент (без сырых байтов в deletedFiles)."""
    body = api[0].get('/api/stand/state').json
    return body['version'], body['data']


def test_manager_reuploads_invoice_after_draft_delete(api):
    item = _manager_with_deleted_invoice(api)
    again = upload(api, b'%PDF-1.4\ninvoice', kind='inv', name='invoice.pdf')
    assert again.status_code == 200, again.json
    draft = read_db()[1]['deals'][0]['_managerDraft']
    assert draft['files']['inv'][0]['file'] == 'invoice.pdf'
    assert draft['deletedFiles']['inv'][0]['id'] == item['id']


def test_admin_save_after_failed_reupload_is_not_blocked(api):
    _manager_with_deleted_invoice(api)
    api[1][0] = 'admin'
    version, current = _snapshot(api)
    unchanged = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert unchanged.status_code == 200, unchanged.json
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft']['comment'] = 'после удаления'
    saved = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert saved.status_code == 200, saved.json


def test_deal_stuck_by_deleted_files_draft_saves_without_db_edit(api):
    """Сделка, зависшая до фикса: _managerDraft.deletedFiles уже лежит в state."""
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
    current['deals'][0]['_managerDraft']['comment'] = 'сохранил после фикса'
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.json
    saved = read_db()[1]['deals'][0]['_managerDraft']
    assert saved['deletedFiles']['inv'][0]['id'] == 'sf_stuck_inv'
    assert saved['comment'] == 'сохранил после фикса'


@pytest.mark.parametrize('deleted_files', [
    {'signed': [{'id': 'sf_x', 'file': 'x.pdf'}]},
    {'clientPayinReceipt': [{'id': 'sf_x', 'file': 'x.pdf'}]},
])
def test_draft_deleted_files_kinds_still_validated(api, deleted_files):
    """Ослабление не пускает в черновик менеджера чужие типы документов.

    Прежний список deletedFiles сервер уже знает, поэтому меняем только комментарий,
    чтобы сработала проверка черновика.
    """
    api[1][0] = 'manager'
    state = board('s5')
    state['deals'][0]['_managerDraft'] = {'deletedFiles': deleted_files}
    seed(state)
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft']['comment'] = 'проверка'
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'Некорректный черновик менеджера'


def test_client_cannot_add_deleted_files_via_put(api):
    """Список удалённых файлов по-прежнему пишет только сервер (PATCH)."""
    api[1][0] = 'manager'
    seed(board('s5'))
    version, current = _snapshot(api)
    current['deals'][0]['_managerDraft'] = {'deletedFiles': {'inv': [{'id': 'sf_forged', 'file': 'x.pdf'}]}}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 409, response.json
    assert response.json['error'] == 'deleted_files_server_only'
