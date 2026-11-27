"""Reconcile and import a reviewed task-board snapshot into a local CalcCRM copy."""

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import psycopg2
from psycopg2 import Binary, sql
from psycopg2.extras import Json, RealDictCursor, execute_values


ASSETS = ('prod.dump', 'stage.dump', 'prod.manifest.json', 'stage.manifest.json',
          'prod.json', 'stage.json', 'report.json', 'stage.objects.json')
ARCHIVED_SOURCE_KEYS = {
    'stand_state': ('id',), 'stand_deleted_deals': ('stand_deal_id',),
    'stand_crm_links': ('origin',), 'stand_close_evidence': ('generation', 'stand_deal_id', 'kind'),
    'stand_files': ('id',), 'agreements': ('id',),
}
DESTINATION_TABLES = ('stand_state', 'stand_deleted_deals', 'stand_files', 'stand_task_imports',
                      'stand_task_history', 'stand_task_history_records')
CLOSED_CRM_STATUSES = {'COMPLETED', 'LOSE', 'NOT_LEAD'}
DECISIONS = {'attach', 'move', 'review', 'archive'}
OBJECT_EXPORT_MANIFEST = 'stand-files-export.json'


class ImportProblem(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ImportProblem(message)


def digest_file(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def json_data(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)


def load_bundle(directory):
    digests = {}
    bundle = {}
    for name in ASSETS:
        path = directory / name
        require(path.resolve().is_relative_to(directory), 'A snapshot asset points outside the supplied bundle.')
        if name.endswith('.json'):
            data = path.read_bytes()
            bundle[name.removesuffix('.json')] = json.loads(data)
            digests[name] = hashlib.sha256(data).hexdigest()
        else:
            digests[name] = digest_file(path)
    bundle_id = hashlib.sha256(json_data(digests).encode()).hexdigest()
    manifests = {name: bundle[f'{name}.manifest'] for name in ('prod', 'stage')}
    snapshots = {name: bundle[name] for name in manifests}
    for name, manifest in manifests.items():
        require(manifest['read_only'] == 'on' and manifest['sha256'] == digests[f'{name}.dump'],
                'Snapshot manifest does not match its readonly dump.')
        require(all(snapshots[name]['meta'][key] == manifest[key]
                    for key in ('db', 'read_only', 'captured_at')),
                'The snapshot selection belongs to a different source.')
    report = bundle['report']
    stages = manifests['stage']['board']
    require(manifests['prod']['db'] != manifests['stage']['db'] and
            report['summary']['snapshots'] == {name: manifest['captured_at'] for name, manifest in manifests.items()}
            and report['summary']['version'] == stages['version'],
            'Reconciliation belongs to a different capture.')
    state, = snapshots['stage']['data']['stand_state']
    require(state['version'] == stages['version'] and state['generation'] == stages['generation'],
            'Board generation or version differs from its manifest.')
    return bundle_id, bundle


def connect(args, name, *, readonly):
    db = psycopg2.connect(host=str(args.socket), port=args.port, user=args.user,
                         dbname=name, connect_timeout=5, application_name='local-task-board-import',
                         options='-c search_path=public,pg_catalog')
    try:
        db.set_session(readonly=readonly, isolation_level='REPEATABLE READ' if readonly else 'READ COMMITTED')
        with db.cursor() as cur:
            cur.execute("SELECT inet_server_addr(), current_setting('data_directory'), current_database()")
            address, data_directory, database = cur.fetchone()
            require(address is None and database == name and Path(data_directory).resolve() == args.cluster,
                    'The PostgreSQL connection is outside the selected local cluster.')
    except Exception:
        db.close()
        raise
    return db


def source_columns(cur):
    cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema='public' ORDER BY table_name, ordinal_position")
    columns = defaultdict(list)
    for table, column in cur:
        columns[table].append(column)
    return columns


def validate_snapshot(cur, snapshot, manifest):
    columns = source_columns(cur)
    require(set(columns) == set(manifest['counts']), 'A readonly source has a different table registry.')
    for table, expected in manifest['counts'].items():
        cur.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
        require(cur.fetchone()[0] == expected, f'Snapshot row count changed in {table}.')
    for table, expected in snapshot['data'].items():
        if not expected:
            continue
        selected = list(expected[0])
        require(set(selected) <= set(columns[table]), f'Snapshot columns changed in {table}.')
        cur.execute(sql.SQL('SELECT {} FROM public.{}').format(
            sql.SQL(', ').join(map(sql.Identifier, selected)), sql.Identifier(table)))
        found = Counter(json_data(dict(zip(selected, row))) for row in cur)
        require(found == Counter(map(json_data, expected)), f'Snapshot data changed in {table}.')
    return columns


def fingerprint(cur, columns):
    # Hash all preexisting columns, even when app startup adds columns to the local copy.
    result = {}
    for name, fields in columns.items():
        cur.execute(sql.SQL("""
            SELECT count(*), md5(coalesce(string_agg(h, ',' ORDER BY h), ''))
            FROM (SELECT md5(to_jsonb(r)::text) h FROM (SELECT {} FROM public.{}) r) hashes
        """).format(sql.SQL(', ').join(map(sql.Identifier, fields)), sql.Identifier(name)))
        result[name] = cur.fetchone()
    return result


def sequence_fingerprint(cur, names=None):
    if names is None:
        cur.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public'")
        names = [row[0] for row in cur.fetchall()]
    result = {}
    for name in names:
        cur.execute(sql.SQL('SELECT last_value, is_called FROM public.{}').format(sql.Identifier(name)))
        result[name] = cur.fetchone()
    return result


def read_native_rows(cur, table):
    with cur.connection.cursor(cursor_factory=RealDictCursor) as records:
        records.execute(sql.SQL('SELECT * FROM public.{}').format(sql.Identifier(table)))
        return [dict(row) for row in records]


def read_raw_rows(cur, table, field=None, ids=()):
    query = sql.SQL('SELECT to_jsonb(t) FROM public.{} t').format(sql.Identifier(table))
    if field is None:
        cur.execute(query)
    else:
        cur.execute(query + sql.SQL(' WHERE {} = ANY(%s)').format(sql.Identifier(field)), (list(ids),))
    return [row[0] for row in cur]


def read_stage_records(cur, stage_deal_ids):
    records = {table: read_raw_rows(cur, table) for table in ARCHIVED_SOURCE_KEYS}
    stage_deals = read_raw_rows(cur, 'deals', 'id', stage_deal_ids)
    require({row['id'] for row in stage_deals} == stage_deal_ids, 'A historical deal is missing from the stage snapshot.')
    records['deals'] = stage_deals
    records['clients'] = read_raw_rows(cur, 'clients', 'id', {row['client_id'] for row in stage_deals if row['client_id']})
    for name in ('deal_agents', 'card_allocations', 'cash_allocations', 'payin_tx_uses', 'payout_tx_uses'):
        records[name] = read_raw_rows(cur, name, 'deal_id', stage_deal_ids)
    reimbursements = {row['reimbursement_id'] for row in stage_deals if row['reimbursement_id']}
    records['reimbursements'] = read_raw_rows(cur, 'reimbursements', 'id', reimbursements)
    records['reimbursement_tx_uses'] = read_raw_rows(cur, 'reimbursement_tx_uses', 'reimbursement_id', reimbursements)
    for prefix in ('payin', 'payout', 'reimbursement'):
        ids = {row['tx_id'] for row in records[f'{prefix}_tx_uses']}
        records[f'{prefix}_txs'] = read_raw_rows(cur, f'{prefix}_txs', 'id', ids)

    archived = []
    for table, rows in records.items():
        keys = ARCHIVED_SOURCE_KEYS.get(table, ('id',))
        archived.extend((table, ':'.join(str(row[key]) for key in keys), row, None, None) for row in rows)
    cur.execute("SELECT to_jsonb(t) - 'data', data FROM public.agreement_docs t")
    for info, content in cur:
        content = bytes(content) if content is not None else None
        require(content is None or len(content) == info['size'], 'A generated document size differs from its metadata.')
        content_hash = hashlib.sha256(content).hexdigest() if content is not None else None
        archived.append(('agreement_docs', str(info['id']), info, content, content_hash))
    return records, archived


def validate_objects(bundle, input_dir, native_files):
    objects = {item['id']: item for item in bundle['stage.objects']}
    require(len(objects) == len(bundle['stage.objects']) and set(objects) == set(native_files),
            'The object inventory differs from the board file metadata.')
    for key, obj in objects.items():
        stored = native_files[key]
        require(all(stored[field] == obj[field] for field in ('object_key', 'sha256', 'size', 'deal_id') if field in stored)
                and obj['ok'] is True, 'A board file does not match the captured object registry.')
        match_object(input_dir, obj)
    return objects


def match_object(directory, obj):
    require(re.fullmatch(r'stand-files/[0-9a-f]{32}', obj['object_key']) and
            re.fullmatch(r'[0-9a-f]{64}', obj['sha256']) and type(obj['size']) is int and obj['size'] > 0,
            'An object inventory entry is invalid.')
    path = directory / obj['object_key']
    require(path.is_file() and path.resolve().is_relative_to(directory) and path.stat().st_size == obj['size']
            and digest_file(path) == obj['sha256'], 'A private board file is missing or has changed.')


def field_references(value, path=()):
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in ('storageId', 'docId', 'agreementId') and nested:
                yield key, str(nested), path
            yield from field_references(nested, path + (key,))
    elif isinstance(value, list):
        for nested in value:
            yield from field_references(nested, path)


def confidential(kind, path):
    return '_managerDraft' in path or any(marker in kind.casefold() for marker in ('pass', 'ipds', 'kyc'))


def document_index(snapshot, board_id, native_files, docs, agreements):
    refs = {}
    file_ids = set()
    agreement_ids = set()

    def add(table, key, info, private):
        identity = (table, key)
        previous = refs.get(identity)
        refs[identity] = {'source': table, 'id': key, 'name': info['filename'], 'mime': info['mime'],
                          'deleted': bool(info['deleted_at']), 'private': private and
                          (previous is None or previous['private'])}

    for field, key, path in field_references(snapshot):
        if field == 'storageId':
            info = native_files.get(key)
            require(info is not None and info['deal_id'] == board_id, 'A task references a file from a different card.')
            file_ids.add(key)
            add('stand_files', key, info, confidential(info['kind'], path))
        elif field == 'docId':
            doc = docs.get(key)
            require(doc is not None and doc[1] is not None, 'A task references a generated document without local bytes.')
            info = doc[0]
            add('agreement_docs', key, info, confidential(info['kind'], path))
        else:
            require(int(key) in agreements, 'A task references an unknown agreement.')
            agreement_ids.add(int(key))

    if board_id is None:
        for field in ('doc_contract_url', 'doc_invoice_url', 'doc_payment_url'):
            match = re.fullmatch(r'/api/docs/file/([1-9][0-9]*)', snapshot.get(field) or '')
            if match and (doc := docs.get(match[1])) and doc[1] is not None:
                add('agreement_docs', match[1], doc[0], True)
    else:
        for key, info in native_files.items():
            if info['deal_id'] == board_id and key not in file_ids:
                add('stand_files', key, info, True)

    # Documents from other payments under the same agreement stay in the archive.
    payment = (snapshot.get('docPack') or {}).get('paymentNo')
    for key, (info, content) in docs.items():
        if (info['agreement_id'] in agreement_ids and content is not None and
                (info['kind'].startswith('source_') or payment is not None and info['seq'] == payment)):
            add('agreement_docs', key, info, True)
    return list(refs.values())


def safe_active_value(value):
    if isinstance(value, dict):
        return {key: safe_active_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_active_value(item) for item in value]
    if isinstance(value, str) and re.match(r'(?i)\s*(?:https?://|//|javascript:|data:)', value):
        return ''
    return value


def build_plan(bundle, records, archive_rows, native_files, owner_map):
    state_row, = records['stand_state']
    state = json.loads(state_row['data'])
    cards = {card['id']: (state_row['generation'], card, False) for card in state['deals']}
    for deleted in records['stand_deleted_deals']:
        snapshot = json.loads(deleted['data'])['deal']
        require(snapshot['id'] == deleted['stand_deal_id'] and snapshot['id'] not in cards,
                'The source board has an inconsistent deleted card.')
        cards[snapshot['id']] = (deleted['generation'] or state_row['generation'], snapshot, True)
    prod = {row['id']: row for row in bundle['prod']['data']['deals']}
    stage = {row['id']: row for row in records['deals']}
    docs = {key: (payload, content) for table, key, payload, content, _ in archive_rows if table == 'agreement_docs'}
    agreements = {row['id'] for row in records['agreements']}
    notes = defaultdict(list)
    for note in state.get('notes', []):
        notes[str(note.get('dealId'))].append(note)

    report = bundle['report']
    decisions = report['rows']
    source_ids = Counter(row['board_id'] for row in decisions if row.get('board_id') is not None)
    require(source_ids == Counter(cards.keys()), 'Every source task must have exactly one reviewed decision.')
    require(Counter(row['prod'] for row in decisions if row.get('prod') is not None) == Counter(prod.keys()),
            'The reviewed plan has incomplete or duplicate coverage of the canonical deals.')
    require(Counter(row['stage'] for row in decisions if row.get('stage') is not None) ==
            Counter(row['id'] for row in bundle['stage']['data']['deals']),
            'The reviewed plan has incomplete or duplicate coverage of the stage deals.')

    plan = []
    active = []
    needed_owners = set()
    for row in decisions:
        board_id = row.get('board_id')
        action = row['action']
        if board_id is None:
            if action != 'archive' or row.get('stage') is None:
                continue
            snapshot = stage[row['stage']]
            require(snapshot['is_test'] is True and prod.get(row.get('prod'), {}).get('is_test') is True,
                    'An unlinked legacy row is not classified as a test deal in both sources.')
            source_kind, source_id, generation = 'legacy_deal', snapshot['id'], None
        else:
            source_kind, source_id = 'board', board_id
            generation, snapshot, deleted = cards[board_id]
            require(action in DECISIONS and row['step'] == snapshot['step'] and
                    bool(row.get('deleted')) == deleted and row['open'] == (action == 'move'),
                    'A decision does not match the task step or archived status.')
            require(not deleted or action == 'archive', 'A deleted task may not return to the board.')
        linked = row.get('attach_target')
        require((action == 'attach') == (linked is not None), 'Incorrect canonical task association.')
        if linked is not None:
            target = prod.get(linked)
            require(target and target['status'] in CLOSED_CRM_STATUSES and not target['is_test'],
                    'A historical association points to a nonfinal or test canonical deal.')
        if action == 'move':
            require(not any(snapshot.get(key) for key in ('closed', 'manual', 'manualNew', 'taskArchived',
                                                          'crmDealId', 'cnvId', 'refId', 'payinHashes', 'payinParts')),
                    'An active task has legacy financial or closure state that needs separate reconciliation.')
            require(not any(field != 'storageId' for field, _, _ in field_references(snapshot)),
                    'An active task has an agreement reference requiring explicit migration.')
            copied = safe_active_value(snapshot)
            for field in ('managerUserId', 'assigneeAdminId'):
                source_owner = snapshot.get(field)
                if source_owner is not None:
                    needed_owners.add(source_owner)
                    copied[field] = owner_map.get(source_owner)
            active.append(copied)
        note_rows = notes[str(board_id)] if board_id is not None else []
        plan.append((source_kind, source_id, generation, action, linked, owner_map.get(snapshot.get('managerUserId')),
                     snapshot, row, document_index(snapshot, board_id, native_files, docs, agreements), note_rows))

    counts = Counter(record[3] for record in plan)
    linked_counts = Counter(record[4] for record in plan if record[4] is not None)
    require(counts['attach'] == report['summary']['attachment_cards'] and
            len(linked_counts) == report['summary']['attachment_targets'] and len(active) == report['summary']['workflow'] and
            len(state['deals']) == report['summary']['board'] and len(cards) - len(state['deals']) == report['summary']['deleted'],
            'Card totals differ from the reviewed reconciliation.')
    active_keys = {card['clientId'] for card in active if card.get('clientId') is not None}
    board_clients = [safe_active_value(client) for client in state.get('clients', []) if client['id'] in active_keys]
    require(len(board_clients) == len(active_keys) and {client['id'] for client in board_clients} == active_keys,
            'An active task does not resolve to a unique board-local client.')
    chat_client_map = {key: client for key, client in state.get('chatClientMap', {}).items() if client in active_keys}
    active_state = {'deals': active, 'clients': board_clients, 'chatClientMap': chat_client_map,
                    'seq': max(state['seq'], *cards), 'notes': []}
    summary = {'cards': sum(record[0] == 'board' for record in plan), 'decisions': counts,
               'legacy_deal_archive': sum(record[0] == 'legacy_deal' for record in plan),
               'canonical_deals': len(linked_counts), 'links_per_deal': Counter(linked_counts.values()),
               'active_steps': Counter(card['step'] for card in active), 'active_board_clients': len(board_clients),
               'active_cards_with_board_client': sum(card.get('clientId') in active_keys for card in active),
               'raw_records': Counter(row[0] for row in archive_rows), 'board_objects': len(native_files),
               'historical_documents': sum(content is not None for _, content in docs.values())}
    return plan, active_state, needed_owners, summary


def read_employee_roles(cur):
    cur.execute("SELECT id, role, coalesce((to_jsonb(u)->>'login_disabled')::boolean, false) "
                "FROM public.admin_users u")
    return {identifier: (role, disabled) for identifier, role, disabled in cur}


def verify_local_provisioning(prod, dest, admin_columns):
    projection = sql.SQL(', ').join(map(sql.Identifier, admin_columns))
    query = sql.SQL('SELECT {} FROM public.admin_users').format(projection)
    prod.execute(query)
    original = {dict(zip(admin_columns, row))['id']: row for row in prod}
    dest.execute(query)
    actual = {dict(zip(admin_columns, row))['id']: row for row in dest}
    require(all(actual.get(key) == row for key, row in original.items()),
            'An original production administrator differs from its canonical snapshot.')
    dest.execute('''
        SELECT count(*) FROM public.admin_users u WHERE NOT (id = ANY(%s)) AND (
            role IS NULL OR role NOT IN ('admin', 'manager', 'operator', 'findir', 'teodor')
            OR telegram_user_id IS NOT NULL OR coalesce(telegram, '') <> ''
            OR coalesce((to_jsonb(u)->>'notify_enabled')::boolean, false))
    ''', (list(original),))
    require(dest.fetchone()[0] == 0, 'Extra destination accounts must be local staff without external identities or notifications.')


def owner_problems(source_roles, target_roles, owner_map, required):
    unresolved = sorted(required - owner_map.keys())
    bad_mappings = sorted(source for source, target in owner_map.items()
                          if source not in source_roles or target not in target_roles or
                          target_roles[target] != (source_roles[source][0], False))
    return {'unmapped_source_staff': unresolved, 'invalid_staff_mappings': bad_mappings}


def ensure_empty_board(cur):
    for table in ('stand_task_history', 'stand_task_history_records', 'stand_deleted_deals', 'stand_files'):
        cur.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{})').format(sql.Identifier(table)))
        require(not cur.fetchone()[0], f'The local destination already has data in {table}.')
    cur.execute('SELECT data, version, notified FROM public.stand_state WHERE id = 1')
    current = cur.fetchone()
    current_state = json.loads(current[0] or '{}') if current else {}
    require(not current or not (current[1] or json.loads(current[2] or '[]')),
            'The target board already has changes or a notification queue.')
    require(all(key == 'cps' or not value for key, value in current_state.items()),
            'The target board already contains tasks or operational state.')
    return current_state


def validate_object_destination(input_dir, output_dir, objects):
    for obj in objects.values():
        source, target = input_dir / obj['object_key'], output_dir / obj['object_key']
        require(target.resolve().is_relative_to(output_dir) and not target.is_symlink(),
                'An output object points outside the local storage directory.')
        require(not target.exists() or target.is_file() and target.stat().st_size == obj['size'] and
                digest_file(target) == obj['sha256'], 'A different file occupies a target object key.')
        yield source, target, obj


def publish_objects(input_dir, output_dir, objects, created):
    for source, target, obj in validate_object_destination(input_dir, output_dir, objects):
        if target.exists():
            continue
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.task_import_') as temp:
            with source.open('rb') as stream:
                shutil.copyfileobj(stream, temp)
            temp.flush()
            os.fsync(temp.fileno())
            require(digest_file(Path(temp.name)) == obj['sha256'], 'Object changed during copy.')
            os.link(temp.name, target)
            created.append(target)


def lock_output_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        os.close(fd)
        raise
    return fd


def write_object_export(args, bundle_id, bundle):
    source = (args.snapshot_dir / 'files').resolve(strict=True)
    output = args.object_output.resolve()
    require(output.parent.is_dir() and output.parent.stat().st_uid == os.getuid() and
            output.parent.stat().st_mode & 0o077 == 0 and not output.is_relative_to(source) and
            not source.is_relative_to(output), 'Export into a separate directory under a private parent.')
    native_files = {row['id']: row for row in bundle['stage']['data']['stand_files']}
    objects = validate_objects(bundle, source, native_files)
    manifest = {'format': 1, 'bundle_sha256': bundle_id, 'objects': [
        {field: entry[field] for field in ('object_key', 'sha256', 'size')}
        for entry in sorted(objects.values(), key=lambda row: row['object_key'])
    ]}
    manifest_bytes = (json_data(manifest) + '\n').encode()
    created = []
    fd = lock_output_directory(output)
    try:
        manifest_path = output / OBJECT_EXPORT_MANIFEST
        require(not manifest_path.is_symlink() and
                (not manifest_path.exists() or manifest_path.read_bytes() == manifest_bytes),
                'The export directory already belongs to a different snapshot.')
        if (output / 'stand-files').exists():
            keys = {entry['object_key'] for entry in objects.values()}
            require(all(path.relative_to(output).as_posix() in keys for path in (output / 'stand-files').iterdir()),
                    'The export directory contains unrelated objects.')
        publish_objects(source, output, objects, created)
        if not manifest_path.exists():
            with tempfile.NamedTemporaryFile(dir=output, prefix='.stand-files-export-') as draft:
                draft.write(manifest_bytes)
                draft.flush()
                os.fsync(draft.fileno())
                os.link(draft.name, manifest_path)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    return {'mode': 'offline-export', 'objects': len(objects), 'bundle_sha256': bundle_id,
            'export_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}


def verify_object_export(directory, expected_digest):
    directory = directory.resolve(strict=True)
    manifest_path = directory / OBJECT_EXPORT_MANIFEST
    require(manifest_path.resolve().is_relative_to(directory), 'The export manifest points outside the object packet.')
    manifest_bytes = manifest_path.read_bytes()
    require(hashlib.sha256(manifest_bytes).hexdigest() == expected_digest,
            'The export manifest does not match its independently approved SHA-256.')
    manifest = json.loads(manifest_bytes)
    require(manifest['format'] == 1 and re.fullmatch(r'[0-9a-f]{64}', manifest['bundle_sha256']),
            'Unsupported object export format.')
    inventory = {entry['object_key'] for entry in manifest['objects']}
    require(len(inventory) == len(manifest['objects']) and
            inventory == {path.relative_to(directory).as_posix() for path in (directory / 'stand-files').iterdir()},
            'The exported object inventory is incomplete or contains unexpected files.')
    for obj in manifest['objects']:
        match_object(directory, obj)
    return {'mode': 'verified-export', 'objects': len(inventory), 'bundle_sha256': manifest['bundle_sha256'],
            'export_manifest_sha256': expected_digest}


def insert_native(cur, table, rows):
    if rows:
        fields = list(rows[0])
        execute_values(cur, sql.SQL('INSERT INTO public.{} ({}) VALUES %s').format(
            sql.Identifier(table), sql.SQL(', ').join(map(sql.Identifier, fields))),
            [tuple(row[field] for field in fields) for row in rows], page_size=25)


def json_parameter(value):
    return Json(value, dumps=json_data)


def write_plan(cur, bundle_id, state_row, plan, state, archived, native_files, deleted, summary, owner_map):
    manifest = {**summary, 'staff_mappings': owner_map}
    cur.execute('''
        INSERT INTO public.stand_task_imports
        (id, bundle_sha256, generation, source_version, applied_at, reconciliation)
        VALUES (1, %s, %s, %s, %s, %s)
    ''', (bundle_id, state_row['generation'], state_row['version'], datetime.now(timezone.utc), json_parameter(manifest)))
    execute_values(cur, '''
        INSERT INTO public.stand_task_history
        (import_id, source_kind, source_id, source_generation, decision, canonical_deal_id, owner_id,
         snapshot, report_row, documents, notes) VALUES %s
    ''', [(1, *row[:6], *(json_parameter(value) for value in row[6:])) for row in plan], page_size=12)
    execute_values(cur, '''
        INSERT INTO public.stand_task_history_records
        (import_id, source_table, source_key, payload, content, content_sha256) VALUES %s
    ''', [(1, table, key, json_parameter(body), Binary(content) if content is not None else None, digest)
          for table, key, body, content, digest in archived], page_size=8)
    insert_native(cur, 'stand_files', list(native_files.values()))
    insert_native(cur, 'stand_deleted_deals', deleted)
    cur.execute('''
        INSERT INTO public.stand_state (id, data, generation, version, updated_by, updated_at, notified)
        VALUES (1, %s, %s, %s, %s, %s, '[]')
        ON CONFLICT (id) DO UPDATE SET data=excluded.data, generation=excluded.generation,
        version=excluded.version, updated_by=excluded.updated_by, updated_at=excluded.updated_at, notified='[]'
    ''', (json_data(state), state_row['generation'], state_row['version'], 'Перенос задачника', datetime.now(timezone.utc)))


def verify_plan(cur, plan, archived, native_files, deleted):
    cur.execute('''
        SELECT source_kind, source_id, source_generation, decision, canonical_deal_id, owner_id,
               snapshot, report_row, documents, notes FROM public.stand_task_history WHERE import_id = 1
    ''')
    require({row[:2]: row[2:] for row in cur} == {row[:2]: row[2:] for row in plan},
            'The imported history or its canonical associations failed verification.')
    cur.execute('''
        SELECT source_table, source_key, payload, content_sha256, encode(sha256(content), 'hex')
        FROM public.stand_task_history_records WHERE import_id = 1
    ''')
    require({row[:2]: row[2:] for row in cur} ==
            {(table, key): (body, digest, digest) for table, key, body, _, digest in archived},
            'The retained source records or document bytes failed verification.')
    stored = {row['id']: row for row in read_native_rows(cur, 'stand_files')}
    require(all(stored.get(key) == row for key, row in native_files.items()),
            'The native file metadata failed verification.')
    kept_deleted = {row['stand_deal_id']: row for row in read_native_rows(cur, 'stand_deleted_deals')}
    require(all(kept_deleted.get(row['stand_deal_id']) == row for row in deleted),
            'Native deleted-card history failed verification.')


def run_import(args, bundle_id, bundle):
    manifests = {name: bundle[f'{name}.manifest'] for name in ('prod', 'stage')}
    stage_deal_ids = {row['stage'] for row in bundle['report']['rows'] if row.get('stage') is not None and
                      (row.get('board_id') is not None or row['action'] == 'archive')}
    created = []
    preserving_objects = False
    output_fd = None
    try:
        with ExitStack() as stack:
            prod_db = stack.enter_context(closing(connect(args, args.prod_db, readonly=True)))
            stage_db = stack.enter_context(closing(connect(args, args.stage_db, readonly=True)))
            dest_db = stack.enter_context(closing(connect(args, args.destination, readonly=not args.apply)))
            prod = stack.enter_context(prod_db.cursor())
            stage = stack.enter_context(stage_db.cursor())
            dest = stack.enter_context(dest_db.cursor())

            prod_columns = validate_snapshot(prod, bundle['prod'], manifests['prod'])
            validate_snapshot(stage, bundle['stage'], manifests['stage'])
            prod_before = fingerprint(prod, prod_columns)
            source_sequences = sequence_fingerprint(prod)
            stage_roles = read_employee_roles(stage)
            records, archived = read_stage_records(stage, stage_deal_ids)
            native_files = {row['id']: row for row in read_native_rows(stage, 'stand_files')}
            deleted = read_native_rows(stage, 'stand_deleted_deals')
            input_dir = (args.snapshot_dir / 'files').resolve()
            objects = validate_objects(bundle, input_dir, native_files)
            plan, active_state, needed_owners, summary = build_plan(bundle, records, archived, native_files, args.owner_map)
            summary.update(bundle_sha256=bundle_id, mode='dry-run')

            dest_columns = source_columns(dest)
            missing_schema = sorted(set(DESTINATION_TABLES) - dest_columns.keys())
            summary['native_models_missing'] = missing_schema
            marker = None
            if not missing_schema:
                if args.apply:
                    dest.execute(sql.SQL('LOCK TABLE {} IN EXCLUSIVE MODE').format(
                        sql.SQL(', ').join(sql.Identifier('public', table) for table in sorted(DESTINATION_TABLES))))
                dest.execute('SELECT bundle_sha256, reconciliation FROM public.stand_task_imports WHERE id = 1')
                marker = dest.fetchone()

            if marker:
                require(marker[0] == bundle_id, 'A different board snapshot was already imported here.')
                archived_mapping = {int(key): value for key, value in marker[1]['staff_mappings'].items()}
                require(not args.owner_map or archived_mapping == args.owner_map,
                        'The applied snapshot used different employee assignments.')
                if args.owner_map != archived_mapping:
                    plan, _, _, _ = build_plan(bundle, records, archived, native_files, archived_mapping)
                verify_plan(dest, plan, archived, native_files, deleted)
                require(all(target.is_file() for _, target, _ in
                            validate_object_destination(input_dir, args.object_output, objects)),
                        'An imported private file is missing from its local store.')
                summary.update(mode='already-applied', added=0,
                               unmapped_source_staff=[], invalid_staff_mappings=[])
                return summary

            require(all(set(fields) <= set(dest_columns.get(table, [])) for table, fields in prod_columns.items()),
                    'The local destination is missing canonical schema columns.')
            if args.apply and not missing_schema:
                dest.execute(sql.SQL('LOCK TABLE {} IN EXCLUSIVE MODE').format(
                    sql.SQL(', ').join(sql.Identifier('public', table) for table in sorted(prod_columns))))
            dest_before = fingerprint(dest, prod_columns)
            dest_sequences = sequence_fingerprint(dest, source_sequences)
            mismatched = sorted(table for table in prod_before if table != 'admin_users' and
                                dest_before[table] != prod_before[table])
            mismatched_sequences = sorted(name for name in source_sequences if name != 'admin_users_id_seq' and
                                         source_sequences[name] != dest_sequences[name])
            require(not mismatched and not mismatched_sequences,
                    'The local target is stale or belongs to a different canonical snapshot. '
                    f'Mismatched tables: {mismatched}. Sequences: {mismatched_sequences}.')
            verify_local_provisioning(prod, dest, prod_columns['admin_users'])
            summary.update(owner_problems(stage_roles, read_employee_roles(dest), args.owner_map, needed_owners))
            summary['canonical_tables_verified'] = len(prod_before) - 1
            summary['canonical_sequences_verified'] = len(source_sequences) - int('admin_users_id_seq' in source_sequences)
            if not missing_schema:
                current_state = ensure_empty_board(dest)
            if not args.apply:
                for _ in validate_object_destination(input_dir, args.object_output, objects):
                    pass
                return summary
            require(not missing_schema, 'Initialize the local application with the task board enabled before apply.')
            require(not summary['unmapped_source_staff'] and not summary['invalid_staff_mappings'],
                    'An explicit mapping to an active local employee with the same role is required. Run dry-run for IDs.')

            active_state = {**current_state, **active_state}
            if 'cps' not in active_state:
                defaults = Path(__file__).resolve().parents[1] / 'static' / 'stand' / 'counterparties.json'
                active_state['cps'] = json.loads(defaults.read_text(encoding='utf-8'))
            output_fd = lock_output_directory(args.object_output)
            publish_objects(input_dir, args.object_output, objects, created)
            write_plan(dest, bundle_id, records['stand_state'][0], plan, active_state, archived,
                       native_files, deleted, summary, args.owner_map)
            verify_plan(dest, plan, archived, native_files, deleted)
            dest.execute('SELECT data FROM public.stand_state WHERE id = 1')
            require(json.loads(dest.fetchone()[0]) == active_state, 'The working task board failed verification.')
            require(fingerprint(dest, prod_columns) == dest_before and
                    sequence_fingerprint(dest, source_sequences) == dest_sequences,
                    'Production tables or sequences changed during import.')
            # Once COMMIT starts a dropped connection leaves the outcome uncertain.
            # Retain the verified private objects in that case so a retry can reconcile.
            preserving_objects = True
            dest_db.commit()
            summary.update(mode='applied', added=len(plan), production_data_unchanged=True)
            return summary
    finally:
        try:
            if not preserving_objects:
                for path in reversed(created):
                    path.unlink(missing_ok=True)
        finally:
            if output_fd is not None:
                os.close(output_fd)


def positive_number(value):
    if not value.isdecimal() or int(value) < 1:
        raise argparse.ArgumentTypeError('expected a positive integer')
    return int(value)


def manager_mapping(value):
    match = re.fullmatch(r'([1-9][0-9]*):([1-9][0-9]*)', value)
    if not match:
        raise argparse.ArgumentTypeError('expected SOURCE_ID:LOCAL_ID')
    return tuple(map(int, match.groups()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-dir', type=Path, help='Reviewed local snapshot bundle directory')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--print-bundle-id', action='store_true', help='Identify the bundle without a database connection')
    mode.add_argument('--apply', action='store_true', help='Write to the local copy. Default: read-only dry-run')
    mode.add_argument('--export-objects', action='store_true', help='Copy verified storage keys and manifest to an offline packet')
    mode.add_argument('--verify-object-export', action='store_true', help='Verify a transferred offline packet without connecting')
    parser.add_argument('--expected-bundle-sha256', help='Digest of the independently reviewed reconciliation bundle')
    parser.add_argument('--expected-export-sha256', help='Approved manifest digest from --export-objects')
    parser.add_argument('--socket', type=Path, help='Directory of the PostgreSQL UNIX socket')
    parser.add_argument('--cluster', type=Path, help='Private PostgreSQL data directory for the local copies')
    parser.add_argument('--port', type=positive_number)
    parser.add_argument('--user')
    parser.add_argument('--prod-db', default='prod_src', help='Readonly local restore of the canonical production dump')
    parser.add_argument('--stage-db', default='stage_src', help='Readonly local restore of the task board dump')
    parser.add_argument('--destination', help='Dedicated local working copy of the production restore')
    parser.add_argument('--object-output', type=Path, help='Destination for STAND_FILES_LOCAL_DIR')
    parser.add_argument('--manager-map', type=manager_mapping, action='append', default=[],
                        metavar='SOURCE_ID:LOCAL_ID', help='Map source staff to a matching local role')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.verify_object_export:
            require(args.object_output and args.expected_export_sha256,
                    'Specify the exported object directory and approved export manifest digest.')
            summary = verify_object_export(args.object_output, args.expected_export_sha256)
            print(json.dumps(summary, sort_keys=True, indent=2))
            return 0
        require(args.snapshot_dir, 'Specify the reviewed snapshot directory.')
        args.snapshot_dir = args.snapshot_dir.resolve(strict=True)
        bundle_id, bundle = load_bundle(args.snapshot_dir)
        if args.print_bundle_id:
            print(bundle_id)
            return 0
        require(bundle_id == args.expected_bundle_sha256, 'Expected an explicitly approved bundle SHA-256.')
        if args.export_objects:
            require(args.object_output, 'Specify a private export directory.')
            summary = write_object_export(args, bundle_id, bundle)
            print(json.dumps(summary, sort_keys=True, indent=2))
            return 0
        require(all((args.socket, args.cluster, args.port, args.user, args.destination, args.object_output)),
                'Specify the UNIX socket, data directory, port, user, destination and private object directory.')
        args.socket = args.socket.resolve(strict=True)
        args.cluster = args.cluster.resolve(strict=True)
        args.object_output = args.object_output.resolve()
        input_dir = (args.snapshot_dir / 'files').resolve(strict=True)
        require(args.socket.is_dir() and args.cluster.is_dir() and args.socket.parent == args.cluster.parent and
                all(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0
                    for path in (args.cluster, args.socket.parent)) and 0 < args.port < 65536,
                'Use a PostgreSQL copy in a private local directory owned by the current user.')
        require(args.object_output.is_relative_to(args.socket.parent) and
                not args.object_output.is_relative_to(input_dir) and not input_dir.is_relative_to(args.object_output) and
                not args.object_output.is_relative_to(args.cluster) and not args.cluster.is_relative_to(args.object_output) and
                not args.object_output.is_relative_to(args.socket) and not args.socket.is_relative_to(args.object_output),
                'The output must be a separate private object directory alongside the local database copies.')
        names = (args.prod_db, args.stage_db, args.destination)
        require(len(set(names)) == 3 and all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,62}', name) for name in names) and
                args.destination not in {'postgres', 'template0', 'template1', bundle['prod.manifest']['db'],
                                         bundle['stage.manifest']['db']},
                'Choose three distinct local databases, with a dedicated destination.')
        require(len(dict(args.manager_map)) == len(args.manager_map), 'A source employee was mapped more than once.')
        require(len({target for _, target in args.manager_map}) == len(args.manager_map),
                'A local employee cannot represent multiple source accounts.')
        args.owner_map = dict(args.manager_map)
        summary = run_import(args, bundle_id, bundle)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except ImportProblem as exc:
        print(f'Import refused: {exc}', file=sys.stderr)
    except psycopg2.Error as exc:
        print(f'Local database operation failed ({exc.pgcode or type(exc).__name__}).', file=sys.stderr)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f'Invalid or inaccessible local snapshot data ({type(exc).__name__}).', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
