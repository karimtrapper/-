"""Выключатель исходящих для тестового стенда (STAND_MODE=1).

Fail-closed сеть: после install() любое исходящее TCP-соединение из процесса
запрещено, кроме loopback и точного host:port базы данных (DATABASE_URL).
Единственное исключение — Telegram, и только изнутри tg_call(): она сама
проверяет токен (только STAND_TG_TOKEN), метод и получателя через can_send(),
и на время своего HTTP-запроса открывает временное разрешение на хост
api.telegram.org для текущего потока.

Важно: имя хоста проверяется ДО разрешения DNS (getaddrinfo) и до открытия
сокета (connect/connect_ex). Тест, который резолвит внешний хост в локальный
фейковый сервер на loopback, не должен обмануть guard — блокировка срабатывает
по запрошенному имени хоста, а не по тому, во что оно в итоге резолвится
(иначе «внешний хост резолвится в loopback» само стало бы обходом: loopback
разрешён всегда, и адрес фейкового сервера прошёл бы как «свой»).

Не покрывает (честно, а не как гарантия):
- libpq (psycopg2) резолвит и коннектится через C-библиотеку напрямую, минуя
  модуль socket. Единственная защита там — что в процессе всего один
  DATABASE_URL и он не меняется в рантайме.
- Внешние процессы (Chromium под Playwright) держат свой собственный сетевой
  стек — guard патчит только Python-процесс. На стенде Playwright-курсы
  выключаются кодом (см. calculator.py), а не этим модулем.
- subprocess с сетевыми утилитами (curl и т. п.) не перехватывается — в этом
  дереве кода такие вызовы не найдены и не заводятся; если появятся, они вне
  периметра guard'а.
"""
import ipaddress
import os
import socket
import threading
import time
from collections import deque
from urllib.parse import urlsplit

_installed = False
_lock = threading.Lock()
_blocked_count = 0
_recent = deque(maxlen=20)

_orig_connect = None
_orig_connect_ex = None
_orig_getaddrinfo = None
_orig_create_connection = None

_db_host = None
_db_port = None
_db_ips = frozenset()

_tg_ctx = threading.local()

_TG_HOST = 'api.telegram.org'
_TG_ALLOWED_METHODS = {'getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage'}

_policy = None  # callable(channel, recipient, operation) -> bool, регистрируется set_policy()


def _default_policy(channel, recipient, operation):
    """Пока T5 не зарегистрировал свою политику — разрешены только read-only
    методы Telegram, никакая отправка получателю не проходит."""
    return operation in ('getMe', 'getWebhookInfo', 'getUpdates')


def set_policy(callable_):
    """Регистрирует политику can_send(channel, recipient, operation) -> bool."""
    global _policy
    _policy = callable_


def can_send(channel, recipient, operation):
    fn = _policy or _default_policy
    try:
        return bool(fn(channel, recipient, operation))
    except Exception:
        return False


def _record_block(where):
    global _blocked_count
    with _lock:
        _blocked_count += 1
        _recent.append({'where': where, 'ts': time.time()})
    print(f'[EGRESS-BLOCKED] where={where}')


def _is_loopback_host(host):
    if host is None:
        return True
    h = host.strip('[]').lower()
    if h in ('localhost', 'localhost.localdomain'):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _parse_db_target():
    """host/port DATABASE_URL один раз, до патча — sqlite не даёт ни того, ни другого."""
    url = os.environ.get('DATABASE_URL', '')
    try:
        parts = urlsplit(url)
    except Exception:
        return None, None
    if not parts.hostname:
        return None, None
    return parts.hostname, parts.port


def _resolve_db_ips(host, port):
    if not host:
        return frozenset()
    try:
        infos = _orig_getaddrinfo(host, port or 0, 0, socket.SOCK_STREAM)
        return frozenset(info[4][0] for info in infos)
    except Exception:
        return frozenset()


def _hostname_allowed(host):
    if _is_loopback_host(host):
        return True
    if host is None:
        return True
    h = host.strip('[]').lower()
    if _db_host and h == _db_host.lower():
        return True
    if h == _TG_HOST and getattr(_tg_ctx, 'active', False):
        return True
    return False


