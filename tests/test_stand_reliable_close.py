"""Проверка готовности, восстановления исхода и очереди после закрытия."""
import json
import secrets
import pytest
from datetime import datetime, timedelta
from sqlalchemy import text

import app as m
from tests.test_stand_single_confirm import setup_verified
from tests.test_stand_crm_close_atomic import _counts, _client
from tests.test_stand_crm_close_atomic import _manual_draft, _crm, _setup, _post_lose
from tests.test_stand_flow_verification import freehold_requisites_deal


def _row():
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        return row.version, row.generation, row.data


def test_readonly_check_status_then_close_retry_and_reload(monkeypatch, caplog):
    manager, uid, crm = setup_verified(monkeypatch)
    version, generation, raw = _row()
    counts = _counts()
    path = '/api/stand/deals/1474'
    headers = {'X-Request-Id': 'reliable_close_001'}
    open_status = manager.get(path + '/crm-close-status', headers=headers)
    assert open_status.status_code == 200
    assert open_status.json['closed'] is False
    assert open_status.json['version'] == version
    assert open_status.json['generation'] == generation
    assert open_status.json['request_id'] == headers['X-Request-Id']

    body = {'version': version, 'crm': crm}
    checked = manager.post(path + '/crm-close/check', json=body, headers=headers)
    assert checked.status_code == 200, checked.json
    assert checked.json['ready'] is True
    assert checked.json['blockers'] == []
    assert checked.json['generation'] == generation
    assert _row() == (version, generation, raw)
    assert _counts() == counts
    with m.SessionLocal() as db:
        outbox_before = db.get(m.StandState, 1).notified
    forged_state = json.loads(raw)
    forged_state['notified'] = [{'id': 'stand:completed:fake', 'text': 'forged'}]
    forged = manager.put('/api/stand/state', json={'version': version, 'data': forged_state})
    assert forged.status_code == 400 and forged.json['error'] == 'server_outbox_only'
    with m.SessionLocal() as db:
        assert db.get(m.StandState, 1).notified == outbox_before
    assert _row() == (version, generation, raw)

    stale = manager.post(path + '/crm-close/check', json={**body, 'version': version - 1})
    assert stale.json['ready'] is False
    assert any(item['code'] == 'conflict' for item in stale.json['blockers'])
    assert _row() == (version, generation, raw)

    done = manager.post(path + '/crm-close', json=body, headers=headers)
    assert done.status_code == 201, done.json
    assert done.json['request_id'] == headers['X-Request-Id']
    assert any('stand_close_attempt request_id=reliable_close_001' in record.message
               and f'actor_id={uid}' in record.message and 'status=201' in record.message
               and 'version=' in record.message for record in caplog.records)
    crm_id = done.json['deal']['id']
    assert _counts() == (counts[0] + 1, counts[1] + 1)
    # Две независимые GET-сессии видят одну сохранённую связь и закрытую доску.
    for _ in range(2):
        reloaded = _client(uid).get(path + '/crm-close-status?expected_generation=' + generation)
        assert reloaded.status_code == 200
        assert reloaded.json['closed'] is True
        assert reloaded.json['crmDealId'] == crm_id
        assert reloaded.json['data']['deals'][0]['step'] == 'done'
    repeat = _client(uid).post(path + '/crm-close', json=body)
    assert repeat.status_code == 200 and repeat.json['duplicate'] is True
    assert repeat.json['deal']['id'] == crm_id
    assert _counts() == (counts[0] + 1, counts[1] + 1)
    changed = manager.get(path + '/crm-close-status?expected_generation=' + '0' * 32)
    assert changed.status_code == 409 and changed.json['error'] == 'generation_changed'
    with m.SessionLocal() as db:
        crm_row = db.get(m.Deal, crm_id)
        crm_row.status = m.DealStatus.LOSE
        db.commit()
    inconsistent = manager.get(path + '/crm-close-status')
    assert inconsistent.status_code == 409 and inconsistent.json['error'] == 'origin_inconsistent'


def test_check_reports_multiple_blockers_and_rejects_manager_spoof(monkeypatch):
    manager, uid, crm = setup_verified(monkeypatch)
    version, generation, _ = _row()
    counts = _counts()
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        deal = state['deals'][0]
        deal['sentToClient'] = False
        deal['files']['receipt'] = []
        row.data = json.dumps(state)
        db.commit()
    forged = {**crm, 'manager_user_id': uid + 100000}
    body = {'version': version, 'crm': forged}
    path = '/api/stand/deals/1474'
    checked = manager.post(path + '/crm-close/check', json=body)
    assert checked.status_code == 200
    fields = {item.get('field') for item in checked.json['blockers']}
    assert {'sentToClient', 'files.receipt'} <= fields
    assert any(item['code'] == 'manager_account_mismatch' for item in checked.json['blockers'])
    refused = manager.post(path + '/crm-close', json=body)
    assert refused.status_code == 409 and refused.json['error'] == 'manager_account_mismatch'
    assert _row()[1] == generation
    assert _counts() == counts


