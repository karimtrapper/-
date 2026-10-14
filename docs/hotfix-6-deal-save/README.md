# Hotfix 6 — deal-save corruption and incoming transactions

Branch: `hotfix/deal-save-corruption`, original base: `origin/stage@631d026`; rebased onto `origin/stage@d37993c`. No push or deployment.

The standard and custom editors now capture a serialized baseline after hydration and PUT only the diff against that baseline. An unchanged editor sends `{}`; the server returns the current deal before any financial/status/allocation recalculation or commit. Unchanged `created_at` is omitted, preserving its full stored timestamp. Explicit edits to the date still use the existing date-only input semantics.

Partial PUT also preserves the existing agent cascade when `agents` is omitted; legacy mirroring cannot collapse it into one row. Reimbursement inference runs only when its payout inputs change, so editing a note cannot reverse an existing reimbursement choice.

Nullable source, founder, payout/payin method and custom currency selects have empty options. Saved founder/card/wallet selections are restored even when absent from the active directory. Edit validation does not force unchanged missing legacy fields to acquire invented values. Changes and explicit clearing of fields remain in the diff. The loading overlay stays until the baseline is ready.

When TronScan returns `None`, incoming errors consistently contain `{address, error}`. Tests verify HTTP 200 with an empty result and with retained cached transactions, without real network calls.

Tests in `tests/test_deal_save_corruption.py` exercise real Flask/SQLite and Chromium for crypto, SBP, bank requisites, cash, bank card, founder personal, Binance, founder without conversion, custom, missing-method, and standard/custom Flow Sole deals. They compare every raw deal column, including `created_at` and `updated_at`, plus wallet operations, cash/card allocations and balances. API tests also send empty PUT independently of the browser. A real notes edit/clear verifies sparse PUT and preserved timestamps/null source/founder; edit/revert checks the diff.

The UI contract for explicit incoming network selection now checks the shared serializer called by submit. Test launchers accept an installed headless Chromium binary; the JS launcher passes its allocated localhost port to the browser test, keeping the existing network fence.

## Read-only assessment

[ID lists and evidence, separately for stand and production](audit-report.md). [Machine-readable results](audit-results.json). [Read-only audit script](audit.py).

Both snapshot datasets have 52 deals with Андрей outside `FOUNDER_PERSONAL`, and cash-without-batch IDs **61, 109, 110**. Both contain 234 midnight timestamps: 64 have a directly linked non-midnight event on the same date; another 67 have events only on other dates and are explicitly classified as weak evidence. Remaining 103 have no such linked timestamp evidence and are not classified as time-corruption candidates. The union of all criteria, including weak signals, is 152 IDs per dataset. These are candidates for investigation, not approved data corrections.

The local `origin/main@7b0a86b` ref contains the same full-form PUT, date truncation and first-option defaults, so production branch code is potentially affected. This does not assert which build is currently deployed.

## Reproduction

```sh
/tmp/calccrm-audit-venv/bin/python scripts/run_fenced_pytest.py -q --browser \
  --chromium-executable=/tmp/calccrm-browsers/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell \
  --disable-warnings --tb=short

NODE_PATH=/tmp/hotfix6-node/node_modules PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/tmp/calccrm-browsers/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell \
  /tmp/calccrm-audit-venv/bin/python scripts/run_fenced_js.py

/tmp/calccrm-audit-venv/bin/python docs/hotfix-6-deal-save/audit.py \
  --socket /tmp/calccrm-hotfix6-audit/socket --port 55486 \
  --stand stand_utf8 --prod prod_utf8 --output /tmp/hotfix6-audit-repeat.json
```

The audit-only PostgreSQL server was stopped after reading; restored local data remains under `/tmp/calccrm-hotfix6-audit/pgdata`. Restart that isolated server before repeating the audit command.

Local JS dependency for the rebased run: `NODE_PATH=/tmp/hotfix6-node/node_modules`, with `playwright` linked to the installed Python Playwright driver package. This temporary link is outside the worktree and is not part of the commit. Headless shell avoids Chrome's singleton socket outside the network fence.

## Final validation after rebase

Rebased onto `d37993c`, preserving Flow Sole, coral `#C2410C`, empty selects and sparse PUT. Receipt validation stays in submit rather than running during baseline serialization. Standard/custom Flow Sole no-op and notes-only saves preserve linked receipts and monetary fields.

Focused tests: **31 passed**. Full Python including Chromium: **2753 passed, 1 failed, 9 skipped, 2 xfailed**; unexpected network attempts: **0**. The failed Tasks navigation click also fails on clean stage `d37993c`. Full JavaScript: **56 passed, 3 failed**, with all 59 outcomes identical to clean stage. These are completed regressions with reproduced baseline failures, not green runs. See [validation details and evidence](validation.md).