def _ip_allowed(ip):
    if _is_loopback_host(ip):
        return True
    if ip in _db_ips:
        return True
    if getattr(_tg_ctx, 'active', False) and ip in getattr(_tg_ctx, 'allowed_ips', ()):
        return True
    return False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if not _hostname_allowed(host):
        _record_block(f'getaddrinfo host={host}')
        raise socket.gaierror(-2, 'Имя или служба неизвестны (заблокировано egress-guard стенда)')
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    if host and str(host).strip('[]').lower() == _TG_HOST and getattr(_tg_ctx, 'active', False):
        ips = {info[4][0] for info in infos}
        _tg_ctx.allowed_ips = ips | set(getattr(_tg_ctx, 'allowed_ips', ()))
    return infos


def _extract_host_port(address, family):
    if family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple) and address:
        return address[0], (address[1] if len(address) > 1 else None)
    return None, None


def _guard_address(address, family, where):
    host, port = _extract_host_port(address, family)
    if host is None:
        return True  # AF_UNIX и т.п. — не сеть наружу
    # Хост уже мог быть текстовым именем (редкий путь, когда connect() сам
    # резолвит) — проверяем и по имени, и (если это IP-литерал) по адресу.
    if not _hostname_allowed(host) and not _ip_allowed(host):
        _record_block(f'{where} host={host}')
        return False
    return True


def _patched_connect(self, address):
    if not _guard_address(address, self.family, 'connect'):
        raise ConnectionRefusedError('[EGRESS-BLOCKED] соединение запрещено политикой стенда')
    return _orig_connect(self, address)


def _patched_connect_ex(self, address):
    if not _guard_address(address, self.family, 'connect_ex'):
        import errno
        return errno.ECONNREFUSED
    return _orig_connect_ex(self, address)


def _patched_create_connection(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else None
    if not _hostname_allowed(host) and not _ip_allowed(host):
        _record_block(f'create_connection host={host}')
        raise ConnectionRefusedError('[EGRESS-BLOCKED] соединение запрещено политикой стенда')
    return _orig_create_connection(address, *args, **kwargs)


def install():
    """Ставит сетевой guard. No-op вне STAND_MODE и при повторном вызове."""
    global _installed, _orig_connect, _orig_connect_ex, _orig_getaddrinfo
    global _orig_create_connection, _db_host, _db_port, _db_ips
    if os.environ.get('STAND_MODE') != '1':
        return False
    with _lock:
        if _installed:
            return True
        _orig_connect = socket.socket.connect
        _orig_connect_ex = socket.socket.connect_ex
        _orig_getaddrinfo = socket.getaddrinfo
        _orig_create_connection = socket.create_connection

        _db_host, _db_port = _parse_db_target()
        _db_ips = _resolve_db_ips(_db_host, _db_port)

        socket.socket.connect = _patched_connect
        socket.socket.connect_ex = _patched_connect_ex
        socket.getaddrinfo = _patched_getaddrinfo
        socket.create_connection = _patched_create_connection
        _installed = True
    return True


def status():
    with _lock:
        return {
            'active': _installed,
            'blocked_count': _blocked_count,
            'recent': list(_recent),
        }


def tg_call(method, payload, _base_url=None):
    """Единственный путь в Telegram. `_base_url` — только для тестов, прод его
    не передаёт и не читает из env."""
    import requests

    if method not in _TG_ALLOWED_METHODS:
        return {'ok': False, 'error': 'method_not_allowed'}

    token = os.environ.get('STAND_TG_TOKEN', '').strip()
    if not token:
        return {'ok': False, 'error': 'no_token'}

    payload = dict(payload or {})
    chat_id = payload.get('chat_id')
    if method == 'sendMessage':
        try:
            chat_id_int = int(chat_id)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'invalid_chat_id'}
        if chat_id_int <= 0:
            return {'ok': False, 'error': 'invalid_chat_id'}
        if not can_send('telegram', chat_id_int, method):
            return {'ok': False, 'error': 'denied'}
    else:
        if not can_send('telegram', None, method):
            return {'ok': False, 'error': 'denied'}

    base = (_base_url or f'https://{_TG_HOST}').rstrip('/')
    url = f'{base}/bot{token}/{method}'

    _tg_ctx.active = True
    _tg_ctx.allowed_ips = set()
    try:
        session = requests.Session()
        session.trust_env = False
        try:
            resp = session.post(url, json=payload, timeout=10, allow_redirects=False)
            try:
                data = resp.json()
            except ValueError:
                data = {}
            return {'ok': bool(data.get('ok')), 'status_code': resp.status_code, 'result': data.get('result')}
        finally:
            session.close()
    except Exception as e:
        return {'ok': False, 'error': str(e)[:200]}
    finally:
        _tg_ctx.active = False
        _tg_ctx.allowed_ips = set()