def test_manual_check_catches_local_document_mismatch_without_network(monkeypatch):
    uid, version = _manual_draft(monkeypatch)
    client = _client(uid)
    crm = {**_crm(), 'doc_invoice_url': 'https://docs.invalid/foreign',
           'doc_contract_url': 'https://docs.invalid/contract',
           'doc_payment_url': 'https://docs.invalid/payment'}
    before = _row(), _counts()
    checked = client.post('/api/stand/deals/1474/crm-close/check',
                          json={'version': version, 'crm': crm})
    assert checked.status_code == 200, checked.json
    assert checked.json['ready'] is False
    assert any(item['code'] == 'document_link_mismatch' for item in checked.json['blockers'])
    assert _row() == before[0] and _counts() == before[1]


def test_close_card_is_queued_before_commit_and_survives_delivery_failure(monkeypatch):
    manager, uid, crm = setup_verified(monkeypatch)
    version, _, _ = _row()
    attempts = []
    def failed_delivery():
        attempts.append('failed')
        raise RuntimeError('synthetic notification failure')
    monkeypatch.setattr(m, '_stand_deliver_notes', failed_delivery)
    body = {'version': version, 'crm': crm}
    path = '/api/stand/deals/1474/crm-close'
    done = manager.post(path, json=body)
    assert done.status_code == 201, done.json
    crm_id = done.json['deal']['id']
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        notes = [n for n in state['notes'] if n['id'] == f'stand:close-card:{crm_id}']
        assert len(notes) == 1
        manager_notes = [n for n in state['notes'] if n['id'] == 'stand:completed:1474']
        assert len(manager_notes) == 1
        assert manager_notes[0]['recipientAdminId'] == uid
        outbox = json.loads(row.notified)
        assert {n['id'] for n in outbox if isinstance(n, dict)} >= {
            f'stand:close-card:{crm_id}', 'stand:completed:1474'}
    assert attempts == ['failed']
    assert manager.post(path, json=body).json['duplicate'] is True
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        state = json.loads(row.data)
        assert sum(n['id'] == f'stand:close-card:{crm_id}' for n in state['notes']) == 1
        for index in range(45):
            m._stand_note(state, f'synthetic:later:{index}', 'operator', {'id': 1474}, 'Later task')
        assert not any(n['id'] == 'stand:completed:1474' for n in state['notes'])
        row.data = json.dumps(state)
        db.commit()
    sent = []
    m.stand_notify.init(m)
    monkeypatch.setattr(m.stand_notify, 'notify_profile', lambda: 'stand_bot')
    monkeypatch.setattr(m.stand_notify, '_user_allowed', lambda user: user.id == uid)
    monkeypatch.setattr(m.stand_notify, 'can_send', lambda *_: True)
    monkeypatch.setattr(m.stand_notify.stand_egress, 'tg_call',
                        lambda method, payload: sent.append((method, payload)) or {'ok': True})
    with m.SessionLocal() as db:
        db.execute(text('INSERT INTO stand_notify_log '
                        '(note_id, admin_id, status, attempts, at) '
                        'VALUES (:note_id, :admin_id, :status, :attempts, :at)'),
                   {'note_id': f'stand:completed:1474::assignee:{uid}',
                    'admin_id': uid, 'status': 'failed', 'attempts': 5,
                    'at': datetime.utcnow()})
        db.commit()
    m.stand_notify.deliver()
    assert not sent, 'очередь выдерживает паузу после пятой неудачи'
    with m.SessionLocal() as db:
        db.execute(text('UPDATE stand_notify_log SET at=:at WHERE note_id=:note_id'),
                   {'at': datetime.utcnow() - timedelta(minutes=6),
                    'note_id': f'stand:completed:1474::assignee:{uid}'})
        db.commit()
    first = m.stand_notify.deliver()
    assert any(item['note_id'] == 'stand:completed:1474' and item['status'] == 'sent'
               for item in first), first
    assert len(sent) == 1
    m.stand_notify.deliver()
    assert len(sent) == 1, 'повтор читает outbox, но notify_log не шлёт второй раз'


def test_new_manager_identity_is_saved_and_cannot_be_cleared(monkeypatch):
    manager, uid, _ = setup_verified(monkeypatch)
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        row.data = json.dumps({'deals': [], 'notes': []})
        row.version = 1
        admin = m.AdminUser(username='reliable-admin-' + secrets.token_hex(5),
                            role='admin', password_hash='unused')
        db.add(admin)
        db.commit()
        admin_id = admin.id
    data = {'deals': [freehold_requisites_deal(1474)], 'notes': []}
    missing = _client(admin_id).put('/api/stand/state', json={'version': 1, 'data': data})
    assert missing.status_code == 409 and missing.json['error'] == 'manager_account_required'
    assert _row()[0] == 1
    created = manager.put('/api/stand/state', json={'version': 1, 'data': data})
    assert created.status_code == 200, created.json
    assert created.json['data']['deals'][0]['managerUserId'] == uid
    removed = json.loads(json.dumps(created.json['data']))
    removed['deals'][0]['managerUserId'] = None
    refused = manager.put('/api/stand/state', json={
        'version': created.json['version'], 'data': removed})
    assert refused.status_code == 409
    assert manager.get('/api/stand/state').json['data']['deals'][0]['managerUserId'] == uid


