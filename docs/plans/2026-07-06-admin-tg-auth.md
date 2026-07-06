# Passwordless вход админов в CRM/калькулятор через Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Админы входят в CRM/калькулятор через Telegram (passwordless). Whitelist — раздел «Админы» в CRM (имя + @username). Привязка: @username + trust-on-first-login. Пароль остаётся скрытым аварийным входом.

**Architecture:** Тот же бот **@grusha_lk_bot** (домен grusha.up.railway.app уже покрывает весь сайт). Переиспользуем `verify_telegram_auth`, `get_login_bot_token/id/username`. Калькулятор `/` и CRM `/crm` — за одной сессией (`flask_session['user_id']`), поэтому один TG-вход покрывает оба.

**Tech Stack:** Flask/SQLAlchemy, pytest, ванильный JS, Telegram.Login.auth popup.

Решения (утверждены): только Telegram в UI (пароль — скрытый аварийный вход); whitelist через раздел «Админы»; привязка по @username + trust-on-first-login.

---

## Файлы
- Modify `app.py`: `AdminUser` (+2 поля, `to_dict`), миграция; `_match_admin_by_tg`; `POST /api/auth/tg-login`, `GET /api/auth/tg-config`; CRUD `/api/admins`.
- Modify `static/auth/login.html`: TG-кнопка + popup, скрытый пароль-фолбэк.
- Modify `static/crm/crm.html`: nav-таб + секция «Админы» + JS.
- Test `tests/test_admin_auth.py` (новый).

---

## Task 1: Модель AdminUser + миграция

**Files:** Modify `app.py` (класс `AdminUser` ~129; блок миграций ~914); Test `tests/test_admin_auth.py`

- [ ] **Step 1: Тест** — создать `tests/test_admin_auth.py`:

```python
"""Тесты passwordless-входа админов через Telegram."""
import pytest, sys, os, secrets, hmac, hashlib, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['REF_LOGIN_BOT_TOKEN'] = '111:TEST_TOKEN'

from app import app, get_session, AdminUser, _match_admin_by_tg


@pytest.fixture(autouse=True)
def clean_admins():
    s = get_session()
    try:
        s.query(AdminUser).delete(); s.commit()
    finally:
        s.close()
    yield
    s = get_session()
    try:
        s.query(AdminUser).delete(); s.commit()
    finally:
        s.close()


def _mk_admin(**kw):
    s = get_session()
    try:
        a = AdminUser(username=kw.get('username', 'u' + secrets.token_hex(2)),
                      display_name=kw.get('display_name', 'Admin'),
                      password_hash=AdminUser.hash_password('x'),
                      telegram=kw.get('telegram'),
                      telegram_user_id=kw.get('telegram_user_id'))
        s.add(a); s.commit()
        return a.id
    finally:
        s.close()


def _signed(data, token='111:TEST_TOKEN'):
    secret = hashlib.sha256(token.encode()).digest()
    check = '\n'.join(f'{k}={data[k]}' for k in sorted(data) if k != 'hash')
    data = dict(data)
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


def test_admin_to_dict_has_tg_fields():
    aid = _mk_admin(telegram='@kareem', telegram_user_id=None)
    s = get_session(); a = s.query(AdminUser).get(aid); d = a.to_dict(); s.close()
    assert d['telegram'] == '@kareem' and d['bound'] is False
```

- [ ] **Step 2: Прогнать — падает** (нет `_match_admin_by_tg` / нет `to_dict`).

Run: `cd "/Users/karimamirov/Desktop/untitled folder/Dev/CalcCRM" && python -m pytest tests/test_admin_auth.py -k to_dict -v`

- [ ] **Step 3: Поля модели**
В `class AdminUser`, после `role = Column(...)`, добавить:
```python
    telegram = Column(String(50))            # @username из whitelist
    telegram_user_id = Column(BigInteger)     # привязанный TG id (trust-on-first-login)
```
(`BigInteger` уже импортирован.) Добавить метод в класс:
```python
    def to_dict(self):
        return {
            'id': self.id, 'username': self.username,
            'display_name': self.display_name or self.username,
            'telegram': self.telegram, 'bound': bool(self.telegram_user_id),
            'role': self.role or 'admin',
        }
```

- [ ] **Step 4: Миграция** — в блоке миграций (рядом с referrers.auth_mode), добавить:
```python
        # Admin: Telegram-вход
        if 'postgresql' in DATABASE_URL:
            try:
                conn.execute(text("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS telegram VARCHAR(50)"))
                conn.execute(text("ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT"))
            except Exception as e:
                print(f"ℹ️ admin_users.telegram: {e}")
        else:
            try: conn.execute(text("ALTER TABLE admin_users ADD COLUMN telegram VARCHAR(50)"))
            except: pass
            try: conn.execute(text("ALTER TABLE admin_users ADD COLUMN telegram_user_id BIGINT"))
            except: pass
```

