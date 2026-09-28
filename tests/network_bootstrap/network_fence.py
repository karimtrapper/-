"""Early Python network fence shared by pytest and its Python subprocesses.

The audit hook protects C socket operations even when application code replaces
socket methods. The append-only ledger makes swallowed thread errors fatal to
the parent test run. No address, URL, token or payload is written to the ledger.
"""
import contextlib
import contextvars
import errno
import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import traceback


_expected = contextvars.ContextVar('network_fence_expected', default=False)
_installed = False
_real_getaddrinfo = socket.getaddrinfo
_real_gethostbyname = socket.gethostbyname
_real_gethostbyname_ex = socket.gethostbyname_ex
_real_getnameinfo = socket.getnameinfo
_real_popen = subprocess.Popen
_real_bind = socket.socket.bind
_PORT_START = int(os.environ.get('CALCCRM_FENCE_PORT_START', '18980'))
_PORTS = range(_PORT_START, _PORT_START + 64)

_POLLERS_OFF = (
    'REESTR_SYNC_ENABLED', 'PAYIN_ADDR_BACKFILL', 'TRONSCAN_WARM_ENABLED',
    'PAYMENT_POLL_ENABLED', 'KYC_RETENTION_ENABLED', 'STAND_TRANSFER_POLL_ENABLED',
    'STAND_SBER_MIRROR_ENABLED', 'STAND_TG_UPDATES_ENABLED',
)


def _local(host):
    if host == 'localhost' or host == b'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _address_local(address):
    if isinstance(address, (str, bytes)):
        return True  # AF_UNIX path; socket audit event carries a path string.
    return isinstance(address, tuple) and bool(address) and _local(address[0])


def _endpoint_owned(address):
    if not _address_local(address):
        return False
    if isinstance(address, tuple):
        return address[1] in _PORTS
    return True


def _deny(kind):
    ledger = os.environ.get('CALCCRM_FENCE_LEDGER')
    if ledger:
        caller = next((f'{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}'
                       for frame in reversed(traceback.extract_stack(limit=20)[:-1])
                       if os.path.basename(frame.filename) in
                       {'app.py', 'calculator.py', 'stand_egress.py', 'stand_notify.py',
                        'stand_sber_mirror.py'}), '')
        # A single O_APPEND write is atomic for these short records. Keep only
        # category and process/test identity, never user-controlled network data.
        record = json.dumps({'pid': os.getpid(), 'kind': kind,
                             'test': os.environ.get('PYTEST_CURRENT_TEST', '').split(' ')[0].split('[')[0],
                             'source': caller, 'expected': _expected.get()},
                            separators=(',', ':')) + '\n'
        fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, record.encode())
        finally:
            os.close(fd)
    raise OSError('test network fence blocked external ' + kind)


def _audit(event, args):
    if event == 'socket.bind' and not _address_local(args[1]):
        _deny('bind')
    if event == 'socket.connect' and not _endpoint_owned(args[1]):
        _deny('connect')
    if event == 'socket.getaddrinfo' and not _local(args[0]):
        _deny('dns')
    if event in ('socket.gethostbyname', 'socket.gethostbyname_ex') and not _local(args[0]):
        _deny('dns')
    if event == 'socket.getnameinfo' and not _address_local(args[0]):
        _deny('dns-reverse')
    if event in ('socket.sendto', 'socket.sendmsg') and args[1] is not None and not _endpoint_owned(args[1]):
        _deny(event.rsplit('.', 1)[1])


def _bind(sock, address):
    if not _address_local(address):
        _deny('bind')
    if isinstance(address, tuple) and len(address) >= 2 and address[1] == 0:
        for port in _PORTS:
            replacement = (address[0], port, *address[2:])
            try:
                return _real_bind(sock, replacement)
            except OSError as exc:
                if exc.errno != errno.EADDRINUSE:
                    raise
        raise OSError('test network fence exhausted local port pool')
    return _real_bind(sock, address)


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if not _local(host):
        _deny('dns')
    # Never ask the system resolver about localhost. A literal address is
    # handed to the C implementation with AI_NUMERICHOST.
    if host in ('localhost', b'localhost'):
        host = '::1' if family == socket.AF_INET6 else '127.0.0.1'
    return _real_getaddrinfo(host, port, family, type, proto,
                             flags | socket.AI_NUMERICHOST)


def _gethostbyname(host):
    if not _local(host):
        _deny('dns')
    return _real_gethostbyname('127.0.0.1' if host == 'localhost' else host)


def _gethostbyname_ex(host):
    if not _local(host):
        _deny('dns')
    return _real_gethostbyname_ex('127.0.0.1' if host == 'localhost' else host)


def _getnameinfo(address, flags):
    if not _address_local(address):
        _deny('dns-reverse')
    return _real_getnameinfo(address, flags | socket.NI_NUMERICHOST)


def _popen(*args, **kwargs):
    env = dict(os.environ if kwargs.get('env') is None else kwargs['env'])
    env['PYTHON_DOTENV_DISABLED'] = '1'
    env['CALCCRM_FENCE_LEDGER'] = os.environ['CALCCRM_FENCE_LEDGER']
    env['CALCCRM_FENCE_BOOTSTRAP'] = os.environ['CALCCRM_FENCE_BOOTSTRAP']
    env['CALCCRM_FENCE_PORT_START'] = os.environ['CALCCRM_FENCE_PORT_START']
    env['PYTEST_CURRENT_TEST'] = os.environ.get('PYTEST_CURRENT_TEST', '')
    path = env.get('PYTHONPATH', '')
    bootstrap = env['CALCCRM_FENCE_BOOTSTRAP']
    env['PYTHONPATH'] = bootstrap + (os.pathsep + path if path else '')
    for name in _POLLERS_OFF:
        env.setdefault(name, '0')
    kwargs['env'] = env
    return _real_popen(*args, **kwargs)


@contextlib.contextmanager
def expect_blocked():
    """Only for an intentional single negative probe in this process."""
    token = _expected.set(True)
    try:
        yield
    finally:
        _expected.reset(token)


def install():
    global _installed
    if _installed or not os.environ.get('CALCCRM_FENCE_LEDGER'):
        return
    _installed = True
    os.environ['CALCCRM_FENCE_ACTIVE'] = '1'
    os.environ['PYTHON_DOTENV_DISABLED'] = '1'
    os.environ['CALCCRM_FENCE_BOOTSTRAP'] = os.path.dirname(__file__)
    for name in _POLLERS_OFF:
        os.environ.setdefault(name, '0')
    socket.getaddrinfo = _getaddrinfo
    socket.gethostbyname = _gethostbyname
    socket.gethostbyname_ex = _gethostbyname_ex
    socket.getnameinfo = _getnameinfo
    socket.socket.bind = _bind
    subprocess.Popen = _popen
    sys.addaudithook(_audit)
