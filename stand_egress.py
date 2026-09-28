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


def lk_call(payload, _base_url=None):
    """Единственный путь для профиля lk_send_only — жёстко sendMessage.

    `_base_url` — только для тестов (фейковый сервер на loopback), прод его
    не передаёт и не читает из env.
    """
    import requests
    global _lk_blocked

    if not lk_preflight_ok():
        return {'ok': False, 'error': 'no_token' if not lk_configured() else 'bot_identity_mismatch'}

    token = _lk_token()
    pinned = _lk_pinned_id()

    payload = dict(payload or {})
    chat_id = payload.get('chat_id')
    if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
        return {'ok': False, 'error': 'invalid_chat_id'}
    if not can_send('telegram_lk', chat_id, 'sendMessage'):
        return {'ok': False, 'error': 'denied'}

    base = (_base_url or f'https://{_TG_HOST}').rstrip('/')
    url = f'{base}/bot{token}/sendMessage'

    _tg_ctx.active = True
    _tg_ctx.allowed_pairs = set()
    if _base_url:
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
            result = data.get('result') if isinstance(data.get('result'), dict) else {}
            sender = result.get('from') if isinstance(result.get('from'), dict) else {}
            chat = result.get('chat') if isinstance(result.get('chat'), dict) else {}
            valid = bool(
                data.get('ok') and resp.status_code == 200
                and sender.get('is_bot') is True
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
        _tg_ctx.active = False
        _tg_ctx.allowed_pairs = set()


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
    return False


def _ip_allowed(ip, port=None):
    if _loopback_pair_allowed(ip, port):
        return True
    if port is not None and (ip, port) in _db_pairs:
        return True
    if getattr(_tg_ctx, 'active', False) and port is not None and (ip, port) in getattr(_tg_ctx, 'allowed_pairs', ()):
        return True
    return False


def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if not _hostname_allowed(host, port if isinstance(port, int) else None):
        _record_block(f'getaddrinfo host={host}:{port}')
        raise socket.gaierror(-2, 'Имя или служба неизвестны (заблокировано egress-guard стенда)')
    infos = _orig_getaddrinfo(host, port, family, type, proto, flags)
    if host and str(host).strip('[]').lower() == _TG_HOST and getattr(_tg_ctx, 'active', False):
        pairs = {(info[4][0], info[4][1]) for info in infos}
        _tg_ctx.allowed_pairs = pairs | set(getattr(_tg_ctx, 'allowed_pairs', ()))
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
