"""Read-only history from the reconciled snapshot of the previous task board."""

import hashlib
import io
import math
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request, send_file, session, url_for
from sqlalchemy import (
    JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary,
    String, Table, exists, select,
)

import stand_object_store


TABLE_NAMES = frozenset({'stand_task_imports', 'stand_task_history', 'stand_task_history_records'})
HISTORY_DECISIONS = {'attach', 'move', 'archive', 'review'}
STAFF_ROLES = {'admin', 'manager', 'operator', 'findir', 'teodor'}
SAFE_INLINE_MIMES = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'}
FINAL_DEAL_STATUSES = {'COMPLETED', 'LOSE', 'NOT_LEAD'}
TASK_SOURCES = {'tg', 'wa', 'bitrix', 'none'}
BANGKOK = ZoneInfo('Asia/Bangkok')


def install_models(base):
    metadata = base.metadata
    Table('stand_task_imports', metadata,
          Column('id', Integer, primary_key=True, autoincrement=False),
          Column('bundle_sha256', String(64), nullable=False, unique=True),
          Column('generation', String(32), nullable=False),
          Column('source_version', Integer, nullable=False),
          Column('applied_at', DateTime(timezone=True), nullable=False),
          Column('reconciliation', JSON, nullable=False),
          CheckConstraint('id = 1', name='ck_single_task_import'))
    Table('stand_task_history', metadata,
          Column('source_kind', String(16), primary_key=True),
          Column('source_id', Integer, primary_key=True, autoincrement=False),
          Column('import_id', ForeignKey('stand_task_imports.id'), nullable=False),
          Column('source_generation', String(32)),
          Column('decision', String(10), nullable=False, index=True),
          Column('canonical_deal_id', ForeignKey('deals.id', ondelete='SET NULL'), index=True),
          Column('owner_id', Integer),
          Column('snapshot', JSON, nullable=False),
          Column('report_row', JSON, nullable=False),
          Column('documents', JSON, nullable=False),
          Column('notes', JSON, nullable=False),
          CheckConstraint("source_kind IN ('board', 'legacy_deal')", name='ck_task_history_kind'),
          CheckConstraint("decision IN ('attach', 'move', 'archive', 'review')", name='ck_task_history_decision'),
          CheckConstraint("decision = 'attach' OR canonical_deal_id IS NULL", name='ck_task_history_link'))
    Table('stand_task_history_records', metadata,
          Column('source_table', String(40), primary_key=True),
          Column('source_key', String(150), primary_key=True),
          Column('import_id', ForeignKey('stand_task_imports.id'), nullable=False),
          Column('payload', JSON, nullable=False),
          Column('content', LargeBinary),
          Column('content_sha256', String(64)))


def linked_deal_exists(base, deal_id):
    history = base.metadata.tables['stand_task_history']
    return exists().where(history.c.canonical_deal_id == deal_id)


def text_for_history(value):
    """Historical text is display-only. URL targets always come from this app."""
    if not isinstance(value, str):
        return ''
    return re.sub(r'(?i)(?:https?://|javascript:|data:|(?<!:)//)\S+', '', value).strip()


def _can_read_card(row, role):
    return role == 'admin' or row['decision'] == 'attach' and row['canonical_deal_id'] is not None


def _can_read_document(row, document, role, user_id):
    if role == 'admin' or role == 'manager' and user_id == row['owner_id']:
        return True
    if document['private']:
        return False
    additional = (row['snapshot'].get('files') or {}).get('additional') or []
    return not any(isinstance(item, dict) and item.get('storageId') == document['id'] and
                   item.get('documentType') in ('pass', 'ipds', 'kyc') for item in additional)


