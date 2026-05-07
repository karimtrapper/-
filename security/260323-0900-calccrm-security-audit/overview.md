# Security Audit Report — CalcCRM

**Date:** 2026-03-23
**Tool:** autoresearch:security (3 iterations, shallow depth)
**Scope:** `Dev/CalcCRM/**/*.py` (app.py, calculator.py, broker_detailed.py)

## Executive Summary

CalcCRM — Flask-приложение для обмена валют. Обнаружено **14 уязвимостей** (3 CRITICAL, 4 HIGH, 5 MEDIUM, 2 LOW). Критические проблемы связаны с хранением паролей и управлением секретами. Бизнес-логика (calculator.py, broker_detailed.py) — безопасна, вся поверхность атаки сконцентрирована в app.py.

## Risk Score: 6.5 / 10

Факторы повышения:
- Финансовое приложение (высокая ценность данных)
- KYC с паспортными данными (PII)
- Hardcoded секреты в git

Факторы понижения:
- auth middleware работает корректно (before_request)
- SQLAlchemy ORM — нет raw SQL injection
- Ограниченный круг пользователей (1-2 админа)
- Не public-facing (CRM за логином)

## Priority Fix Plan

### Sprint 1 — Must Fix (день)
| # | Что | Effort | Impact |
|---|-----|--------|--------|
| C2 | Убрать fallback secret key | 15 мин | Session forgery prevention |
| C1 | Заменить SHA-256 → bcrypt | 2 часа | Password security |
| M1 | Пароль минимум 8 символов | 5 мин | Brute force resistance |

### Sprint 2 — Should Fix (неделя)
| # | Что | Effort | Impact |
|---|-----|--------|--------|
| H1 | Rate limiting на login | 1 час | Anti-brute-force |
| H4 | Auth на KYC photo endpoint | 30 мин | PII protection |
| M4 | CORS origins whitelist | 15 мин | Request origin control |
| M5 | MAX_CONTENT_LENGTH для uploads | 5 мин | DoS prevention |

### Sprint 3 — Nice to Have (месяц)
| # | Что | Effort | Impact |
|---|-----|--------|--------|
| C3 | Webhook HMAC + PUBLIC_PATHS | 2 часа | Payment integrity |
| H2 | Disable /setup в production | 30 мин | Edge case prevention |
| H3 | Валидация proxy body | 1 час | Payment API security |
| M3 | Generic error messages | 1 час | Info disclosure prevention |

## Files

- [threat-model.md](threat-model.md) — STRIDE analysis + attack surface map
- [findings.md](findings.md) — Detailed findings with PoC, locations, recommendations
- [security-audit-results.tsv](security-audit-results.tsv) — Machine-readable results

## What Works Well
- Auth middleware (`before_request`) — правильная архитектура
- SQLAlchemy ORM — нет SQL injection
- `secrets.token_urlsafe(16)` для KYC tokens — криптографически стойкий
- `secure_filename()` для uploads — path traversal protection
- `send_from_directory()` — безопасная отдача файлов

## What NOT Checked (shallow scope)
- Frontend JS (XSS в шаблонах)
- Railway deployment config (env vars actually set?)
- Network-level security (TLS, headers)
- Dependencies (pip audit)
- Google Sheets API credentials exposure
