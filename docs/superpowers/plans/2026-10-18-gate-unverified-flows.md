# Gate Unverified Deal Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make unverified combinations of deal type (Аренда, Обычный обмен) and Pay-In method (Наличные, Крипта, СБП) visible-but-disabled when a manager creates a new заявка or changes Pay-In method on an existing step, in both the stand/задачник (`static/stand/tasks.html`) and the legacy CRM (`static/crm/crm.html`), while admin can still pick them behind an explicit confirm. Server enforces the same rule independently of the UI. Already-in-progress deals keep running on their current step untouched.

**Architecture:** One canonical taxonomy and one `VERIFIED_FLOWS` set live in `app.py`. Each of the two creation surfaces (stand JSON-blob deals, legacy ORM `Deal` rows) has its own native vocabulary already in the codebase; small, pure translation functions in `app.py` map each surface's native values to the canonical taxonomy before checking membership in `VERIFIED_FLOWS`. A new read-only endpoint exposes the canonical verified-pairs list so both frontends check the same server-held truth instead of hardcoding a second copy of the list. Gate is enforced server-side at the two creation/change call sites (`_stand_guard_transition`'s `before is None`/combo-changed branch, `_create_deal_impl` + the deal-edit route), and mirrored in the UI as disabled chips/options with an admin-only confirm-and-bypass path.

**Tech Stack:** Flask/SQLAlchemy (`app.py`), vanilla JS/HTML (`static/stand/tasks.html`, `static/crm/crm.html`, `static/calculator`), pytest, repo's custom fenced-JS test runner (`tests/test_*.js` executed via the existing JS runner — follow `tests/test_stand_gate.py`'s and `tests/test_crm_ui_contracts.py`'s conventions for calling into the fenced JS).

**Spec:** User requirements, verbatim in conversation on 2026-10-18 (summarized in Global Constraints below); no separate spec file — this plan section is the spec of record.

## Global Constraints

- `VERIFIED_FLOWS = {(FREEHOLD, REQUISITES), (LEASEHOLD, REQUISITES)}` — exactly these two canonical pairs are verified; every other (deal-kind, payin-method) pair is unverified by default, including any future deal kind or payin method added later.
- Gate fires only at **creation** of a new deal and at an actual **change** of deal-kind or payin-method on an existing deal (i.e. compare against the stored/previous value); it must NOT fire when an already-existing deal with an unverified combo progresses through its normal steps untouched (e.g. a pre-existing rental+cash deal).
- Admin identity: `current_role() == 'admin'` (`app.py:5227-5245`). Only admin may pick an unverified combo, and only when the request carries an explicit per-request confirmation flag (`unverified_confirmed: true` in the payload) — the flag is not sticky across requests; every creation/change needs its own confirmation.
- A non-admin sending `unverified_confirmed: true` directly via the API must still be rejected — the server checks the actor's role itself, the flag alone never authorizes.
- Server rejection must be a clear, structured error, not a 500: HTTP 422 with JSON body `{"error": "unverified_flow", "message": "Этот флоу (тип сделки + способ оплаты) ещё не проверен. Проведите сделку через Карима."}` for a blocked manager/non-confirmed attempt, and `{"error": "unverified_flow_confirmation_required", "message": "Непроверенный флоу. Требуется подтверждение (unverified_confirmed=true)."}` specifically when the actor is admin but didn't send the confirm flag.
- UI copy, exact strings (do not paraphrase):
  - Disabled-option caption/tooltip: `Флоу в проверке — пока проводите через Карима`
  - Admin pre-submit confirm dialog: `Непроверенный флоу, продолжить?`
