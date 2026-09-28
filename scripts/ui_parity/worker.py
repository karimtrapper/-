"""Isolated Flask HTTP test client. JSON lines on stdin/stdout; no PII in stderr."""
import contextlib
import ctypes
import datetime as dt
import io
import hashlib
import hmac
import json
import os
import re
import signal
import sys
import threading
import traceback
from urllib.parse import parse_qs, urlsplit

if sys.platform != 'darwin':
    raise SystemExit('T18 worker requires the macOS network sandbox')
_sandbox_check = ctypes.CDLL('/usr/lib/libSystem.B.dylib').sandbox_check
_sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_sandbox_check.restype = ctypes.c_int
if _sandbox_check(os.getpid(), b'network-outbound', 0) != 1:
    raise SystemExit('T18 worker refused app import: OS network fence absent')

# libpq bypasses Python socket hooks: reject every non-private DB target before app import.
_db_url = urlsplit(os.environ.get('DATABASE_URL', ''))
_db_host = parse_qs(_db_url.query).get('host', [''])[0]
if (_db_url.scheme != 'postgresql' or _db_url.hostname is not None
        or not _db_host.startswith('/tmp/calccrm-t18-')
        or not _db_host.endswith('/socket') or not os.path.isdir(_db_host)):
    raise SystemExit('prod parity: DATABASE_URL must use the private local Unix socket')
sys.path.insert(0, os.getcwd())
# Background polling is outside parity; fake external calls stay synchronous.
original_thread_start = threading.Thread.start
threading.Thread.start = lambda self: None
import requests

calls = []
audit_key = bytes.fromhex(os.environ['PARITY_AUDIT_KEY'])


def fingerprint(value):
    packed = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str,
                        separators=(',', ':')).encode()
    return hmac.new(audit_key, packed, hashlib.sha256).hexdigest()


def fake_request(self, method, url, **kwargs):
    from urllib.parse import urlsplit
    p = urlsplit(url)
    calls.append({'function': 'requests.Session.request', 'method': method.upper(),
                  'host': p.hostname, 'path': p.path,
                  'payload_hmac': fingerprint({'url': url, 'kwargs': kwargs}),
                  'json_keys': sorted((kwargs.get('json') or {}).keys()) if isinstance(kwargs.get('json'), dict) else []})
    r = requests.Response()
    r.status_code = 200
    r._content = (b'{"ok":true,"success":true,"result":{"id":123456,"username":"t12_fake_bot"}}'
                  if p.path.endswith('/getMe') else
                  b'{"result":[]}' if 'crm.deal.list' in p.path else
                  b'{"ok":true,"success":true,"result":true,"data":[],"rates":{}}')
    r.headers['Content-Type'] = 'application/json'
    r.url = url
    return r


requests.sessions.Session.request = fake_request
_startup_out, _startup_err = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(_startup_out), contextlib.redirect_stderr(_startup_err):
    import app as mod
_startup_text = _startup_out.getvalue() + '\n' + _startup_err.getvalue()
_startup_issue_kinds = []
for line in _startup_text.splitlines():
    if 'CR-05 migration skipped' in line:
        _startup_issue_kinds.append('CR-05 duplicate wallet_operations')
    elif re.search(r'migration failed', line, re.I):
        _startup_issue_kinds.append('migration failed')
    elif re.search(r'migration skipped', line, re.I):
        _startup_issue_kinds.append('migration skipped')
    elif 'Traceback' in line:
        _startup_issue_kinds.append('startup traceback')
_startup_issue_count = len(_startup_issue_kinds)
threading.Thread.start = original_thread_start

# Freeze all route-level now()/utcnow() calls at a fixed audit instant.
class FrozenDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 9, 28, 1, 0, 0)
        return fixed.replace(tzinfo=tz) if tz else fixed

    @classmethod
    def utcnow(cls):
        return cls(2026, 9, 27, 22, 0, 0)


