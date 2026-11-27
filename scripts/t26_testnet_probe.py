"""Preimport Python fence proof for the T26 PostgreSQL HTTP run."""
import os
import socket

from network_fence import expect_blocked


assert os.environ.get('CALCCRM_FENCE_ACTIVE') == '1'
port = int(os.environ['T26_HTTP_PORT'])
foreign = int(os.environ['T26_FOREIGN_PORT'])
with socket.socket() as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(1)
    with socket.create_connection(('127.0.0.1', port), timeout=2):
        peer, _ = server.accept()
        peer.close()
with socket.socket(socket.AF_UNIX) as pg:
    pg.connect(os.environ['T26_PG_SOCKET'])
with expect_blocked():
    try:
        socket.create_connection(('127.0.0.1', foreign), timeout=2)
    except OSError:
        pass
    else:
        raise AssertionError('foreign loopback was permitted')
print('TEST-NET preimport: own exact HTTP+PG Unix PASS; foreign loopback blocked')