- DESIGN.md does not exist anywhere in this repo (confirmed by full-tree and `git log --all` search) — do not reference or invent tokens from it. Disabled styling must follow the codebase's existing convention: `.btn:disabled{opacity:.45;cursor:not-allowed}` (`static/stand/tasks.html:128`). Add a `.chip.disabled` (stand) and equivalent `<option disabled>` / styled-badge (legacy CRM) treatment built on that same opacity/cursor pair — no ad hoc greys.
- Legacy CRM currently has **no "Аренда" deal kind at all** (`static/crm/crm.html:1169-1174` only offers `exchange|custom|mf_realty|mf_freehold`). Per explicit user decision, add `rental` as a selectable `deal_kind` value there (label "Аренда") purely for selection/analytics parity with the stand world — do NOT build out rental-specific business/realty-field logic beyond what `exchange`/`custom` already get; it only needs to exist as a labeled, gate-checked option.
- Calculator (`static/calculator`) does not POST a deal directly; `createDealFromCalc()` hands off to `/crm#create?data=...`, landing in the legacy CRM create form. The authoritative gate for anything coming through the calculator is therefore the legacy-CRM submit-time check and the server (Tasks 5, 7) — calculator's own button-disabling (Task 8) is a UX nicety layered on top, not the enforcement point.
- Do not touch already-existing deals/rows (no migration, no retroactive status change) — this plan only changes the create/change code path.
- No pushing. No `DESIGN.md` creation. No unrelated refactors.
- JS regression baseline: these 9 files are known-pre-existing-failing and must not be treated as new breakage, but no *additional* JS test may newly fail: `test_stand_crm_close_race.js`, `test_stand_crm_labels.js`, `test_stand_freehold.js`, `test_stand_hash_split.js`, `test_stand_log_xss.js`, `test_stand_mobile_tasks_nav.js`, `test_stand_owner_summary.js`, `test_t34_parallel.js`, `test_t34_wallet_cards_dropdown.js`.

## Review Focus

- Retroactive blocking: an existing deal with an unverified combo (e.g. rental+cash) must keep moving through its current step with zero new errors when nothing about its kind/payType changed — test this explicitly, not just "creation is blocked".
- Sticky-bypass risk: admin confirming once must not silently authorize a second, later unverified pick without a fresh confirm flag in that specific request — test two sequential admin actions, second without the flag, expect rejection.
- Role-spoofing risk: a non-admin session sending `unverified_confirmed: true` straight to the API (bypassing the UI) must still get the 422 — test this directly against the endpoint, not just through the UI.
- Edit-vs-create risk on legacy CRM's `PUT /api/deals/<id>`: editing an existing deal's unrelated fields (amount, client name, etc.) without changing `deal_kind`/`payin_method` must not retrigger the gate even if the stored combo is unverified.
- Cross-surface bypass: a manager going calculator → crm.html with an unverified combo pre-filled from the calculator handoff must still be blocked at crm.html submit-time and at the server — test the full `dealData` shape the calculator actually produces, not a synthetic payload.

---

### Task 1: Canonical taxonomy, `VERIFIED_FLOWS`, and translation helpers (server)

**Files:**
- Modify: `app.py` (new section near existing `PayInMethod`/`DealType` enums, `app.py:474-519`)
- Test: `tests/test_flow_verification.py` (new)

**Interfaces:**
- Produces (used by Tasks 2–5):
  - `class DealKindCanon(str, Enum)`: `FREEHOLD='freehold'`, `LEASEHOLD='leasehold'`, `RENTAL='rental'`, `EXCHANGE='exchange'`
  - `class PayInCanon(str, Enum)`: `REQUISITES='requisites'`, `CASH='cash'`, `CRYPTO='crypto'`, `SBP='sbp'`
  - `VERIFIED_FLOWS: set[tuple[str, str]]` — holds `{(DealKindCanon.FREEHOLD.value, PayInCanon.REQUISITES.value), (DealKindCanon.LEASEHOLD.value, PayInCanon.REQUISITES.value)}`
  - `def canonical_deal_kind_from_stand(deal_type: str, kind: str | None) -> str | None` — `deal_type=='Обмен валюты'` → `EXCHANGE`; else map `{'Фрихолд':FREEHOLD,'Лизхолд':LEASEHOLD,'Аренда':RENTAL}.get(kind)`
  - `def canonical_payin_from_stand(pay_type: str | None) -> str | None` — map `{'По реквизитам':REQUISITES,'СБП':SBP,'Крипта':CRYPTO,'Наличные':CASH}.get(pay_type)`
  - `def canonical_deal_kind_from_legacy(deal_kind: str | None) -> str | None` — map `{'mf_freehold':FREEHOLD,'mf_realty':LEASEHOLD,'rental':RENTAL,'exchange':EXCHANGE,'custom':EXCHANGE}.get(deal_kind)`
  - `def canonical_payin_from_legacy(payin_method: str | None) -> str | None` — map `{'flow_sole_reqs':REQUISITES,'sber_reqs':REQUISITES,'sber_wl':SBP,'spp_doverka':SBP,'crypto_direct':CRYPTO,'partners_cash':CASH}.get(payin_method)`
  - `def is_verified_flow(deal_kind_canon: str | None, payin_canon: str | None) -> bool` — `True` only if both are non-`None` and `(deal_kind_canon, payin_canon) in VERIFIED_FLOWS`