def _history_entry(row, role, user_id, *, details):
    card = row['snapshot']
    report = row['report_row']
    board = row['source_kind'] == 'board'
    item = {
        'id': row['source_id'], 'source_kind': row['source_kind'],
        'code': text_for_history(card.get('code')) or f"№{row['source_id']}",
        'step': card.get('step') if board else None,
        'client': text_for_history(card.get('client') if board else card.get('client_name')),
        'type': text_for_history(card.get('type') if board else card.get('deal_kind')),
        'decision': row['decision'], 'crm_deal_id': row['canonical_deal_id'],
        'closed': row['decision'] != 'move', 'source_deleted': bool(report.get('deleted')),
        'manual': bool(report.get('manual_entry')),
        'created_at': text_for_history(card.get('createdAt') if board else card.get('created_at')),
        'source_status': text_for_history(report.get('stage_status')),
        'detail_url': url_for('stand_task_history_entry', source_kind=row['source_kind'], source_id=row['source_id']),
    }
    if details:
        item['log'] = [{key: text_for_history(entry.get(key)) for key in ('ts', 'text', 'author', 'role')}
                       for entry in card.get('log') or [] if isinstance(entry, dict)]
        item['notes'] = [{key: text_for_history(note.get(key)) for key in ('text', 'role')}
                         for note in row['notes']
                         if role == 'admin' or role == note.get('role') and
                         note.get('recipientAdminId') in (None, user_id)]
        item['documents'] = [
            {'name': document['name'], 'mime': document['mime'], 'deleted': document['deleted'],
             'url': url_for('stand_task_history_document', source_kind=row['source_kind'],
                            source_id=row['source_id'], index=index)}
            for index, document in enumerate(row['documents'])
            if _can_read_document(row, document, role, user_id)
        ]
        if role == 'admin' and row['decision'] == 'review':
            item['candidates'] = [candidate['id'] for candidate in report.get('candidates', [])]
    return item


def _enum_name(value):
    return getattr(value, 'name', str(value or '').upper())


def _enum_value(value):
    return getattr(value, 'value', value)


def _canonical_payin(deal):
    amounts = {currency: deal[f'payin_amount_{currency.lower()}'] for currency in ('RUB', 'THB', 'USDT')}
    custom_currency = (deal['custom_payin_currency'] or '').upper()
    custom = deal['custom_payin_amount']
    if custom_currency in ('RUB', 'THB', 'USDT', 'USD') and isinstance(custom, (float, int)) and math.isfinite(custom) and custom > 0:
        return {'currency': custom_currency, 'amount': custom}
    positive = {currency: amount for currency, amount in amounts.items()
                if isinstance(amount, (float, int)) and math.isfinite(amount) and amount > 0}
    rail = _enum_value(deal['payin_method'])
    preferred = ('USDT' if rail == 'crypto_direct' else 'RUB'
                 if rail in ('spp_doverka', 'partners_cash', 'sber_wl', 'sber_reqs', 'flow_sole_reqs') else None)
    currency = preferred if preferred in positive else next(iter(positive)) if len(positive) == 1 else None
    return {'currency': currency, 'amount': positive.get(currency)}


def _local_date(value):
    try:
        if isinstance(value, datetime):
            clock = value
        elif type(value) in (int, float) and value >= 1e11:
            clock = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value)
        elif isinstance(value, str) and (match := re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{4})(?:,? \d{2}:\d{2})?', value)):
            day, month, year = map(int, match.groups())
            return date(year, month, day)
        elif isinstance(value, str) and re.match(r'^\d{4}-\d{2}-\d{2}T', value):
            clock = datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            return None
        return (clock if clock.tzinfo else clock.replace(tzinfo=timezone.utc)).astimezone(BANGKOK).date()
    except (ValueError, OverflowError, OSError):
        return None


def _legacy_closed_date(card, status, reason):
    card_reason = card.get('closeReason')
    expected_reason = 'Успешно завершена' if status == 'COMPLETED' else reason
    if card.get('closed') is not True or not expected_reason or card_reason != expected_reason:
        return None
    stage_deal_id = card.get('crmDealId')
    if type(stage_deal_id) is int and stage_deal_id > 0:
        if saved := _local_date(card.get('closedAt')) or _local_date(card.get('closedTs')):
            return saved
    for entry in reversed(card.get('log') or []):
        if (isinstance(entry, dict) and entry.get('kind') != 'comment' and
                entry.get('text') in (f'Закрыта: {card_reason}', f'Закрыта сразу: {card_reason}')):
            if confirmed := _local_date(entry.get('at')) or _local_date(entry.get('ts')):
                return confirmed
    return None


def _group_value(cards, key, accepted):
    values = {card[key] for card in cards if card.get(key) in accepted}
    return next(iter(values)) if len(values) == 1 else None


