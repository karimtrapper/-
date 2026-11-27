"""Run T31 browser trace with a clean environment and OS network fence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from run_fenced_pytest import choose_ports, profile_text

ROOT = Path(__file__).resolve().parents[1]

if sys.version_info[:2] != (3, 11) or not shutil.which('sandbox-exec'):
    raise SystemExit('Python 3.11 and sandbox-exec required')
with tempfile.TemporaryDirectory(prefix='calccrm-t31-') as work:
    port = choose_ports()
    profile = Path(work) / 'network.sb'
    profile.write_text(profile_text([port], work))
    ledger = Path(work) / 'attempts.jsonl'
    ledger.touch(mode=0o600)
    bootstrap = Path(work) / 'bootstrap'
    bootstrap.mkdir()
    (bootstrap / 'sitecustomize.py').write_text(
        'import os, network_fence, dotenv\n'
        'network_fence.install()\n'
        'dotenv.load_dotenv = lambda *args, **kwargs: False\n'
        'os.environ["CALCCRM_FENCE_BOOTSTRAP"] = os.path.dirname(__file__)\n')
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TZ') if k in os.environ}
    env.update(HOME=work, TMPDIR=work, PYTHON_DOTENV_DISABLED='1', STAND_MODE='1',
               SECRET_KEY='synthetic-t31', DATABASE_URL=f'sqlite:///{work}/test.db',
               PLAYWRIGHT_BROWSERS_PATH=str(Path.home() / 'Library/Caches/ms-playwright'),
               T31_PORT=str(port), CALCCRM_FENCE_LEDGER=str(ledger),
               CALCCRM_FENCE_PORT_START=str(port),
               T31_TRACE_OUT='/tmp/calccrm-t31-click-trace.json',
               PYTHONPATH=os.pathsep.join((str(bootstrap), str(ROOT / 'tests/network_bootstrap'), str(ROOT))))
    for name in ('REESTR_SYNC_ENABLED', 'PAYIN_ADDR_BACKFILL', 'TRONSCAN_WARM_ENABLED',
                 'PAYMENT_POLL_ENABLED', 'KYC_RETENTION_ENABLED', 'STAND_SBER_MIRROR_ENABLED',
                 'STAND_TG_UPDATES_ENABLED', 'STAND_TRANSFER_POLL_ENABLED'):
        env[name] = '0'
    native = subprocess.run([shutil.which('sandbox-exec'), '-f', str(profile),
        sys.executable, '-I', '-S', '-c', '''import errno,socket,sys
port=int(sys.argv[1]); server=socket.socket(); server.bind(('127.0.0.1',port)); server.listen(1)
peer=socket.create_connection(('127.0.0.1',port)); peer.close(); server.accept()[0].close(); server.close()
for address in (('127.0.0.1',port+1),('192.0.2.1',443)):
 sock=socket.socket()
 try: sock.connect(address)
 except OSError as exc: assert exc.errno==errno.EPERM,exc.errno
 else: raise AssertionError('OS network denial missing')
 finally: sock.close()
print('T31_OS_FENCE own_loopback=allowed foreign_loopback=EPERM external=EPERM')''',
        str(port)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=20)
    if native.returncode:
        print(native.stderr, file=sys.stderr)
        raise SystemExit(native.returncode)
    print(native.stdout, end='')
    command = [shutil.which('sandbox-exec'), '-f', str(profile), sys.executable,
               str(ROOT / 'tests/t31_click_trace.py')]
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True,
                            timeout=90)
    print(result.stdout, end='')
    if result.returncode:
        print(result.stderr[-6000:], file=sys.stderr)
    js_results = []
    if not result.returncode:
        node = shutil.which('node')
        if not node:
            raise SystemExit('node required for focused JS regressions')
        for name in ('test_stand_incoming.js', 'test_stand_freehold.js',
                     'test_stand_manual_origin_queue.js'):
            path = ROOT / 'tests' / name
            js = subprocess.run([shutil.which('sandbox-exec'), '-f', str(profile),
                                 node, str(path)], cwd=ROOT, env=env, text=True,
                                capture_output=True, timeout=30)
            js_results.append({'name': name, 'exit': js.returncode})
            if js.returncode:
                print(js.stdout[-2000:], js.stderr[-2000:], file=sys.stderr)
            else:
                print(f'T31_JS {name} passed')
    attempts = [json.loads(s) for s in ledger.read_text().splitlines()]
    unexpected = [x for x in attempts if not x['expected']]
    report = Path('/tmp/calccrm-t31-fence-report.json')
    report.write_text(json.dumps({'python': sys.version.split()[0], 'native': native.stdout.strip(),
                                  'exit': result.returncode, 'js': js_results,
                                  'attempts': attempts}, indent=2))
    report.chmod(0o600)
    print(f'T31_FENCE unexpected={len(unexpected)} attempts={len(attempts)} exit={result.returncode}')
    print(f'T31_FENCE_REPORT {report}')
    raise SystemExit(result.returncode or bool(unexpected) or
                     any(row['exit'] for row in js_results))