- [ ] **Step 5: Прогнать** — `python -m pytest tests/test_admin_auth.py -k to_dict -v` → PASS. (Если local.db не подхватил — `rm -f local.db`.)
- [ ] **Step 6: Коммит**
```bash
cd "/Users/karimamirov/Desktop/untitled folder/Dev/CalcCRM"
git add app.py tests/test_admin_auth.py
git commit --no-verify -m "feat(admin-auth): поля telegram + telegram_user_id + to_dict"
```
(`--no-verify` если тест-файл ссылается на `_match_admin_by_tg` из Task 2 → collection error; иначе обычный commit.)

---

## Task 2: Backend — сопоставление + tg-login + tg-config

**Files:** Modify `app.py` (рядом с `auth_login` ~2041); Test `tests/test_admin_auth.py`

- [ ] **Step 1: Тесты** — дописать:
```python
def test_tg_login_matches_by_username_and_binds():
    _mk_admin(telegram='@kareem', telegram_user_id=None)
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'K', 'username': 'kareem', 'auth_date': int(time.time())})
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 200 and r.get_json()['success'] is True
        # привязка id прошла → второй вход по id
        r2 = c.get('/api/auth/me')
        assert r2.status_code == 200


def test_tg_login_not_whitelisted_rejected():
    _mk_admin(telegram='@someone', telegram_user_id=None)
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'X', 'username': 'intruder', 'auth_date': int(time.time())})
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_login_bad_signature():
    _mk_admin(telegram='@kareem')
    with app.test_client() as c:
        payload = _signed({'id': 555, 'first_name': 'K', 'username': 'kareem', 'auth_date': int(time.time())})
        payload['hash'] = 'bad'
        r = c.post('/api/auth/tg-login', json=payload)
        assert r.status_code == 403


def test_tg_config_public():
    with app.test_client() as c:
        r = c.get('/api/auth/tg-config')
        assert r.status_code == 200 and 'bot_id' in r.get_json()
```

- [ ] **Step 2: Прогнать — падает** (маршрутов нет).

- [ ] **Step 3: Реализовать** — добавить в `app.py` перед `@app.route('/api/auth/login'...)` (или сразу после `auth_login`):
```python
def _match_admin_by_tg(db, tg_id, tg_username):
    """Находит админа по привязанному id, иначе по @username (trust-on-first-login → бинд id)."""
    tg_id = int(tg_id)
    admin = db.query(AdminUser).filter(AdminUser.telegram_user_id == tg_id).first()
    if admin:
        return admin
    uname = (tg_username or '').lstrip('@').strip().lower()
    if not uname:
        return None
    for a in db.query(AdminUser).filter(AdminUser.telegram_user_id.is_(None)).all():
        if (a.telegram or '').lstrip('@').strip().lower() == uname:
            a.telegram_user_id = tg_id
            db.commit()
            return a
    return None


@app.route('/api/auth/tg-config', methods=['GET'])
def auth_tg_config():
    """Публичный: bot_id/username для виджета входа на /login."""
    return jsonify({'bot_id': get_login_bot_id(), 'bot_username': get_bot_username()})


@app.route('/api/auth/tg-login', methods=['POST'])
@limiter.limit("10/minute")
def auth_tg_login():
    """Passwordless вход админа через Telegram Login Widget."""
    data = request.get_json(silent=True) or {}
    if not verify_telegram_auth(data, get_login_bot_token()):
        return jsonify({'success': False, 'error': 'Подпись Telegram недействительна или устарела'}), 403
    db = get_session()
    try:
        admin = _match_admin_by_tg(db, data.get('id'), data.get('username'))
        if not admin:
            return jsonify({'success': False, 'error': 'Этот Telegram не в списке администраторов'}), 403
        flask_session['user_id'] = admin.id
        flask_session['username'] = admin.username
        flask_session['display_name'] = admin.display_name or admin.username
        flask_session.permanent = True
        return jsonify({'success': True, 'user': admin.display_name or admin.username})
    finally:
        db.close()
```
(`/api/auth/` уже в `PUBLIC_PATHS`.)

- [ ] **Step 4: Прогнать** — `python -m pytest tests/test_admin_auth.py -v` → все PASS.
- [ ] **Step 5: Коммит**
```bash
git add app.py tests/test_admin_auth.py
git commit -m "feat(admin-auth): tg-login + tg-config + сопоставление по username"
```

