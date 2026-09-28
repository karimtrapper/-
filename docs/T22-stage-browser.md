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

## Follow-up after coordinator review (new commit after c43c87c)

Two findings were reproduced on the original c43c87c build with clean-env synthetic SQLite under `/tmp/calccrm-t22-followup-fence.sb` (own loopback ports 18924/18925):

1. Authorized `GET /static/partner/index.html` returned 200 with `fonts.googleapis.com` and no CSP; `HEAD` lacked CSP, and conditional GET returned 304. The exact static alias was registered in `19fdf87`. Independent QA later found that file-serving trailing-slash and other normalized filename aliases also return 200; the next section records that fix.
2. Anonymous raw paths `/static/stand/vendor/../../crm/crm.html`, `%2e%2e/%2e%2e`, and encoded slash variants returned 200 CRM HTML without CSP. Raw `curl --path-as-is` and Flask test client reproduced this. The pre-login bypass now matches only CSS, JS and WOFF2 paths explicitly listed in the SHA-256 manifest. Raw dot-segment attempts now redirect to `/login` (302); `/api/bitrix/active-deals` remains 401 without a session. CSS, JS and WOFF2 assets still return 200 before login. This follows the existing stage HTML authentication behavior; it does not introduce a new 401 contract for protected pages.

An authenticated browser load of `/static/partner/index.html?v=1` returned 200 with CSP, loaded local Inter, and emitted zero external request events.

A browser probe also reproduced a false “Webhook активен” for `{"success":false,"is_configured":true}`. The stage status layer now requires a successful response and a boolean `is_configured` before showing configuration status. Non-JSON replies show a readable error. It keeps the original Bitrix list renderer if that API ever returns a valid success. Browser checks saw one request per desktop or mobile navigation action, no listener buildup, and working `data:` and `blob:` images plus a local blob iframe.

Compatibility probes under the same OS fence: transformed login from T16 commit `a5db5a3` loaded Inter locally, showed the stage password form, hid Telegram controls and emitted no external request. The current **uncommitted** T17 worktree tasks HTML and its two local draft scripts were supplied to the browser via route fixtures under this T22 CSP; `startManual()` mounted the CRM form in a ShadowRoot, with no external request or page error. This proves mount compatibility for that snapshot only. It does not test the full T17 form workflow or the eventual merge; T17 owns its earlier `screens-data.js` 404 issue. The eight-page T22 load smoke is not a functional PASS for tasks.

Exact local probe files: `/tmp/calccrm-t22-alias-probe.py`, `/tmp/calccrm-t22-alias-probe-clean.json`, `/tmp/calccrm-t22-partner-alias-browser.py`, `/tmp/calccrm-t22-status-followup.py`, `/tmp/calccrm-t22-t16-probe.py`, `/tmp/calccrm-t22-t17-probe.py`. Focused Python 3.11 tests: `15 passed`. The profile and probes are author evidence; independent Claude QA must use its own ports and fence. The prod response tests still compare bytes with this branch's unchanged source/base and check that prod conditional responses receive no CSP. The earlier `origin/main` divergence remains outside T22.

## Follow-up after independent QA FAIL on 19fdf87

The QA report at `/tmp/calccrm-t22-claudeqa/T22-19fdf87-CLAUDE-QA.md` found raw HTML for reachable file aliases, including `/static/crm/crm.html/` and `/static/auth/login.html/`, plus raw 206 responses for Range. Both were reproduced under this author's own OS fence before the new fix. The stage response hook now identifies which of the eight registered source files was actually served, using the same `safe_join` path resolution as Flask and `samefile` for identity. This includes case-only aliases on macOS; on a case-sensitive filesystem, an unavailable alias may instead remain 404. No second URL decoding is done. Successful GET/HEAD 200, 206, and 304 responses for these files are rebuilt as full transformed 200 with CSP and no-store. Original file validators and Content-Range are removed. Other statuses and files retain their existing behavior. The prod branch remains outside the hook.

Author regression matrix: `tests/test_stand_html_aliases.py` covers all eight pages with canonical and filename aliases, trailing slash, dot, encoded dot, duplicate slash, case-only variants, query strings, GET/HEAD, conditional requests, Range and If-Range. It also checks anonymous protected aliases and public vendor assets, and raw prod-mode bytes/statuses on the same URLs. Under `/tmp/calccrm-t22-followup-fence.sb` with Python 3.11 and synthetic SQLite, that test plus `tests/test_stand_browser_assets.py` returned **17 passed**. No old QA artifact was edited.

Browser smoke on port 18924 under the same fence loaded the canonical eight pages, local fonts, Chart.js 4.4.7 graphs and disabled integration messages. It emitted zero external requests before the intentional CSP negative injection. The injected external image was blocked by CSP. Separate alias navigation to `/static/auth/login.html/` and `/static/crm/crm.html/` returned 200 with CSP and local Inter; the CRM graph had 14,353 nontransparent pixels and made zero external requests. Artifacts: `/tmp/calccrm-t22-d1d2-browser.json`, `/tmp/calccrm-t22-d1d2-browser-alias.json`, and their matching Python probe scripts. Independent QA repeat on the new SHA is pending. Mobile more-panel click and merged T16/T17 compatibility remain OPEN.
