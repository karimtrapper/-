# Реферальный кабинет: вход через Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить per-referrer режим входа в кабинет `/ref/<token>`: `link` (открыт по ссылке, дефолт) или `telegram` (вход через Telegram Login Widget на @grusha_lk_bot, аккаунт должен совпасть с реферером).

**Architecture:** Flask/SQLAlchemy монолит (`app.py`). +2 колонки на `Referrer`. Виджет подписан токеном `REF_LOGIN_BOT_TOKEN`; бэкенд верифицирует HMAC, привязывает TG-id (trust-on-first-login), кладёт разрешение в подписанный cookie-сессию (30 дней). Фронт — статические `static/referrer/index.html` (кабинет) и `static/crm/crm.html` (настройка).

**Tech Stack:** Python 3, Flask, SQLAlchemy, pytest, ванильный JS, Telegram Login Widget.

Спека: `docs/specs/2026-07-06-referrer-telegram-auth-design.md`.

---

## Файлы

- Modify `app.py`:
  - модель `Referrer` (~265) — поля + `to_dict`
  - миграция (~914, рядом с `is_test`)
  - хелперы: `get_login_bot_token`, `get_bot_username`, `verify_telegram_auth`, `apply_referrer_tg_binding`, `ref_session_authorized`
  - `referrer_stats` (~5202) — гейт
  - новый `POST /api/ref/<token>/tg-login`
  - `create_payout_request` (~5372) + cancel (~5619) — гейт
  - `create_referrer` (~5675) / `update_referrer` (~5727) — приём `auth_mode`
- Modify `static/referrer/index.html` — экран входа + виджет
- Modify `static/crm/crm.html` — селект «Вход в кабинет»
- Test `tests/test_referrer_auth.py` (новый)

Замечание по окружению: `REF_LOGIN_BOT_TOKEN` уже записан в Railway env (@grusha_lk_bot), домен `/setdomain` выставлен. `SECRET_KEY`, `permanent_session_lifetime=30d`, cookie Secure/HttpOnly/SameSite=Lax — уже в `app.py`. `/api/ref/` — в `PUBLIC_PATHS` (login-эндпоинт не требует админ-сессии).

---

## Task 1: Модель — поля auth_mode, telegram_user_id + миграция

**Files:**
- Modify: `app.py` (класс `Referrer` ~265; `to_dict`; блок миграций ~914)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Написать падающий тест**

Создать `tests/test_referrer_auth.py`:

```python
"""Тесты входа в реферальный кабинет через Telegram."""
import pytest, sys, os, secrets, hmac, hashlib, time, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'  # фиктивный, для HMAC

from app import app, get_session, Referrer, verify_telegram_auth, apply_referrer_tg_binding


@pytest.fixture(autouse=True)
def clean_db():
    s = get_session()
    try:
        s.query(Referrer).delete(); s.commit()
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(Referrer).delete(); s.commit()
    finally:
        s.close()


def _mk_referrer(**kw):
    s = get_session()
    try:
        r = Referrer(name=kw.get('name', 'Ed'), code=kw.get('code', 'GR-ED'),
                     token=kw.get('token', secrets.token_hex(16)),
                     default_percent=10.0, telegram=kw.get('telegram', '@ed_test'),
                     auth_mode=kw.get('auth_mode', 'link'),
                     telegram_user_id=kw.get('telegram_user_id'))
        s.add(r); s.commit()
        return r.to_dict()
    finally:
        s.close()


def test_referrer_defaults_to_link_mode():
    d = _mk_referrer()
    assert d['auth_mode'] == 'link'
    assert d['telegram_user_id'] is None
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py::test_referrer_defaults_to_link_mode -v`
Expected: FAIL — `TypeError: 'auth_mode' is an invalid keyword argument` (поля ещё нет).

- [ ] **Step 3: Добавить поля в модель**

В классе `Referrer` после строки `is_test = Column(...)` добавить:

```python
    auth_mode = Column(String(20), default='link')       # 'link' | 'telegram'
    telegram_user_id = Column(BigInteger)                  # привязанный TG id (>2^31)
```

`BigInteger` нужен: Telegram ID уже длиннее 32 бит. Добавить в импорт SQLAlchemy
(строка ~120 `from sqlalchemy import Column, Integer, String, Float, ...`) —
дописать `BigInteger`:

```python
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
```

В `to_dict()` добавить в возвращаемый словарь (рядом с `'active': self.active,`):

```python
            'auth_mode': self.auth_mode or 'link',
            'telegram_user_id': self.telegram_user_id,
```

- [ ] **Step 4: Добавить миграцию**

В блоке миграций сразу после SQLite-ветки `is_test` (после строки `try: conn.execute(text("ALTER TABLE referrers ADD COLUMN is_test BOOLEAN DEFAULT 0"))` / `except: pass`) добавить:

```python
        # Вход в кабинет: режим + привязанный TG id
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS auth_mode VARCHAR(20) DEFAULT 'link'"))
                conn.execute(text("ALTER TABLE referrers ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT"))
            except Exception as e:
                print(f"ℹ️ referrers.auth_mode: {e}")
        else:
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN auth_mode VARCHAR(20) DEFAULT 'link'"))
            except: pass
            try: conn.execute(text("ALTER TABLE referrers ADD COLUMN telegram_user_id BIGINT"))
            except: pass
```

- [ ] **Step 5: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py::test_referrer_defaults_to_link_mode -v`
Expected: PASS.

(Если локальная `local.db` не подхватила колонки — удалить её: `rm -f Dev/CalcCRM/local.db`; тесты пересоздадут схему через `create_all`.)

- [ ] **Step 6: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): поля auth_mode + telegram_user_id + миграция"
```

---

## Task 2: Хелперы — токен бота, username, HMAC-верификация

**Files:**
- Modify: `app.py` (добавить функции рядом с `send_telegram_group`, ~4525)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Тесты HMAC**

Дописать в `tests/test_referrer_auth.py`:

```python
def _signed(data: dict, token='111:TEST_TOKEN'):
    """Собрать валидную подпись Telegram для data."""
    secret = hashlib.sha256(token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    data = dict(data)
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


def test_verify_ok():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is True


def test_verify_bad_hash():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    d['hash'] = 'deadbeef'
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is False


def test_verify_expired():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time()) - 90000})
    assert verify_telegram_auth(d, '111:TEST_TOKEN', max_age_sec=86400) is False


def test_verify_tampered_field():
    d = _signed({'id': 42, 'first_name': 'Ed', 'auth_date': int(time.time())})
    d['id'] = 999  # подменили после подписи
    assert verify_telegram_auth(d, '111:TEST_TOKEN') is False
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k verify -v`
Expected: FAIL — `ImportError: cannot import name 'verify_telegram_auth'`.

- [ ] **Step 3: Реализовать хелперы**

Добавить в `app.py` после функции `send_telegram_group` (после её `return False`, ~4553):

```python
# ── Вход реферера через Telegram Login Widget ──────────────────────────────
_login_bot_username_cache = None

def get_login_bot_token():
    """Токен бота для виджета входа. REF_LOGIN_BOT_TOKEN или фолбэк на нотификатор."""
    return (os.environ.get('REF_LOGIN_BOT_TOKEN')
            or os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()

def get_bot_username():
    """Username бота-логина без @ (getMe, кэш в памяти). None если токена нет."""
    global _login_bot_username_cache
    if _login_bot_username_cache is not None:
        return _login_bot_username_cache
    token = get_login_bot_token()
    if not token:
        return None
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        _login_bot_username_cache = r.json()['result']['username']
    except Exception as e:
        print(f'[LoginBot] getMe error: {e}')
        return None
    return _login_bot_username_cache

def verify_telegram_auth(data: dict, bot_token: str, max_age_sec: int = 86400) -> bool:
    """Проверка подписи Telegram Login Widget (HMAC-SHA256) и свежести auth_date."""
    if not bot_token or not data.get('hash'):
        return False
    received_hash = data['hash']
    secret = hashlib.sha256(bot_token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, str(received_hash)):
        return False
    try:
        if (time.time() - int(data.get('auth_date', 0))) > max_age_sec:
            return False
    except (TypeError, ValueError):
        return False
    return True
```

Добавить импорт `hmac` в шапку (`import hashlib` уже есть, ~15):

```python
import hmac
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k verify -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): HMAC-верификация Telegram Login + get_bot_username"
```

---

## Task 3: Логика привязки (trust-on-first-login)

**Files:**
- Modify: `app.py` (функция `apply_referrer_tg_binding` после хелперов Task 2)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Тесты привязки**

Дописать в `tests/test_referrer_auth.py`:

```python
def _get_referrer(rid_or_token):
    s = get_session()
    try:
        return s.query(Referrer).filter(Referrer.token == rid_or_token).first()
    finally:
        s.close()


def test_bind_by_username_match():
    d = _mk_referrer(telegram='@ed_test', token='t1')
    r = _get_referrer('t1')
    ok, err = apply_referrer_tg_binding(r, tg_id=42, tg_username='ed_test')
    assert ok is True and err is None
    assert _get_referrer('t1').telegram_user_id == 42


def test_bind_by_username_mismatch():
    _mk_referrer(telegram='@ed_test', token='t2')
    r = _get_referrer('t2')
    ok, err = apply_referrer_tg_binding(r, tg_id=42, tg_username='someone_else')
    assert ok is False and err


def test_bind_empty_username_trusts_first():
    _mk_referrer(telegram='', token='t3')
    r = _get_referrer('t3')
    ok, err = apply_referrer_tg_binding(r, tg_id=77, tg_username=None)
    assert ok is True
    assert _get_referrer('t3').telegram_user_id == 77


def test_prebound_id_must_match():
    _mk_referrer(telegram='@ed_test', token='t4', telegram_user_id=42)
    r = _get_referrer('t4')
    assert apply_referrer_tg_binding(r, tg_id=42, tg_username='ed_test')[0] is True
    r = _get_referrer('t4')
    ok, err = apply_referrer_tg_binding(r, tg_id=999, tg_username='ed_test')
    assert ok is False and err
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k bind -v`
Expected: FAIL — `cannot import name 'apply_referrer_tg_binding'`.

- [ ] **Step 3: Реализовать**

Добавить в `app.py` после `verify_telegram_auth`:

```python
def apply_referrer_tg_binding(referrer, tg_id, tg_username):
    """
    Привязка TG-аккаунта к рефереру (trust-on-first-login). Коммитит id при первом входе.
    Возвращает (ok: bool, error: str|None).
    - есть telegram_user_id → пришедший id обязан совпасть;
    - иначе задан referrer.telegram (@username) → сверка username, совпал → биндим id;
    - иначе → биндим первый вошедший id.
    """
    tg_id = int(tg_id)
    if referrer.telegram_user_id:
        if int(referrer.telegram_user_id) != tg_id:
            return False, 'Этот Telegram-аккаунт не привязан к кабинету'
        return True, None

    expected = (referrer.telegram or '').lstrip('@').strip().lower()
    if expected:
        got = (tg_username or '').lstrip('@').strip().lower()
        if got != expected:
            return False, 'Ваш Telegram не совпадает с указанным для этого реферера'

    # Биндим id (совпал username, либо username не задан → первый вошедший)
    s = get_session()
    try:
        r = s.query(Referrer).get(referrer.id)
        r.telegram_user_id = tg_id
        s.commit()
    finally:
        s.close()
    return True, None
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k bind -v`
Expected: PASS (4 теста).

- [ ] **Step 5: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): trust-on-first-login привязка TG-аккаунта"
```

---

## Task 4: Гейт stats + сессия + эндпоинт tg-login

**Files:**
- Modify: `app.py` (`ref_session_authorized` хелпер; `referrer_stats` ~5203; новый роут после `referrer_page`)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Тесты гейта и логина**

Дописать в `tests/test_referrer_auth.py`:

```python
def test_stats_link_mode_open():
    _mk_referrer(auth_mode='link', token='s1')
    with app.test_client() as c:
        r = c.get('/api/ref/s1/stats')
    assert r.status_code == 200 and r.get_json()['success'] is True


def test_stats_telegram_mode_requires_auth():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s2')
    with app.test_client() as c:
        r = c.get('/api/ref/s2/stats')
    assert r.status_code == 401
    assert r.get_json().get('auth_required') is True


def test_tg_login_grants_access():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s3')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'Ed', 'username': 'ed_test',
                           'auth_date': int(time.time())})
        r = c.post('/api/ref/s3/tg-login', json=payload)
        assert r.status_code == 200 and r.get_json()['success'] is True
        # теперь stats открыт в той же сессии
        r2 = c.get('/api/ref/s3/stats')
        assert r2.status_code == 200 and r2.get_json()['success'] is True


def test_tg_login_wrong_account_rejected():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s4')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'X', 'username': 'intruder',
                           'auth_date': int(time.time())})
        r = c.post('/api/ref/s4/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_login_bad_signature_rejected():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='s5')
    with app.test_client() as c:
        payload = _signed({'id': 42, 'first_name': 'Ed', 'username': 'ed_test',
                           'auth_date': int(time.time())})
        payload['hash'] = 'deadbeef'
        r = c.post('/api/ref/s5/tg-login', json=payload)
        assert r.status_code == 403
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k "stats or tg_login" -v`
Expected: FAIL (эндпоинта нет / stats не гейтит → 200 вместо 401).

- [ ] **Step 3: Хелпер сессии + гейт stats**

Добавить в `app.py` после `apply_referrer_tg_binding`:

```python
def ref_session_authorized(referrer, token) -> bool:
    """True если реферер в link-режиме ИЛИ в сессии есть валидная привязка по токену."""
    if (referrer.auth_mode or 'link') != 'telegram':
        return True
    auth = flask_session.get('ref_auth') or {}
    bound = auth.get(token)
    return bool(bound and referrer.telegram_user_id and int(bound) == int(referrer.telegram_user_id))
```

В `referrer_stats`, сразу после блока `if not referrer: ... 404` (после строки 5209), вставить:

```python
        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'bot_username': get_bot_username()}), 401
```

- [ ] **Step 4: Эндпоинт tg-login**

Добавить в `app.py` сразу после функции `referrer_page` (после строки 5199):

```python
@app.route('/api/ref/<token>/tg-login', methods=['POST'])
def referrer_tg_login(token):
    """Вход реферера в кабинет через Telegram Login Widget."""
    data = request.get_json(silent=True) or {}
    db = get_session()
    try:
        referrer = db.query(Referrer).filter(Referrer.token == token, Referrer.active == True).first()
    finally:
        db.close()
    if not referrer:
        return jsonify({'success': False, 'error': 'Реферер не найден'}), 404

    bot_token = get_login_bot_token()
    if not verify_telegram_auth(data, bot_token):
        return jsonify({'success': False, 'error': 'Подпись Telegram недействительна или устарела'}), 403

    ok, err = apply_referrer_tg_binding(referrer, data.get('id'), data.get('username'))
    if not ok:
        return jsonify({'success': False, 'error': err}), 403

    flask_session.permanent = True
    auth = dict(flask_session.get('ref_auth') or {})
    auth[token] = int(data['id'])
    flask_session['ref_auth'] = auth
    return jsonify({'success': True})
```

- [ ] **Step 5: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 6: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): гейт stats + эндпоинт tg-login с сессией"
```

---

## Task 5: Гейт payout-эндпоинтов в telegram-режиме

**Files:**
- Modify: `app.py` (`create_payout_request` ~5372; cancel ~5619)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Тест**

Дописать:

```python
def test_payout_request_blocked_without_tg_auth():
    _mk_referrer(auth_mode='telegram', telegram='@ed_test', token='p1')
    with app.test_client() as c:
        r = c.post('/api/ref/p1/payout-request',
                   json={'wallet': 'x', 'contact_method': 'telegram', 'contact_value': '@ed_test'})
    assert r.status_code == 401
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k payout -v`
Expected: FAIL — вернёт 400 (нет средств), не 401.

- [ ] **Step 3: Добавить гейт**

В `create_payout_request`, сразу после получения `referrer` и проверки `if not referrer: ... 404` (после строки 5394), вставить:

```python
        if not ref_session_authorized(referrer, token):
            return jsonify({'success': False, 'auth_required': True,
                            'error': 'Требуется вход через Telegram'}), 401
```

В `cancel_payout_request` (~5619) аналогично — после того как получен `referrer` и проверен на существование, добавить тот же блок. Открыть файл и вставить сразу после проверки `if not referrer`.

- [ ] **Step 4: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -v`
Expected: PASS (все).

- [ ] **Step 5: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): гейт payout-эндпоинтов в telegram-режиме"
```

---

## Task 6: CRUD-эндпоинты принимают auth_mode

**Files:**
- Modify: `app.py` (`create_referrer` ~5710; `update_referrer` ~5754)
- Test: `tests/test_referrer_auth.py`

- [ ] **Step 1: Тест**

Дописать:

```python
def test_create_referrer_with_telegram_mode():
    with app.test_client() as c:
        r = c.post('/api/referrers', json={'name': 'Zed', 'auth_mode': 'telegram', 'telegram': '@zed'})
        assert r.status_code == 200
        assert r.get_json()['referrer']['auth_mode'] == 'telegram'


def test_update_referrer_auth_mode_validated():
    rid = _mk_referrer(token='u1')['id']
    with app.test_client() as c:
        c.put(f'/api/referrers/{rid}', json={'auth_mode': 'garbage'})
        r = c.get('/api/ref/u1/stats')  # мусор → остался link → открыт
    assert r.status_code == 200
```