- [ ] **Step 1: Write failing tests for all translation helpers and `is_verified_flow`**

```python
def test_stand_canonical_mapping_freehold_requisites_verified():
    assert is_verified_flow(canonical_deal_kind_from_stand('Оплата недвижимости', 'Фрихолд'),
                             canonical_payin_from_stand('По реквизитам')) is True

def test_stand_canonical_mapping_rental_cash_unverified():
    assert is_verified_flow(canonical_deal_kind_from_stand('Оплата недвижимости', 'Аренда'),
                             canonical_payin_from_stand('Наличные')) is False

def test_legacy_canonical_mapping_mf_realty_flow_sole_verified():
    assert is_verified_flow(canonical_deal_kind_from_legacy('mf_realty'),
                             canonical_payin_from_legacy('flow_sole_reqs')) is True

def test_legacy_canonical_mapping_rental_sber_wl_unverified():
    assert is_verified_flow(canonical_deal_kind_from_legacy('rental'),
                             canonical_payin_from_legacy('sber_wl')) is False

def test_is_verified_flow_none_inputs_are_unverified():
    assert is_verified_flow(None, 'requisites') is False
    assert is_verified_flow('freehold', None) is False
```

- [ ] **Step 2: Run tests, verify they fail with `NameError`/`AttributeError`**

Run: `pytest tests/test_flow_verification.py -v`
Expected: FAIL — names not defined.

- [ ] **Step 3: Implement the enums, `VERIFIED_FLOWS`, and the four translation functions plus `is_verified_flow` in `app.py`**

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_flow_verification.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_flow_verification.py
git commit -m "feat: add canonical deal-flow taxonomy and VERIFIED_FLOWS single source of truth"
```

---

### Task 2: Add `rental` as a selectable legacy `deal_kind` value (server-side label/data only)

**Files:**
- Modify: `app.py:515-519` (`DEAL_KIND_LABELS`)
- Test: `tests/test_crm_ui_contracts.py` (update existing expectations)

**Interfaces:**
- Consumes: nothing new.
- Produces: `DEAL_KIND_LABELS` now includes `'rental': 'Аренда'`, consumed by Task 7's frontend select and by Task 5's error messages.

- [ ] **Step 1: Update/extend the failing assertion in `tests/test_crm_ui_contracts.py::test_kind_select_options_match_toggles`** (around line 248) to expect `{exchange, custom, mf_realty, mf_freehold, rental}` as the full option set once Task 7 adds the `<option>`. (This step only touches the Python-side label-map assertion now; the HTML-option assertion will go green once Task 7 lands — note this dependency in the test or split it into two assertions if the existing test conflates both.)
- [ ] **Step 2: Run `pytest tests/test_crm_ui_contracts.py -v -k kind_select`, confirm it fails** (missing `rental` in `DEAL_KIND_LABELS` and/or missing `<option>`).
- [ ] **Step 3: Add `'rental': 'Аренда'` to `DEAL_KIND_LABELS` in `app.py:515-519`.**
- [ ] **Step 4: Re-run the test — the label-map half should now pass; the `<option>` half stays red until Task 7.** Note this explicitly in the task's commit message.
- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_crm_ui_contracts.py
git commit -m "feat: add rental deal_kind label for legacy CRM analytics parity"
```

---

### Task 3: `GET /api/deal-flow-config` endpoint

**Files:**
- Modify: `app.py` (new route, near the other `/api/...` config-style routes)
- Test: `tests/test_flow_verification.py` (extend from Task 1)

