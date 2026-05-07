# Security Re-Audit Report — CalcCRM

**Date:** 2026-03-23 12:00
**Tool:** autoresearch:security (5 iterations, shallow depth)
**Scope:** `Dev/CalcCRM/app.py`
**Focus:** Верификация security-фиксов из предыдущего аудита

## Summary

- **Total Findings:** 5 (was 14)
  - Critical: 1 (was 3) | High: 1 (was 4) | Medium: 1 (was 5) | Low: 2 (was 2)
- **Fixed:** 10 из 14 findings
- **New findings:** 1 (M6 — утечка response.text от Doverka)
- **Recurring:** 4 (C3, H3, L1, L2)

## Risk Score: 3.5 / 10 (was 6.5 / 10)

Факторы понижения (новые):
- Bcrypt с per-user salt
- SECRET_KEY без fallback (задан в Railway env)
- Rate limiting на login/setup
- CORS whitelist
- Generic error messages
- ProxyFix для корректного IP
- KYC фото за auth
- Setup endpoint за env gate

## Historical Comparison

**Previous audit:** security/260323-0900-calccrm-security-audit/

### Trend
| Metric | Previous | Current | Change |
|--------|----------|---------|--------|
| Critical | 3 | 1 | ↓ -2 ✅ |
| High | 4 | 1 | ↓ -3 ✅ |
| Medium | 5 | 1 | ↓ -4 ✅ |
| Low | 2 | 2 | → 0 |
| Total | 14 | 5 | ↓ -9 ✅ |
| Risk Score | 6.5 | 3.5 | ↓ -3.0 ✅ |

### Finding Status
| Status | Count | Details |
|--------|-------|---------|
| ✅ Fixed | 10 | C1, C2, H1, H2, H4, M1-M5 |
| 🆕 New | 1 | M6 (Doverka response.text leak) |
| 🔄 Recurring | 4 | C3, H3, L1, L2 |

## What Still Needs Fixing

| Priority | ID | Что | Блокер |
|----------|-----|-----|--------|
| When needed | C3 | Webhook HMAC | Нужен ключ от Doverka |
| When needed | H3 | Proxy body validation | Нужна документация Doverka API |
| Nice to have | L1 | RBAC | Архитектурное решение |
| Nice to have | L2 | Audit log | Новая функциональность |

## Verified on Production

| Тест | Результат |
|------|-----------|
| Health check | ✅ `status: ok` |
| Курсы /api/rates | ✅ USDT/THB: 32.97 |
| Логин admin/test1234 | ✅ Bcrypt миграция прошла |
| Неверный пароль | ✅ Generic error, no leak |
| CRM /api/deals | ✅ 50 сделок, auth работает |
| Калькулятор / | ✅ HTTP 200 |

## Files
- [findings.md](findings.md) — Все findings с comparison
- [security-audit-results.tsv](security-audit-results.tsv) — Iteration log
