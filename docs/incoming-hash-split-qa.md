# Incoming USDT hash shares: QA handoff

Branch: `hotfix/incoming-hash-split`, base `origin/stage@3c1fd2d`. No push/deploy.

## Storage and transaction boundaries

- `PayinTx` is the common CRM/stand transaction. `PayinTxUse` holds both deal shares and batch reservations; reservations have `deal_id = NULL`, `stand_generation`, `stand_cnv_id`.
- Partial unique indexes allow one reservation per transaction/batch/generation and one use per transaction/CRM deal. Existing rows and IDs are retained. `conversion_id` records the source of newly calculated CRM shares.
- `txs[].amount` on the board is the allocated share. `verifiedAmount` is the checked whole transfer; `ledgerUseId` identifies the server-created use. Old full-hash entries are read as shares and lazily registered without rewriting the board or old uses.
- `/api/stand/incoming/check` supports `preview: true`; committing a share repeats on-chain verification and recalculates available funds with the board and transaction locked. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses row locks.
- Comparisons use Decimal. An excess of at most 0.005 USDT is clamped to the exact available amount, never booked as extra money. Zero, negative, non-finite and more-than-six-decimal shares are rejected.
- Recipient/network/token/time verification is retained for every batch. Canonical lookup recognizes legacy uppercase/0x spellings; ambiguous duplicate ledger records fail closed.
- CRM close consumes the reservation in the same transaction as CRM creation and board closure. A whole reservation keeps its ID and gains the real CRM deal ID. Closing one member of a multi-deal batch consumes only that member's amount. Exceptions roll the transfer back; retries use the existing close link.
- Direct CRM edits of conversions mirrored by the board are rejected to prevent desynchronizing their reservations. Unlink releases an unconsumed reservation and its CRM conversion link. Already transferred CRM shares require a CRM correction and cannot be silently released from the board.
- New mixed batches use the same per-hash rounding in the board and CRM. Legacy conversions retain their historical rounding.

## Migration / rollback

PostgreSQL scripts:

- `migrations/20261014_payin_reservations_up.sql`
- `migrations/20261014_payin_reservations_down.sql`

Startup applies the idempotent upgrade; migration failure aborts startup. SQLite upgrades rebuild the table transactionally while preserving old values. Fresh installation uses the new model constraints.

Before deployment: stop writers and take a database backup. Run SQL scripts in a transaction (`psql -X -v ON_ERROR_STOP=1 -1 -f ...`). Do not run the down script concurrently with the application.

**Down refuses to run if any reservation or new provenance exists.** It never deletes those rows or throws away their metadata. After the feature has been used, rollback requires a reviewed data resolution or recovery from the pre-deployment backup; simply downgrading the application/schema is not safe.

The fresh stand dump supplied on 2026-10-14 at 17:54 was restored into a disposable UTF8 PostgreSQL 17 cluster, Unix socket only, using libpq18 tools. No live database connection was used.

`python scripts/verify_payin_migration.py /absolute/path/to/dump.sql.gz` verified:

1. Full restore; all original columns/rows unchanged by up.
2. Repeated up is idempotent.
3. Down restores the exact original schema and data dump hashes.
4. An active synthetic reservation blocks down, with no change to data/schema.

Roundtrip SHA256:

- Schema: `c56bc229e76ee405c51e3b7ca46f55ee3767940b045d160ea3c41ec3951a6182`
- Data: `8566899a51b296b97165778d90fed5b208cdac8843157c89d302f05dd70f5583`

## Tests

TDD failures were observed before fixes for cross-conversion deletion, missing shared reservations, uppercase legacy hashes, funding guards rejecting split hashes, and the mixed-batch rounding mismatch.

Covered by `test_stand_hash_split.py`, `test_conversion_share_ownership.py`, `test_payin_reservation_schema.py`, and `test_stand_s18_crm_incomes.py`:

| Scenario | Result |
| --- | --- |
| 200 transfer -> A 100, B 100; remainder 100 then 0 | PASS |
| 100 transfer -> A 100, attempted B 101; clear used/free error | PASS |
| Unlink A releases 100; another batch can use it | PASS |
| Different recipient wallet rejects B despite available funds | PASS |
| Legacy whole hash and legacy PayinTxUse without data rewrite | PASS |
| A recalculation preserves B's share and reservation | PASS |
| Actual CRM close transfers the same reservation row, retry is idempotent | PASS |
| Injected failure after transfer rolls back CRM and restores reservation | PASS |
| Partial close keeps the rest of the multi-deal batch reserved | PASS |
| Concurrent requests cannot overspend the same remainder | PASS (SQLite) |
| ±0.005 boundary, zero, negative, NaN, Infinity, six-decimal amounts | PASS |
| CRM cannot consume stand-reserved funds; uppercase legacy hash is counted | PASS |
| Fresh schema and upgrade retain rows and enforce owner/uniqueness | PASS |
| Mixed CRM/stand batch agrees on the allocation and free amount | PASS |

Final regression on the delivered code: **2674 Python tests passed, 36 skipped; all 58 JavaScript test files passed**. The Python fence recorded eight intentional negative probes and zero unexpected external attempts. The 21 dedicated split tests all passed.

Skipped: 27 optional CRM Python browser cases, one storage/browser case, three opt-in PostgreSQL concurrency cases, four LibreOffice PDF conversions, and one Docker smoke test. PostgreSQL fresh startup/schema checks did run in the full suite.

Local logs: `/tmp/hashsplit-regression-release.log`, `/tmp/hashsplit-full-js-final.log`, `/tmp/hashsplit-migration-final.log`. Test commands use `scripts/run_fenced_pytest.py` and `scripts/run_fenced_js.py`; external network is blocked. Browser JS checks use the installed Playwright/headless Chromium and a port from the fence's permitted pool.

## Not exercised

Live TRON/Ethereum providers and live deals were not contacted. Transfer verification runs against synthetic chain responses. The concurrent-request test uses SQLite; PostgreSQL schema/startup and migration roundtrip are tested locally, but the request race was not repeated on PostgreSQL. The 36 skipped checks are enumerated above. Deployment, production migrations, backups of production, and production acceptance belong to the coordinator's rollout/financial QA.
