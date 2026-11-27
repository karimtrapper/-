import copy
import json

import pytest

import app as m


@pytest.fixture
def actors(monkeypatch):
    monkeypatch.setattr(m, 'STAND_MODE', True)
    m._stand_migrate()
    with m.SessionLocal() as db:
        users = {name: m.AdminUser(username='delete_qa_' + name, display_name=display,
                                   password_hash='unused', role=role)
                 for name, display, role in (
                     ('lisa', 'Елизавета Архив QA', 'manager'), ('other', 'Другой менеджер QA', 'manager'),
                     ('operator', 'Оператор QA', 'operator'), ('admin', 'Администратор QA', 'admin'))}
        db.add_all(users.values())
        db.flush()
        ids = {name: user.id for name, user in users.items()}
        db.commit()
    yield ids
    with m.SessionLocal() as db:
        db.query(m.StandDeletedDeal).filter(m.StandDeletedDeal.deleted_by.in_(ids.values())).delete()
        db.query(m.StandState).delete()
        db.query(m.AdminUser).filter(m.AdminUser.id.in_(ids.values())).delete()
        db.commit()


def client_for(ids, actor='lisa'):
    client = m.app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = ids[actor]
        session['username'] = 'delete_qa_' + actor
    return client


def card(deal_id, owner, *, step='manual', **values):
    return {'id': deal_id, 'code': f'СД-{deal_id}', 'step': step, 'client': 'Тестовый клиент',
            'type': 'Обмен валюты', 'pair': 'USDT → THB', 'payType': 'Крипта', 'amountRub': 35000,
            'managerUserId': owner, 'manager': 'Елизавета Архив QA', 'manual': step == 'manual',
            'isTask': step not in ('manual', 'done'), 'log': [{'role': 'manager', 'text': 'Создана'}],
            **values}


def seed(*deals, notes=(), outbox=(), **extra):
    state = {'deals': list(deals), 'notes': list(notes), 'seq': max(d['id'] for d in deals), **extra}
    with m.SessionLocal() as db:
        row = m._stand_row(db)
        row.version = 13
        row.generation = 'delete-qa-generation'
        row.data = json.dumps(state)
        row.notified = json.dumps(list(outbox))
        db.commit()
    return state


def delete(client, deal_id, version=13):
    return client.post(f'/api/stand/deals/{deal_id}/delete', json={'version': version})


@pytest.mark.parametrize('step', ['s4', 's14', 's23', 's27', 'done'])
def test_manager_can_remove_unfunded_card_at_each_stage(actors, step):
    deal = card(1535, actors['lisa'], step=step, closed=step == 'done',
                transfer={'addr': 'planned', 'amount': 100},
                payinHashes=[{'hash': '', 'amount': None}], payinExtra=[{'hashes': [], 'amountRub': None}],
                payout={'invoice': {'amount': 100}}, payTo={'acc': 'planned'})
    seed(deal)
    result = delete(client_for(actors), 1535)
    assert result.status_code == 200, result.json
    assert result.json['data']['deals'] == []


def test_lisa_deletes_only_unfunded_manual_duplicates_and_their_board_notifications(actors):
    ids = (1535, 1537, 1538, 1536, 1539, 1540)
    notes = [{'id': f'task-{deal_id}', 'dealId': deal_id, 'role': 'manager', 'text': 'Проверить'}
             for deal_id in ids]
    duplicates = [card(deal_id, actors['lisa'], amountRub=35000 if deal_id == 1535 else 50000)
                  for deal_id in ids[:3]]
    real = [card(deal_id, actors['lisa'], payinHashes=[{'hash': f'confirmed-{deal_id}', 'verified': True}])
            for deal_id in ids[3:]]
    seed(*duplicates, *real, notes=notes, outbox=notes, seq=1542)
    client = client_for(actors)
    for version, item in enumerate(duplicates, start=13):
        result = delete(client, item['id'], version)
        assert result.status_code == 200, result.json
    assert delete(client, 1536, 16).status_code == 409
    board = client.get('/api/stand/state?read_only=1').json
    assert board['version'] == 16
    assert board['data'] == {'deals': real, 'notes': notes[3:], 'seq': 1542}
    count = client.get('/api/stand/nav-count').json
    assert count['notifications'] == 3
    with m.SessionLocal() as db:
        assert json.loads(db.get(m.StandState, 1).notified) == notes[3:]
        archive = db.get(m.StandDeletedDeal, 1538)
        assert archive.deleted_by == actors['lisa'] and archive.deleted_at
        assert json.loads(archive.data) == {'deal': duplicates[2], 'notes': [notes[2]], 'outbox': [notes[2]]}


