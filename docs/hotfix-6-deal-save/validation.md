# Validation — hotfix 6

Pre-rebase complete Python regression, including Chromium, on 2026-10-15: **2742 passed, 9 skipped, 2 xfailed**, 342.47 seconds. Network fence: **8 expected negative probes, 0 unexpected attempts**. [Fence report](regression-python.json). A previous run lost its connection at 99% and has no pytest summary/fence report, so it is not counted as a successful final run.

## Pre-rebase JavaScript regression

Full repository JS suite: **57 passed, 1 failed**. The failure is `tests/test_stand_mobile_tasks_nav.js:86`: document/body width is 1207 px at a 375 px viewport. The identical failure was reproduced on an archived, unchanged product-code baseline `631d026`, with the same browser, dependency and fence launcher settings. It is not introduced by this hotfix. This is a known failing regression, not a green JS run.

Machine-readable results: [final JS](regression-js.json), [baseline JS](baseline-js.json).

## Scope of targeted tests

`tests/test_deal_save_corruption.py` contains 31 cases after the rebase:

- 12 real Chromium open/save scenarios and 12 independent API empty-PUT scenarios: crypto, SBP, requisites, cash, bank card, founder personal, Binance, founder without conversion, custom, missing methods, standard Flow Sole and custom Flow Sole.
- Two Flow Sole browser edits (standard/custom): only notes in PUT, linked manual receipt and monetary fields unchanged, no duplicate receipt upload; both method selects retain a blank option and Flow Sole, and the coral color remains `#C2410C`.
- A real UI edit/revert/clear scenario proving sparse payloads, full timestamp preservation and preservation of null payout fields and the reimbursement choice.
- Two incoming-transaction scenarios with a synthetic `None` TronScan response: empty result and cached partial result.
- Two sparse-PUT scenarios preserving and recalculating the multi-agent cascade when notes or the incoming amount change.

No-op checks compare all raw deal columns and related wallet operations, cash/card allocations, agents, balances and linked bank receipts. The test network fence disables external traffic and all production integrations. Full-suite expected negative network probes are recorded separately from unexpected attempts.

The two pre-existing strict browser xfails cover mobile logout session revocation and Bitrix title escaping. Skips remain explicit; no failing test was reclassified to make this change pass.

## Rebase onto stage d37993c

Both conflicts were merged deliberately: CRM hydration retains Flow Sole's receipt
parts and the empty method option; the fenced JS launcher retains stage's environment
support and automatic discovery of all JS tests. Coral remains `#C2410C`.

Receipt validation was moved out of the extracted standard serializer and into
submit, before reducing the payload to a diff. This avoids validation side effects
while taking the initial snapshot and keeps receipt upload's `flowBody` in scope.
A failed receipt upload captures the saved deal baseline before retrying.

Focused suite: **31 passed**, including real Chromium standard/custom Flow Sole
no-op saves and notes-only edits. No unexpected network attempts.

Full rebased JS: **56 passed, 3 failed**. A clean `git archive d37993c`, with the
same interpreter, dependency, browser and fenced launcher, produces **exactly the
same 59 results**. Failures are `test_stand_mobile_tasks_nav.js`,
`test_stand_owner_summary.js`, and `test_t34_wallet_cards_dropdown.js`; all concern
`static/stand/tasks.html`, which this hotfix does not change. This suite is not green.
See [rebased JS](rebase-js.json) and [clean-stage JS](stage-baseline-js.json).

Full rebased Python + Chromium: **2753 passed, 1 failed, 9 skipped, 2 xfailed**
in 375.35 seconds. Network fence: **8 expected negative probes, 0 unexpected**.
Failure: `test_shared_section_click_opens_task_pages[tasks-/tasks]`, a 30-second
click timeout on the shared navigation's Tasks item. A targeted rerun gives
**1 failed, 1 passed** (Tasks fails, Analytics passes). The same targeted test on
clean stage application code `d37993c` gives the identical result. Only the test
harness's `--chromium-executable` option and its launcher were applied to that
archive to use the same installed headless shell; application code was unchanged.
This is a reproduced stage failure, not a green full Python regression.

Evidence: [full Python output](rebase-python.log), [network fence](rebase-python.json),
[rebased navigation rerun](rebase-nav.log), [stage navigation run](stage-baseline-nav.log).
The original audit files and suspect IDs were retained unchanged during this rebase.
