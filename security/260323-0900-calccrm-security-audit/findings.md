# Security Findings — CalcCRM

**Audit date:** 2026-03-23
**Auditor:** autoresearch:security (Claude)

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3 |
| HIGH | 4 |
| MEDIUM | 5 |
| LOW | 2 |
| **Total** | **14** |

---

## CRITICAL Findings

### C1. Слабое хэширование паролей (SHA-256 + статическая соль)
- **Файл:** `app.py:102-105`
- **STRIDE:** Spoofing
- **OWASP:** A02:2021 Cryptographic Failures
- **Описание:** Пароли хэшируются SHA-256 с hardcoded солью `grusha-salt-2026`. SHA-256 — НЕ password hashing function: нет key stretching, одинаковая соль для всех. Атакующий с доступом к БД расшифрует за минуты через rainbow tables.
- **PoC:** `hashlib.sha256('grusha-salt-2026admin_password'.encode()).hexdigest()` — мгновенный reverse lookup
- **Рекомендация:** Заменить на `bcrypt` или `argon2id`. Добавить уникальную per-user соль. Миграция: при следующем логине — rehash.
- **Effort:** 2 часа

### C2. Hardcoded secret key fallback
- **Файл:** `app.py:21`
- **STRIDE:** Spoofing, Tampering
- **OWASP:** A02:2021 Cryptographic Failures
- **Описание:** `app.secret_key = os.environ.get('SECRET_KEY', 'grusha-crm-secret-change-in-prod-2026')`. Если env-переменная не задана — используется hardcoded ключ, опубликованный в git. Позволяет подделывать Flask-сессии = полный доступ к CRM.
- **Валидация:** Проверить на проде: если SECRET_KEY задан в Railway env — фактический риск LOW. Если НЕ задан — CRITICAL.
- **Рекомендация:** Убрать fallback. Крашить приложение если SECRET_KEY не задан: `app.secret_key = os.environ['SECRET_KEY']`
- **Effort:** 15 минут

### C3. Doverka webhook без верификации подписи
- **Файл:** `app.py:2693-2703`
- **STRIDE:** Tampering
- **OWASP:** A08:2021 Software and Data Integrity Failures
- **Описание:** Webhook принимает POST JSON и при `status: PAID` отправляет Telegram-уведомление. Нет проверки HMAC/подписи. Однако endpoint сейчас ЗАЩИЩЁН auth middleware (не в PUBLIC_PATHS) — Doverka НЕ сможет отправить webhook. Это означает:
  1. Webhook сейчас **не работает** (функциональный баг)
  2. Когда его добавят в PUBLIC_PATHS — станет CRITICAL без подписи
- **Рекомендация:** Добавить `/api/webhook/` в PUBLIC_PATHS + реализовать HMAC-верификацию Doverka подписи одновременно.
- **Effort:** 1-2 часа (зависит от Doverka API docs)

---

## HIGH Findings

### H1. Нет rate limiting на login
- **Файл:** `app.py:860-884`
- **STRIDE:** Spoofing
- **OWASP:** A07:2021 Identification and Authentication Failures
- **Описание:** Бесконечные попытки логина без задержки. При 4-символьном пароле (мин. требование) — brute force тривиален.
- **Рекомендация:** `flask-limiter` с лимитом 5 попыток / минуту на IP. Account lockout после 10 неудач.
- **Effort:** 1 час

### H2. Публичный `/api/auth/setup` — создание админа
- **Файл:** `app.py:906-943`
- **STRIDE:** Elevation of Privilege
- **OWASP:** A01:2021 Broken Access Control
- **Описание:** Если таблица `AdminUser` пуста (DB wipe, migration fail) — любой может создать админа. Проверка `if existing` защищает при нормальной работе, но edge case: DB сброс в проде.
- **Рекомендация:** Добавить env-переменную `SETUP_ENABLED=true` как дополнительный gate. Или disable endpoint в production.
- **Effort:** 30 минут

### H3. User-controlled proxy к Doverka API
- **Файл:** `app.py:2675-2691`
- **STRIDE:** Tampering
- **OWASP:** A10:2021 Server-Side Request Forgery (SSRF)
- **Описание:** `/api/proxy/create-payment` принимает произвольный JSON и forwarding к `grushab-2-b.ru`. Хотя URL фиксирован (не SSRF в чистом виде), пользователь контролирует полностью тело запроса к платёжному API. Может создавать платежи с произвольными параметрами.
- **Рекомендация:** Валидировать обязательные поля и их типы перед проксированием. Whitelist допустимых полей.
- **Effort:** 1 час

### H4. KYC фото без auth — только token
- **Файл:** `app.py:2901-2924`
- **STRIDE:** Information Disclosure
- **OWASP:** A01:2021 Broken Access Control
- **Описание:** `/api/kyc/photo/<token>/<photo_type>` — доступ к паспортным фото только по 16-байт token (secrets.token_urlsafe(16)). Token в URL может утечь через логи, referer, browser history. Паспортные данные = PII.
- **Рекомендация:** Добавить auth check (session required) для `/api/kyc/photo/`. Клиенту показывать фото через KYC-страницу с другим механизмом.
- **Effort:** 30 минут

---

## MEDIUM Findings

### M1. Минимальная длина пароля 4 символа
- **Файл:** `app.py:923`
- **Рекомендация:** Увеличить до 8+ символов.

### M2. Сессия живёт 30 дней
- **Файл:** `app.py:880`
- **Рекомендация:** Уменьшить до 7 дней или добавить re-auth для критических операций.

### M3. Exception messages в ответах
- **Файлы:** Множественные `str(e)` в catch-блоках
- **Рекомендация:** Логировать полную ошибку, клиенту — generic message.

### M4. CORS без ограничений
- **Файл:** `app.py:22`
- **Рекомендация:** Указать конкретные origins: `proud-renewal-production-e9b8.up.railway.app`, `grusha.space`.

### M5. Нет ограничения размера KYC-файлов
- **Файл:** `app.py:2814-2873`
- **Рекомендация:** `app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024` (10MB).

---

## LOW Findings

### L1. Role-based access control не реализован
- **Файл:** `app.py:98` — поле `role` есть, но нигде не проверяется.

### L2. Нет audit log для действий в CRM
- Изменения сделок, KYC approve/reject не логируются.
