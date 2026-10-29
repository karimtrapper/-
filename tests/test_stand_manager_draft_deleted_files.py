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
