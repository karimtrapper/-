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
_lk_ctx = threading.local()

_TG_HOST = 'api.telegram.org'
_TG_ALLOWED_METHODS = {'getMe', 'getWebhookInfo', 'getUpdates', 'sendMessage'}

_dp_ctx = threading.local()

_OR_HOST = 'openrouter.ai'
_OR_PATH = '/api/v1/chat/completions'
# Ключи payload, которые вообще может собрать docparse.py — 'tools'/'tool_choice'/
# внешний image URL сюда никогда не попадут, потому что их здесь нет в allowlist'е.
_DP_ALLOWED_KEYS = frozenset({'model', 'messages', 'response_format', 'max_tokens', 'temperature'})
_DP_IMAGE_URL_RE = re.compile(r'^data:image/png;base64,[A-Za-z0-9+/]+=*$')
_DP_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_DP_MAX_REQUEST_BYTES = 12 * 1024 * 1024
_DP_TOTAL_DEADLINE = 20.0

_read_ctx = threading.local()

_policy = None  # callable(channel, recipient, operation) -> bool, регистрируется set_policy()
_bot_identity = None  # (токен, адрес тестового сервера, имя, id, срок проверки)
_pinned_bot_id = None  # id первого подтверждённого бота в этом процессе
_BOT_IDENTITY_TTL = 60
_PROD_BOTS = {'grusha_lk_bot', 'grushath_bot'}

# ---- T14: профиль «только отправка» через прод-бот @grusha_lk_bot ----
#
# Отдельный от tg_call() путь: у lk_send_only СВОЙ токен (STAND_LK_BOT_TOKEN,
# никогда TELEGRAM_BOT_TOKEN/REF_LOGIN_BOT_TOKEN — они гасятся блоком
# STAND_MODE и остаются погашены) и СВОЙ разрешённый метод — ровно один,
# sendMessage. lk_call() физически не умеет собрать URL другого метода,
# поэтому getMe/getUpdates/getWebhookInfo/setWebhook и т. п. этим токеном
# невозможны даже при ошибке в вызывающем коде — не «запрещено политикой»,
# а «такого пути в коде нет».
#
# Идентичность бота проверяется ДО сети: bot_id — это цифры до первого ':'
# в самом токене (формат Bot API), сравниваются с STAND_LK_BOT_ID — независимо
# закреплённым числом, которое Карим положит из уже проверенного источника
# (не производное от токена — иначе подмена токена подменила бы и ожидание).
# Совпадения нет → профиль не делает вообще ни одного сетевого вызова.
# После ответа — почтконтроль (from.id/from.is_bot/from.username, chat.id/
# chat.type=private): расхождение защёлкивает профиль (_lk_blocked) навсегда
# для этого процесса — без ретраев и без перехода на tg_call().
_LK_EXPECTED_USERNAME = 'grusha_lk_bot'
_lk_blocked = False


def _lk_token():
    return os.environ.get('STAND_LK_BOT_TOKEN', '').strip()


def _lk_pinned_id():
    raw = os.environ.get('STAND_LK_BOT_ID', '').strip()
    if not re.fullmatch(r'[0-9]{1,20}', raw):
        return None
    value = int(raw)
    return value if value > 0 else None


def _lk_token_bot_id(token):
    match = re.match(r'^([0-9]{1,20}):', token or '')
    if not match:
        return None
    value = int(match.group(1))
    return value if value > 0 else None


def lk_configured():
    return bool(_lk_token())


def lk_preflight_ok():
    """Сверка до сети: токен есть, id закреплён и совпадает с префиксом токена."""
    if _lk_blocked:
        return False
    token = _lk_token()
    pinned = _lk_pinned_id()
    if not token or pinned is None:
        return False
    return _lk_token_bot_id(token) == pinned


def lk_status():
    if _lk_blocked:
        return 'bot_identity_mismatch'
    if not lk_configured():
        return 'disabled'
    if not lk_preflight_ok():
        return 'bot_identity_mismatch'
    return 'ready'


# Белый список полей payload: business_connection_id/allow_paid_broadcast/
# reply_markup/любые другие поля sendMessage — это лишний функционал, которого
# у send-only профиля быть не должно (лидер, QA N02). Отказ до сети, а не
# фильтрация «на всякий случай» — заведомо неожиданные поля не бывают в
# вызовах stand_notify, значит это либо ошибка вызывающего кода, либо попытка
# использовать канал не по назначению.
_LK_ALLOWED_PAYLOAD_KEYS = frozenset({'chat_id', 'text', 'parse_mode', 'disable_web_page_preview'})


