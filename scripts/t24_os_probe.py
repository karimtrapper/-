"""Native OS sandbox proof for T24 exact HTTP and PostgreSQL Unix targets."""
import errno
import os
import socket
import subprocess
import sys


def denied(address, family):
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.connect(address)
        except OSError as exc:
            assert exc.errno == errno.EPERM, (family, exc.errno)
            return
    raise AssertionError('OS sandbox unexpectedly permitted a foreign target')


port = int(os.environ['T26_HTTP_PORT'])
foreign_port = int(os.environ['T26_FOREIGN_PORT'])
pg_socket = os.environ['T26_PG_SOCKET']
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', port))
server.listen(1)
try:
    with socket.create_connection(('127.0.0.1', port), timeout=2):
        peer, _ = server.accept()
        peer.close()
    denied(('127.0.0.1', foreign_port), socket.AF_INET)
    denied(('192.0.2.1', 443), socket.AF_INET)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as own:
        own.connect(pg_socket)
    child = subprocess.run([sys.executable, '-I', '-S', '-c',
        'import errno,socket,sys; s=socket.socket(); '
        'code=None; '\
        '\ntry: s.connect(("127.0.0.1",int(sys.argv[1])))'\
        '\nexcept OSError as e: code=e.errno'\
        '\nassert code==errno.EPERM, code', str(foreign_port)],
        capture_output=True, text=True)
    assert child.returncode == 0, child.stderr
    print('OS fence native: own HTTP+PG Unix PASS; denied=3 '
          '(foreign loopback, external, native child EPERM)')
finally:
    server.close()