mod.datetime = FrozenDateTime
import time as _time
_time.time = lambda: 1790546400.0  # 2026-09-27 22:00:00 UTC
import secrets as _secrets
_nonce_counter = 0
def fake_nonce(length):
    global _nonce_counter
    _nonce_counter += 1
    return f't12-local-nonce-{_nonce_counter:04d}'
_secrets.token_urlsafe = fake_nonce
from sqlalchemy import DateTime as SQLDateTime
for table in mod.Base.metadata.tables.values():
    for column in table.columns:
        if isinstance(column.type, SQLDateTime):
            if column.default is not None and column.default.is_callable:
                column.default.arg = lambda context=None: FrozenDateTime.utcnow()
            if column.onupdate is not None and column.onupdate.is_callable:
                column.onupdate.arg = lambda context=None: FrozenDateTime.utcnow()
async def fake_all_rates():
    calls.append({'function': 'ExchangeRateProvider.get_all_rates', 'args': []})
    return {'usdt_thb': 32.5, 'rub_usdt': 80.0}

mod.ExchangeRateProvider.get_all_rates = fake_all_rates
mod._bitazza_calc_quote = lambda *args, **kwargs: {'effective': 32.4, 'raw_vwap': 32.5}

def fake_incoming(wallets, **kwargs):
    calls.append({'function': '_tronscan_fetch_incoming', 'wallet_count': len(wallets), 'kwargs': sorted(kwargs)})
    return [], [], []

def fake_outgoing(wallets, internal_wallet_addresses, **kwargs):
    calls.append({'function': '_tronscan_fetch_outgoing', 'wallet_count': len(wallets), 'kwargs': sorted(kwargs)})
    return ([], set()) if kwargs.get('with_errors') else []

mod._tronscan_fetch_incoming = fake_incoming
mod._tronscan_fetch_outgoing = fake_outgoing
mod.limiter.enabled = False
mod.app.config['TESTING'] = True


def safe_arg(arg):
    from sqlalchemy import inspect as sa_inspect
    if hasattr(arg, '__table__'):
        fields = {a.key: getattr(arg, a.key) for a in sa_inspect(arg).mapper.column_attrs}
        return {'model': type(arg).__name__, 'id': arg.id,
                'fields': sorted(fields), 'hmac': fingerprint(fields)}
    if isinstance(arg, (list, tuple)):
        return [safe_arg(x) for x in arg]
    if isinstance(arg, dict):
        return {'type': 'dict', 'fields': sorted(arg), 'hmac': fingerprint(arg)}
    return {'type': type(arg).__name__, 'hmac': fingerprint(arg)}


for name in ('sync_deals_to_gsheet', 'sync_realty_deal_to_gsheet',
             'sync_referrer_reward_to_gsheet', 'update_deal_in_gsheet',
             'mark_referrer_rewards_paid_in_gsheet', '_send_deal_telegram',
             'send_deal_completed_webhook', 'send_referrer_dm'):
    if hasattr(mod, name):
        def make_fake(func_name):
            def fake(*args, **kwargs):
                calls.append({'function': func_name, 'args': [safe_arg(a) for a in args],
                              'kwargs': {k: safe_arg(v) for k, v in sorted(kwargs.items())}})
                return {} if func_name == 'sync_deals_to_gsheet' else None
            return fake
        setattr(mod, name, make_fake(name))

client = mod.app.test_client()
public_client = mod.app.test_client()
ref_client = mod.app.test_client()
local_server = None