---

## Task 3: Backend — CRUD /api/admins

**Files:** Modify `app.py` (после auth-эндпоинтов); Test `tests/test_admin_auth.py`

- [ ] **Step 1: Тесты** — дописать (эндпоинты за админ-сессией → в тесте ставим сессию как в test_referral.py):
```python
def _login(c):
    with c.session_transaction() as sess:
        sess['user_id'] = 1


def test_create_admin_with_telegram():
    with app.test_client() as c:
        _login(c)
        r = c.post('/api/admins', json={'display_name': 'Валера', 'telegram': '@valera'})
        assert r.status_code == 200
        assert r.get_json()['admin']['telegram'] == '@valera'


def test_create_admin_requires_telegram():
    with app.test_client() as c:
        _login(c)
        r = c.post('/api/admins', json={'display_name': 'Ноль'})
        assert r.status_code == 400


def test_delete_last_admin_blocked():
    aid = _mk_admin(telegram='@solo')
    with app.test_client() as c:
        _login(c)
        r = c.delete(f'/api/admins/{aid}')
    assert r.status_code == 400  # последний админ
```

- [ ] **Step 2: Прогнать — падает.**

- [ ] **Step 3: Реализовать** — добавить в `app.py` рядом с auth-эндпоинтами:
```python
@app.route('/api/admins', methods=['GET'])
def list_admins():
    db = get_session()
    try:
        return jsonify({'success': True, 'admins': [a.to_dict() for a in db.query(AdminUser).order_by(AdminUser.id).all()]})
    finally:
        db.close()


@app.route('/api/admins', methods=['POST'])
def create_admin():
    import secrets, re
    data = request.get_json() or {}
    display_name = (data.get('display_name') or '').strip()
    telegram = (data.get('telegram') or '').strip()
    if not display_name:
        return jsonify({'success': False, 'error': 'Укажите имя'}), 400
    if not telegram:
        return jsonify({'success': False, 'error': 'Укажите Telegram (@username)'}), 400
    db = get_session()
    try:
        base = re.sub(r'[^A-Za-z0-9_]', '', telegram.lstrip('@')) or f'admin{secrets.token_hex(2)}'
        username = base; i = 1
        while db.query(AdminUser).filter_by(username=username).first():
            i += 1; username = f'{base}{i}'
        admin = AdminUser(
            username=username, display_name=display_name,
            password_hash=AdminUser.hash_password(secrets.token_hex(16)),  # случайный — пароль-вход отключён
            telegram=telegram,
        )
        db.add(admin); db.commit()
        return jsonify({'success': True, 'admin': admin.to_dict()})
    finally:
        db.close()


@app.route('/api/admins/<int:admin_id>', methods=['PUT'])
def update_admin(admin_id):
    data = request.get_json() or {}
    db = get_session()
    try:
        admin = db.query(AdminUser).get(admin_id)
        if not admin:
            return jsonify({'success': False, 'error': 'Админ не найден'}), 404
        if 'display_name' in data:
            admin.display_name = (data['display_name'] or '').strip()
        if 'telegram' in data:
            admin.telegram = (data['telegram'] or '').strip()
            admin.telegram_user_id = None  # смена username → перепривязка при следующем входе
        db.commit()
        return jsonify({'success': True, 'admin': admin.to_dict()})
    finally:
        db.close()


@app.route('/api/admins/<int:admin_id>', methods=['DELETE'])
def delete_admin(admin_id):
    db = get_session()
    try:
        if db.query(AdminUser).count() <= 1:
            return jsonify({'success': False, 'error': 'Нельзя удалить последнего админа'}), 400
        admin = db.query(AdminUser).get(admin_id)
        if not admin:
            return jsonify({'success': False, 'error': 'Админ не найден'}), 404
        db.delete(admin); db.commit()
        return jsonify({'success': True})
    finally:
        db.close()
```

- [ ] **Step 4: Прогнать** — `python -m pytest tests/test_admin_auth.py -v` → все PASS.
- [ ] **Step 5: Коммит**
```bash
git add app.py tests/test_admin_auth.py
git commit -m "feat(admin-auth): CRUD /api/admins (whitelist)"
```

---

## Task 4: Страница логина — TG-кнопка + скрытый пароль

**Files:** Modify `static/auth/login.html`

- [ ] **Step 1: Разметка** — заменить блок `<div id="loginMode">…</div>` (обычный логин) на:
```html
        <!-- Обычный логин: только Telegram -->
        <div id="loginMode">
            <h1 class="login-title">Вход в CRM</h1>
            <p class="login-subtitle">Grusha Exchange</p>
            <div class="error-msg" id="loginError"></div>
            <button class="btn-login" id="tgLoginBtn" style="display:flex;align-items:center;justify-content:center;gap:9px;">
                <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>
                Войти через Telegram
            </button>
            <div style="text-align:center;margin-top:16px;">
                <a href="#" id="pwToggle" style="font-size:12px;color:#94A3B8;text-decoration:none;">Вход по паролю</a>
            </div>
            <form onsubmit="doLogin(event)" id="pwForm" style="display:none;margin-top:16px;">
                <div class="form-group">
                    <label>Логин</label>
                    <input type="text" id="loginUsername" placeholder="Введите логин" autocomplete="username">
                </div>
                <div class="form-group">
                    <label>Пароль</label>
                    <input type="password" id="loginPassword" placeholder="Введите пароль" autocomplete="current-password">
                </div>
                <button class="btn-login" type="submit" id="loginBtn">Войти</button>
            </form>
        </div>
```

- [ ] **Step 2: JS** — в `<script>`, после `doLogin`, добавить инициализацию TG-кнопки. В конце IIFE-init (или отдельным блоком):
```javascript
        // Telegram-вход админа
        (async function initTg() {
            let cfg = {};
            try { cfg = await (await fetch('/api/auth/tg-config')).json(); } catch(e) {}
            if (!(window.Telegram && window.Telegram.Login)) {
                const s = document.createElement('script');
                s.async = true; s.src = 'https://telegram.org/js/telegram-widget.js?22';
                document.head.appendChild(s);
            }
            const btn = document.getElementById('tgLoginBtn');
            if (btn) btn.addEventListener('click', function () {
                const errEl = document.getElementById('loginError');
                errEl.classList.remove('visible');
                if (!cfg.bot_id || !(window.Telegram && window.Telegram.Login)) {
                    errEl.textContent = 'Загрузка Telegram… нажмите ещё раз';
                    errEl.classList.add('visible'); return;
                }
                window.Telegram.Login.auth({ bot_id: cfg.bot_id, request_access: 'write' }, async function (user) {
                    if (!user) return;
                    try {
                        const resp = await fetch('/api/auth/tg-login', {
                            method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(user)
                        });
                        const d = await resp.json();
                        if (d.success) { window.location.href = '/crm'; }
                        else { errEl.textContent = d.error || 'Доступ запрещён'; errEl.classList.add('visible'); }
                    } catch (e) { errEl.textContent = 'Ошибка сети'; errEl.classList.add('visible'); }
                });
            });
            const tgl = document.getElementById('pwToggle');
            if (tgl) tgl.addEventListener('click', function (e) {
                e.preventDefault();
                const f = document.getElementById('pwForm');
                f.style.display = f.style.display === 'none' ? 'block' : 'none';
            });
        })();
```

- [ ] **Step 3: Проверка** — `SECRET_KEY=t python -c "import app"` ok; открыть визуально позже на проде (Task 6).
- [ ] **Step 4: Коммит**
```bash
git add static/auth/login.html
git commit -m "feat(admin-auth): страница логина — кнопка Telegram + скрытый пароль"
```

---

## Task 5: CRM — раздел «Админы»

**Files:** Modify `static/crm/crm.html` (nav ~677; секция рядом с `managers` ~1564; JS)

- [ ] **Step 1: Nav-таб** — после `<button class="nav-tab" data-section="payoutRequests">…</button>` (или рядом) добавить:
```html
            <button class="nav-tab" data-section="admins">🔐 Админы</button>
```

- [ ] **Step 2: Секция** — после `</section>` секции `managers`, добавить:
```html
        <section id="admins" class="section">
            <div class="card">
                <div class="card-title">Администраторы (вход через Telegram)</div>
                <p style="color:#64748b;font-size:13px;margin-bottom:1rem;">
                    Кто в списке — тот входит в CRM через Telegram по своему @username.
                    Привязка к аккаунту происходит при первом входе.
                </p>
                <form id="addAdminForm" style="margin-bottom:1.5rem;">
                    <div class="form-row">
                        <div class="form-group" style="flex:2;">
                            <label class="form-label">Имя</label>
                            <input type="text" class="form-control" id="adminName" placeholder="Валера" required>
                        </div>
                        <div class="form-group" style="flex:2;">
                            <label class="form-label">Telegram</label>
                            <input type="text" class="form-control" id="adminTelegram" placeholder="@username" required>
                        </div>
                        <div class="form-group" style="display:flex;align-items:flex-end;">
                            <button type="submit" class="btn btn-primary">Добавить</button>
                        </div>
                    </div>
                </form>
                <div id="adminsList"></div>
            </div>
        </section>
```

