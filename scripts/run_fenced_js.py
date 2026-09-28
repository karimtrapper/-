"""Run every repository JS test inside an exact-port macOS network sandbox."""
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


def main():
    sandbox = shutil.which('sandbox-exec')
    node = shutil.which('node')
    if not sandbox or not node:
        print('sandbox-exec and node are required; refusing unprotected JS tests', file=sys.stderr)
        return 2
    paths = sorted((ROOT / 'tests').glob('test_*.js'))
    with tempfile.TemporaryDirectory(prefix='calccrm-fence-js-') as work:
        start = choose_ports()
        profile = Path(work) / 'network.sb'
        profile.write_text(profile_text(range(start, start + PORT_COUNT), work))
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TZ')
               if key in os.environ}
        env.update(HOME=work, TMPDIR=work, PYTHON_DOTENV_DISABLED='1')
        results = []
        for path in paths:
            print('JS_TEST', path.name, flush=True)
            result = subprocess.run([sandbox, '-f', str(profile), node, str(path)],
                                    cwd=ROOT, env=env, capture_output=True, text=True,
                                    timeout=90)
            results.append({'test': path.name, 'exit': result.returncode})
            if result.returncode:
                print(result.stdout[-2000:], result.stderr[-2000:], file=sys.stderr)
        report_dir = Path('/tmp/calccrm-t19-fence-reports')
        report_dir.mkdir(mode=0o700, exist_ok=True)
        report = report_dir / (datetime.datetime.now().strftime('%Y%m%dT%H%M%S') + f'-js-{os.getpid()}.json')
        report.write_text(json.dumps({'node': subprocess.check_output([node, '--version'], text=True).strip(),
                                      'port_pool': [start, start + PORT_COUNT - 1],
                                      'results': results, 'native_attempt_audit': 'unavailable'}, indent=2))
        report.chmod(0o600)
        passed = sum(row['exit'] == 0 for row in results)
        print(f'JS_FENCED_RESULT passed={passed} failed={len(results)-passed} report={report}')
        return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
