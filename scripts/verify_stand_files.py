#!/usr/bin/env python3
"""Только чтение: проверяет ссылки, размеры и SHA256 объектов, не импортирует app.

DATABASE_URL и переменные бакета берутся из окружения.
--before-json: необязательная копия старого stand_state.data для сверки переноса.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, text
from stand_file_storage import entries, decode, digest
from stand_object_store import read_verified


def verify(conn, before=None):
    states = [json.loads(row[0] or '{}') for row in conn.execute(text('SELECT data FROM stand_state'))]
    stored = {row['id']: row for row in conn.execute(text('SELECT * FROM stand_files')).mappings()}
    errors, checked, references = [], {}, 0
    for state in states:
        for deal, kind, item in entries(state):
            if not item.get('storageId'):
                if str(item.get('data') or '').startswith('data:'):
                    errors.append(f"deal={deal['id']} kind={kind}: остался base64")
                continue
            references += 1
            row = stored.get(item['storageId'])
            if (not row or row['deal_id'] != deal['id'] or row['kind'] != kind
                    or row['deleted_at'] or row['size'] != item.get('bytes')
                    or row['sha256'] != item.get('sha256')):
                errors.append(f"deal={deal['id']} kind={kind}: повреждена ссылка")
                continue
            if row['id'] not in checked:
                try:
                    read_verified(row['object_key'], row['size'], row['sha256'])
                    checked[row['id']] = row
                except (ValueError, OSError):
                    errors.append(f"object={row['id']}: нет объекта или не совпали размер/SHA256")
    if before:
        # Экспорт API может оборачивать исходный снимок в data.
        before = before.get('data', before)
        for deal, kind, item in entries(before):
            if not str(item.get('data') or '').startswith('data:'):
                continue
            raw = decode(item)
            if not any(row['deal_id'] == deal['id'] and row['kind'] == kind
                       and row['sha256'] == digest(raw) and row['size'] == len(raw)
                       for row in checked.values()):
                errors.append(f"deal={deal['id']} kind={kind}: исходный файл не найден")
    return {'ok': not errors, 'references': references, 'objects_verified': len(checked),
            'bytes_verified': sum(row['size'] for row in checked.values()), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-json', type=Path)
    args = parser.parse_args()
    url = os.environ['DATABASE_URL'].replace('postgres://', 'postgresql://', 1)
    engine = create_engine(url)
    before = json.loads(args.before_json.read_text()) if args.before_json else None
    with engine.connect() as conn:
        conn.execute(text('SET TRANSACTION READ ONLY' if engine.dialect.name == 'postgresql'
                          else 'PRAGMA query_only=ON'))
        result = verify(conn, before)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
