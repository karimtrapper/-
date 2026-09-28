"""Synthetic T17 import smoke. Run only under /tmp/qa-t17/fence.sb with clean env."""
import errno
import socket


def probe(host, port):
    sock = socket.socket()
    try:
        return sock.connect_ex((host, port))
    finally:
        sock.close()


for host, port in [('127.0.0.1', 18881), ('192.0.2.1', 443)]:
    result = probe(host, port)
    assert result == errno.EPERM, (host, port, result)

import dotenv  # noqa: E402

dotenv.load_dotenv = lambda *args, **kwargs: False
import stand_notify  # noqa: E402
stand_notify.start_updates = lambda: False
import stand_sber_mirror  # noqa: E402
stand_sber_mirror.start = lambda appmod: False
import stand_egress  # noqa: E402
stand_egress.allow_test_target('127.0.0.1', 18917)

import app  # noqa: E402

app.app.config['TESTING'] = True
response = app.app.test_client().get('/api/health')
print('fenced app import:', response.status_code)
assert response.status_code == 200
