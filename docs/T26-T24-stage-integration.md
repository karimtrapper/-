# T26: integration of T24 into stage

Base: `da074461d42201b85c4d617617d6e45676723b36`. Merged component:
`88577ca15d2e6fbe8775b8bdfbf345275b032922`. This document describes
the integration contract; the private QA handoff records the frozen SHA and
raw fenced reports. T17 is outside this merge.

## Conflict inventory and decisions

| File / exact code | Stage contract | T24 contract | Resolution |
| --- | --- | --- | --- |
| `app.py`, `stand_state_put` | `_stand_guard_transition` rejects invalid client mutations; `preserve_server_fields` restores trusted fields; `_stand_check_funding_state(previous, clean)` rejects forged or underfunded batch money with 409. | A manager's accepted `sentToClient` transition writes `StandCloseEvidence` in the same transaction. | Keep the order: guard raw payload, preserve, recheck funding on clean state, then write server evidence and state together. A rejected client mutation never becomes a successful no-op by being preserved first. |
| `scripts/run_fenced_pytest.py`, `scripts/run_fenced_js.py` | T19 exact 64-port OS profile, preimport Python audit, isolated env and `/tmp/calccrm-t19-fence-reports`. | Older T24 copies used T24 socket/report prefixes. | Use stage versions exactly; no T24 runner changes. |
| `stand_transfers.py`, `preserve_server_fields` | Preserve server-confirmed payin and transfer facts, canonical send fingerprint and T25 funding fields. | Extend protected payin hash fields to `network` and `net`. | Retain T24 extension. The guard first rejects forbidden changes to accepted hashes, network and amounts; preservation then carries forward server-verified fields on otherwise legal PUTs. Missing and empty hash lists, plus omitted TRC20 labels, are canonical representation only and do not grant mutation rights. |
| `app.py`, `_stand_batch_main`, `_stand_check_transfers` | T23 owner follows `conv`/`sources`, independent of side route; T25 validates registered positive RUB sources, confirmed incoming and aggregate outgoing before dispatch, isolates BAD poll batch, and repeats validation under lock. | T24 adds close evidence, origin link and money checks. | Preserve stage resolver and dispatch checks. `stand_crm_close` also rechecks the persisted conversion's canonical owner and funding under its row lock before creating CRM/link/board close; an already advanced but underfunded batch cannot close. |
| `app.py`, `_stand_crm_fact_problem`, `stand_crm_close`, `_create_deal_impl` | Existing CRM money calculation and stage role/version rules. | Mandatory persisted monetary basis, JS-compatible RUB/rate fees, derived exchange payout, hash/recipient equality, atomic CRM+origin+board commit, retry same ID. | Keep T24 checks and transaction; direct CRM close has an additional T25 funding check. Retry checks existing link before stale version or money payload so a lost response returns the original ID. |
| `static/stand/tasks.html` | T22 overlay/local assets/CSP, T16 login, T20 labels and stage UI. | Close evidence controls, saved-money locks, manual origin and atomic close UI. | Git's automatic merge retained both; JS gate exercises 17 suites including assets, login, labels, locks, manual origin and close retry. |
| `tests/test_prod_schema.py` and T24 fixtures | Stage schema gate, T25 source admission and T19 runner. | New stand-only CRM link/evidence tables and close tests. | Include both tables in schema exclusion; preserve new T24 business assertions. The freehold integration fixture now registers synthetic RUB source and confirmed USDT incoming to satisfy T25 instead of weakening admission. |

## Additional integration proof

`test_freehold_ipps_server_settlement_receipt_sent_then_close[True]` creates a
funded freehold main with a Coins side deal and a malformed neighboring batch.
The canonical owner is the freehold main. With outgoing total 39,383 USDT,
39,382.99 confirmed incoming is rejected at dispatch and at close with no CRM
row; 39,533.77 permits GOOD poll and server completion while BAD stays pending.
Manager/operator evidence then closes GOOD once. The close check repeats under
lock, so funding corruption after `s27` also returns 409 and leaves CRM/link
counts unchanged.

The own PostgreSQL proof uses an isolated UTF-8 PostgreSQL 17 cluster, a
private Unix socket under the accepted T19 prefix, one exact HTTP port from a
fresh 64-port pool, synthetic keys and disabled pollers. Its Python preimport
probe verifies own HTTP/Unix access and one expected blocked foreign loopback
entry in the Python ledger. Native `-I -S` probes separately demonstrate three
EPERM denials: foreign loopback, external address and a native child. The
Python ledger cannot count those native denied attempts; they are reported
separately.

## Remaining functional limit

Standalone Coins/client workflow without an authoritative persisted recipient
still fails network proof. That functional path remains OPEN. This integration
does not declare rollout PASS; independent T26 intersection QA follows the
frozen commit. T17 integration is separate.