**Interfaces:**
- Consumes: `VERIFIED_FLOWS`, `DealKindCanon`, `PayInCanon` from Task 1.
- Produces: `GET /api/deal-flow-config` → `200` JSON:
  ```json
  {"verified": [["freehold", "requisites"], ["leasehold", "requisites"]]}
  ```
  consumed by Task 6 (stand JS) and Task 7 (legacy CRM JS) to compute disabled state client-side without re-declaring the list.

- [ ] **Step 1: Write failing test**

```python
def test_deal_flow_config_endpoint_returns_verified_pairs(client):
    resp = client.get('/api/deal-flow-config')
    assert resp.status_code == 200
    assert sorted(tuple(p) for p in resp.get_json()['verified']) == sorted(VERIFIED_FLOWS)
```

(Use whatever `client` fixture pattern `tests/test_flowsole_crm_ui.js`'s Python counterpart or another existing `app.test_client()`-based test in this repo already uses — match the existing fixture, don't invent a new one.)

- [ ] **Step 2: Run test, verify it 404s.**
- [ ] **Step 3: Implement the route** `@app.route('/api/deal-flow-config', methods=['GET'])` returning `jsonify({'verified': [list(pair) for pair in VERIFIED_FLOWS]})`. No auth required (read-only, non-sensitive).
- [ ] **Step 4: Run test, verify pass.**
- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_flow_verification.py
git commit -m "feat: expose verified deal-flow pairs via /api/deal-flow-config"
```

---

### Task 4: Server-side gate on the stand creation/change path

**Files:**
- Modify: `app.py:9538-9558` (`_stand_guard_transition`, new-deal branch) and the method-change branch nearby (search for where `payType`/`kind` diffs against `before` are already handled around `app.py:9504-9537`)
- Test: `tests/test_stand_gate.py` (extend) or new `tests/test_stand_flow_verification.py`

**Interfaces:**
- Consumes: `canonical_deal_kind_from_stand`, `canonical_payin_from_stand`, `is_verified_flow` (Task 1); `current_role()` (`app.py:5227`).
- Produces: `_stand_guard_transition` raises/returns the same guard-error shape it already uses elsewhere (check the existing return convention at `app.py:9538-9558` — likely a tuple/exception the caller turns into a 4xx; match it) carrying `error: 'unverified_flow'` or `'unverified_flow_confirmation_required'` per Global Constraints, for `stand_state_put` (`app.py:6288`) to surface as HTTP 422.

- [ ] **Step 1: Read `app.py:9480-9560` in full to find the exact guard-error return/raise convention used by neighboring checks** (e.g. the existing `kind not in (...)` check at `app.py:9557`) so the new check matches it exactly — this is a prerequisite read, not a code change.
- [ ] **Step 2: Write failing tests:**

```python
def test_stand_create_unverified_combo_rejected_for_manager():
    # POST a fresh board via PUT /api/stand/state as a manager actor with a
    # new deal: type='Оплата недвижимости', kind='Аренда', payType='Наличные'
    # Expect HTTP 422, body['error'] == 'unverified_flow'

def test_stand_create_unverified_combo_rejected_for_admin_without_confirm():
    # same new deal, actor admin, no unverified_confirmed flag
    # Expect HTTP 422, body['error'] == 'unverified_flow_confirmation_required'

def test_stand_create_unverified_combo_allowed_for_admin_with_confirm():
    # same new deal, actor admin, deal carries unverified_confirmed: true
    # Expect success (200/whatever the existing successful-save status is)

def test_stand_existing_unverified_deal_progresses_untouched():
    # seed `previous` with an existing deal: kind='Аренда', payType='Наличные', step=N
    # PUT a `new_state` that only advances step/other fields, kind/payType unchanged
    # Expect success — gate must not fire

def test_stand_manager_cannot_bypass_with_confirm_flag():
    # manager actor sends unverified_confirmed: true directly
    # Expect still HTTP 422 'unverified_flow' — flag alone never authorizes non-admin
