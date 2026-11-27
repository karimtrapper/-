"""Small T12-derived helpers for the T18 UI runner; no standalone suite."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys


HERE = Path(__file__).resolve().parent
FIXED_SECRET = 't18-parity-local-session-key-only'
FILTERED = (b'SET transaction_timeout =', b'\\restrict ', b'\\unrestrict ')


def run_cmd(argv, **kwargs):
    p = subprocess.run([str(a) for a in argv], stdout=subprocess.DEVNULL, **kwargs)
    if p.returncode:
        raise RuntimeError(f'local command failed: {Path(str(argv[0])).name} (exit {p.returncode})')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def sha(worktree):
    return subprocess.check_output(['git', '-C', str(worktree), 'rev-parse', 'HEAD'], text=True).strip()


def tracked_clean(worktree):
    return not subprocess.check_output(['git', '-C', str(worktree), 'status', '--porcelain',
                                        '--untracked-files=no'], text=True).strip()


class Worker:
    def __init__(self, worktree, db_url, mode, private_dir, label, audit_key,
                 synthetic=False):
        if not worktree.joinpath('app.py').is_file():
            raise ValueError('worktree has no app.py')
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'TMPDIR') if k in os.environ}
        env.update(PYTHONHASHSEED='0', PYTHONPATH=str(HERE), DATABASE_URL=db_url, SECRET_KEY=FIXED_SECRET,
                   PARITY_AUDIT_KEY=audit_key, REF_LK_WEBHOOK_SECRET='t18-fake-webhook-secret',
                   PYTHON_DOTENV_DISABLED='1', REESTR_SYNC_ENABLED='0', TRONSCAN_WARM_ENABLED='0',
                   CHANNEL_TRAFFIC_ENABLED='0', KYC_RETENTION_ENABLED='0', PAYMENT_LINK_POLL_ENABLED='0',
                   CRM_WEBHOOK_URL='http://127.0.0.1:9/webhook', TELEGRAM_BOT_TOKEN='123456:fake-local-token',
                   TELEGRAM_CHAT_ID='-1000000000000', DOVERKA_API_KEY='fake-local-key',
                   BITRIX_WEBHOOK='http://127.0.0.1:9/bitrix/', WL_BOT_URL='http://127.0.0.1:9/wl',
                   SERVICE_API_KEY='fake-local-service', SERVICE_API_KEY_RO='fake-local-ro',
                   SERVICE_API_KEY_RO_FINANCE='fake-local-finance', SERVICE_API_KEY_RO_LEADS='fake-local-leads',
                   STAND_PASSWORD='fake-stand-password', STAND_TG_TOKEN='123456:fake-stand-token',
                   STAND_TG_CHAT='-1000000000000', STAND_BASE_URL='http://stand.invalid',
                   STAND_PROD_RO_KEY='fake-stand-readonly', PUBLIC_BASE_URL='http://127.0.0.1:9')
        if mode is not None:
            env['STAND_MODE'] = mode
        if synthetic:
            env['PARITY_SYNTHETIC'] = '1'
        self.log = open(private_dir / f'{label}.log', 'w', opener=lambda path, flags: os.open(path, flags, 0o600))
        self.p = subprocess.Popen([sys.executable, '-u', str(HERE / 'worker.py')], cwd=worktree,
                                  env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.log, text=True, bufsize=1)

    def ask(self, **cmd):
        if self.p.poll() is not None:
            raise RuntimeError(f'worker exited {self.p.returncode}')
        self.p.stdin.write(json.dumps(cmd) + '\n')
        self.p.stdin.flush()
        ready, _, _ = select.select([self.p.stdout], [], [], 12)
        if not ready:
            self.p.kill(); self.p.wait()
            raise RuntimeError('worker request deadline')
        answer = None
        for _ in range(40):
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError('worker ended without response')
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue  # Stand startup can log to stdout; never echo private data.
            if isinstance(parsed, dict) and 'ok' in parsed:
                answer = parsed
                break
        if answer is None:
            raise RuntimeError('worker emitted no protocol response')
        if not answer['ok']:
            raise RuntimeError(f"worker {answer['error_type']} at {answer['traceback_functions']}")
        return answer['result']

    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill(); self.p.wait()
        self.log.close()
