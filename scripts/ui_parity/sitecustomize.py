"""Process-level network fence: PostgreSQL Unix sockets and loopback only."""
import socket

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_create_connection = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo


def _allowed(sock, address):
    if sock.family == socket.AF_UNIX:
        return True
    host = address[0] if isinstance(address, tuple) else ''
    return host in ('127.0.0.1', '::1', 'localhost')


def _connect(sock, address):
    if not _allowed(sock, address):
        raise OSError('prod parity network fence: external connection blocked')
    return _original_connect(sock, address)


def _connect_ex(sock, address):
    if not _allowed(sock, address):
        raise OSError('prod parity network fence: external connection blocked')
    return _original_connect_ex(sock, address)


def _create_connection(address, *args, **kwargs):
    if address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise OSError('prod parity network fence: external connection blocked')
    return _original_create_connection(address, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection


def _getaddrinfo(host, *args, **kwargs):
    if host not in (None, '127.0.0.1', '::1', 'localhost'):
        raise OSError('prod parity network fence: external DNS blocked')
    return _original_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo
