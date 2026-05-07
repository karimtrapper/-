# STRIDE Threat Model — CalcCRM

**Target:** CalcCRM (Flask + SQLAlchemy + PostgreSQL/SQLite)
**Date:** 2026-03-23
**Scope:** `Dev/CalcCRM/**/*.py`
**Depth:** Shallow (3 iterations)

## Tech Stack
- **Backend:** Python 3, Flask, SQLAlchemy ORM
- **DB:** PostgreSQL (prod/Railway), SQLite (local)
- **Auth:** Session-based (flask_session), SHA-256 password hashing
- **External:** Doverka API, Binance API, TronGrid API, Telegram Bot API, Google Sheets API
- **File uploads:** KYC documents (passport, selfie, liveness frames)

## Attack Surface Map

| Surface | Routes | Auth | Risk |
|---------|--------|------|------|
| **Calculator API** | `/api/rates`, `/api/calculate` | Public | LOW — read-only |
| **Auth** | `/api/auth/login`, `/api/auth/setup`, `/api/auth/logout`, `/api/auth/me` | Public | CRITICAL — brute force, weak hashing |
| **CRM Deals** | `/api/deals/*` (CRUD, 10+ routes) | Session | HIGH — business logic |
| **Doverka Proxy** | `/api/proxy/create-payment`, `/api/doverka/payments` | Session* | CRITICAL — SSRF, payment manipulation |
| **Doverka Webhook** | `/api/webhook/doverka` | Public | HIGH — no signature verification |
| **KYC Upload** | `/api/kyc/submit`, `/api/kyc/photo/*` | Token-based | HIGH — file upload, path traversal |
| **KYC Admin** | `/api/kyc/list`, `/api/kyc/review/*`, `/api/kyc/approve/*` | Session | MEDIUM |
| **Wallets** | `/api/wallets/*` | Session | HIGH — financial data |
| **Cash Batches** | `/api/cash-batches/*` | Session | HIGH — financial data |
| **Telegram** | Internal (send_telegram_notification) | N/A | LOW — outbound only |
| **Static Files** | Multiple `send_from_directory` routes | Mixed | LOW |

*Note: `/api/doverka/payments` uses session auth but `/api/proxy/create-payment` auth status unclear from code.

## STRIDE Analysis

### S — Spoofing
| Finding | Severity | Location |
|---------|----------|----------|
| SHA-256 with static salt for passwords — easily crackable | CRITICAL | app.py:102-105 |
| Hardcoded fallback secret key — session forgery possible | CRITICAL | app.py:21 |
| No rate limiting on login — brute force viable | HIGH | app.py:860 |
| Min password length = 4 chars | MEDIUM | app.py:923 |
| 30-day session lifetime — excessive | MEDIUM | app.py:880 |

### T — Tampering
| Finding | Severity | Location |
|---------|----------|----------|
| Doverka webhook has no signature/HMAC verification — fake payment notifications | CRITICAL | app.py:2693-2703 |
| User-controlled JSON forwarded to Doverka API via proxy | HIGH | app.py:2675-2691 |
| No CSRF protection on state-changing endpoints | MEDIUM | Global |

### R — Repudiation
| Finding | Severity | Location |
|---------|----------|----------|
| No audit log for deal modifications | MEDIUM | Deal CRUD routes |
| No logging of failed login attempts | MEDIUM | app.py:860-884 |

### I — Information Disclosure
| Finding | Severity | Location |
|---------|----------|----------|
| Exception messages returned to client (`str(e)`) | MEDIUM | Multiple routes |
| Hardcoded salt visible in source code | HIGH | app.py:104 |
| CORS wildcard allows any origin | MEDIUM | app.py:22 |

### D — Denial of Service
| Finding | Severity | Location |
|---------|----------|----------|
| No file size limit on KYC uploads | MEDIUM | app.py:2814-2873 |
| No rate limiting on any endpoint | MEDIUM | Global |

### E — Elevation of Privilege
| Finding | Severity | Location |
|---------|----------|----------|
| `/api/auth/setup` public — if DB wiped, anyone creates admin | HIGH | app.py:906-943 |
| No role-based access control (admin/manager enum unused) | LOW | app.py:98 |
| KYC photo endpoint has no auth — token is the only gate | MEDIUM | app.py:2901-2924 |
