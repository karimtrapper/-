"""Run the T24 PostgreSQL transaction proof in a private T19-style OS fence."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from run_fenced_pytest import PORT_COUNT, choose_ports, profile_text


ROOT = Path(__file__).resolve().parents[1]
BIN = Path('/opt/homebrew/opt/postgresql@17/bin')


def main():
    if sys.version_info[:2] != (3, 11) or not shutil.which('sandbox-exec'):
        raise RuntimeError('Python 3.11 and sandbox-exec required')
    if not all((BIN / name).exists() for name in ('initdb', 'pg_ctl', 'postgres')):
        raise RuntimeError('local PostgreSQL 17 binaries required')
    with (tempfile.TemporaryDirectory(prefix='calccrm-t26-pg-', dir='/tmp') as work,
          tempfile.TemporaryDirectory(prefix='calccrm-t19-pg-t26-', dir='/tmp') as socket_work):
        own = Path(work)
        sock = Path(socket_work)
        data = own / 'data'
        start = choose_ports()
        port = start
        profile = own / 'network.sb'
        profile.write_text(profile_text(range(start, start + PORT_COUNT), work))
        ledger = own / 'attempts.jsonl'
        ledger.touch(mode=0o600)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ}
        env.update(HOME=work, TMPDIR=work, LC_ALL='C', STAND_MODE='1',
                   SECRET_KEY='t26-synthetic-only', STAND_PASSWORD='t26-synthetic-only',
                   LOCAL_NO_AUTH='0', PYTHON_DOTENV_DISABLED='1',
                   DATABASE_URL=f'postgresql://t26_pg@/postgres?host={sock}',
                   PYTHONPATH=str(ROOT / 'tests' / 'network_bootstrap') + os.pathsep + str(ROOT),
                   CALCCRM_FENCE_LEDGER=str(ledger), CALCCRM_FENCE_PORT_START=str(start),
                   T26_HTTP_PORT=str(port), T26_FOREIGN_PORT=str(start + PORT_COUNT),
                   T26_PG_SOCKET=str(sock / '.s.PGSQL.5432'))
        for name in ('REESTR_SYNC_ENABLED', 'PAYIN_ADDR_BACKFILL',
                     'TRONSCAN_WARM_ENABLED', 'PAYMENT_POLL_ENABLED',
                     'KYC_RETENTION_ENABLED', 'STAND_TRANSFER_POLL_ENABLED',
                     'STAND_SBER_MIRROR_ENABLED', 'STAND_TG_UPDATES_ENABLED'):
            env[name] = '0'
        sandbox = shutil.which('sandbox-exec')
        def run(args, *, bootstrap=True):
            child_env = env if bootstrap else {k: v for k, v in env.items()
                                               if k not in ('PYTHONPATH', 'CALCCRM_FENCE_LEDGER')}
            result = subprocess.run([sandbox, '-f', str(profile), *map(str, args)],
                                    cwd=ROOT, env=child_env, capture_output=True,
                                    text=True, timeout=120)
            print(result.stdout, end='', flush=True)
            if result.returncode:
                print(result.stderr[-6000:], file=sys.stderr)
                pg_log = own / 'postgres.log'
                if pg_log.exists():
                    print(pg_log.read_text()[-6000:], file=sys.stderr)
                raise RuntimeError(f'proof subprocess failed: {args[0]} exit={result.returncode}')
        run([BIN / 'initdb', '-D', data, '-A', 'trust', '-U', 't26_pg', '-E', 'UTF8',
             '--no-instructions'], bootstrap=False)
        server = [BIN / 'pg_ctl', '-D', data]
        run([*server, '-o', f'-k {sock} -h ""', '-l', own / 'postgres.log', 'start'],
            bootstrap=False)
        try:
            run([sys.executable, '-I', '-S', ROOT / 'scripts' / 't24_os_probe.py'],
                bootstrap=False)
            run([sys.executable, ROOT / 'scripts' / 't26_testnet_probe.py'])
            run([sys.executable, ROOT / 'scripts' / 't24_pg_proof.py'])
        finally:
            run([*server, '-m', 'immediate', 'stop'], bootstrap=False)
        attempts = [json.loads(line) for line in ledger.read_text().splitlines()]
        unexpected = [entry for entry in attempts if not entry['expected']]
        report_dir = Path('/tmp/calccrm-t19-fence-reports')
        report_dir.mkdir(mode=0o700, exist_ok=True)
        report = report_dir / (datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
                               + f'-t26-pg-{os.getpid()}.json')
        report.write_text(json.dumps({'python': sys.version.split()[0],
                                      'port_pool': [start, start + PORT_COUNT - 1],
                                      'pg_socket': 'own private Unix socket',
                                      'attempts': attempts,
                                      'native_denied': 3,
                                      'native_denial_proof': 't24_os_probe.py passed'}, indent=2))
        report.chmod(0o600)
        print(f'T26_PG_FENCE attempts={len(attempts)} unexpected={len(unexpected)} report={report}')
        return 1 if unexpected else 0


if __name__ == '__main__':
    sys.exit(main())