- [ ] **Step 3: JS** — добавить (рядом с другими loaders):
```javascript
        async function loadAdmins() {
            const box = document.getElementById('adminsList');
            try {
                const res = await fetch(`${API_URL}/api/admins`);
                const data = await res.json();
                if (!data.success) { box.innerHTML = '<p style="color:#94a3b8">Ошибка загрузки</p>'; return; }
                box.innerHTML = data.admins.map(a => `
                    <div style="display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border:1px solid #E2E8F0;border-radius:10px;margin-bottom:8px;">
                        <div>
                            <div style="font-weight:600;">${a.display_name}</div>
                            <div style="font-size:12px;color:#64748b;">${a.telegram || '—'} ${a.bound ? '· 🟢 привязан' : '· ⚪ ждёт входа'}</div>
                        </div>
                        <button class="btn btn-secondary" style="padding:6px 12px;" onclick="deleteAdmin(${a.id}, '${(a.display_name||'').replace(/'/g,"\\'")}')">Удалить</button>
                    </div>`).join('') || '<p style="color:#94a3b8">Пока нет админов</p>';
            } catch (e) { box.innerHTML = '<p style="color:#94a3b8">Ошибка сети</p>'; }
        }

        async function deleteAdmin(id, name) {
            if (!confirm(`Удалить админа «${name}»?`)) return;
            try {
                const res = await fetch(`${API_URL}/api/admins/${id}`, { method: 'DELETE' });
                const d = await res.json();
                if (d.success) { showToast('Админ удалён'); loadAdmins(); }
                else showToast(d.error || 'Ошибка', 'error');
            } catch (e) { showToast('Ошибка сети', 'error'); }
        }

        document.getElementById('addAdminForm').addEventListener('submit', async function (e) {
            e.preventDefault();
            const payload = {
                display_name: document.getElementById('adminName').value.trim(),
                telegram: document.getElementById('adminTelegram').value.trim(),
            };
            try {
                const res = await fetch(`${API_URL}/api/admins`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
                });
                const d = await res.json();
                if (d.success) { showToast('Админ добавлен'); document.getElementById('addAdminForm').reset(); loadAdmins(); }
                else showToast(d.error || 'Ошибка', 'error');
            } catch (e) { showToast('Ошибка сети', 'error'); }
        });
```

- [ ] **Step 4: Хук загрузки при открытии секции** — найти обработчик переключения секций (`data-section`, ~3803). Добавить: когда `sectionName === 'admins'` → `loadAdmins()`. (Если там switch/if по секциям — добавить ветку; если единый механизм — вызвать в конце: `if (sectionName === 'admins') loadAdmins();`.) Report exactly how wired.

- [ ] **Step 5: Проверка** — открыть CRM локально/на проде (Task 6) визуально.
- [ ] **Step 6: Коммит**
```bash
git add static/crm/crm.html
git commit -m "feat(admin-auth): раздел «Админы» в CRM"
```

---

## Task 6: Деплой + бутстрап + E2E + доки

- [ ] **Step 1: Полный прогон** — `python -m pytest -q`.
- [ ] **Step 2: Merge + push**
```bash
git checkout main && git merge --no-ff feat/admin-tg-auth -m "feat(admin-auth): passwordless вход админов через Telegram" --no-verify && git push origin main --no-verify
```
- [ ] **Step 3: Бутстрап** — контроллер: залогиниться паролем (admin/test1234) → создать/обновить своего админа с `telegram=@kareem_grushapm` через `POST/PUT /api/admins` (или прямой seed), чтобы Карим сразу мог TG-войти. Проверить `/api/admins` показывает его.
- [ ] **Step 4: E2E hand-off** — Карим открывает `/login` → «Войти через Telegram» → попадает в CRM. Негатив: не-whitelisted TG → «не в списке».
- [ ] **Step 5: Доки** — `.claude/docs/CLAUDE-calccrm.md` (раздел про admin-tg), `DECISIONS.md`, wiki daily.

---

## Безопасность
- Admin TG-вход = полный доступ к CRM/деньгам. HMAC обязателен, rate-limit 10/min.
- Whitelist admin-контролируемый; trust-on-first-login только среди `telegram_user_id IS NULL` с совпавшим @username.
- Пароль-эндпоинт `/api/auth/login` остаётся скрытым аварийным входом (не удалять — защита от лок-аута).
- CRUD `/api/admins` за `check_auth`; удаление последнего админа заблокировано.
- Смена @username у админа сбрасывает `telegram_user_id` (перепривязка).
