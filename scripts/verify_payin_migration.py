"""Restore an explicit local dump into a disposable socket-only PostgreSQL.

No application import, no inherited DB credentials, no external connection.
Usage: python scripts/verify_payin_migration.py /absolute/local/dump.sql.gz
"""
import gzip
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PG = Path('/opt/homebrew/opt/postgresql@17/bin')


def main():
    dump = Path(sys.argv[1]).expanduser().resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='calccrm-t19-pg-hashsplit-', dir='/private/tmp') as folder:
        work = Path(folder)
        env = {'PATH': str(PG) + ':/usr/bin:/bin', 'HOME': folder, 'LC_ALL': 'C'}
        def run(binary, *args, data=None):
            result = subprocess.run([str((Path('/opt/homebrew/opt/libpq/bin') if binary in ('psql', 'pg_dump') else PG) / binary), *map(str, args)], input=data,
                                    capture_output=True, env=env)
            if result.returncode:
                # Keep dump data/private values out of the tool output.
                error_path = Path('/tmp/hashsplit-migration-private-errors.log')
                error_path.touch(mode=0o600, exist_ok=True)
                error_path.write_bytes(result.stderr)
                raise RuntimeError(f'{binary} failed (code {result.returncode}); private log: /tmp/hashsplit-migration-private-errors.log')
            return result.stdout
        run('initdb', '-E', 'UTF8', '-D', work / 'db', '-A', 'trust', '-U', 'migration_test')
        (work / 'socket').mkdir()
        run('pg_ctl', '-D', work / 'db', '-l', work / 'server.log', '-o',
            f"-k {work / 'socket'} -h '' -p 55439", '-w', 'start')
        args = ['-h', work / 'socket', '-p', '55439', '-U', 'migration_test', '-d', 'postgres']
        def sql(value):
            return run('psql', *args, '-X', '-v', 'ON_ERROR_STOP=1', '-1', data=value.encode())
        def snapshot(flag):
            value = run('pg_dump', *args, '--no-owner', '--no-privileges', flag).decode()
            value = re.sub(r'^\\(?:un)?restrict .*\n', '', value, flags=re.M)
            return hashlib.sha256(value.encode()).hexdigest()
        try:
            sql(gzip.open(dump, 'rt').read())
            before = {kind: snapshot(kind) for kind in ('--schema-only', '--data-only')}
            columns = run('psql', *args, '-X', '-At', '-c', "SELECT quote_ident(table_name) || '|' || string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema='public' GROUP BY table_name ORDER BY table_name").decode().splitlines()
            def original_data():
                queries = []
                for line in columns:
                    table, names = line.split('|', 1)
                    queries.append(f"SELECT '{table}', count(*), md5(string_agg(v, E'\\n' ORDER BY v COLLATE \"C\")) FROM (SELECT ROW({names})::text v FROM public.{table}) q;")
                return run('psql', *args, '-X', '-At', data='\n'.join(queries).encode())
            before_rows = original_data()
            up = (ROOT / 'migrations/20261014_payin_reservations_up.sql').read_text()
            down = (ROOT / 'migrations/20261014_payin_reservations_down.sql').read_text()
            sql(up)
            assert original_data() == before_rows, 'up changed existing data'
            sql(up)  # idempotent
            sql(down)
            after = {kind: snapshot(kind) for kind in before}
            assert before == after, f'roundtrip mismatch: {before} != {after}'
            sql(up)
            sql("INSERT INTO payin_tx_uses (id, tx_id, amount_usdt, stand_generation, stand_cnv_id) SELECT -2147483000, id, 0.001, 'migration-probe', 'A' FROM payin_txs ORDER BY id LIMIT 1")
            probe_count = run('psql', *args, '-X', '-At', '-c', 'SELECT count(*) FROM payin_tx_uses WHERE id=-2147483000').strip()
            assert probe_count == b'1', 'dump has no transaction for downgrade guard probe'
            guard_before = {kind: snapshot(kind) for kind in before}
            attempt = subprocess.run([str(Path('/opt/homebrew/opt/libpq/bin/psql')), *map(str, args),
                '-X', '-v', 'ON_ERROR_STOP=1', '-1'], input=down.encode(), capture_output=True, env=env)
            assert attempt.returncode and b'Cannot roll back' in attempt.stderr
            assert {kind: snapshot(kind) for kind in before} == guard_before, 'blocked down changed data/schema'
            sql('DELETE FROM payin_tx_uses WHERE id=-2147483000')
            sql(down)
            assert {kind: snapshot(kind) for kind in before} == before
            print('DOWN GUARD PASS: active reservation blocks rollback without changing any data/schema')
            print('RESTORE/UP/UP/DOWN PASS: all table data and original schema hashes identical')
            print('Schema SHA256:', after['--schema-only'])
            print('Data SHA256:', after['--data-only'])
        finally:
            run('pg_ctl', '-D', work / 'db', '-m', 'fast', '-w', 'stop')


if __name__ == '__main__':
    main()