@pytest.mark.parametrize('owner_field', ['managerUserId', 'manager'])
def test_nonowner_cannot_delete_or_claim_ownership_through_board_put(actors, owner_field):
    deal = card(1535, actors['lisa'] if owner_field == 'managerUserId' else None)
    state = seed(deal)
    other = client_for(actors, 'other')
    assert delete(other, 1535).status_code == 403
    assert delete(client_for(actors, 'operator'), 1535).status_code == 403
    forged = copy.deepcopy(state)
    forged['deals'][0][owner_field] = actors['other'] if owner_field == 'managerUserId' else 'Другой менеджер QA'
    refused = other.put('/api/stand/state', json={'version': 13, 'data': forged})
    assert refused.status_code == 409, refused.json
    assert refused.json['error'] == 'Менеджера сделки меняет её менеджер или администратор'
    assert delete(client_for(actors, 'admin'), 1535).status_code == 200


@pytest.mark.parametrize('legacy_owner', ['  ЕЛИЗАВЕТА   Архив QA  ', 'DELETE_QA_LISA'])
def test_legacy_owner_matches_unique_active_account(actors, legacy_owner):
    seed(card(1535, None, manager=legacy_owner))
    result = delete(client_for(actors), 1535)
    assert result.status_code == 200, result.json


def test_ambiguous_legacy_owner_is_not_authorized(actors):
    with m.SessionLocal() as db:
        db.get(m.AdminUser, actors['other']).display_name = 'Елизавета Архив QA'
        db.commit()
    seed(card(1535, None))
    assert delete(client_for(actors), 1535).status_code == 403


@pytest.mark.parametrize('facts,board_extras', [
    ({'cashPartnerUsdt': True}, {}),
    ({'manualBankReceipt': {'status': 'pending'}}, {}),
    ({'transferClaim': {'byId': 7}}, {}),
    ({'transfer': {'sends': [{'hash': 'outgoing', 'status': 'pending'}]}}, {}),
    ({'outgoingOrderAt': '2026-11-24T12:00:00Z'}, {}),
    ({'pay': {'invoicePaid': True}}, {}),
    ({}, {'incomes': [{'dealId': '1535', 'rub': 35000}]}),
    ({}, {'convs': [{'id': 50, 'sources': [{'dealId': 1535, 'rub': 35000}]}]}),
])
def test_active_funds_prevent_deletion_without_moving_the_card(actors, facts, board_extras):
    deal = card(1535, actors['lisa'], **facts)
    before = seed(deal, **board_extras)
    result = delete(client_for(actors, 'admin'), 1535)
    assert result.status_code == 409, result.json
    with m.SessionLocal() as db:
        assert db.get(m.StandDeletedDeal, 1535) is None
        board = db.get(m.StandState, 1)
        assert board.version == 13 and json.loads(board.data) == before


def test_stale_snapshot_cannot_restore_removed_id_or_creation_key(actors):
    archived = card(1542, actors['lisa'], creationKey='a' * 32)
    active = card(1539, actors['lisa'])
    before = seed(archived, active, seq=1541)
    client = client_for(actors)
    stale_delete = delete(client, 1542, 12)
    assert stale_delete.status_code == 409 and stale_delete.json['error'] == 'conflict'
    deleted = delete(client, 1542)
    assert deleted.status_code == 200, deleted.json
    assert deleted.json['data']['seq'] == 1542
    before['deals'][1]['client'] = 'Локальная конкурентная правка'
    stale = client.put('/api/stand/state', json={'version': 13, 'data': before})
    assert stale.status_code == 409 and stale.json['error'] == 'conflict'
    assert [deal['id'] for deal in stale.json['data']['deals']] == [1539]
    for deal_id in (1542, 1543):
        before['deals'][0]['id'] = deal_id
        refused = client.put('/api/stand/state', json={'version': 14, 'data': before})
        assert refused.status_code == 409 and 'Удалённую сделку' in refused.json['error']
    assert client.get('/api/stand/state?read_only=1').json['data'] == deleted.json['data']
    assert client_for(actors, 'admin').post('/api/stand/reset').status_code == 200
    assert client.get('/api/stand/state?read_only=1').json['data']['seq'] >= 1542