def _analytics_entry(deal, cards):
    status = _enum_name(deal['status'])
    reason = text_for_history(deal['lose_reason']) or None
    created_at = deal['created_at']
    opened_on = _local_date(created_at)
    recent = {day for card in cards if (day := _legacy_closed_date(card, status, reason)) and
              (opened_on is None or day >= opened_on)}
    closed_on = next(iter(recent)) if len(recent) == 1 else None
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    source = {'telegram': 'tg', 'whatsapp': 'wa'}.get(deal['source_channel'], deal['source_channel'])
    if source not in TASK_SOURCES:
        source = None
    if deal['source_channel'] is None:
        source = _group_value(cards, 'source', TASK_SOURCES)
    identifier = deal['id']
    return {'crm_deal_id': identifier, 'code': f'№{identifier}', 'url': f'/crm?deal={identifier}',
            'status': status, 'created_at': created_at.isoformat() if created_at else None,
            'closed_at': closed_on.isoformat() if closed_on else None,
            'deal_kind': deal['deal_kind'], 'deal_type': _enum_value(deal['deal_type']), 'source': source,
            'inquiry_type': _group_value(cards, 'inquiryType', {'agent', 'client'}),
            'client': text_for_history(deal['client_name']) or None, 'manager': text_for_history(deal['manager_name']) or None,
            'payin': _canonical_payin(deal), 'close_reason': reason}


