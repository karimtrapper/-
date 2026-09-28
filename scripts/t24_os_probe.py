"""Native OS sandbox proof for T24 exact HTTP and PostgreSQL Unix targets."""
import errno
import socket


def denied(address, family):
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(address)
        except OSError as exc:
            assert exc.errno == errno.EPERM, (family, exc.errno)
            return
    raise AssertionError('OS sandbox unexpectedly permitted a foreign target')


server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', 29991))
server.listen(1)
try:
    with socket.create_connection(('127.0.0.1', 29991), timeout=2):
        peer, _ = server.accept()
        peer.close()
    denied(('127.0.0.1', 29992), socket.AF_INET)
    denied(('192.0.2.1', 443), socket.AF_INET)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as own:
        own.connect('/tmp/calccrm-t24-pg-own/socket/.s.PGSQL.29990')
    print('OS fence: own HTTP and own PG Unix PASS; foreign loopback/external EPERM PASS')
finally:
    server.close()
