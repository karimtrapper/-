"""Synthetic boundaries between the reviewed import, the board and canonical CRM."""
import hashlib
import json
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

import app as crm
from scripts import import_task_board as importer
from tests.qa_wallet_roles_helpers import client_for, make_user, put_board


CARD_IDS = (3101, 3102, 3103)
CREATION_KEY = 'a' * 32
GENERATION = 'b' * 32
PRIVATE_PDF = b'%PDF-1.4 synthetic private attachment'


@pytest.fixture
def local_tasks(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "unified.db"}'
    engine = create_engine(url)
    crm.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    scoped = scoped_session(factory)
    monkeypatch.setattr(crm, 'engine', engine)
    monkeypatch.setattr(crm, 'SessionLocal', factory)
    monkeypatch.setattr(crm, 'Session', scoped)
    monkeypatch.setattr(crm, 'DATABASE_URL', url)
    monkeypatch.setattr(crm, 'STAND_MODE', False)
    monkeypatch.setattr(crm, 'TASKS_ENABLED', True)
    try:
        yield
    finally:
        scoped.remove()
        engine.dispose()


def input_rows(deal_id):
    cards = [{'id': card_id, 'client': 'Synthetic client', 'step': 'done',
              'managerUserId': 71, 'closed': True} for card_id in CARD_IDS]
    cards[0].update(creationKey=CREATION_KEY, issued={'passport': {'docId': 91}})
    rows = [{'board_id': card_id, 'attach_target': deal_id, 'action': 'attach',
             'step': 'done', 'open': False} for card_id in CARD_IDS]
    rows[0]['prod'] = deal_id
    bundle = {
        'prod': {'data': {'deals': [{'id': deal_id, 'status': 'COMPLETED', 'is_test': False}]}},
        'stage': {'data': {'deals': []}},
        'report': {'rows': rows, 'summary': {'attachment_cards': 3, 'attachment_targets': 1,
                                            'workflow': 0, 'board': 3, 'deleted': 0}},
    }
    records = {'stand_state': [{'generation': GENERATION, 'data': json.dumps({'deals': cards, 'seq': 1})}],
               'stand_deleted_deals': [], 'deals': [], 'agreements': [{'id': 92}]}
    doc = {'id': 91, 'agreement_id': 92, 'seq': 1, 'kind': 'passport', 'filename': 'synthetic.pdf', 'mime': 'application/pdf', 'deleted_at': None}
    archive = [('agreement_docs', '91', doc, PRIVATE_PDF, hashlib.sha256(PRIVATE_PDF).hexdigest())]
    return bundle, records, archive


@pytest.fixture
def imported(local_tasks):
    admin = client_for(make_user('admin'))
    owner_id = make_user('manager')
    owner = client_for(owner_id)
    other = client_for(make_user('manager'))
    operator = client_for(make_user('operator'))
    with crm.get_session() as db:
        deal = crm.Deal(deal_type=crm.DealType.PAY_IN, status=crm.DealStatus.COMPLETED,
                        client_name='Synthetic canonical', source_channel='site',
                        payin_method=crm.PayInMethod.CRYPTO_DIRECT, payin_amount_usdt=1800,
                        payout_amount_usdt=1730, profit_usdt=70, net_profit_usdt=70)
        db.add(deal)
        db.commit()
        deal_id = deal.id
    report_url = '/api/analytics/site-customers?period=all&source=site'
    before = admin.get(report_url).json['summary']

    bundle, records, documents = input_rows(deal_id)
    plan, state, _, summary = importer.build_plan(bundle, records, documents, {}, {71: owner_id})
    assert summary['canonical_deals'] == 1 and summary['links_per_deal'] == {3: 1}
    tables = crm.Base.metadata.tables
    with crm.get_session() as db:
        db.execute(tables['stand_task_imports'].insert().values(
            id=1, bundle_sha256='d' * 64, generation=GENERATION, source_version=1,
            applied_at=datetime.now(timezone.utc), reconciliation={}))
        fields = ('source_kind', 'source_id', 'source_generation', 'decision', 'canonical_deal_id',
                  'owner_id', 'snapshot', 'report_row', 'documents', 'notes')
        db.execute(tables['stand_task_history'].insert(), [
            {'import_id': 1, **dict(zip(fields, row, strict=True))} for row in plan
        ])
        db.execute(tables['stand_task_history_records'].insert(), [
            dict(import_id=1, source_table=table, source_key=key, payload=payload,
                 content=body, content_sha256=sha) for table, key, payload, body, sha in documents
        ])
        db.commit()
    put_board(state)
    return admin, owner, other, operator, deal_id, report_url, before


