# T22: stage browser assets and disabled integration status

## Inventory, 2026-09-28

| Source page | Automatic external resource in the source HTML/JS | Stage response |
| --- | --- | --- |
| calculator | Google Fonts Inter CSS | local Inter v20 CSS and WOFF2 |
| crm | Google Fonts Inter CSS; jsDelivr Chart.js 4.4.7 | local Inter and Chart.js |
| referrer | Google Fonts Inter CSS | local Inter |
| partner | Google Fonts Inter CSS | local Inter |
| kyc | Google Fonts Plus Jakarta Sans CSS | local Plus Jakarta Sans v12 |
| login | Google Fonts Inter CSS; dynamic Telegram widget script | local Inter; widget insertion gated by blocked stage config |
| tasks | Google Fonts Inter CSS; Google Fonts preconnect and fonts.gstatic preconnect | local Inter; preconnect removed |
| walkthrough | Google Fonts Inter CSS; both preconnects | local Inter; preconnect removed |

The CSS `url(...)` values from Google Fonts point to versioned WOFF2 files and are now local. The other external URLs found in these files are user-initiated links (for example transaction explorers), URL input placeholders, or payload values rather than automatic page resources. Stage CSP blocks page-initiated external resource and API requests, including new URLs accidentally added later. It allows inline JS/styles, same-origin documents, blob/data images and PDF previews, and same-origin walkthrough iframes.

## Isolation checkpoint

`stand_browser.py` is an exact page and resource registry. A single existing `after_request` hook applies it only when `STAND_MODE=1` and only to registered HTML pages. A conditional 304 is rebuilt as transformed 200, and stage HTML uses `Cache-Control: no-store` so old cached external tags cannot survive rollout. The original eight HTML files, including `static/crm/crm.html`, are untouched. `STAND_MODE=0` bypasses the overlay and CSP; tests compare its response bytes to the source files and assert no new CSP header. `git diff 67ac1c0 --` on those eight files is empty. Some source pages already differ from `origin/main` before T22; this change does not reconcile those earlier differences.

`static/stand/browser-status.js` is injected only into stage CRM. It reads the actual blocked Bitrix and webhook responses and shows “На стенде отключено” in Closing and Verification. The API guards remain in place. It does not change deal creation or other CRM sections.

Version and license provenance and all asset hashes are in [`static/stand/vendor/README.md`](../static/stand/vendor/README.md) and [`SHA256SUMS`](../static/stand/vendor/SHA256SUMS).

## Author verification

- Python 3.11, clean environment, synthetic SQLite, OS network fence on local port 18922: `tests/test_stand_browser_assets.py` — 14 passed. The two existing library/SQLAlchemy warnings and Flask-Limiter development storage warning remain.
- Browser smoke on the same fenced local app: eight pages, 0 external request events on normal load; local Inter and Plus Jakarta Sans loaded; Chart.js 4.4.7 rendered profit, deals and methods graphs, with nonempty canvas pixels. Closing and Verification displayed the disabled messages after real 403 `stand_blocked` responses.
- CSP negative control: an injected external image raised a CSP violation and failed. Playwright records a request event for that intentionally blocked URL; there was no successful network fetch.
- Detailed synthetic browser observations: [`qa-t22-author-smoke-2026-09-28.json`](qa-t22-author-smoke-2026-09-28.json).

Independent Claude QA after the commit SHA is still required; the author smoke is not an acceptance verdict. No push or deployment was performed.