def test_archived_card_keeps_crm_row_link_and_invoice_through_reset(actors):
    raw = b'%PDF-1.4\nsynthetic invoice'
    origin = 'delete-qa-generation:1535'
    with m.SessionLocal() as db:
        crm = m.Deal(deal_type=m.DealType.PAY_IN, status=m.DealStatus.LOSE, client_name='Архив QA')
        db.add(crm)
        db.flush()
        crm_id = crm.id
        db.add(m.StandCrmLink(origin=origin, crm_deal_id=crm_id))
        item = m.stand_file_storage.store(db, m.StandFile, 1535, 'inv',
                                          {'id': 'invoice-qa', 'file': 'invoice.pdf',
                                           'mime': 'application/pdf'}, raw)
        file_row = db.get(m.StandFile, item['storageId'])
        object_key = file_row.object_key
        db.commit()
    try:
        deal = card(1535, actors['lisa'], step='done', closed=True,
                    crmDealId=crm_id, files={'inv': [item]})
        seed(deal)
        result = delete(client_for(actors), 1535)
        assert result.status_code == 200, result.json
        assert client_for(actors, 'admin').post('/api/stand/reset').status_code == 200
        assert client_for(actors).get('/api/stand/file/1535/inv/0').status_code == 404
        with m.SessionLocal() as db:
            assert db.get(m.Deal, crm_id).status == m.DealStatus.LOSE
            assert db.get(m.StandCrmLink, origin).crm_deal_id == crm_id
            assert db.get(m.StandFile, item['storageId']).deleted_at is None
            assert json.loads(db.get(m.StandDeletedDeal, 1535).data)['deal'] == deal
        with m.stand_object_store.storage().open(object_key) as source:
            assert source.read() == raw
    finally:
        with m.SessionLocal() as db:
            db.delete(db.get(m.StandCrmLink, origin))
            db.flush()
            db.delete(db.get(m.Deal, crm_id))
            m.stand_file_storage.purge(db, m.StandFile, db.get(m.StandFile, item['storageId']))
            db.commit()


def test_task_archive_is_server_owned_and_hidden_from_nav_counts(actors):
    archived = card(201, actors['lisa'], step='s18w', taskArchived=True)
    active = card(202, actors['lisa'], step='s18w')
    notes = [{'id': 'archived', 'dealId': '201', 'role': 'operator'},
             {'id': 'active', 'dealId': 202, 'role': 'operator'},
             {'id': 'general', 'role': 'operator'}]
    seed(archived, active, notes=notes)
    client = client_for(actors, 'operator')
    assert client.get('/api/stand/nav-count').json == {
        'success': True, 'count': 1, 'notifications': 2,
    }
    admin = client_for(actors, 'admin')
    saved = admin.get('/api/stand/state?read_only=1').json
    proposal = saved['data']
    proposal['deals'][0].pop('taskArchived')
    proposal['deals'][1]['taskArchived'] = True
    proposal['deals'].append(card(203, actors['lisa'], taskArchived=True,
                                  unverified_confirmed=True))
    result = admin.put('/api/stand/state', json={'version': saved['version'], 'data': proposal})
    assert result.status_code == 200, result.json
    proposed_again = result.json['data']
    assert proposed_again['deals'][0]['taskArchived'] is True
    assert all('taskArchived' not in d for d in proposed_again['deals'][1:])
    assert proposed_again['notes'] == notes
    proposed_again['deals'][0]['taskArchived'] = False
    result = admin.put('/api/stand/state', json={'version': result.json['version'], 'data': proposed_again})
    assert result.status_code == 200, result.json
    assert result.json['data']['deals'][0]['taskArchived'] is True
    assert client.get('/api/stand/nav-count').json == {
        'success': True, 'count': 1, 'notifications': 2,
    }