def _lk_test_origin(value):
    """Accept only a complete IPv4 loopback origin, including an explicit port."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(https?)://127\.0\.0\.1:([0-9]{1,5})', value)
    if not match:
        return None
    port = int(match.group(2))
    if not 1 <= port <= 65535:
        return None
    return match.group(1), '127.0.0.1', port


class _LKConnectMixin:
    """Only the private HTTP connection may open the Telegram socket gate."""
    def connect(self):
        _lk_ctx.active = True
        _lk_ctx.host = getattr(_lk_ctx, 'pending_host', None)
        _lk_ctx.allowed_pairs = set(getattr(_lk_ctx, 'pending_pairs', ()) or ())
        try:
            return super().connect()
        finally:
            _lk_ctx.active = False
            _lk_ctx.host = None
            _lk_ctx.allowed_pairs = set()


def _lk_adapter():
    import urllib3
    from requests.adapters import HTTPAdapter

    class _HTTPConn(_LKConnectMixin, urllib3.connection.HTTPConnection):
        pass

    class _HTTPSConn(_LKConnectMixin, urllib3.connection.HTTPSConnection):
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


def lk_call(payload, _base_url=None):
    """Единственный путь для профиля lk_send_only — жёстко sendMessage.

    `_base_url` — только для тестов (фейковый сервер на loopback), прод его
    не передаёт и не читает из env; хост, отличный от loopback, отклоняется
    здесь же, до создания сессии (QA N02 — прод и так его никогда не передаёт,
    но тестовый override не должен превращаться в лазейку на произвольный хост).
    """
    import requests
    global _lk_blocked

    if not lk_preflight_ok():
        return {'ok': False, 'error': 'no_token' if not lk_configured() else 'bot_identity_mismatch'}

    test_origin = None
    if _base_url is not None:
        test_origin = _lk_test_origin(_base_url)
        if test_origin is None:
            return {'ok': False, 'error': 'invalid_base_url'}

    token = _lk_token()
    pinned = _lk_pinned_id()

    payload = dict(payload or {})
    if not set(payload.keys()) <= _LK_ALLOWED_PAYLOAD_KEYS:
        return {'ok': False, 'error': 'payload_not_allowed'}
    chat_id = payload.get('chat_id')
    if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
        return {'ok': False, 'error': 'invalid_chat_id'}
    if not can_send('telegram_lk', chat_id, 'sendMessage'):
        return {'ok': False, 'error': 'denied'}

    base = (_base_url or f'https://{_TG_HOST}').rstrip('/')
    url = f'{base}/bot{token}/sendMessage'

    _lk_ctx.pending_host = test_origin[1] if test_origin else _TG_HOST
    _lk_ctx.pending_pairs = {(test_origin[1], test_origin[2])} if test_origin else set()
    try:
        session = requests.Session()
        session.trust_env = False
        adapter = _lk_adapter()
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        try:
            resp = session.post(url, json=payload, timeout=10, allow_redirects=False, proxies={})
            try:
                data = resp.json()
            except ValueError:
                data = None
            if not isinstance(data, dict):
                # Не-JSON или битый ответ — ошибка доставки конкретному получателю,
                # не доказательство того, что это не наш бот: латч только на
                # ПОДТВЕРЖДЁННОЕ несовпадение идентичности в успешном ответе.
                return {'ok': False, 'error': 'tg_bad_response'}
            if resp.status_code != 200 or not data.get('ok'):
                # 401/403 (бота заблокировали/чужой чат)/429/5xx — временная или
                # адресная ошибка Telegram, канал остаётся рабочим для остальных
                # получателей. Код статуса отдаём, тело ответа — нет (QA N09).
                return {'ok': False, 'error': 'tg_http_error', 'status_code': resp.status_code}
            result = data.get('result') if isinstance(data.get('result'), dict) else {}
            sender = result.get('from') if isinstance(result.get('from'), dict) else {}
            chat = result.get('chat') if isinstance(result.get('chat'), dict) else {}
            valid = bool(
                sender.get('is_bot') is True
                and sender.get('id') == pinned
                and isinstance(sender.get('username'), str)
                and sender.get('username').lower() == _LK_EXPECTED_USERNAME
                and chat.get('id') == chat_id
                and chat.get('type') == 'private'
            )
            if not valid:
                _lk_blocked = True
                print('[STAND-LK] bot_identity_mismatch')
                return {'ok': False, 'error': 'bot_identity_mismatch'}
            return {'ok': True, 'status_code': resp.status_code, 'result': result}
        finally:
            session.close()
    except Exception:
        # Текст исключения requests часто содержит сам URL (…/bot<TOKEN>/…) —
        # ни его, ни оригинальное исключение никуда не отдаём и не логируем.
        return {'ok': False, 'error': 'tg_network_error'}
    finally:
        _lk_ctx.active = False
        _lk_ctx.host = None
        _lk_ctx.allowed_pairs = set()
        _lk_ctx.pending_host = None
        _lk_ctx.pending_pairs = set()


def expected_bot_username():
    """Имя бота стенда; боевые имена нельзя разрешить через env."""
    name = os.environ.get('STAND_BOT_USERNAME', 'grusha_stand_bot').strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', name) or name.lower() in _PROD_BOTS:
        return None
    return name


def bot_identity_status():
    return 'bot_identity_mismatch' if expected_bot_username() is None or (
        _bot_identity is not None and _bot_identity[3] is None) else None


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
    if getattr(_lk_ctx, 'active', False) and (key, port) in getattr(_lk_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_read_ctx, 'active', False) and (key, port) in getattr(_read_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_dp_ctx, 'active', False) and (key, port) in getattr(_dp_ctx, 'allowed_pairs', ()):
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
    if getattr(_lk_ctx, 'active', False) and h == getattr(_lk_ctx, 'host', None):
        return port is None or port == 443
    if getattr(_read_ctx, 'active', False) and h == getattr(_read_ctx, 'host', None):
        return port is None or port == 443
    if getattr(_dp_ctx, 'active', False) and h == getattr(_dp_ctx, 'host', None):
        return port is None or port == 443
    return False


def _ip_allowed(ip, port=None):
    if _loopback_pair_allowed(ip, port):
        return True
    if port is not None and (ip, port) in _db_pairs:
        return True
    if getattr(_tg_ctx, 'active', False) and port is not None and (ip, port) in getattr(_tg_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_lk_ctx, 'active', False) and port is not None and (ip, port) in getattr(_lk_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_read_ctx, 'active', False) and port is not None and (ip, port) in getattr(_read_ctx, 'allowed_pairs', ()):
        return True
    if getattr(_dp_ctx, 'active', False) and port is not None and (ip, port) in getattr(_dp_ctx, 'allowed_pairs', ()):
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
    if getattr(_lk_ctx, 'active', False) and h == getattr(_lk_ctx, 'host', None):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _lk_ctx.allowed_pairs = pairs | set(getattr(_lk_ctx, 'allowed_pairs', ()))
    if getattr(_read_ctx, 'active', False) and h == getattr(_read_ctx, 'host', None):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _read_ctx.allowed_pairs = pairs | set(getattr(_read_ctx, 'allowed_pairs', ()))
    if getattr(_dp_ctx, 'active', False) and h == getattr(_dp_ctx, 'host', None):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _dp_ctx.allowed_pairs = pairs | set(getattr(_dp_ctx, 'allowed_pairs', ()))
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

    expected = expected_bot_username()
    if expected is None:
        return {'ok': False, 'error': 'bot_identity_mismatch'}

    global _bot_identity, _pinned_bot_id
    identity_key = (token, _base_url, expected)

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
        if method != 'getMe' and not can_send('telegram', None, method):
            return {'ok': False, 'error': 'denied'}

    if method in ('sendMessage', 'getUpdates', 'getWebhookInfo') and (
            _bot_identity is None or _bot_identity[:3] != identity_key
            or _bot_identity[3] is None or _bot_identity[4] <= time.monotonic()):
        identity = tg_call('getMe', {}, _base_url=_base_url)
        if not identity.get('ok'):
            return {'ok': False, 'error': 'bot_identity_mismatch'}
    if method in ('sendMessage', 'getUpdates', 'getWebhookInfo') and _bot_identity[3] is None:
        return {'ok': False, 'error': 'bot_identity_mismatch'}

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
            if not isinstance(data, dict):
                data = {}
            result = {'ok': bool(data.get('ok')), 'status_code': resp.status_code, 'result': data.get('result')}
            if method == 'getMe':
                bot = data.get('result') if isinstance(data.get('result'), dict) else {}
                name, bot_id = bot.get('username'), bot.get('id')
                pinned_id = os.environ.get('STAND_BOT_ID', '').strip()
                previous_id = (_bot_identity[3] if _bot_identity and _bot_identity[:3] == identity_key else None)
                valid = bool(result['ok'] and isinstance(name, str) and name.lower() == expected.lower()
                             and name.lower() not in _PROD_BOTS and isinstance(bot_id, int)
                             and not isinstance(bot_id, bool) and bot_id > 0
                             and (not pinned_id or str(bot_id) == pinned_id)
                             and (previous_id is None or bot_id == previous_id)
                             and (_pinned_bot_id is None or bot_id == _pinned_bot_id))
                if valid:
                    _pinned_bot_id = bot_id
                _bot_identity = (*identity_key, bot_id if valid else None,
                                 time.monotonic() + _BOT_IDENTITY_TTL if valid else 0)
                if not valid:
                    print('[STAND-TG] bot_identity_mismatch')
                    return {'ok': False, 'error': 'bot_identity_mismatch'}
            return result
        finally:
            session.close()
    except Exception:
        if method == 'getMe':
            _bot_identity = (*identity_key, None, 0)
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
    'exgreen_thb_bank_rates': {
        # Публичные TT Buying курсы банков-застройщиков для фрихолд-сделок
        # в батах — читает тот же сервис, что отдаёт /api/rates на лендинге.
        'host': 'api.exgreen.pro',
        'path': '/api/thb-bank-rates',
        'params': {},
        'required': set(),
    },
}

_MAX_READ_RESPONSE_BYTES = 2 * 1024 * 1024
# Любой 3xx (300–399) — контролируемый отказ, не только «типичные» редиректы:
# 300/304/305/306 тоже не должны молча идти дальше как обычный ответ.
_READ_TOTAL_DEADLINE = 8.0  # секунд на всю операцию: connect + заголовки + тело


class _BodyDeadlineSocket:
    """Apply the operation deadline at every buffered socket read.

    A timeout is terminal: SocketIO marks itself poisoned after one. We never
    retry it. Buffered bytes are consumed by http.client without select(), and
    the library retains ownership of Content-Length/chunk/EOF framing.
    """
    def __init__(self, sock, deadline):
        self._sock = sock
        self._deadline = deadline
        self._io_refs = 0

    def recv_into(self, *args, **kwargs):
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout('deadline')
        self._sock.settimeout(remaining)
        return self._sock.recv_into(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def makefile(self, mode='r', buffering=None, *, encoding=None, errors=None, newline=None):
        # http.client creates its BufferedReader while parsing response headers.
        # Put the same deadline below that buffer, including for header reads.
        stream = socket.socket.makefile(self, mode, buffering, encoding=encoding,
                                        errors=errors, newline=newline)
        self._sock._io_refs += 1
        return stream

    def _decref_socketios(self):
        self._io_refs -= 1
        self._sock._decref_socketios()


def _bounded_http_body(resp, deadline, limit, *, compressed=False):
    """Читает HTTP framing до конца с общим сроком и лимитом готового тела.

    Только OCR разрешает gzip/deflate. Сжатые байты тоже ограничены `limit`;
    zlib за один шаг может выдать не больше оставшегося лимита плюс байт.
    """
    import http.client
    import zlib
    try:
        encoding = resp.headers.get('Content-Encoding', 'identity').strip().lower()
        if encoding not in (('identity', 'gzip', 'deflate') if compressed else ('identity',)):
            return None, 'unsupported_encoding'
        http_resp = resp.raw._fp
        socket_io = http_resp.fp.raw
        if not isinstance(socket_io._sock, _BodyDeadlineSocket):
            socket_io._sock = _BodyDeadlineSocket(socket_io._sock, deadline)
    except (AttributeError, TypeError):
        return None, 'read_error'
    if http_resp.length is not None and http_resp.length > limit:
        return None, 'too_large'
    decoder = (zlib.decompressobj(31 if encoding == 'gzip' else zlib.MAX_WBITS)
               if encoding != 'identity' else None)
    parts, size, wire_size = [], 0, 0
    try:
        while True:
            if deadline - time.monotonic() <= 0:
                return None, 'timeout'
            part = http_resp.read1(min(65536, limit + 1 - wire_size))
            if not part:
                if http_resp.length is not None and http_resp.length > 0:
                    return None, 'read_error'
                if http_resp.chunked and not http_resp.isclosed():
                    return None, 'read_error'
                if decoder is not None:
                    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                        return None, 'read_error'
                if deadline - time.monotonic() <= 0:
                    return None, 'timeout'
                return b''.join(parts), None
            wire_size += len(part)
            if wire_size > limit:
                return None, 'too_large'
            if decoder is None:
                size += len(part)
                parts.append(part)
                continue
            if decoder.eof:
                return None, 'read_error'  # хвост или ещё один gzip member
            pending = part
            while pending:
                if deadline - time.monotonic() <= 0:
                    return None, 'timeout'
                before = len(pending)
                decoded = decoder.decompress(pending, min(65536, limit + 1 - size))
                if deadline - time.monotonic() <= 0:
                    return None, 'timeout'
                size += len(decoded)
                if size > limit:
                    return None, 'too_large'
                if decoded:
                    parts.append(decoded)
                if decoder.unused_data:
                    return None, 'read_error'
                pending = decoder.unconsumed_tail
                if pending and len(pending) == before and not decoded:
                    return None, 'read_error'
                if decoder.eof and pending:
                    return None, 'read_error'
    except (socket.timeout, TimeoutError):
        return None, 'timeout'
    except (http.client.HTTPException, OSError, ValueError, zlib.error):
        return None, 'read_error'


class _ConnectScopedMixin:
    """Guard-разрешение выставляется СТРОГО на время своего connect() — не на
    весь HTTP-запрос. Если тест подменяет requests.Session.get/post целиком
    (сам метод, не транспорт), эта connect() вообще не вызывается —
    разрешение не открывается, и прямой сокет из того же потока получит
    отказ, как и положено (E2). Параметризован конкретным thread-local
    контекстом канала (_ctx) — read_get и docparse_post используют одну и
    ту же реализацию с разными контекстами (_read_ctx / _dp_ctx)."""
    _ctx = None

    def connect(self):
        ctx = self._ctx
        ctx.active = True
        ctx.host = getattr(ctx, 'pending_host', None)
        ctx.allowed_pairs = set(getattr(ctx, 'pending_pairs', ()) or ())
        try:
            result = super().connect()
            deadline = getattr(ctx, 'pending_deadline', None)
            if deadline is not None and self.sock is not None:
                self.sock = _BodyDeadlineSocket(self.sock, deadline)
            return result
        finally:
            ctx.active = False
            ctx.host = None
            ctx.allowed_pairs = set()


def _connect_scoped_adapter(ctx):
    """HTTPAdapter с одноразовым пулом, чьи соединения открывают guard-
    разрешение только на время своего connect() (см. _ConnectScopedMixin)."""
    import urllib3
    from requests.adapters import HTTPAdapter

    class _HTTPConn(_ConnectScopedMixin, urllib3.connection.HTTPConnection):
        _ctx = ctx

    class _HTTPSConn(_ConnectScopedMixin, urllib3.connection.HTTPSConnection):
        _ctx = ctx

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

    # identity — тело читается напрямую с сырого сокета (см. ниже), в обход
    # decode_content requests/urllib3; сжатый ответ без их распаковки был бы
    # мусором для json.loads.
    headers = {'Accept-Encoding': 'identity'}
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
    _read_ctx.pending_deadline = deadline
    try:
        session = requests.Session()
        session.trust_env = False
        adapter = _connect_scoped_adapter(_read_ctx)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, None, 'timeout'
            resp = session.get(url, params=query, headers=headers, timeout=remaining,
                               allow_redirects=False, stream=True, proxies={})
            try:
                if 300 <= resp.status_code < 400:
                    return resp.status_code, None, 'redirect_blocked'
                raw, read_err = _bounded_http_body(resp, deadline, _MAX_READ_RESPONSE_BYTES)
                if read_err:
                    return (resp.status_code if read_err == 'too_large' else None), None, (
                        'read_timeout' if read_err == 'timeout' else
                        'response_too_large' if read_err == 'too_large' else read_err)
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
        _read_ctx.pending_deadline = None


# ─────────── T15: канал распознавания документов (docparse_post) ───────────

_dp_auth_ctx = threading.local()


def docparse_request_scope():
    """Context manager: открывает разрешение на docparse.parse_file(stand=True)
    только для текущего потока и только на время исполнения. Вызывается
    ИСКЛЮЧИТЕЛЬНО из обработчика /api/docs/parse — после того как
    check_auth уже проверил сессию сотрудника. Прямой вызов parse_file() из
    фонового потока/скрипта, минуя HTTP-запрос через этот route, не находит
    авторизованный контекст на своём потоке и отказывает до сети (docparse.py
    проверяет docparse_request_authorized() до любой сетевой попытки)."""
    return _DocparseRequestScope()


class _DocparseRequestScope:
    def __enter__(self):
        from flask import g, has_request_context, request, session
        authorized = (has_request_context() and request.endpoint == 'docs_parse'
                      and request.method == 'POST'
                      and bool(session.get('user_id'))
                      and getattr(g, '_docparse_checked_user', None) == session.get('user_id'))
        _dp_auth_ctx.authorized = authorized
        _dp_auth_ctx.deadline = (getattr(g, '_docparse_started', time.monotonic())
                                 + _DP_TOTAL_DEADLINE) if authorized else None
        return self

    def __exit__(self, *exc):
        _dp_auth_ctx.authorized = False
        _dp_auth_ctx.deadline = None
        return False


def docparse_request_authorized():
    from flask import g, has_request_context, request, session
    return bool(getattr(_dp_auth_ctx, 'authorized', False)
                and has_request_context() and request.endpoint == 'docs_parse'
                and request.method == 'POST'
                and getattr(g, '_docparse_checked_user', None) == session.get('user_id')
                and session.get('user_id')
                and getattr(_dp_auth_ctx, 'deadline', None) is not None)


def docparse_remaining():
    if not docparse_request_authorized():
        return 0.0
    return max(0.0, _dp_auth_ctx.deadline - time.monotonic())


def _dp_content_item_ok(item):
    if not isinstance(item, dict):
        return False
    if item.get('type') == 'text':
        return set(item.keys()) == {'type', 'text'} and isinstance(item['text'], str)
    if item.get('type') == 'image_url':
        if set(item.keys()) != {'type', 'image_url'}:
            return False
        url = item.get('image_url')
        return (isinstance(url, dict) and set(url.keys()) == {'url'}
                and isinstance(url.get('url'), str) and bool(_DP_IMAGE_URL_RE.match(url['url'])))
    return False


def _valid_docparse_payload(payload):
    """Payload — фиксированная схема docparse.py, не то, что прислал браузер.

    Проверяется здесь, а не доверяется вызывающему коду: это последняя граница
    перед сетью. Модель — из закрытого списка (docparse.DEFAULT_MODEL/
    FALLBACK_MODELS), сообщения — только текст и data-URI PNG, без tools,
    внешних URL и произвольной response_format-схемы: response_format
    обязателен и должен побайтово совпадать со схемой docparse._schema() —
    не «какой-то валидный json_schema», а именно прод-схема (иначе чужой
    response_format мог бы вытащить из модели произвольные поля)."""
    if not isinstance(payload, dict) or set(payload.keys()) - _DP_ALLOWED_KEYS:
        return False
    if not {'model', 'messages', 'response_format'} <= set(payload.keys()):
        return False
    import docparse  # noqa: PLC0415 — только здесь, чтобы избежать цикла на уровне модулей
    if payload['model'] not in ([docparse.DEFAULT_MODEL] + docparse.FALLBACK_MODELS):
        return False
    messages = payload['messages']
    if not isinstance(messages, list) or len(messages) != 1:
        return False
    message = messages[0]
    if not isinstance(message, dict) or set(message.keys()) != {'role', 'content'} or message['role'] != 'user':
        return False
    content = message['content']
    if not isinstance(content, list) or not content:
        return False
    if content[0].get('type') != 'text' or not all(_dp_content_item_ok(item) for item in content):
        return False
    rf = payload['response_format']
    expected_rf = {'type': 'json_schema',
                  'json_schema': {'name': 'doc', 'strict': True, 'schema': docparse._schema()}}
    if rf != expected_rf:
        return False
    if 'max_tokens' in payload:
        mt = payload['max_tokens']
        if isinstance(mt, bool) or not isinstance(mt, int) or not (0 < mt <= 20000):
            return False
    if 'temperature' in payload and payload['temperature'] != 0:
        return False
    return True


def docparse_post(payload, timeout=_DP_TOTAL_DEADLINE, _base_url=None):
    """Единственный путь распознавания документов в OpenRouter на стенде.

    Ровно POST на chat/completions с ключом STAND_DOCPARSE_KEY, через тот же
    connect-scoped транспорт, что read_get (см. _ConnectScopedMixin) — guard
    открывает openrouter.ai только на время СВОЕГО connect(), не на весь
    вызов: перехват requests.Session.post целиком (мимо транспорта) или
    прямой socket.create_connection в этом же потоке во время вызова так и
    остаются заблокированными. `_base_url` — только для тестов (фейковый
    локальный сервер), прод его не передаёт.

    Возвращает (status_code|None, json|None, error_code|None): error_code не
    None — сеть не дошла до успешного JSON-ответа 200; тело читается с
    общим дедлайном: один HTTP-aware reader для обоих каналов применяет
    остаток срока на каждом низкоуровневом чтении и не повторяет чтение
    после socket timeout (такой SocketIO уже непригоден). Текст
    исключений SDK/requests наружу не отдаётся никогда.
    """
    import requests

    if not docparse_request_authorized():
        return None, None, 'no_request_context'
    timeout = min(timeout, docparse_remaining())
    if timeout <= 0:
        return None, None, 'timeout'
    deadline = min(_dp_auth_ctx.deadline, time.monotonic() + timeout)

    key = os.environ.get('STAND_DOCPARSE_KEY', '').strip()
    if not key:
        return None, None, 'no_key'
    if not _valid_docparse_payload(payload):
        return None, None, 'invalid_payload'
    body = json.dumps(payload).encode('utf-8')
    if len(body) > _DP_MAX_REQUEST_BYTES:
        return None, None, 'too_large'

    base = (_base_url or f'https://{_OR_HOST}').rstrip('/')
    url = f'{base}{_OR_PATH}'

    permit_host = _OR_HOST
    permit_pairs = set()
    if _base_url is not None:
        allowed = _validate_base_url_override(_base_url)
        if allowed is None:
            return None, None, 'invalid_base_url'
        _, key_host, port = allowed
        permit_host = key_host
        permit_pairs = {(key_host, port)}

    _dp_ctx.pending_host = permit_host
    _dp_ctx.pending_pairs = permit_pairs
    _dp_ctx.pending_deadline = deadline
    try:
        session = requests.Session()
        session.trust_env = False
        adapter = _connect_scoped_adapter(_dp_ctx)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, None, 'timeout'
            resp = session.post(url, data=body, headers={
                'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                'Accept-Encoding': 'identity'},
                timeout=remaining, allow_redirects=False, stream=True, proxies={})
            try:
                if 300 <= resp.status_code < 400:
                    return resp.status_code, None, 'redirect_blocked'
                raw, read_err = _bounded_http_body(resp, deadline, _DP_MAX_RESPONSE_BYTES,
                                                   compressed=True)
                if read_err:
                    return (resp.status_code if read_err == 'too_large' else None), None, read_err
                try:
                    data = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    return resp.status_code, None, 'bad_json'
                if not isinstance(data, dict):
                    return resp.status_code, None, 'bad_json'
                return resp.status_code, data, None
            finally:
                resp.close()
        finally:
            session.close()
    except requests.exceptions.Timeout:
        return None, None, 'timeout'
    except requests.exceptions.ChunkedEncodingError:
        return None, None, 'read_error'
    except requests.exceptions.RequestException:
        # Текст исключения requests нередко содержит сам URL/токен — наружу
        # уходит только стабильный код, как и в tg_call/read_get.
        return None, None, 'network_error'
    except Exception:
        return None, None, 'network_error'
    finally:
        _dp_ctx.pending_host = None
        _dp_ctx.pending_pairs = set()
        _dp_ctx.pending_deadline = None