```

Follow the exact request/fixture shape `tests/test_stand_gate.py` already uses for actor/role simulation and `PUT /api/stand/state` calls — mirror it rather than inventing a new harness.

- [ ] **Step 3: Run tests, verify all fail (no gate exists yet).**
- [ ] **Step 4: Implement the gate** inside `_stand_guard_transition`:
  - In the `if not before:` branch (`app.py:9538`), after translating `deal.get('type')`/`deal.get('kind')`/`deal.get('payType')` to canonical values, call `is_verified_flow(...)`; if `False`, check `actor == 'admin' and deal.get('unverified_confirmed') is True` — if that's also false, return the appropriate guard error (confirmation-required variant only when `actor == 'admin'`, plain unverified variant otherwise).
  - In the combo-changed branch (diff `before.get('kind')`/`before.get('payType')` vs `new`'s), apply the identical check only when `(type, kind, payType)` canonical tuple actually differs from `before`'s — do not check when unchanged.
- [ ] **Step 5: Wire `stand_state_put` (`app.py:6288`) to turn the new guard-error into HTTP 422 with the exact JSON body from Global Constraints**, if it doesn't already generically forward guard-function errors as structured JSON — check first, only add translation code if missing.
- [ ] **Step 6: Run tests, verify pass.**
- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_stand_gate.py tests/test_stand_flow_verification.py
git commit -m "feat: enforce verified-flow gate on stand deal creation and combo change"
```

---

### Task 5: Server-side gate on the legacy CRM creation/edit path

**Files:**
- Modify: `app.py:16364-16726` (`_create_deal_impl`) and `app.py:16728` (`PUT /api/deals/<int:deal_id>`)
- Test: `tests/test_crm_ui_contracts.py` or new `tests/test_legacy_flow_verification.py`

**Interfaces:**
- Consumes: `canonical_deal_kind_from_legacy`, `canonical_payin_from_legacy`, `is_verified_flow` (Task 1), `current_role()`.
- Produces: `POST /api/deals` and `PUT /api/deals/<id>` return HTTP 422 with the same two error shapes as Task 4, for symmetry across both surfaces.

