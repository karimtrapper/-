# Security Findings — CalcCRM (Re-Audit)

**Audit date:** 2026-03-23 (повторный после фиксов)
**Previous audit:** security/260323-0900-calccrm-security-audit/

## Summary

| Severity | Previous | Current | Change |
|----------|----------|---------|--------|
| CRITICAL | 3 | 1 | ↓ -2 (fixed) |
| HIGH | 4 | 1 | ↓ -3 (fixed) |
| MEDIUM | 5 | 1 | ↓ -4 (fixed) |
| LOW | 2 | 2 | → 0 |
| **Total** | **14** | **5** | **↓ -9** |

---

## Fixed Findings (10 из 14)

| ID | Что было | Статус | Как исправлено |
|----|---------|--------|----------------|
| C1 | SHA-256 пароли | ✅ Fixed | bcrypt + per-user salt + автомиграция (app.py:112-132) |
| C2 | Hardcoded SECRET_KEY fallback | ✅ Fixed | `os.environ['SECRET_KEY']` без fallback (app.py:25) |
| H1 | Нет rate limiting на login | ✅ Fixed | `@limiter.limit("5/minute")` (app.py:885) |
| H2 | /setup публичный | ✅ Fixed | `SETUP_ENABLED` env gate + `@limiter.limit("3/minute")` (app.py:935-938) |
| H4 | KYC фото без auth | ✅ Fixed | `flask_session.get('user_id')` check (app.py:2964) |
| M1 | Пароль мин. 4 символа | ✅ Fixed | Минимум 8 символов (app.py:954) |
| M2 | Сессия 30 дней | ✅ Fixed | 7 дней (app.py:908) |
| M3 | str(e) в ответах | ✅ Fixed | Generic messages + `app.logger.error()` |
| M4 | CORS wildcard | ✅ Fixed | Origins whitelist из env (app.py:26-27) |
| M5 | Нет лимита загрузки | ✅ Fixed | `MAX_CONTENT_LENGTH = 10MB` (app.py:28) |

---

## Remaining Findings (5)

### 🔄 C3. Doverka webhook без HMAC (RECURRING)
- **Файл:** `app.py:2749-2760`
- **STRIDE:** Tampering | **OWASP:** A08
- **Статус:** Webhook защищён auth middleware (не в PUBLIC_PATHS), поэтому сейчас НЕ работает для Doverka. Когда откроют — нужен HMAC.
- **Фактический риск:** LOW (пока закрыт auth middleware)
- **Действие:** Нужен API-ключ от Doverka для HMAC

### 🔄 H3. Proxy к Doverka без валидации body (RECURRING)
- **Файл:** `app.py:2730-2747`
- **STRIDE:** Tampering | **OWASP:** A10
- **Статус:** Endpoint за auth, но авторизованный пользователь может передать произвольный JSON в Doverka API.
- **Фактический риск:** MEDIUM (только для авторизованных, 1-2 админа)
- **Действие:** Whitelist допустимых полей (нужна документация Doverka API)

### 🆕 M6. Утечка response.text от Doverka в ошибке (NEW)
- **Файл:** `app.py:2744`
- **Описание:** `response.text[:300]` возвращается клиенту при HTTP-ошибке Doverka. Может содержать внутренние данные Doverka API.
- **Фактический риск:** LOW (за auth, только для админов)

### 🔄 L1. RBAC не реализован (RECURRING)
- **Файл:** `app.py:109`
- **Описание:** Поле `role` есть, но не проверяется.

### 🔄 L2. Нет audit log (RECURRING)
- **Описание:** CRM-действия (сделки, KYC) не логируются.
