"""Focused T29 pytest: preimport OS/Python proofs and explicit dotenv neutralization."""
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
BOOTSTRAP = ROOT / 'tests' / 'network_bootstrap'
NATIVE = r'''
import errno, socket, subprocess, sys
own, foreign = map(int, sys.argv[1:])
server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', own)); server.listen(1)
with socket.create_connection(('127.0.0.1', own), timeout=2):
    peer, _ = server.accept(); peer.close()
server.close()
for address in (('127.0.0.1', foreign), ('192.0.2.1', 443)):
    sock = socket.socket()
    try: sock.connect(address)
    except OSError as exc: assert exc.errno == errno.EPERM, exc.errno
    else: raise AssertionError('OS network denial missing')
    finally: sock.close()
child = subprocess.run([sys.executable, '-I', '-S', '-c',
    'import errno,socket,sys\ns=socket.socket()\ntry: s.connect(("127.0.0.1",int(sys.argv[1])))\nexcept OSError as e: assert e.errno==errno.EPERM,e.errno\nelse: raise AssertionError("child network denial missing")',
    str(foreign)], capture_output=True, text=True)
assert child.returncode == 0, child.stderr
print('T29_NATIVE own_positive=1 foreign_loopback_EPERM=1 external_EPERM=1 child_EPERM=1')
'''
PYTHON = r'''
import os, socket
from pathlib import Path
import dotenv
from network_fence import expect_blocked
assert os.environ['CALCCRM_FENCE_ACTIVE'] == '1'
Path(os.environ['T29_DOTENV_PROBE']).write_text('T29_DOTENV_LEAK=forbidden\n')
assert dotenv.load_dotenv(os.environ['T29_DOTENV_PROBE']) is False
assert 'T29_DOTENV_LEAK' not in os.environ
own, foreign = int(os.environ['T29_OWN_PORT']), int(os.environ['T29_FOREIGN_PORT'])
server = socket.socket(); server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', own)); server.listen(1)
with socket.create_connection(('127.0.0.1', own), timeout=2):
    peer, _ = server.accept(); peer.close()
server.close()
with expect_blocked():
    try: socket.create_connection(('127.0.0.1', foreign), timeout=2)
    except OSError: pass
    else: raise AssertionError('Python network denial missing')
print('T29_TEST_NET own_positive=1 foreign_blocked=1 dotenv_disabled=1')
'''


def main():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError('Python 3.11 required')
    sandbox = shutil.which('sandbox-exec')
    if not sandbox:
        raise RuntimeError('sandbox-exec required')
    with tempfile.TemporaryDirectory(prefix='calccrm-t29-fence-', dir='/tmp') as work:
        boot = Path(work) / 'bootstrap'
        boot.mkdir()
        (boot / 'sitecustomize.py').write_text(
            'import os, network_fence, dotenv\n'
            'network_fence.install()\n'
            'dotenv.load_dotenv = lambda *args, **kwargs: False\n'
            'os.environ["CALCCRM_FENCE_BOOTSTRAP"] = os.path.dirname(__file__)\n')
        start = choose_ports()
        profile = Path(work) / 'network.sb'
        profile.write_text(profile_text(range(start, start + PORT_COUNT), work))
        ledger = Path(work) / 'attempts.jsonl'
        ledger.touch(mode=0o600)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ')
               if key in os.environ}
        env.update(HOME=work, TMPDIR=work, PYTHON_DOTENV_DISABLED='1',
                   DATABASE_URL=f'sqlite:///{work}/test.db',
                   CALCCRM_FENCE_LEDGER=str(ledger),
                   CALCCRM_FENCE_PORT_START=str(start),
                   T29_OWN_PORT=str(start), T29_FOREIGN_PORT=str(start + PORT_COUNT),
                   T29_DOTENV_PROBE=str(Path(work) / 'synthetic.env'),
                   PYTHONPATH=os.pathsep.join((str(boot), str(BOOTSTRAP), str(ROOT))))
        for name in ('REESTR_SYNC_ENABLED', 'PAYIN_ADDR_BACKFILL',
                     'TRONSCAN_WARM_ENABLED', 'PAYMENT_POLL_ENABLED',
                     'KYC_RETENTION_ENABLED', 'STAND_TRANSFER_POLL_ENABLED',
                     'STAND_SBER_MIRROR_ENABLED', 'STAND_TG_UPDATES_ENABLED'):
            env[name] = '0'
        def run(args, *, native=False):
            command = [sandbox, '-f', str(profile), sys.executable]
            if native:
                command += ['-I', '-S']
            command += args
            result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                                    capture_output=True, timeout=120)
            print(result.stdout, end='', flush=True)
            if result.returncode:
                print(result.stderr[-5000:], file=sys.stderr)
            return result.returncode
        print(f'T29_FENCED_RUN python={sys.version.split()[0]} pool={start}-{start+PORT_COUNT-1}', flush=True)
        if run(['-c', NATIVE, str(start), str(start + PORT_COUNT)], native=True):
            return 2
        if run(['-c', PYTHON]):
            return 2
        result = run(['-m', 'pytest', *sys.argv[1:]])
        attempts = [json.loads(line) for line in ledger.read_text().splitlines()]
        unexpected = [entry for entry in attempts if not entry['expected']]
        reports = Path('/tmp/calccrm-t29-fence-reports')
        reports.mkdir(mode=0o700, exist_ok=True)
        report = reports / (datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
                            + f'-{os.getpid()}.json')
        report.write_text(json.dumps({'python': sys.version.split()[0],
                                      'port_pool': [start, start + PORT_COUNT - 1],
                                      'native_denied': 3, 'pytest_exit': result,
                                      'attempts': attempts}, indent=2))
        report.chmod(0o600)
        print(f'T29_NETWORK_FENCE attempts={len(attempts)} unexpected={len(unexpected)} report={report}')
        return result or (1 if unexpected else 0)


if __name__ == '__main__':
    sys.exit(main())
