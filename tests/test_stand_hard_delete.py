"""Удаление вложений сделки насовсем: строка StandFile, объект в хранилище, разовая очистка."""
import json
from datetime import datetime

import pytest

import app as m
import stand_object_store as objects
from tests.test_stand_files_storage import board, upload, read_db, seed, clear_file_rows
from tests.test_stand_incoming_wallet_persist import api, fake_role_api, base_api


def _uploaded_invoice(api, raw):
    """Менеджер загружает инвойс на шаге s23: возвращает элемент доски и ключ объекта."""
    api[1][0] = 'manager'
    seed(board('s23'))
    response = upload(api, raw)
    assert response.status_code == 200, response.json
    item = response.json['data']['deals'][0]['files']['inv'][0]
    with m.SessionLocal() as db:
        key = db.get(m.StandFile, item['storageId']).object_key
    return item, key


def _object_bytes(key):
    with objects.storage().open(key) as stream:
        return stream.read()


def _mark_legacy_deleted(item):
    """Состояние старой версии: файл убран с доски и помечен deleted_at (мягкое удаление)."""
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        state['deals'][0]['files'] = {'inv': []}
        state['deals'][0]['deletedFiles'] = {'inv': [item]}
        row.data = json.dumps(state, ensure_ascii=False)
        db.get(m.StandFile, item['storageId']).deleted_at = datetime.utcnow()
        db.commit()


def test_delete_removes_row_and_object(api):
    raw = b'%PDF-1.4\nhard'
    item, key = _uploaded_invoice(api, raw)
    assert _object_bytes(key) == raw
    response = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}", json={'action': 'delete'})
    assert response.status_code == 200, response.json
    with m.SessionLocal() as db:
        assert db.get(m.StandFile, item['storageId']) is None
    with pytest.raises(FileNotFoundError):
        objects.storage().open(key)


def test_storage_failure_keeps_file_row_and_state(api, monkeypatch):
    raw = b'%PDF-1.4\nkeep'
    item, key = _uploaded_invoice(api, raw)

    def unavailable(self, key):
        raise objects.StorageUnavailable('недоступно')

    monkeypatch.setattr(objects.LocalStore, 'delete', unavailable)
    response = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}", json={'action': 'delete'})
    assert response.status_code == 400, response.json
    assert response.json['error'] == 'Хранилище файлов недоступно. Повторите позже.'
    with m.SessionLocal() as db:
        assert db.get(m.StandFile, item['storageId']) is not None
    assert read_db()[1]['deals'][0]['files']['inv'][0]['id'] == item['id']
    assert _object_bytes(key) == raw


def test_reupload_same_bytes_after_hard_delete_creates_new_object(api):
    """Сценарий QA/Codex: удалил, загрузил тот же файл заново — новая строка и новый объект."""
    raw = b'%PDF-1.4\nsame'
    item, old_key = _uploaded_invoice(api, raw)
    url = f"/api/stand/files/1473/inv/{item['id']}"
    assert api[0].patch(url, json={'action': 'delete'}).status_code == 200
    again = upload(api, raw)
    assert again.status_code == 200, again.json
    new_item = again.json['data']['deals'][0]['files']['inv'][0]
    assert new_item['storageId'] != item['storageId']
    with m.SessionLocal() as db:
        new_key = db.get(m.StandFile, new_item['storageId']).object_key
    assert new_key != old_key
    with pytest.raises(FileNotFoundError):
        objects.storage().open(old_key)
    assert _object_bytes(new_key) == raw


def test_restore_action_is_unknown_for_stand_files(api):
    item, _ = _uploaded_invoice(api, b'%PDF-1.4\nrestore')
    api[1][0] = 'admin'
    response = api[0].patch(f"/api/stand/files/1473/inv/{item['id']}", json={'action': 'restore'})
    assert response.status_code == 400, response.json
    assert response.json['error'] == 'Неизвестное действие'