def handle(cmd):
    op = cmd['op']
    if op == 'auth':
        s = mod.SessionLocal()
        try:
            user = s.query(mod.AdminUser).filter_by(username='t12-parity').first()
            if not user:
                user = mod.AdminUser(username='t12-parity', display_name='T12', role='admin',
                                     telegram='t12local',
                                     password_hash=mod.bcrypt.hashpw(b't12-local-only', b'$2b$12$abcdefghijklmnopqrstuu').decode())
                s.add(user)
                s.commit()
            uid = user.id
        finally:
            s.close()
        r = client.post('/api/auth/login', json={'username': 't12-parity', 'password': 't12-local-only'})
        s2 = mod.SessionLocal()
        try:
            stored_disabled = getattr(s2.get(mod.AdminUser, uid), 'login_disabled', None)
        finally:
            s2.close()
        return {'status': r.status_code, 'id': uid, 'success': (r.json or {}).get('success'),
                'stored_disabled': stored_disabled}
    if op == 'request':
        kwargs = {'json': cmd.get('json')} if 'json' in cmd else {}
        if cmd.get('headers'):
            kwargs['headers'] = cmd['headers']
        def timeout_handler(signum, frame):
            raise TimeoutError('request timeout')
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, 5)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                selected = {'admin': client, 'public': public_client, 'ref': ref_client}[cmd.get('client', 'admin')]
                r = selected.open(cmd['path'], method=cmd.get('method', 'GET'), **kwargs)
        except TimeoutError:
            return {'status': 598, 'body': {'error': 'local_request_timeout'}}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
        body = r.get_json(silent=True)
        return {'status': r.status_code, 'body': body if body is not None else {'content_type': r.content_type, 'size': len(r.data)}}
    if op == 'ids':
        s = mod.SessionLocal()
        try:
            public_ref = s.query(mod.Referrer.token).filter(mod.Referrer.active.is_(True),
                mod.Referrer.auth_mode != 'telegram').order_by(mod.Referrer.id).first()
            return {'deals': [x[0] for x in s.query(mod.Deal.id).order_by(mod.Deal.id)],
                    'referrers': [(x.id, x.token) for x in s.query(mod.Referrer).order_by(mod.Referrer.id)],
                    'partners': [(x.id, x.token) for x in s.query(mod.Partner).order_by(mod.Partner.id)],
                    'public_ref_token': public_ref[0] if public_ref else None,
                    'kyc_tokens': [x[0] for x in s.query(mod.KycRequest.token).order_by(mod.KycRequest.id).limit(5)]}
        finally:
            s.close()
    if op == 'deal_kinds':
        s = mod.SessionLocal()
        try:
            return [(kind, ident) for kind, ident in s.query(mod.Deal.deal_kind, mod.Deal.id)
                    .order_by(mod.Deal.id) if kind in ('exchange', 'mf_realty', 'mf_freehold')]
        finally:
            s.close()
    if op == 'serve':
        global local_server
        from werkzeug.serving import make_server
        port = int(cmd['port'])
        if local_server is None:
            local_server = make_server('127.0.0.1', port, mod.app, threaded=True)
            threading.Thread(target=local_server.serve_forever, daemon=True).start()
        return {'port': port}
    if op == 'seed_referrer':
        s = mod.SessionLocal()
        try:
            ref = s.query(mod.Referrer).filter_by(code='T12LOCAL').first()
            if ref is None:
                ref = mod.Referrer(name='T12 LOCAL ONLY', code='T12LOCAL', token='t12-local-ref-token',
                                   telegram='t12ref', auth_mode='telegram', active=True, is_test=True)
                s.add(ref)
                s.commit()
            return {'id': ref.id, 'token': ref.token}
        finally:
            s.close()
    if op == 'startup':
        return {'issue_count': _startup_issue_count, 'issue_kinds': sorted(set(_startup_issue_kinds))}
    if op == 'calls':
        out = list(calls)
        if cmd.get('clear'):
            calls.clear()
        return out
    if op == 'mode':
        import socket, sitecustomize
        egress = sys.modules.get('stand_egress')
        notify = sys.modules.get('stand_notify')
        return {'stand_mode': mod.STAND_MODE,
                'fence_intact': socket.socket.connect is sitecustomize._connect,
                'stand_egress_installed': bool(getattr(egress, '_installed', False)),
                'stand_notify_active': bool(getattr(notify, '_app', None))}
    raise ValueError('unknown op')


for line in sys.stdin:
    try:
        result = {'ok': True, 'result': handle(json.loads(line))}
    except Exception as exc:
        result = {'ok': False, 'error_type': type(exc).__name__,
                  'traceback_functions': [f.name for f in traceback.extract_tb(exc.__traceback__)[-5:]]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + '\n')
    sys.stdout.flush()