- [ ] **Step 1: Write failing tests mirroring Task 4's five cases, against `/api/deals` POST/PUT** — same five scenarios (manager rejected, admin-no-confirm rejected, admin-with-confirm allowed, existing deal with unrelated-field edit untouched, manager cannot bypass with the flag). For the "existing deal, unrelated field edit" case, create a `Deal` row directly with `deal_kind='rental'`, `payin_method='partners_cash'` (unverified), then `PUT` only `client_name` or `amount` and assert 200, not 422.
- [ ] **Step 2: Run tests, verify all fail.**
- [ ] **Step 3: Implement the gate in `_create_deal_impl`** right before the `Deal(...)` construction (near `app.py:16505-16544`): translate `data.get('deal_kind')`/`data.get('payin_method')`, call `is_verified_flow`, same admin+confirm-flag logic as Task 4 (`data.get('unverified_confirmed') is True`), return `(jsonify({...}), 422)` directly rather than raising (match whichever convention `_create_deal_impl` already uses for its other validation errors, e.g. the `realty_payload_error` check at `app.py:16654-16657` — follow that exact pattern).
- [ ] **Step 4: Implement the equivalent check in the `PUT /api/deals/<int:deal_id>` handler (`app.py:16728`)**, comparing incoming `deal_kind`/`payin_method` against the stored row's current values — only gate when either actually changes.
- [ ] **Step 5: Run tests, verify pass.**
- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_legacy_flow_verification.py
git commit -m "feat: enforce verified-flow gate on legacy CRM deal creation and edit"
```

---

### Task 6: Stand/tasks.html frontend gating

**Files:**
- Modify: `static/stand/tasks.html` (chip rendering around `5915-5933`, `payWays()` at `6083-6088`, CSS near `128`/`163-166`, `createGo()`/submit path `6293-6318`)
- Test: existing fenced-JS test pattern — extend `tests/test_stand_gate.py` or add `tests/test_stand_flow_ui_gate.js` following the structure of `tests/test_stand_freehold.js` (read that file first to copy its harness-invocation style)

**Interfaces:**
- Consumes: `GET /api/deal-flow-config` (Task 3); existing `standMe`/`S.role` admin-detection pattern (`static/stand/tasks.html:5173` etc.).
- Produces: deal draft object gains `unverified_confirmed: true` only when admin explicitly confirms, read by Task 4's server check.

- [ ] **Step 1: Read `static/stand/tasks.html:5900-5940` and `6080-6090` in full** to confirm current chip-rendering structure before editing (prerequisite read).
- [ ] **Step 2: Write a failing fenced-JS test** asserting: (a) a `Аренда`/`Наличные` chip combo renders with class `disabled` and `title="Флоу в проверке — пока проводите через Карима"` for a manager actor; (b) for an admin actor the same chip is clickable and clicking it triggers a `confirm('Непроверенный флоу, продолжить?')` call before `draftSet` applies the value; (c) declining the confirm leaves `D.kind`/`D.payType` unchanged.
- [ ] **Step 3: Run the test, verify it fails.**
- [ ] **Step 4: Implement:**
  - Fetch `/api/deal-flow-config` once at page load (or lazily before rendering the create form), cache as `S.verifiedFlows` (array of canonical pairs).
  - Add local label→canonical maps mirroring Task 1's stand-side mapping (pure presentation lookups, not a second copy of the verified list itself).
  - In the kind-chip and `payWays()` chip templates, compute per-chip verified status against the *currently selected* value of the other field; add `disabled` class + `title` attribute when unverified and actor isn't admin confirming; for admin, keep clickable but route the `onclick` through a small `draftSetGated(field, value)` helper that runs the `confirm(...)` dialog and sets `unverified_confirmed` on the draft when accepted.
  - Add `.chip.disabled{opacity:.45;cursor:not-allowed;pointer-events:none}` near the existing `.chip` rules (`static/stand/tasks.html:163-166`), modeled on `.btn:disabled` (`128`).
  - Ensure `createGo()`/`save()`/`standSave()` forward `unverified_confirmed` on the deal object untouched to the server payload (it already forwards the whole deal object — confirm no field-allowlist strips it; add it if one exists).
- [ ] **Step 5: Run the test, verify pass.**
- [ ] **Step 6: Commit**

```bash
git add static/stand/tasks.html tests/test_stand_flow_ui_gate.js
git commit -m "feat: gray out unverified deal-flow combos in stand task creation UI"
```

---

### Task 7: Legacy CRM frontend gating + "Аренда" option

**Files:**
- Modify: `static/crm/crm.html` (`dealKindSelect` `1169-1174`, `payinMethod` select `1386-1396`, submit handler `9195-9202`)
- Test: `tests/test_crm_ui_contracts.py` (finishes Task 2's split test), extend with new cases

**Interfaces:**
- Consumes: `GET /api/deal-flow-config` (Task 3).
- Produces: submitted payload gains `unverified_confirmed: true` only on admin confirm, read by Task 5's server check.

- [ ] **Step 1: Add `<option value="rental">Аренда</option>` to `dealKindSelect` (`static/crm/crm.html:1169-1174`).**
- [ ] **Step 2: Re-run `tests/test_crm_ui_contracts.py::test_kind_select_options_match_toggles` from Task 2 — now both halves (label map + `<option>`) should pass.** Also update `onDealKindChange`/`syncDealKindSelect` if they enumerate kinds explicitly, so `rental` is handled like `exchange`/`custom` (no special toggle fields) — read those functions first to confirm whether an explicit list needs the new value appended.
- [ ] **Step 3: Write failing tests for the gating behavior:**
  - Manager session: selecting `deal_kind=rental` then `payin_method` options for `sber_wl/crypto_direct/partners_cash` render as `<option disabled>`; `flow_sole_reqs`/`sber_reqs` (both canonical `requisites`) remain enabled only when paired with `mf_freehold`/`mf_realty`, not with `rental`/`exchange`/`custom`.
  - Admin session: no `<option disabled>`, but submit handler calls `confirm('Непроверенный флоу, продолжить?')` when the current combo is unverified, and aborts the `fetch` if declined.
  - Submitting an unverified combo as admin with confirm accepted includes `unverified_confirmed: true` in the POST/PUT body.
- [ ] **Step 4: Run tests, verify they fail.**
- [ ] **Step 5: Implement:**
  - Fetch `/api/deal-flow-config` once, cache verified pairs.
  - Add the same small local label→canonical maps as Task 6 (legacy-side mapping from Task 1, presentation-only).
  - On `change` of either select, recompute the other select's option `disabled` attributes against the verified-pairs cache for non-admin sessions; for admin sessions leave options enabled but mark the currently-selected unverified combo with a visible badge/hint text (`Флоу в проверке — пока проводите через Карима`) near the selects.
  - In the submit handler (`static/crm/crm.html:9195-9202`), before `fetch`, compute canonical verified-ness of the current selection; if unverified and session is admin, call `confirm(...)`, abort on cancel, otherwise set `data.unverified_confirmed = true`; if unverified and session is not admin, block submit client-side too (defense in depth — server is the real gate per Task 5).
- [ ] **Step 6: Run tests, verify pass.**
- [ ] **Step 7: Commit**

```bash
git add static/crm/crm.html tests/test_crm_ui_contracts.py
git commit -m "feat: add Аренда option and gate unverified flows in legacy CRM create/edit form"
```

---

### Task 8: Calculator UX gating (non-authoritative, defense-in-depth only)

**Files:**
- Modify: `static/calculator/index.html` (category/method buttons, read exact current markup around `238-264` before editing), `static/calculator/calculator.js` (`createDealFromCalc`, `2175-2222`)
- Test: whatever existing calculator JS test file already exercises `createDealFromCalc` (locate via `grep -l createDealFromCalc tests/`); add a case there

**Interfaces:**
- Consumes: `GET /api/deal-flow-config` (Task 3).
- Produces: nothing new consumed downstream — purely cosmetic gating, since Task 7/5 are the real enforcement for anything reaching `/crm#create`.