def test_startup_purge_removes_legacy_soft_deleted_rows_once(api):
    raw = b'%PDF-1.4\nlegacy'
    item, key = _uploaded_invoice(api, raw)
    _mark_legacy_deleted(item)
    assert m._stand_purge_deleted() == (1, len(raw), 0, 0)
    with m.SessionLocal() as db:
        assert db.get(m.StandFile, item['storageId']) is None
    with pytest.raises(FileNotFoundError):
        objects.storage().open(key)
    assert 'deletedFiles' not in read_db()[1]['deals'][0]
    assert m._stand_purge_deleted() == (0, 0, 0, 0)


def test_startup_purge_tolerates_object_already_missing(api):
    raw = b'%PDF-1.4\nmissing'
    item, key = _uploaded_invoice(api, raw)
    _mark_legacy_deleted(item)
    objects.storage().delete(key)
    assert m._stand_purge_deleted() == (1, len(raw), 0, 0)
    with m.SessionLocal() as db:
        assert db.get(m.StandFile, item['storageId']) is None
    assert m._stand_purge_deleted() == (0, 0, 0, 0)


def test_startup_purge_keeps_file_still_referenced_by_board(api):
    raw = b'%PDF-1.4\nalive'
    item, key = _uploaded_invoice(api, raw)
    with m.SessionLocal() as db:
        db.get(m.StandFile, item['storageId']).deleted_at = datetime.utcnow()
        db.commit()
    assert m._stand_purge_deleted() == (0, 0, 0, 0)
    with m.SessionLocal() as db:
        assert db.get(m.StandFile, item['storageId']) is not None
    assert _object_bytes(key) == raw


def _legacy_agreement_doc(number, raw):
    """Документ договора, помеченный удалённым по старой схеме (deleted_at, байты в строке)."""
    with m.SessionLocal() as db:
        agreement = m.Agreement(client_name='Очистка QA', client_key='qa-purge-' + number,
                                route_key='legacy', deal_type='freehold', number=number)
        db.add(agreement)
        db.flush()
        doc = m.AgreementDoc(agreement_id=agreement.id, kind='invoice', filename='old.pdf',
                             mime='application/pdf', size=len(raw), data=raw, seq=1,
                             deleted_at=datetime.utcnow())
        db.add(doc)
        db.flush()
        doc_id = doc.id
        db.commit()
    return doc_id


def test_startup_purge_removes_legacy_agreement_docs_and_refs(api):
    raw = b'%PDF-1.4\nold-doc'
    doc_id = _legacy_agreement_doc('QA-PURGE-1', raw)
    state = board('s14')
    stamp = '2026-10-01T10:00:00'
    state['deals'][0]['docsIssued'] = [{'kind': 'bill', 'docId': doc_id, 'file': 'old.pdf',
                                         'version': 1, 'deletedAt': stamp}]
    state['deals'][0]['issued'] = {'bill': {'kind': 'bill', 'docId': doc_id, 'file': 'old.pdf',
                                            'deletedAt': stamp}}
    seed(state)
    assert m._stand_purge_deleted() == (0, 0, 1, len(raw))
    with m.SessionLocal() as db:
        assert db.get(m.AgreementDoc, doc_id) is None
    deal = read_db()[1]['deals'][0]
    assert deal['docsIssued'] == [] and deal['issued'] == {}
    assert m._stand_purge_deleted() == (0, 0, 0, 0)


def test_startup_purge_keeps_agreement_doc_with_live_reference(api):
    raw = b'%PDF-1.4\nlive-ref'
    doc_id = _legacy_agreement_doc('QA-PURGE-2', raw)
    state = board('s14')
    state['deals'][0]['docsIssued'] = [{'kind': 'bill', 'docId': doc_id, 'file': 'old.pdf', 'version': 1}]
    seed(state)
    assert m._stand_purge_deleted() == (0, 0, 0, 0)
    with m.SessionLocal() as db:
        assert db.get(m.AgreementDoc, doc_id) is not None
