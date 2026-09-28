"""Closed LK transport checks in fresh processes with the egress guard installed."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(source, mode='1'):
    env = {'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT),
           'STAND_LK_BOT_TOKEN': '555:fake', 'STAND_LK_BOT_ID': '555'}
    if mode is not None:
        env['STAND_MODE'] = mode
    process = subprocess.run([sys.executable, '-c', textwrap.dedent(source)],
                             env=env, cwd=ROOT, capture_output=True, text=True,
                             timeout=20)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout.splitlines()[-1])


def test_same_thread_and_other_thread_cannot_borrow_lk_post_window():
    result = _run('''
        import json, socket, threading, requests
        from types import SimpleNamespace
        import stand_egress as e
        e.install()
        e.set_policy(lambda c, r, op: c == 'telegram_lk' and r == 42 and op == 'sendMessage')
        calls = []
        e._orig_getaddrinfo = lambda *args: calls.append(('dns', args)) or []
        e._orig_connect = lambda *args: calls.append(('connect', args))
        seen = {}
        def probe():
            try:
                socket.getaddrinfo('api.telegram.org', 443)
                return 'allowed'
            except socket.gaierror:
                return 'blocked'
        def post(self, url, **kw):
            seen['same_dns'] = probe()
            s = socket.socket()
            try:
                s.connect(('127.0.0.1', 443))
                seen['same_connect'] = 'allowed'
            except ConnectionRefusedError:
                seen['same_connect'] = 'blocked'
            finally:
                s.close()
            t = threading.Thread(target=lambda: seen.update(other_dns=probe()))
            t.start(); t.join()
            seen['session_safe'] = not self.trust_env and kw['proxies'] == {} and kw['allow_redirects'] is False
            return SimpleNamespace(status_code=200, json=lambda: {'ok': True, 'result': {
                'from': {'id': 555, 'username': 'grusha_lk_bot', 'is_bot': True},
                'chat': {'id': 42, 'type': 'private'}}})
        requests.Session.post = post
        seen['ok'] = e.lk_call({'chat_id': 42, 'text': 'fake'})['ok']
        seen['after_dns'] = probe()
        seen['orig_calls'] = len(calls)
        print(json.dumps(seen))
    ''')
    assert result == {'same_dns': 'blocked', 'same_connect': 'blocked',
                      'other_dns': 'blocked', 'after_dns': 'blocked',
                      'session_safe': True, 'ok': True, 'orig_calls': 0}


def test_own_connection_to_fake_server_succeeds_and_closes_context():
    result = _run('''
        import http.server, json, threading, socket
        import stand_egress as e
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.hits.append((self.path, body['chat_id']))
                response = {'ok': True, 'result': {'from': {
                    'id': 555, 'username': 'grusha_lk_bot', 'is_bot': True},
                    'chat': {'id': body['chat_id'], 'type': 'private'}}}
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        server.hits = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        e.install()
        e.set_policy(lambda c, r, op: c == 'telegram_lk' and r == 42 and op == 'sendMessage')
        result = e.lk_call({'chat_id': 42, 'text': 'fake'},
                           _base_url='http://127.0.0.1:' + str(server.server_port))
        try:
            socket.create_connection(('127.0.0.1', server.server_port), timeout=0.1)
            direct = 'allowed'
        except ConnectionRefusedError:
            direct = 'blocked'
        print(json.dumps({'ok': result['ok'], 'hits': server.hits,
                          'direct': direct, 'active': getattr(e._lk_ctx, 'active', False),
                          'pending': getattr(e._lk_ctx, 'pending_host', None)}))
        server.shutdown()
    ''')
    assert result == {'ok': True, 'hits': [['/bot555:fake/sendMessage', 42]],
                      'direct': 'blocked', 'active': False, 'pending': None}


def test_redirect_and_environment_proxy_do_not_open_second_request():
    result = _run('''
        import http.server, json, os, threading
        import stand_egress as e
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.hits.append(self.path)
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(302)
                self.send_header('Location', '/redirected')
                self.end_headers()
            def do_GET(self):
                self.server.hits.append(self.path)
                self.send_response(200)
                self.end_headers()
            def log_message(self, *args): pass
        server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
        server.hits = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        os.environ['HTTP_PROXY'] = 'http://127.0.0.1:9999'
        os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:9999'
        e.install()
        e.set_policy(lambda c, r, op: c == 'telegram_lk' and r == 42 and op == 'sendMessage')
        response = e.lk_call({'chat_id': 42, 'text': 'fake'},
                             _base_url='http://127.0.0.1:' + str(server.server_port))
        print(json.dumps({'error': response['error'], 'hits': server.hits,
                          'active': getattr(e._lk_ctx, 'active', False)}))
        server.shutdown()
    ''')
    assert result == {'error': 'tg_bad_response',
                      'hits': ['/bot555:fake/sendMessage'], 'active': False}


def test_invalid_origins_rejected_before_session_and_error_closes_context():
    result = _run('''
        import json, requests, socket
        import stand_egress as e
        e.install()
        e.set_policy(lambda *args: True)
        hits = []
        def post(self, url, **kwargs):
            hits.append(url)
            raise RuntimeError('secret in transport failure')
        requests.Session.post = post
        bad = ['ftp://127.0.0.1:80', 'http://localhost:80',
               'http://[::1]:80', 'http://127.0.0.1', 'http://127.0.0.1:0',
               'http://127.0.0.1:65536', 'http://user@127.0.0.1:80',
               'http://127.0.0.1:80/', 'http://127.0.0.1:80?q=1',
               'http://127.0.0.1:80#x', 'http://evil.invalid:80', None, 42]
        errors = [e.lk_call({'chat_id': 42}, _base_url=b)['error'] for b in bad[:-2]]
        errors.append(e.lk_call({'chat_id': 42}, _base_url=42)['error'])
        failed = e.lk_call({'chat_id': 42})
        try:
            socket.getaddrinfo('api.telegram.org', 443)
            direct = 'allowed'
        except socket.gaierror:
            direct = 'blocked'
        print(json.dumps({'errors': errors, 'failed': failed, 'hits': len(hits),
                          'direct': direct, 'active': getattr(e._lk_ctx, 'active', False),
                          'pending': getattr(e._lk_ctx, 'pending_host', None)}))
    ''')
    assert result['errors'] == ['invalid_base_url'] * 12
    assert result['failed'] == {'ok': False, 'error': 'tg_network_error'}
    assert result['hits'] == 1
    assert result['direct'] == 'blocked'
    assert result['active'] is False and result['pending'] is None


def test_prod_mode_does_not_install_guard():
    for mode in (None, '0'):
        result = _run('''
            import json, socket, stand_egress as e
            before = socket.getaddrinfo
            e.install()
            print(json.dumps({'installed': e._installed,
                              'same_socket': before is socket.getaddrinfo}))
        ''', mode=mode)
        assert result == {'installed': False, 'same_socket': True}