def test_three_imported_cards_keep_one_financial_deal(imported):
    admin, owner, _, _, deal_id, report_url, before = imported
    response = admin.get('/api/deals?closed_via_tasks=1')
    assert response.status_code == 200
    assert [deal['id'] for deal in response.json['deals']] == [deal_id]
    assert admin.get(report_url).json['summary'] == before
    assert (before['deals'], before['volume_usdt'], before['profit_usdt']) == (1, 1800, 70)
    history = owner.get(f'/api/deals/{deal_id}/task-history')
    assert history.status_code == 200
    assert [card['id'] for card in history.json['cards']] == list(CARD_IDS)
    assert {card['crm_deal_id'] for card in history.json['cards']} == {deal_id}
    analytics = admin.get('/api/stand/task-history/analytics')
    assert analytics.status_code == 200
    entry, = analytics.json['deals']
    assert entry['crm_deal_id'] == deal_id
    assert entry['payin'] == {'currency': 'USDT', 'amount': 1800}

    response = admin.get('/api/stand/state?read_only=1')
    assert response.status_code == 200
    state, version = response.json['data'], response.json['version']
    assert state['deals'] == [] and state['seq'] >= max(CARD_IDS)
    for card_id, key in [(CARD_IDS[0], 'c' * 32), (max(CARD_IDS) + 1, CREATION_KEY)]:
        refused = admin.put('/api/stand/state', json={
            'version': version, 'data': {**state, 'deals': [{'id': card_id, 'creationKey': key}]},
        })
        assert refused.status_code == 409, refused.json
        assert 'истории задачника' in refused.json['error']
    assert admin.delete(f'/api/deals/{deal_id}').status_code == 409
    assert admin.get(f'/api/deals/{deal_id}').status_code == 200
    assert admin.get(report_url).json['summary'] == before


def test_history_private_file_requires_admin_or_owning_manager(imported):
    admin, owner, other, operator, deal_id, _, _ = imported
    history = owner.get(f'/api/deals/{deal_id}/task-history').json['cards']
    document, = history[0]['documents']
    url = document['url']
    for client in [owner, admin]:
        response = client.get(url)
        assert response.status_code == 200 and response.data == PRIVATE_PDF
        assert response.headers['Cache-Control'] == 'private, no-store'
    for client in [other, operator]:
        cards = client.get(f'/api/deals/{deal_id}/task-history').json['cards']
        assert cards[0]['documents'] == []
        assert client.get(url).status_code == 404
    assert crm.app.test_client().get(url).status_code == 401
    assert admin.delete(url).status_code == 405
    assert admin.get(url).data == PRIVATE_PDF


def test_not_lead_is_excluded_from_conversion(local_tasks):
    admin = client_for(make_user('admin'))
    with crm.get_session() as db:
        db.add_all(crm.Deal(deal_type=crm.DealType.PAY_IN, status=status,
                            client_name=f'Synthetic {status.value}', created_at=datetime.now(),
                            profit_usdt=70)
                   for status in (crm.DealStatus.COMPLETED, crm.DealStatus.LOSE, crm.DealStatus.NOT_LEAD))
        db.commit()
    result = admin.get('/api/analytics/conversion?months=2')
    assert result.status_code == 200
    totals = result.json['totals']
    assert totals['new'] == {'total': 2, 'won': 1, 'cr': 50.0}
    assert totals['lost_episodes'] == 1 and totals['avg_profit_usdt'] == 70


def test_import_rejects_unapproved_digest_before_database_access(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(importer, 'load_bundle', lambda _: ('a' * 64, {}))
    monkeypatch.setattr(importer, 'run_import', lambda *_: pytest.fail('import reached the database'))
    monkeypatch.setattr(sys, 'argv', [
        'import_task_board', '--snapshot-dir', str(tmp_path), '--expected-bundle-sha256', 'b' * 64,
        '--apply',
    ])
    current_umask = importer.os.umask(0o077)
    try:
        assert importer.main() == 1
    finally:
        importer.os.umask(current_umask)
    assert 'explicitly approved bundle SHA-256' in capsys.readouterr().err


def test_import_rejects_foreign_crm_target_and_wrong_manager_role():
    bundle, records, archive = input_rows(17)
    bundle['report']['rows'][1]['attach_target'] = 999
    with pytest.raises(importer.ImportProblem, match='nonfinal or test canonical deal'):
        importer.build_plan(bundle, records, archive, {}, {71: 88})

    source_roles = {71: ('manager', False)}
    target_roles = {88: ('operator', False), 89: ('manager', True), 90: ('manager', False)}
    for target in (88, 89, 999):
        assert importer.owner_problems(source_roles, target_roles, {71: target}, {71}) == {
            'unmapped_source_staff': [], 'invalid_staff_mappings': [71],
        }
    assert importer.owner_problems(source_roles, target_roles, {71: 90}, {71}) == {
        'unmapped_source_staff': [], 'invalid_staff_mappings': [],
    }
