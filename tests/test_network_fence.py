"""Mutation probes for the early Python and native network barriers."""
import http.server
import os
import socket
import ssl
import subprocess
import sys
import threading
import warnings

import pytest

from network_fence import expect_blocked


@pytest.mark.parametrize('probe', [
    lambda: socket.socket().connect(('192.0.2.1', 443)),
    lambda: socket.socket().connect_ex(('192.0.2.1', 443)),
    lambda: socket.getaddrinfo('external.invalid', 443),
    lambda: __import__('requests').get('https://external.invalid/', timeout=1),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
        b'x', ('192.0.2.1', 443)),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendmsg(
        [b'x'], [], 0, ('192.0.2.1', 443)),
    lambda: socket.socket(socket.AF_INET6).connect(('2001:db8::1', 443)),
])
def test_parent_external_probe_blocked(probe):
    with expect_blocked(), pytest.raises((OSError, RuntimeError)):
        probe()


def test_python_subprocess_with_replaced_env_is_fenced():
    script = '''import socket, network_fence
with network_fence.expect_blocked():
    try: socket.socket().connect(('192.0.2.1', 443))
    except OSError: pass
    else: raise AssertionError('external connect succeeded')
print('FENCED')
'''
    result = subprocess.run([sys.executable, '-c', script], env={'PATH': os.environ['PATH']},
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'FENCED'


def test_native_subprocess_os_barrier():
    # -I -S disables sitecustomize; this is a syscall check of sandbox-exec.
    result = subprocess.run(['/usr/bin/python3', '-I', '-S', '-c',
                             'import socket; print(socket.socket().connect_ex(("192.0.2.1",443))); '
                             'print(socket.socket().connect_ex(("127.0.0.1",18884)))'],
                            capture_output=True, text=True, timeout=5, check=True)
    assert result.stdout.splitlines() == ['1', '1']  # EPERM, including foreign loopback


def test_local_http_survives():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'local')

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert __import__('requests').get(
            f'http://127.0.0.1:{server.server_port}/', timeout=2).content == b'local'
    finally:
        server.shutdown()
        thread.join()


def test_localhost_resolution_and_unix_socket_survive():
    assert socket.getaddrinfo('localhost', 80)[0][4][0] == '127.0.0.1'
    path = os.path.join(os.environ['TMPDIR'], f'u-{os.getpid()}.sock')
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(path)
        server.listen()
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(path)
            accepted, _ = server.accept()
            with accepted:
                client.sendall(b'x')
                assert accepted.recv(1) == b'x'


def test_local_https_survives(tmp_path):
    cert = tmp_path / 'cert.pem'
    key = tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-subj', '/CN=localhost',
                    '-days', '1'], check=True, capture_output=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'secure-local')

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', __import__('urllib3').exceptions.InsecureRequestWarning)
            response = __import__('requests').get(
                f'https://127.0.0.1:{server.server_port}/', verify=False, timeout=2)
        assert response.content == b'secure-local'
    finally:
        server.shutdown()
        thread.join()


def test_fake_keys_import_has_no_startup_pollers(tmp_path):
    env = {'PATH': os.environ['PATH'],
           'DATABASE_URL': f'sqlite:///{tmp_path}/stand.db',
           'SECRET_KEY': 'test-secret', 'STAND_MODE': '1',
           'STAND_PASSWORD': 'test-password',
           'STAND_TG_TOKEN': '333:fake', 'STAND_PROD_RO_KEY': 'fake-key'}
    code = '''import app, threading
bad = {'reestr-sync', 'payin-addr-backfill', 'tronscan-warm',
       'channel-traffic', 'payment-link-poll', 'kyc-retention',
       'stand-transfer-poll', 'stand-tg-updates', 'stand-sber-mirror'}
assert not bad.intersection(t.name for t in threading.enumerate())
print('POLLERS_OFF')
'''
    result = subprocess.run([sys.executable, '-c', code], env=env,
                            capture_output=True, text=True, check=True, timeout=30)
    assert 'POLLERS_OFF' in result.stdout
