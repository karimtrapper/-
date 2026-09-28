"""Выключатель исходящих для тестового стенда (STAND_MODE=1).

Fail-closed сеть: после install() любое исходящее TCP/UDP-соединение из
процесса запрещено, кроме loopback и точного host:port базы данных
(DATABASE_URL; порт по умолчанию 5432, если в DSN не указан — тот же хост на
чужом порту не считается «своим»). Единственное исключение — Telegram, и
только изнутри tg_call(): она сама проверяет токен (только STAND_TG_TOKEN),
метод и получателя через can_send(), и на время своего HTTP-запроса
открывает временное разрешение на хост api.telegram.org:443 для текущего
потока.

Важно: имя хоста (и порт) проверяются ДО разрешения DNS (getaddrinfo) и до
открытия сокета (connect/connect_ex/sendto/sendmsg). Тест, который резолвит
внешний хост в локальный фейковый сервер на loopback, не должен обмануть
guard — блокировка срабатывает по запрошенному имени хоста, а не по тому,
во что оно в итоге резолвится. По той же причине сравнение хоста — точное,
не по суффиксу/подстроке.

Loopback НЕ разрешён целиком (это была дыра: env-прокси указывает на локальный
CONNECT-туннель, адрес прокси — loopback, а реальная цель едет внутри
HTTP CONNECT и на сокетном уровне не видна). Разрешены только точные пары
(host, port): цель БД из DATABASE_URL и, на время самого HTTP-запроса,
петля внутри tg_call(). Тестам, которым нужен фейковый сервер на loopback,
даётся явный хук allow_test_target(host, port) — прод его никогда не вызывает.

Дополнительный слой для requests/urllib: install() заставляет requests
игнорировать и env-прокси, и явный kwarg `proxies=`, а urllib.request —
не читать getproxies() из окружения. Это не отменяет проверку пары (host,
port) выше, а страхует от прокси на разрешённом адресе (порт БД/tg_call).

UDP (sendto/sendmsg) на заблокированный адрес не бросает исключение — молча
«теряет» пакет (возвращает длину данных, как будто отправка удалась): вызывающий
код почти никогда не оборачивает sendto в try/except, и внезапное исключение
там было бы хуже тихой потери. TCP (connect/connect_ex/create_connection),
наоборот, поднимает исключение — это ожидаемый и обрабатываемый библиотеками
результат отказа соединения.

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
import json
import os
import re
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
_orig_sendto = None
_orig_sendmsg = None
_orig_session_request = None
_orig_session_send = None
_orig_urllib_getproxies = None

_DEFAULT_DB_PORT = 5432

_db_host = None
_db_port = None
_db_pairs = frozenset()  # {(ip, port)} — точная пара, не просто «IP базы»

_test_allowed_pairs = set()  # {(канонический host, port)} — только allow_test_target()

_tg_ctx = threading.local()

_TG_HOST = 'api.telegram.org'
_TG_ALLOWED_METHODS = {'getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage'}

_read_ctx = threading.local()

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


def _loopback_key(host):
    """Канонический ключ для сравнения loopback-адресов: 'localhost' и
    '127.0.0.1' — один и тот же адрес, пару нужно узнавать по обеим формам.
    Возвращает None для не-loopback (тогда сравнение идёт по обычному имени)."""
    if host is None:
        return None
    h = host.strip('[]').lower()
    if h in ('localhost', 'localhost.localdomain', '127.0.0.1'):
        return '127.0.0.1'
    if h in ('::1', '0:0:0:0:0:0:0:1'):
        return '::1'
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return None
    if not ip.is_loopback:
        return None
    return '127.0.0.1' if ip.version == 4 else '::1'


def allow_test_target(host, port):
    """Тестовый хук: явно разрешить (host, port) на loopback для сценариев с
    фейковым сервером. Прод-код эту функцию никогда не вызывает — loopback
    по умолчанию запрещён (см. docstring модуля)."""
    key = _loopback_key(host) or (host or '').strip('[]').lower()
    _test_allowed_pairs.add((key, int(port)))


def _parse_db_target():
    """host/port DATABASE_URL один раз, до патча — sqlite не даёт ни того, ни другого.

    Порт по умолчанию — 5432 (Postgres), если в DSN его нет: «разрешён точный
    host:port базы» не должен молча превращаться в «разрешён весь хост базы»."""
    url = os.environ.get('DATABASE_URL', '')
    try:
        parts = urlsplit(url)
    except Exception:
        return None, None
    if not parts.hostname:
        return None, None
    return parts.hostname, (parts.port or _DEFAULT_DB_PORT)


def _resolve_db_pairs(host, port):
    if not host:
        return frozenset()
    try:
        infos = _orig_getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        return frozenset((info[4][0], port) for info in infos)
    except Exception:
        return frozenset()


def _loopback_pair_allowed(host, port):
    """Loopback запрещён целиком — разрешены только явно перечисленные пары
    (DB-цель уже проверяется отдельно через _db_pairs; здесь — тестовый хук
    и активная петля tg_call на время HTTP-запроса)."""
    if not _is_loopback_host(host):
        return False
    if port is None:
        return False
    key = _loopback_key(host) or host.strip('[]').lower()
    if (key, port) in _test_allowed_pairs:
        return True
    if getattr(_tg_ctx, 'active', False) and (key, port) in getattr(_tg_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_read_ctx, 'active', False) and (key, port) in getattr(_read_ctx, 'allowed_pairs', ()):
        return True
    return False


def _hostname_allowed(host, port=None):
    """Решение по запрошенному имени — до резолва. Хост сравнивается точно
    (не суффиксом/подстрокой), порт базы — тоже точно (иначе тот же хост на
    другом порту прошёл бы как «свой»)."""
    if host is None:
        return True
    if _loopback_pair_allowed(host, port):
        return True
    h = host.strip('[]').lower()
    if _db_host and h == _db_host.lower():
        return port is None or port == _db_port
    if h == _TG_HOST and getattr(_tg_ctx, 'active', False):
        return port is None or port == 443
    if getattr(_read_ctx, 'active', False) and h == getattr(_read_ctx, 'host', None):
        return port is None or port == 443
    return False


def _ip_allowed(ip, port=None):
    if _loopback_pair_allowed(ip, port):
        return True
    if port is not None and (ip, port) in _db_pairs:
        return True
    if getattr(_tg_ctx, 'active', False) and port is not None and (ip, port) in getattr(_tg_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_read_ctx, 'active', False) and port is not None and (ip, port) in getattr(_read_ctx, 'allowed_pairs', ()):
        return True
    return False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if not _hostname_allowed(host, port if isinstance(port, int) else None):
        _record_block(f'getaddrinfo host={host}:{port}')
        raise socket.gaierror(-2, 'Имя или служба неизвестны (заблокировано egress-guard стенда)')
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    h = str(host).strip('[]').lower() if host else None
    if h == _TG_HOST and getattr(_tg_ctx, 'active', False):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _tg_ctx.allowed_pairs = pairs | set(getattr(_tg_ctx, 'allowed_pairs', ()))
    if getattr(_read_ctx, 'active', False) and h == getattr(_read_ctx, 'host', None):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _read_ctx.allowed_pairs = pairs | set(getattr(_read_ctx, 'allowed_pairs', ()))
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
    # резолвит) — проверяем и по имени, и (если это IP-литерал) по адресу;
    # порт участвует в обоих сравнениях.
    if not _hostname_allowed(host, port) and not _ip_allowed(host, port):
        _record_block(f'{where} host={host}:{port}')
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
    host, port = (address[0], address[1]) if isinstance(address, tuple) and len(address) >= 2 else (None, None)
    if not _hostname_allowed(host, port) and not _ip_allowed(host, port):
        _record_block(f'create_connection host={host}:{port}')
        raise ConnectionRefusedError('[EGRESS-BLOCKED] соединение запрещено политикой стенда')
    return _orig_create_connection(address, *args, **kwargs)


def _patched_sendto(self, *args):
    # sendto(data, address) или sendto(data, flags, address) — адрес всегда
    # последний, данные — первый аргумент. UDP fire-and-forget: вызывающий код
    # обычно не оборачивает sendto в try/except, поэтому блок — тихий (как
    # будто пакет ушёл и потерялся), а не исключение, лог и счётчик всё равно есть.
    address = args[-1] if args else None
    data = args[0] if args else b''
    if isinstance(address, tuple) and not _guard_address(address, self.family, 'sendto'):
        return len(data)
    return _orig_sendto(self, *args)


def _patched_sendmsg(self, buffers, *rest):
    # sendmsg(buffers[, ancdata[, flags[, address]]]) — адрес, если есть, последний аргумент.
    address = rest[-1] if rest and isinstance(rest[-1], tuple) else None
    if address is not None and not _guard_address(address, self.family, 'sendmsg'):
        return sum(len(b) for b in buffers)
    return _orig_sendmsg(self, buffers, *rest)


def _patched_session_request(self, method, url, **kwargs):
    # Второй слой поверх проверки (host, port): даже если прокси однажды
    # окажется на разрешённом адресе (порт БД/tg_call), requests не должен
    # сам решать идти через прокси — ни по env, ни по явному kwarg'у.
    self.trust_env = False
    kwargs['proxies'] = {}
    return _orig_session_request(self, method, url, **kwargs)


def _patched_session_send(self, request, **kwargs):
    self.trust_env = False
    kwargs['proxies'] = {}
    return _orig_session_send(self, request, **kwargs)


def _patched_getproxies(*args, **kwargs):
    return {}


def install():
    """Ставит сетевой guard. No-op вне STAND_MODE и при повторном вызове."""
    global _installed, _orig_connect, _orig_connect_ex, _orig_getaddrinfo
    global _orig_create_connection, _orig_sendto, _orig_sendmsg
    global _orig_session_request, _orig_session_send, _orig_urllib_getproxies
    global _db_host, _db_port, _db_pairs
    if os.environ.get('STAND_MODE') != '1':
        return False
    with _lock:
        if _installed:
            return True
        # env-прокси — дыра мимо этого guard'а: connect() видит адрес прокси
        # (часто loopback — он разрешён всегда), а реальная цель едет внутри
        # HTTP CONNECT и на сокетном уровне не видна. requests/urllib/httpx
        # читают эти переменные из os.environ на каждый запрос — стираем их
        # здесь же, а не только в app.py, чтобы install() был самодостаточным
        # для любого вызывающего кода, а не только для приложения целиком.
        for _proxy_var in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                           'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
                           'FTP_PROXY', 'ftp_proxy'):
            os.environ.pop(_proxy_var, None)
        _orig_connect = socket.socket.connect
        _orig_connect_ex = socket.socket.connect_ex
        _orig_getaddrinfo = socket.getaddrinfo
        _orig_create_connection = socket.create_connection
        _orig_sendto = socket.socket.sendto
        _orig_sendmsg = socket.socket.sendmsg

        _db_host, _db_port = _parse_db_target()
        _db_pairs = _resolve_db_pairs(_db_host, _db_port)

        socket.socket.connect = _patched_connect
        socket.socket.connect_ex = _patched_connect_ex
        socket.getaddrinfo = _patched_getaddrinfo
        socket.create_connection = _patched_create_connection
        socket.socket.sendto = _patched_sendto
        socket.socket.sendmsg = _patched_sendmsg

        try:
            import requests
            _orig_session_request = requests.Session.request
            _orig_session_send = requests.Session.send
            requests.Session.request = _patched_session_request
            requests.Session.send = _patched_session_send
        except ImportError:
            pass

        try:
            import urllib.request
            _orig_urllib_getproxies = urllib.request.getproxies
            urllib.request.getproxies = _patched_getproxies
        except ImportError:
            pass

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
        # Только настоящий int > 0 — не строка "555" (int('555') её бы тихо
        # приняла) и не bool (bool — подкласс int в Python, True/False не chat_id).
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
            return {'ok': False, 'error': 'invalid_chat_id'}
        chat_id_int = chat_id
        if not can_send('telegram', chat_id_int, method):
            return {'ok': False, 'error': 'denied'}
    else:
        if not can_send('telegram', None, method):
            return {'ok': False, 'error': 'denied'}

    base = (_base_url or f'https://{_TG_HOST}').rstrip('/')
    url = f'{base}/bot{token}/{method}'

    _tg_ctx.active = True
    _tg_ctx.allowed_pairs = set()
    if _base_url:
        # Тестовый override (прод никогда не передаёт _base_url): пускаем
        # именно этот host:port на время запроса — тем же полем, которым
        # ниже помечается резолв настоящего api.telegram.org.
        parts = urlsplit(_base_url)
        if parts.hostname and parts.port:
            key = _loopback_key(parts.hostname) or parts.hostname.strip('[]').lower()
            _tg_ctx.allowed_pairs.add((key, parts.port))
    try:
        session = requests.Session()
        session.trust_env = False
        try:
            resp = session.post(url, json=payload, timeout=10, allow_redirects=False, proxies={})
            try:
                data = resp.json()
            except ValueError:
                data = {}
            return {'ok': bool(data.get('ok')), 'status_code': resp.status_code, 'result': data.get('result')}
        finally:
            session.close()
    except Exception:
        # Текст исключения requests часто содержит сам URL (…/bot<TOKEN>/method) —
        # ни его, ни оригинальное исключение никуда не отдаём и не логируем.
        return {'ok': False, 'error': 'tg_network_error'}
    finally:
        _tg_ctx.active = False
        _tg_ctx.allowed_pairs = set()


# ─────────────────────── T9: контролируемые каналы чтения ──────────────────
# Блокчейн (TronScan/Etherscan), публичные рыночные котировки (Rapira/Bitazza)
# и зеркало прод-поступлений — read_get(op, params) единственный путь наружу.
# op — из закрытого словаря ниже: URL, заголовки и ключ строит канал сам,
# вызывающий код передаёт только значения параметров операции.

def _valid_tron_hash(v):
    return isinstance(v, str) and bool(re.fullmatch(r'[0-9a-fA-F]{64}', v))


def _valid_eth_hash(v):
    return isinstance(v, str) and bool(re.fullmatch(r'0x[0-9a-fA-F]{64}', v))


def _valid_eth_block_tag(v):
    return isinstance(v, str) and bool(re.fullmatch(r'0x[0-9a-fA-F]{1,16}', v))


def _valid_chainid(v):
    return v == '1'  # только Ethereum mainnet — единственная сеть, которую проверяет код


def _valid_eth_module_proxy(v):
    return v == 'proxy'


def _valid_eth_action_receipt(v):
    return v == 'eth_getTransactionReceipt'


def _valid_eth_action_block(v):
    return v == 'eth_getBlockByNumber'


def _valid_eth_bool_false(v):
    return v == 'false'


def _valid_bitazza_oms_id(v):
    return v == 1


def _valid_bitazza_instrument_id(v):
    return v == 5  # OMSId=1/InstrumentId=5 — фиксированная пара USDT/THB на Bitazza APEX


def _valid_bitazza_depth(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 400


def _valid_prod_all_flag(v):
    return v in (1, '1')


_TRON_B58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
_TRON_USDT_CONTRACT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'


def _valid_tron_address(v):
    """TRON base58check, с контрольной суммой — не просто «T + 33 символа
    из алфавита» (та же проверка, что и tron_address_problem в app.py, но
    без импорта app.py — независимая копия алгоритма, не общий модуль)."""
    if not isinstance(v, str) or len(v) != 34 or not v.startswith('T'):
        return False
    if any(c not in _TRON_B58_ALPHABET for c in v):
        return False
    num = 0
    for c in v:
        num = num * 58 + _TRON_B58_ALPHABET.index(c)
    raw = num.to_bytes(25, 'big')
    import hashlib
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


def _valid_usdt_trc20_contract(v):
    return v == _TRON_USDT_CONTRACT  # фиксированный контракт, не произвольный адрес


def _valid_transfers_limit(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 50


def _valid_transfers_start(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1000


# host/path — точные, без wildcard/prefix; params — закрытый словарь имя→валидатор
# значения (не только имени параметра); required — какие обязательны.
_READ_CHANNELS = {
    'tron_tx_info': {
        'host': 'apilist.tronscanapi.com',
        'path': '/api/transaction-info',
        'params': {'hash': _valid_tron_hash},
        'required': {'hash'},
        'key_env': 'TRONSCAN_API_KEY', 'key_header': 'TRON-PRO-API-KEY', 'key_optional': True,
    },
    'tron_account_balance': {
        'host': 'apilist.tronscanapi.com',
        'path': '/api/account',
        'params': {'address': _valid_tron_address},
        'required': {'address'},
        'key_env': 'TRONSCAN_API_KEY', 'key_header': 'TRON-PRO-API-KEY', 'key_optional': True,
    },
    'tron_account_tokens': {
        'host': 'apilist.tronscanapi.com',
        'path': '/api/account/tokens',
        'params': {'address': _valid_tron_address},
        'required': {'address'},
        'key_env': 'TRONSCAN_API_KEY', 'key_header': 'TRON-PRO-API-KEY', 'key_optional': True,
    },
    'tron_trc20_transfers': {
        'host': 'apilist.tronscanapi.com',
        'path': '/api/token_trc20/transfers',
        'params': {
            'relatedAddress': _valid_tron_address,
            'contract_address': _valid_usdt_trc20_contract,
            'limit': _valid_transfers_limit,
            'start': _valid_transfers_start,
        },
        'required': {'relatedAddress', 'contract_address', 'limit', 'start'},
        'key_env': 'TRONSCAN_API_KEY', 'key_header': 'TRON-PRO-API-KEY', 'key_optional': True,
    },
    'eth_tx_receipt': {
        'host': 'api.etherscan.io',
        'path': '/v2/api',
        'params': {
            'chainid': _valid_chainid, 'module': _valid_eth_module_proxy,
            'action': _valid_eth_action_receipt, 'txhash': _valid_eth_hash,
        },
        'required': {'chainid', 'module', 'action', 'txhash'},
        'key_env': 'STAND_ETHERSCAN_API_KEY', 'key_param': 'apikey', 'key_optional': False,
    },
    'eth_block_by_number': {
        'host': 'api.etherscan.io',
        'path': '/v2/api',
        'params': {
            'chainid': _valid_chainid, 'module': _valid_eth_module_proxy,
            'action': _valid_eth_action_block, 'tag': _valid_eth_block_tag,
            'boolean': _valid_eth_bool_false,
        },
        'required': {'chainid', 'module', 'action', 'tag', 'boolean'},
        'key_env': 'STAND_ETHERSCAN_API_KEY', 'key_param': 'apikey', 'key_optional': False,
    },
    'market_rapira': {
        'host': 'api.rapira.net',
        'path': '/open/market/rates',
        'params': {},
        'required': set(),
    },
    'market_bitazza': {
        'host': 'apexapi.bitazza.com',
        'path': '/AP/GetL2Snapshot',
        'params': {
            'OMSId': _valid_bitazza_oms_id, 'InstrumentId': _valid_bitazza_instrument_id,
            'Depth': _valid_bitazza_depth,
        },
        'required': {'OMSId', 'InstrumentId', 'Depth'},
    },
    'market_binance_ticker': {
        'host': 'api.binance.com',
        'path': '/api/v3/ticker/price',
        'params': {'symbol': lambda v: v == 'USDTTHB'},
        'required': {'symbol'},
    },
    'market_binance_th_ticker': {
        # Прод (calculator.py вне стенда) берёт курс USDT/THB в первую очередь
        # с Binance TH, Binance Global — только фоллбэк. Канал повторяет тот же
        # порядок источников, иначе курс стенда систематически отличался бы от прода.
        'host': 'api.binance.th',
        'path': '/api/v1/ticker/price',
        'params': {'symbol': lambda v: v == 'USDTTHB'},
        'required': {'symbol'},
    },
    'prod_incomes': {
        'host': 'grusha.up.railway.app',
        'path': '/api/sber-incomes',
        'params': {'all': _valid_prod_all_flag},
        'required': set(),
        'key_env': 'STAND_PROD_RO_KEY', 'key_header': 'X-Api-Key', 'key_optional': False,
    },
}

_MAX_READ_RESPONSE_BYTES = 2 * 1024 * 1024
_READ_REDIRECT_CODES = (301, 302, 303, 307, 308)
_READ_TOTAL_DEADLINE = 8.0  # секунд на всю операцию: connect + заголовки + тело


class _ReadChannelConnectMixin:
    """Guard-разрешение выставляется СТРОГО на время своего connect() — не на
    весь HTTP-запрос. Если тест подменяет requests.Session.get целиком (сам
    метод, не транспорт), эта connect() вообще не вызывается — разрешение
    не открывается, и прямой сокет из того же потока получит отказ, как и
    положено (E2)."""
    def connect(self):
        _read_ctx.active = True
        _read_ctx.host = getattr(_read_ctx, 'pending_host', None)
        _read_ctx.allowed_pairs = set(getattr(_read_ctx, 'pending_pairs', ()) or ())
        try:
            return super().connect()
        finally:
            _read_ctx.active = False
            _read_ctx.host = None
            _read_ctx.allowed_pairs = set()


def _read_channel_adapter():
    """HTTPAdapter с одноразовым пулом, чьи соединения открывают guard-
    разрешение только на время своего connect() (см. _ReadChannelConnectMixin)."""
    import urllib3
    from requests.adapters import HTTPAdapter

    class _HTTPConn(_ReadChannelConnectMixin, urllib3.connection.HTTPConnection):
        pass

    class _HTTPSConn(_ReadChannelConnectMixin, urllib3.connection.HTTPSConnection):
        pass

    class _HTTPPool(urllib3.HTTPConnectionPool):
        ConnectionCls = _HTTPConn

    class _HTTPSPool(urllib3.HTTPSConnectionPool):
        ConnectionCls = _HTTPSConn

    class _Adapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {'http': _HTTPPool, 'https': _HTTPSPool}

    return _Adapter()


def _validate_base_url_override(_base_url):
    """_base_url — тестовый хук (как у tg_call): допускается ТОЛЬКО когда его
    точная пара (host, port) заранее зарегистрирована test-only хуком T1
    `allow_test_target()` и host — loopback. Схема http/https, без userinfo/
    query/fragment; путь берётся из спецификации op — собственный путь
    _base_url в URL не попадает вовсе. Обходы host.evil/@userinfo///../ и
    т. п. отсекаются урезанным списком допустимых полей urlsplit, а не
    попыткой распознать каждый конкретный трюк."""
    if not isinstance(_base_url, str) or '\\' in _base_url:
        return None
    try:
        parts = urlsplit(_base_url)
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https'):
        return None
    if '@' in parts.netloc:
        return None
    if parts.query or parts.fragment:
        return None
    if parts.path not in ('', '/'):
        return None
    host, port = parts.hostname, parts.port
    if not host or not port:
        return None
    key = _loopback_key(host)
    if key is None:
        return None  # не loopback — не тестовый адрес
    if (key, port) not in _test_allowed_pairs:
        return None
    return parts.scheme, key, port


def read_get(op, params=None, _base_url=None):
    """Единственный путь в закрытый список внешних чтений (блокчейн, курсы,
    зеркало прод-поступлений).

    `op` — enum-ключ из `_READ_CHANNELS`, не URL: адрес, заголовки и ключ
    строит сам канал, вызывающий код передаёт только значения параметров.
    Возвращает (status_code|None, parsed_json|None, error_code|None).
    `_base_url` — только для тестов (как `_base_url` у tg_call), прод его не
    передаёт и не читает из env; проходит только зарегистрированный
    allow_test_target() loopback-адрес, иначе — 'invalid_base_url' до сети.
    """
    import requests
    import urllib3

    spec = _READ_CHANNELS.get(op)
    if spec is None:
        return None, None, 'unknown_op'
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None, None, 'invalid_params'

    validators = spec['params']
    if set(params) - set(validators):
        return None, None, 'unknown_param'  # неизвестный параметр — отказ до сети
    if spec['required'] - set(params):
        return None, None, 'missing_param'

    query = {}
    for name, value in params.items():
        if isinstance(value, (list, tuple, dict, set)):
            return None, None, 'invalid_param'  # дубли/multi-value так и приходят — список значений
        if isinstance(value, bool) or not validators[name](value):
            return None, None, 'invalid_param'
        query[name] = value

    headers = {}
    key_env = spec.get('key_env')
    if key_env:
        key = os.environ.get(key_env, '').strip()
        if key:
            if spec.get('key_header'):
                headers[spec['key_header']] = key
            elif spec.get('key_param'):
                query[spec['key_param']] = key
        elif not spec.get('key_optional'):
            return None, None, 'no_key'

    host = spec['host']
    permit_host = host
    permit_pairs = set()
    if _base_url is not None:
        allowed = _validate_base_url_override(_base_url)
        if allowed is None:
            return None, None, 'invalid_base_url'
        scheme, key, port = allowed
        base = f'{scheme}://{key}:{port}'
        permit_host = key
        permit_pairs = {(key, port)}
    else:
        base = f'https://{host}'
    url = f'{base}{spec["path"]}'

    deadline = time.monotonic() + _READ_TOTAL_DEADLINE
    _read_ctx.pending_host = permit_host
    _read_ctx.pending_pairs = permit_pairs
    try:
        session = requests.Session()
        session.trust_env = False
        adapter = _read_channel_adapter()
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        try:
            remaining = max(0.05, deadline - time.monotonic())
            resp = session.get(url, params=query, headers=headers, timeout=remaining,
                               allow_redirects=False, stream=True, proxies={})
            try:
                if resp.status_code in _READ_REDIRECT_CODES:
                    return resp.status_code, None, 'redirect_blocked'
                try:
                    raw = resp.raw.read(_MAX_READ_RESPONSE_BYTES + 1, decode_content=True)
                except urllib3.exceptions.ReadTimeoutError:
                    return None, None, 'read_timeout'
                except (urllib3.exceptions.ProtocolError,
                        requests.exceptions.ChunkedEncodingError,
                        ConnectionError) as exc:
                    return None, None, 'read_error'
                if len(raw) > _MAX_READ_RESPONSE_BYTES:
                    return resp.status_code, None, 'response_too_large'
                if resp.status_code == 429:
                    return resp.status_code, None, 'http_429'
                if 500 <= resp.status_code < 600:
                    return resp.status_code, None, 'http_5xx'
                if 400 <= resp.status_code < 500:
                    return resp.status_code, None, 'http_4xx'
                try:
                    data = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    return resp.status_code, None, 'invalid_json'
                return resp.status_code, data, None
            finally:
                resp.close()
        finally:
            session.close()
    except requests.exceptions.Timeout:
        return None, None, 'timeout'
    except requests.exceptions.SSLError:
        return None, None, 'tls_error'
    except requests.exceptions.ChunkedEncodingError:
        return None, None, 'read_error'
    except requests.exceptions.RequestException:
        # Текст исключения requests нередко содержит сам URL/параметры — наружу
        # уходит только стабильный код, как и в tg_call.
        return None, None, 'network_error'
    except Exception:
        # Любая другая ошибка транспорта (в том числе низкоуровневый
        # ConnectionRefusedError guard'а, если тест/код в обход requests сам
        # открыл сокет) — read_get никогда не поднимает исключение наружу,
        # как и tg_call.
        return None, None, 'network_error'
    finally:
        _read_ctx.pending_host = None
        _read_ctx.pending_pairs = set()
