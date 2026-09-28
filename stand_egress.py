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
во что оно в итоге резолвится (иначе «внешний хост резолвится в loopback»
само стало бы обходом: loopback разрешён всегда, и адрес фейкового сервера
прошёл бы как «свой»). По той же причине сравнение хоста — точное, не по
суффиксу/подстроке.

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

_DEFAULT_DB_PORT = 5432

_db_host = None
_db_port = None
_db_pairs = frozenset()  # {(ip, port)} — точная пара, не просто «IP базы»

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


def _hostname_allowed(host, port=None):
    """Решение по запрошенному имени — до резолва. Хост сравнивается точно
    (не суффиксом/подстрокой), порт базы — тоже точно (иначе тот же хост на
    другом порту прошёл бы как «свой»)."""
    if _is_loopback_host(host):
        return True
    if host is None:
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
    if _is_loopback_host(ip):
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


def install():
    """Ставит сетевой guard. No-op вне STAND_MODE и при повторном вызове."""
    global _installed, _orig_connect, _orig_connect_ex, _orig_getaddrinfo
    global _orig_create_connection, _orig_sendto, _orig_sendmsg
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
    except Exception:
        # Текст исключения requests часто содержит сам URL (…/bot<TOKEN>/method) —
        # ни его, ни оригинальное исключение никуда не отдаём и не логируем.
        return {'ok': False, 'error': 'tg_network_error'}
    finally:
        _tg_ctx.active = False
        _tg_ctx.allowed_ips = set()


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


def read_get(op, params=None, _base_url=None):
    """Единственный путь в закрытый список внешних чтений (блокчейн, курсы,
    зеркало прод-поступлений).

    `op` — enum-ключ из `_READ_CHANNELS`, не URL: адрес, заголовки и ключ
    строит сам канал, вызывающий код передаёт только значения параметров.
    Возвращает (status_code|None, parsed_json|None, error_code|None).
    `_base_url` — только для тестов (как `_base_url` у tg_call), прод его не
    передаёт и не читает из env.
    """
    import requests

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
    base = (_base_url or f'https://{host}').rstrip('/')
    url = f'{base}{spec["path"]}'

    _read_ctx.active = True
    _read_ctx.host = host
    _read_ctx.allowed_pairs = set()
    try:
        session = requests.Session()
        session.trust_env = False
        try:
            resp = session.get(url, params=query, headers=headers, timeout=8,
                               allow_redirects=False, stream=True)
            try:
                if resp.status_code in _READ_REDIRECT_CODES:
                    return resp.status_code, None, 'redirect_blocked'
                raw = resp.raw.read(_MAX_READ_RESPONSE_BYTES + 1, decode_content=True)
                if len(raw) > _MAX_READ_RESPONSE_BYTES:
                    return resp.status_code, None, 'response_too_large'
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
    except requests.exceptions.RequestException:
        # Текст исключения requests нередко содержит сам URL/параметры — наружу
        # уходит только стабильный код, как и в tg_call.
        return None, None, 'network_error'
    finally:
        _read_ctx.active = False
        _read_ctx.host = None
        _read_ctx.allowed_pairs = set()