def register_routes(app, base, get_session, stand_file, current_role, *, enabled):
    history = base.metadata.tables['stand_task_history']
    records = base.metadata.tables['stand_task_history_records']
    deals = base.metadata.tables['deals']

    def authorized():
        if not enabled():
            abort(404)
        user_id = session.get('user_id')
        role = current_role()
        if user_id is None or role not in STAFF_ROLES:
            abort(401)
        return role, user_id

    def private_json(**body):
        response = jsonify(success=True, **body)
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def entry(db, source_kind, source_id, role):
        row = db.execute(select(history).where(
            history.c.source_kind == source_kind, history.c.source_id == source_id,
        )).mappings().one_or_none()
        if row is None or not _can_read_card(row, role):
            abort(404)
        return row

    def archived_document(db, document_id):
        return db.execute(select(records.c.payload, records.c.content, records.c.content_sha256).where(
            records.c.source_table == 'agreement_docs', records.c.source_key == document_id,
        )).mappings().one_or_none()

    def board_file_content(db, document_id, deal_id):
        stored = db.get(stand_file, document_id)
        if stored is None or stored.deal_id != deal_id:
            abort(404)
        try:
            return stand_object_store.read_verified(stored.object_key, stored.size, stored.sha256)
        except (OSError, ValueError):
            abort(503)

    def checked_document_content(document):
        if document is None or document['content'] is None:
            abort(404)
        content = bytes(document['content'])
        if hashlib.sha256(content).hexdigest() != document['content_sha256']:
            abort(503)
        return content

    def serve_document(content, mime, name):
        inline = mime in SAFE_INLINE_MIMES and 'download' not in request.args
        filename = re.sub(r'[\x00-\x1f\x7f]', '', Path(name).name) or 'document'
        response = send_file(io.BytesIO(content), mimetype=mime if inline else 'application/octet-stream',
                             as_attachment=not inline, download_name=filename)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/api/deals/<int:deal_id>/task-history')
    def crm_task_history(deal_id):
        role, user_id = authorized()
        with get_session() as db:
            rows = db.execute(select(history).where(
                history.c.canonical_deal_id == deal_id,
            ).order_by(history.c.source_id)).mappings()
            return private_json(cards=[_history_entry(row, role, user_id, details=True) for row in rows])

    @app.get('/api/stand/task-history')
    def stand_task_history_index():
        role, user_id = authorized()
        if role != 'admin':
            abort(403)
        decision = request.args.get('decision', 'archive')
        if decision not in ('archive', 'review'):
            abort(400)
        with get_session() as db:
            rows = db.execute(select(history).where(history.c.decision == decision).order_by(
                history.c.source_kind, history.c.source_id.desc(),
            )).mappings()
            return private_json(cards=[_history_entry(row, role, user_id, details=False) for row in rows])

    @app.get('/api/stand/task-history/analytics')
    def stand_task_history_analytics():
        authorized()
        fields = ('id', 'created_at', 'status', 'deal_kind', 'deal_type', 'source_channel',
                  'client_name', 'manager_name', 'payin_method', 'payin_amount_rub', 'payin_amount_thb',
                  'payin_amount_usdt', 'custom_payin_currency', 'custom_payin_amount', 'lose_reason')
        with get_session() as db:
            cards = defaultdict(list)
            for identifier, card in db.execute(select(history.c.canonical_deal_id, history.c.snapshot).where(
                history.c.decision == 'attach', history.c.canonical_deal_id.is_not(None),
            )):
                cards[identifier].append(card)
            if not cards:
                return private_json(deals=[])
            rows = db.execute(select(*(deals.c[name] for name in fields)).where(
                deals.c.id.in_(cards), deals.c.status.in_(FINAL_DEAL_STATUSES), deals.c.is_test.is_not(True),
            ).order_by(deals.c.created_at.desc(), deals.c.id.desc())).mappings()
            return private_json(deals=[_analytics_entry(row, cards[row['id']]) for row in rows])

    @app.get('/api/stand/task-history/agreements')
    def stand_task_history_agreements():
        role, _ = authorized()
        if role != 'admin':
            abort(403)
        with get_session() as db:
            rows = db.execute(select(records.c.source_table, records.c.payload, records.c.content_sha256).where(
                records.c.source_table.in_(('agreements', 'agreement_docs', 'stand_files')),
            )).all()
            board_ids = set(db.execute(select(history.c.source_id).where(history.c.source_kind == 'board')).scalars())
        agreements = {
            row.payload['id']: {'id': row.payload['id'], 'number': text_for_history(row.payload['number']),
                                'client': text_for_history(row.payload.get('client_name')), 'documents': []}
            for row in rows if row.source_table == 'agreements'
        }
        unattached = []
        for row in rows:
            if row.source_table == 'stand_files' and row.payload['deal_id'] not in board_ids:
                unattached.append({'name': row.payload['filename'], 'mime': row.payload['mime'],
                                   'deleted': bool(row.payload['deleted_at']),
                                   'url': url_for('stand_task_history_unattached_document', file_id=row.payload['id'])})
            if row.source_table != 'agreement_docs' or row.content_sha256 is None:
                continue
            doc = row.payload
            agreement = agreements.get(doc['agreement_id'])
            if agreement is not None:
                agreement['documents'].append({
                    'name': doc['filename'], 'mime': doc['mime'], 'deleted': bool(doc['deleted_at']),
                    'url': url_for('stand_task_history_agreement_document', agreement_id=agreement['id'],
                                   doc_id=doc['id']),
                })
        return private_json(agreements=sorted(agreements.values(), key=lambda agreement: agreement['id'], reverse=True),
                            unattached_files=unattached)

    @app.get('/api/stand/task-history/agreements/<int:agreement_id>/documents/<int:doc_id>')
    def stand_task_history_agreement_document(agreement_id, doc_id):
        role, _ = authorized()
        if role != 'admin':
            abort(404)
        with get_session() as db:
            document = archived_document(db, str(doc_id))
            if document is None or document['payload']['agreement_id'] != agreement_id:
                abort(404)
            content = checked_document_content(document)
        return serve_document(content, document['payload']['mime'], document['payload']['filename'])

    @app.get('/api/stand/task-history/unattached-files/<file_id>')
    def stand_task_history_unattached_document(file_id):
        role, _ = authorized()
        if role != 'admin' or not re.fullmatch(r'[0-9a-f]{32}', file_id):
            abort(404)
        with get_session() as db:
            info = db.execute(select(records.c.payload).where(
                records.c.source_table == 'stand_files', records.c.source_key == file_id,
            )).scalar_one_or_none()
            if info is None or db.execute(select(history.c.source_id).where(
                history.c.source_kind == 'board', history.c.source_id == info['deal_id'],
            )).scalar_one_or_none() is not None:
                abort(404)
            content = board_file_content(db, file_id, info['deal_id'])
        return serve_document(content, info['mime'], info['filename'])

    @app.get('/api/stand/task-history/<int:source_id>', defaults={'source_kind': 'board'})
    @app.get('/api/stand/task-history/<source_kind>/<int:source_id>')
    def stand_task_history_entry(source_kind, source_id):
        role, user_id = authorized()
        with get_session() as db:
            row = entry(db, source_kind, source_id, role)
            return private_json(card=_history_entry(row, role, user_id, details=True))

    @app.get('/api/stand/task-history/<source_kind>/<int:source_id>/documents/<int:index>')
    def stand_task_history_document(source_kind, source_id, index):
        role, user_id = authorized()
        with get_session() as db:
            row = entry(db, source_kind, source_id, role)
            if index >= len(row['documents']):
                abort(404)
            document = row['documents'][index]
            if not _can_read_document(row, document, role, user_id):
                abort(404)
            if document['source'] == 'stand_files':
                content = board_file_content(db, document['id'], source_id)
            else:
                content = checked_document_content(archived_document(db, document['id']))
        return serve_document(content, document['mime'], document['name'])
