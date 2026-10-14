"""Restore a local stand dump to disposable PostgreSQL and check account migration.

Usage: python3 scripts/verify_income_account_migration.py /absolute/dump.sql.gz
No application import, inherited DB credentials or external connection.
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
LIBPQ = Path('/opt/homebrew/opt/libpq/bin')


def main():
    dump = Path(sys.argv[1]).expanduser().resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='calccrm-income-migration-', dir='/private/tmp') as folder:
        work = Path(folder)
        env = {'PATH': str(PG) + ':/usr/bin:/bin', 'HOME': folder, 'LC_ALL': 'C'}

        def run(binary, *args, data=None):
            path = (LIBPQ if binary in ('psql', 'pg_dump') else PG) / binary
            result = subprocess.run([str(path), *map(str, args)], input=data,
                                    capture_output=True, env=env)
            if result.returncode:
                # A restore error can include real customer data. Keep it private.
                error_path = work / 'private-errors.log'
                error_path.write_bytes(result.stderr)
                raise RuntimeError(f'{binary} failed ({result.returncode}); private log: {error_path}')
            return result.stdout

        run('initdb', '-E', 'UTF8', '-D', work / 'db', '-A', 'trust', '-U', 'migration_test')
        (work / 'socket').mkdir()
        run('pg_ctl', '-D', work / 'db', '-l', work / 'server.log', '-o',
            f"-k {work / 'socket'} -h '' -p 55441", '-w', 'start')
        args = ['-h', work / 'socket', '-p', '55441', '-U', 'migration_test', '-d', 'postgres']

        def sql(value):
            return run('psql', *args, '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-1', data=value.encode())

        def snapshot(flag):
            value = run('pg_dump', *args, '--no-owner', '--no-privileges', flag).decode()
            value = re.sub(r'^\\(?:un)?restrict .*\n', '', value, flags=re.M)
            return hashlib.sha256(value.encode()).hexdigest()

        try:
            sql(gzip.open(dump, 'rt').read())
            initial = {kind: snapshot(kind) for kind in ('--schema-only', '--data-only')}
            columns = run('psql', *args, '-X', '-At', '-c',
                "SELECT quote_ident(table_name) || '|' || "
                "string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) "
                "FROM information_schema.columns WHERE table_schema='public' "
                "GROUP BY table_name ORDER BY table_name").decode().splitlines()

            def original_rows():
                queries = []
                for line in columns:
                    table, names = line.split('|', 1)
                    queries.append(f"SELECT '{table}', count(*), "
                        f"md5(string_agg(v, E'\\n' ORDER BY v COLLATE \"C\")) "
                        f"FROM (SELECT ROW({names})::text v FROM public.{table}) q;")
                return run('psql', *args, '-X', '-At', data='\n'.join(queries).encode())

            before_rows = original_rows()
            up = (ROOT / 'scripts/migrations/20261014_income_account_up.sql').read_text()
            down = (ROOT / 'scripts/migrations/20261014_income_account_down.sql').read_text()
            sql(up)
            assert sql("SELECT 'FLOW_SOLE_REQS'::payinmethod").strip() == b'FLOW_SOLE_REQS'
            assert original_rows() == before_rows, 'up changed existing row content/count'
            old_count = int(sql('SELECT count(*) FROM sber_incomes').strip())
            sber_count = int(sql("SELECT count(*) FROM sber_incomes WHERE account_key='sber'").strip())
            assert old_count == sber_count, 'old receipts did not default to sber'
            sql(up)  # idempotent startup
            sql(down)
            assert original_rows() == before_rows, 'down changed existing row content/count'
            after = {kind: snapshot(kind) for kind in initial}
            assert initial == after, 'schema/data hashes differ after up/down'
            sql(up)
            sql("INSERT INTO sber_incomes (uuid, operation_date, amount_rub, account_key) "
                "VALUES ('migration-flowsole-probe', '2026-10-14', 1, 'flow_sole')")
            guarded = subprocess.run([str(LIBPQ / 'psql'), *map(str, args), '-X',
                '-v', 'ON_ERROR_STOP=1', '-1'], input=down.encode(), capture_output=True, env=env)
            assert guarded.returncode and b'Cannot drop account_key' in guarded.stderr
            assert sql("SELECT account_key FROM sber_incomes WHERE uuid='migration-flowsole-probe'").strip() == b'flow_sole'
            print(f'UP/DOWN PASS: {old_count} sber_incomes rows, all original table row hashes and schema/data dumps identical')
            print('DOWN GUARD PASS: active Flow Sole receipt blocks rollback')
            print('Schema SHA256:', after['--schema-only'])
            print('Data SHA256:', after['--data-only'])
        finally:
            run('pg_ctl', '-D', work / 'db', '-m', 'fast', '-w', 'stop')


if __name__ == '__main__':
    main()