- [ ] **Step 2: Прогнать — падает**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -k "create_referrer_with or auth_mode_validated" -v`
Expected: FAIL (auth_mode не сохраняется → дефолт link, первый тест падает на assert 'telegram').

- [ ] **Step 3: Реализовать**

В `create_referrer`, в конструктор `Referrer(...)` (после `is_test=...,`) добавить:

```python
            auth_mode=('telegram' if (data.get('auth_mode') == 'telegram') else 'link'),
```

В `update_referrer`, перед `db.commit()` (после блока `if 'total_paid_usdt' in data:`) добавить:

```python
        if 'auth_mode' in data:
            referrer.auth_mode = 'telegram' if data['auth_mode'] == 'telegram' else 'link'
```

- [ ] **Step 4: Прогнать — проходит**

Run: `cd Dev/CalcCRM && python -m pytest tests/test_referrer_auth.py -v`
Expected: PASS (все).

- [ ] **Step 5: Коммит**

```bash
cd Dev/CalcCRM
git add app.py tests/test_referrer_auth.py
git commit -m "feat(referrer): CRUD принимает auth_mode"
```

---

## Task 7: Фронт кабинета — экран входа + виджет

**Files:**
- Modify: `static/referrer/index.html` (`loadStats` ~357; добавить контейнер + функции)

- [ ] **Step 1: Обработать 401 в loadStats**

В `loadStats`, заменить блок:

```javascript
            const resp = await fetch(`/api/ref/${token}/stats`);
            const d = await resp.json();
            statsData = d;
            if (!d.success) {
                document.getElementById('app').innerHTML = '<div class="error">Реферер не найден</div>';
                return;
            }
```

на:

```javascript
            const resp = await fetch(`/api/ref/${token}/stats`);
            const d = await resp.json();
            statsData = d;
            if (resp.status === 401 && d.auth_required) {
                renderTelegramLogin(d.bot_username);
                return;
            }
            if (!d.success) {
                document.getElementById('app').innerHTML = '<div class="error">Реферер не найден</div>';
                return;
            }