@pytest.mark.parametrize('bad_id', [True, 0, -1, '11', [], {'id': 11}])
def test_new_deal_rejects_malformed_manager_id_without_write(monkeypatch, bad_id):
    manager, _, _ = setup_verified(monkeypatch)
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        row.data = json.dumps({'deals': [], 'notes': []})
        row.version = 1
        db.commit()
    data = {'deals': [freehold_requisites_deal(1474)], 'notes': []}
    data['deals'][0]['managerUserId'] = bad_id
    before = _row()
    response = manager.put('/api/stand/state', json={'version': 1, 'data': data})
    assert response.status_code == 409 and response.json['error'] == 'manager_account_invalid'
    assert _row() == before


def test_freehold_completion_note_targets_bound_manager_only():
    before = {'deals': [{'id': 7, 'step': 's27', 'closed': False}], 'notes': []}
    after = {'deals': [{'id': 7, 'code': 'СД-7', 'type': 'Оплата недвижимости',
                        'kind': 'Фрихолд', 'step': 'done', 'closed': True,
                        'closeReason': 'Успешно завершена', 'managerUserId': 31}], 'notes': []}
    m._stand_completion_notes(before, after)
    assert len(after['notes']) == 1
    assert after['notes'][0]['recipientAdminId'] == 31
    m._stand_completion_notes(before, after)
    assert len(after['notes']) == 1


def test_lose_close_queues_manager_notice_before_failed_delivery(monkeypatch):
    uid = _setup(monkeypatch)
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: (_ for _ in ()).throw(
        RuntimeError('synthetic delivery failure')))
    baseline = _counts()
    response = _post_lose(_client(uid))
    assert response.status_code == 201, response.json
    assert _post_lose(_client(uid)).json['duplicate'] is True
    assert _counts() == (baseline[0] + 1, baseline[1] + 1)
    with m.SessionLocal() as db:
        row = db.get(m.StandState, 1)
        outbox = json.loads(row.notified)
        notes = [n for n in outbox if isinstance(n, dict)
                 and n.get('id') == 'stand:completed:1474']
        assert len(notes) == 1 and notes[0]['recipientAdminId'] == uid


def test_background_retry_tick_obeys_stand_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(m.stand_notify, 'deliver', lambda: calls.append('tick') or [])
    monkeypatch.setattr(m, 'STAND_MODE', False)
    assert m._stand_close_notify_retry_once() == [] and calls == []
    monkeypatch.setattr(m, 'STAND_MODE', True)
    assert m._stand_close_notify_retry_once() == [] and calls == ['tick']


def test_close_outbox_waits_for_transient_profile_without_suppressing(monkeypatch):
    manager, uid, crm = setup_verified(monkeypatch)
    version, _, _ = _row()
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    done = manager.post('/api/stand/deals/1474/crm-close',
                        json={'version': version, 'crm': crm})
    assert done.status_code == 201, done.json
    m.stand_notify.init(m)
    monkeypatch.setattr(m.stand_notify, 'notify_profile', lambda: 'lk_send_only')
    monkeypatch.setattr(m.stand_notify.stand_egress, 'lk_preflight_ok', lambda: False)
    sent = []
    monkeypatch.setattr(m.stand_notify.stand_egress, 'lk_call',
                        lambda payload: sent.append(payload) or {'ok': True})
    result = m.stand_notify.deliver()
    assert any(item['note_id'] == 'stand:completed:1474' and item['status'] == 'failed'
               for item in result)
    assert sent == []
    with m.SessionLocal() as db:
        logs = db.execute(text('SELECT status FROM stand_notify_log '
                               'WHERE note_id LIKE :prefix AND admin_id=:uid'),
                          {'prefix': 'stand:completed:1474%', 'uid': uid}).all()
        assert logs == []


def test_notification_transport_error_does_not_log_secret_url(monkeypatch, caplog):
    manager, uid, crm = setup_verified(monkeypatch)
    version, _, _ = _row()
    monkeypatch.setattr(m, '_stand_deliver_notes', lambda: [])
    assert manager.post('/api/stand/deals/1474/crm-close',
                        json={'version': version, 'crm': crm}).status_code == 201
    m.stand_notify.init(m)
    monkeypatch.setattr(m.stand_notify, 'notify_profile', lambda: 'stand_bot')
    monkeypatch.setattr(m.stand_notify, '_user_allowed', lambda user: user.id == uid)
    monkeypatch.setattr(m.stand_notify, 'can_send', lambda *_: True)
    secret_marker = 'https://api.example.invalid/botSECRET_TOKEN/sendMessage'
    def fail_transport(*_):
        raise RuntimeError(secret_marker)
    monkeypatch.setattr(m.stand_notify.stand_egress, 'tg_call', fail_transport)
    result = m.stand_notify.deliver()
    assert any(item['note_id'] == 'stand:completed:1474' and item['status'] == 'failed'
               for item in result)
    assert secret_marker not in caplog.text
    assert 'stand notification failed error_type=RuntimeError' in caplog.text
