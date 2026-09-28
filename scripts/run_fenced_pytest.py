"""Run pytest with an early Python fence and fail on every unapproved attempt."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import socket
import random
import datetime


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / 'tests' / 'network_bootstrap'
PORT_COUNT = 64


def profile_text(ports, work):
    lines = ['(version 1)', '(allow default)', '(deny network*)']
    for port in ports:
        lines.extend((f'(allow network-bind (local tcp "localhost:{port}"))',
                      f'(allow network-inbound (local tcp "localhost:{port}"))',
                      f'(allow network-outbound (remote ip "localhost:{port}"))'))
    for prefix in ('calccrm-t24-pg-',):
        lines.extend((f'(allow network-bind (regex #"^/private/tmp/{prefix}"))',
                      f'(allow network-outbound (regex #"^/private/tmp/{prefix}"))'))
    own_tmp = str(Path(work).resolve()).replace('/tmp/', '/private/tmp/')
    lines.extend((f'(allow network-bind (regex #"^{own_tmp}/"))',
                  f'(allow network-outbound (regex #"^{own_tmp}/"))'))
    return '\n'.join(lines) + '\n'


def choose_ports():
    for _ in range(30):
        start = random.SystemRandom().randrange(20000, 50000 - PORT_COUNT)
        try:
            for port in range(start, start + PORT_COUNT):
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', port))
        except OSError:
            continue
        return start
    raise RuntimeError('Could not reserve a free local TCP port pool')


def main():
    if sys.version_info[:2] != (3, 11):
        print('Python 3.11 required; run with the test venv interpreter', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='calccrm-fence-') as work:
        sandbox = shutil.which('sandbox-exec')
        if not sandbox:
            print('sandbox-exec is required for the native/subprocess network barrier', file=sys.stderr)
            return 2
        port_start = choose_ports()
        profile = Path(work) / 'network.sb'
        profile.write_text(profile_text(range(port_start, port_start + PORT_COUNT), work))
        ledger = Path(work) / 'attempts.jsonl'
        ledger.touch(mode=0o600)
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ')
               if key in os.environ}
        env.update(HOME=work, TMPDIR=work, CALCCRM_FENCE_LEDGER=str(ledger),
                   CALCCRM_FENCE_PORT_START=str(port_start),
                   PYTHON_DOTENV_DISABLED='1', DATABASE_URL=f'sqlite:///{work}/test.db')
        env['PYTHONPATH'] = str(BOOTSTRAP) + os.pathsep + str(ROOT)
        verify = sys.argv[1:] == ['--verify-fail-closed']
        plain_refusal = sys.argv[1:] == ['--verify-plain-refusal']
        if verify:
            probe = '''import socket, subprocess, sys, threading
def swallowed():
    try: socket.socket().connect(('192.0.2.1', 443))
    except OSError: pass
thread = threading.Thread(target=swallowed); thread.start(); thread.join()
subprocess.run([sys.executable, '-c', "import socket;\\ntry: socket.getaddrinfo('external.invalid', 443)\\nexcept OSError: pass"], check=True)
print('probe_child_exit_zero')
'''
            command = [sandbox, '-f', str(profile), sys.executable, '-c', probe]
        elif plain_refusal:
            env.pop('CALCCRM_FENCE_LEDGER')
            env['PYTHONPATH'] = str(ROOT)
            command = [sandbox, '-f', str(profile), sys.executable, '-m', 'pytest',
                       '--collect-only', '-q', 'tests/test_network_fence.py']
        else:
            command = [sandbox, '-f', str(profile), sys.executable, '-m', 'pytest', *sys.argv[1:]]
        print(f'FENCED_RUN python={sys.version.split()[0]} port_pool={port_start}-{port_start + PORT_COUNT - 1}', flush=True)
        result = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=plain_refusal, text=plain_refusal)
        if plain_refusal:
            if result.returncode and 'Tests require scripts/run_fenced_pytest.py' in (result.stdout + result.stderr):
                print('PLAIN_PYTEST_REFUSED before app import')
                return 0
            print('Plain pytest was not safely refused', file=sys.stderr)
            return 1
        attempts = [json.loads(line) for line in ledger.read_text().splitlines()]
        unexpected = [entry for entry in attempts if not entry['expected']]
        report_dir = Path('/tmp/calccrm-t24-fence-reports')
        report_dir.mkdir(mode=0o700, exist_ok=True)
        report = report_dir / (datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + f'-{os.getpid()}.json')
        report.write_text(json.dumps({'python': sys.version.split()[0],
                                      'mode': 'verify-fail-closed' if verify else 'pytest',
                                      'port_pool': [port_start, port_start + PORT_COUNT - 1],
                                      'pytest_exit': result.returncode,
                                      'attempts': attempts}, indent=2))
        report.chmod(0o600)
        print(f'NETWORK_FENCE attempts={len(attempts)} unexpected={len(unexpected)} report={report}')
        for entry in unexpected:
            print('NETWORK_FENCE_BLOCKED', json.dumps(entry, sort_keys=True))
        return result.returncode or (1 if unexpected else 0)


if __name__ == '__main__':
    sys.exit(main())