```

- [ ] **Step 2: Функции входа**

Добавить перед `async function loadStats() {` (около строки 357):

```javascript
    // Экран входа через Telegram (для рефереров с auth_mode='telegram')
    window.onTgAuth = async function (user) {
        try {
            const resp = await fetch(`/api/ref/${token}/tg-login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(user),
            });
            const d = await resp.json();
            if (d.success) { location.reload(); return; }
            document.getElementById('tg-login-error').textContent =
                d.error || 'Не удалось войти';
        } catch (e) {
            document.getElementById('tg-login-error').textContent = 'Ошибка сети';
        }
    };

    function renderTelegramLogin(botUsername) {
        const app = document.getElementById('app');
        if (!botUsername) {
            app.innerHTML = '<div class="error">Вход через Telegram временно недоступен</div>';
            return;
        }
        app.innerHTML = `
          <div style="max-width:420px;margin:80px auto;text-align:center;padding:24px;">
            <h2 style="font-size:20px;margin-bottom:8px;">Вход в кабинет</h2>
            <p style="color:#64748b;font-size:14px;margin-bottom:24px;">
              Подтвердите, что это ваш кабинет — войдите через Telegram.</p>
            <div id="tg-login-widget"></div>
            <div id="tg-login-error" style="color:#ef4444;font-size:13px;margin-top:14px;"></div>
          </div>`;
        const s = document.createElement('script');
        s.async = true;
        s.src = 'https://telegram.org/js/telegram-widget.js?22';
        s.setAttribute('data-telegram-login', botUsername);
        s.setAttribute('data-size', 'large');
        s.setAttribute('data-onauth', 'onTgAuth(user)');
        s.setAttribute('data-request-access', 'write');
        document.getElementById('tg-login-widget').appendChild(s);
    }
```

- [ ] **Step 3: Проверить локально (smoke)**

Run: `cd Dev/CalcCRM && python -c "import app"` — импорт без ошибок.
Визуально: виджет проверяется на проде (Task 9), т.к. требует настроенного домена бота.

- [ ] **Step 4: Коммит**

```bash
cd Dev/CalcCRM
git add static/referrer/index.html
git commit -m "feat(referrer): экран входа через Telegram в кабинете"
```

---

## Task 8: CRM — селект «Вход в кабинет»

**Files:**
- Modify: `static/crm/crm.html` (форма ~2270; `openReferrerModal` ~7845; `editReferrer` ~7862; `saveReferrer` ~7884)

- [ ] **Step 1: Поле в форме**

В `referrerModal`, после блока «Валюта выплаты» (после строки 2270, `</div>` группы payout-currency), вставить:

```html
                <div class="form-group" style="margin-bottom: 1rem;">
                    <label class="form-label">Вход в кабинет</label>
                    <select class="form-control" id="referrerAuthMode">
                        <option value="link">По ссылке (открыт всем с ссылкой)</option>
                        <option value="telegram">Через Telegram (только свой аккаунт)</option>
                    </select>
                    <small style="color: var(--text-muted); font-size: 12px; margin-top: 4px; display: block;">
                        «Через Telegram» — при первом входе кабинет привяжется к TG-аккаунту реферера (по @username).
                    </small>
                </div>
```

- [ ] **Step 2: Сброс в openReferrerModal**

В `openReferrerModal`, после строки `document.getElementById('referrerPayoutCurrency').value = 'USDT';` добавить:

```javascript
            document.getElementById('referrerAuthMode').value = 'link';
```

- [ ] **Step 3: Заполнение в editReferrer**

В `editReferrer`, после строки `document.getElementById('referrerPayoutCurrency').value = r.payout_currency || 'USDT';` добавить:

```javascript
            document.getElementById('referrerAuthMode').value = r.auth_mode || 'link';
```

- [ ] **Step 4: Отправка в saveReferrer**

В `saveReferrer`, в объект `payload` добавить строку (после `notes: ...`):

```javascript
                auth_mode: document.getElementById('referrerAuthMode').value || 'link',
```

- [ ] **Step 5: Коммит**

```bash
cd Dev/CalcCRM
git add static/crm/crm.html
git commit -m "feat(crm): селект режима входа в кабинет реферера"
```

---

## Task 9: Полный прогон + деплой + E2E

- [ ] **Step 1: Все тесты**

Run: `cd Dev/CalcCRM && python -m pytest -q`
Expected: все тесты проходят (236 старых + новые).

- [ ] **Step 2: Пуш**

```bash
cd Dev/CalcCRM
git push
```

Railway задеплоит из `main` автоматически (~1–2 мин).

- [ ] **Step 3: Проверить деплой**

Run: `curl -s -o /dev/null -w "%{http_code}" https://grusha.up.railway.app/`
Expected: `200`.

- [ ] **Step 4: E2E вручную (юзер)**

1. `/setdomain grusha.up.railway.app` у @grusha_lk_bot — **уже сделано**.
2. В CRM создать тестового реферера: имя любое, Telegram = свой `@username`, **Вход в кабинет = Через Telegram**.
3. Открыть `/ref/<token>` этого реферера → должен показаться виджет «Вход через Telegram».
4. Нажать виджет, подтвердить → попадаешь в кабинет.
5. Негатив: открыть тот же URL в приватном окне другим TG-аккаунтом → «не совпадает» / отказ.

- [ ] **Step 5: Обновить доки**

- Дописать в `.claude/docs/CLAUDE-calccrm.md`: новое поле `auth_mode`, эндпоинт `/api/ref/<token>/tg-login`, env `REF_LOGIN_BOT_TOKEN`, бот @grusha_lk_bot.
- Запись в `DECISIONS.md`: выбран отдельный логин-бот + trust-on-first-login.
- Обновить `wiki/daily/2026-07-06.md` (Done).

```bash
cd "/Users/karimamirov/Desktop/untitled folder"
git add .claude/docs/CLAUDE-calccrm.md DECISIONS.md wiki/daily/2026-07-06.md
git commit -m "docs: вход в реферальный кабинет через Telegram"
```

---

## Заметки по безопасности

- HMAC-подпись обязательна (`verify_telegram_auth`), `hmac.compare_digest`, TTL 24ч.
- Сессия — подписанный cookie (Flask `SECRET_KEY`), Secure/HttpOnly/SameSite=Lax уже настроены.
- Прямые API по токену (`stats`, `payout-request`, `cancel`) гейтятся в telegram-режиме → нельзя обойти виджет.
- `telegram_user_id` наружу клиенту не отдаётся (в `to_dict` — да, но `to_dict` уходит только в CRM/админ-ответах `/api/referrers`, не в публичный `stats`). Публичный `stats` формирует ответ отдельно и это поле не включает — проверить, что не добавили.
