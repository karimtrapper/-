"""Баг 1261 (29.10): менеджер сохраняет документ своей сделки через доску — 200, файл на месте."""
from tests.test_stand_files_storage import api, clear_file_rows, board, pdf, read_db, seed, m
from tests.test_stand_incoming_wallet_persist import fake_role_api, base_api


def test_lisa_manager_saves_own_deal_document_through_board(api):
    api[1][0] = 'manager'
    with api[0].session_transaction() as session:
        uid = session['user_id']
    with m.SessionLocal() as db:
        user = db.get(m.AdminUser, uid)
        manager_name = user.display_name or user.username
    state = board('s5')
    state['deals'][0]['manager'] = manager_name
    seed(state)
    version, current = read_db()
    current['deals'][0]['_managerDraft'] = {'files': {'pass': [pdf(b'lisa-board-save', 'pass.pdf')]}}
    response = api[0].put('/api/stand/state', json={'version': version, 'data': current})
    assert response.status_code == 200, response.data[:500]
    saved_version, saved = read_db()
    assert saved_version == version + 1
    file_item = saved['deals'][0]['_managerDraft']['files']['pass'][0]
    assert file_item['file'] == 'pass.pdf'
    assert file_item['data'] == '__detached__'
    with m.SessionLocal() as db:
        stored = db.get(m.StandFile, file_item['storageId'])
        assert stored is not None
        assert stored.uploaded_by == str(uid)
    assert api[0].get('/api/stand/file/1473/pass/0?draft=1').data == b'%PDF-1.4\nlisa-board-save'