- [ ] **Step 1: Read `static/calculator/index.html:230-270` and `static/calculator/calculator.js:2150-2225` in full** to confirm the exact current category and method controls and how `state.method`/category map into `dealData.deal_kind`/`payin_method` in `createDealFromCalc()` — this plan's earlier research pass was imprecise here, so verify directly before writing code.
- [ ] **Step 2: Write a failing test** asserting that selecting a category/method combination whose translated canonical pair is unverified renders the corresponding button(s) with the disabled convention (`opacity:.45;cursor:not-allowed`) and the tooltip text, mirroring Task 6/7's behavior — exact selector names to be filled in once Step 1's read confirms them.
- [ ] **Step 3: Run test, verify it fails.**
- [ ] **Step 4: Implement the same fetch-once-cache-verified-pairs pattern as Tasks 6/7, applied to whatever controls Step 1 identified.** No admin-bypass UI needed here (admin bypass happens at the crm.html landing form, Task 7) — calculator only needs to show the disabled state; it does not need its own confirm dialog.
- [ ] **Step 5: Run test, verify pass.**
- [ ] **Step 6: Commit**

```bash
git add static/calculator/index.html static/calculator/calculator.js <test file>
git commit -m "feat: gray out unverified combos in calculator deal-category UX (cosmetic; server/CRM enforce)"
```

---

### Task 9: Full regression, design-gate, independent QA, and report

No code changes — verification only.

- [ ] **Step 1: Run full pytest suite**, confirm 0 failed: `pytest -q`
- [ ] **Step 2: Run the JS test runner** (whichever script already runs `tests/test_*.js` — check `pytest.ini`/`scripts/run_fenced_js.py` for the invocation), confirm no NEW failures beyond the 9-file baseline in Global Constraints.
- [ ] **Step 3: Invoke the `design-gate` skill** against the type/payin selection screens in both the stand task-create flow and the legacy CRM create/edit form, for both manager and admin roles, at 375px and 1280px, using a real authorized session (not a mock) — capture screenshots.
- [ ] **Step 4: Dispatch an independent reviewer** (a `qa-tester` subagent, or a fresh Claude thread with no prior context) to execute the exact test matrix from Global Constraints' Review Focus section against a running instance, independent of whoever implemented Tasks 1–8.
- [ ] **Step 5: Compile the final report** covering: files/lines changed per task, confirmation that `VERIFIED_FLOWS` is the single constant read by both server paths and both frontends (cite the one `app.py` location), screenshots from Step 3, regression results from Steps 1–2, independent QA findings from Step 4, and explicit confirmation (with a concrete example, e.g. a seeded rental+cash deal) that an already-in-progress deal was unaffected.
