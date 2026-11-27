# T18 UI parity audit

This directory contains a read-only product audit. It does not change product code or contact external services. The runtime audit uses three independent PostgreSQL 17 restores of the same dump: main prod mode, candidate prod mode, and candidate `STAND_MODE=1`. It uses a synthetic admin and fixed browser clock. Only the stage STAND clone receives a synthetic rental write, after all common screen snapshots are captured.

## Runtime audit on macOS

Run only through `safe_run.py`; it refuses to import the app unless the macOS OS sandbox is active. `fence.sb` denies all network operations except the audit's own PostgreSQL Unix socket prefix and exact local app ports 18881–18883. The bootstrap clears inherited environment variables, disables dotenv, and proves external and unauthorized local connects return `EPERM`, including in a native Ruby child process. Browser requests to external assets are also aborted by Playwright; attempted assets are still counted as a finding. The Python socket guard in `sitecustomize.py` is an additional layer, not the OS boundary.

```sh
python3 scripts/ui_parity/safe_run.py \
  --baseline /tmp/calccrm-t12-main \
  --candidate /tmp/calccrm-t18 \
  --dump /path/to/read-only-dump.sql.gz \
  --report /tmp/t18-anonymized-report.md \
  --evidence-dir /tmp/t18-private-evidence
```

Use a new report path and evidence directory on each run. The evidence directory is 0700; full DOM JSON and screenshots are 0600. Keep that directory outside the repository and never publish it in CI artifacts. The Markdown report has only hashes, static field labels, counts, paths and classifications. Nonzero exit is expected while recorded baseline failures or unreviewed source changes remain; never relabel it PASS merely because a subset of DOM hashes match. The audited input trees must be tracked-file clean.

## Dump-free browser CI gate

```sh
python3 scripts/ui_parity/safe_run.py --synthetic-runtime \
  --baseline /tmp/calccrm-t12-main --candidate /tmp/calccrm-t18
python3 scripts/ui_parity/safe_run.py --synthetic-runtime \
  --baseline /tmp/calccrm-t12-main --candidate /tmp/calccrm-t18 --mutation-test
```

The baseline must be the pinned main SHA `2c40e91`; the CI workflow checks it out separately. Both input trees must be clean and stable before and after the run. A dirty main tree is refused before app import; a dirty candidate can only run with `--capture-out`, which is explicitly exploratory and cannot pass the acceptance gate. The runtime creates three independent private SQLite databases, seeds synthetic admin/partner/referrer and exchange/MF Realty/freehold deals, starts main, stage prod and stage STAND under the same OS network fence, and reuses the raw-dump harness's browser navigation and DOM/control extractor. Its registry records exact rendered text, visible control values/options/required/readOnly/disabled attributes and open ShadowRoot content for 91 current cases, including unauthenticated login and a separate extractor fixture. It separately checks that main versus stage prod has only the frozen Admins text difference and no visible control schema difference. It prints the known baseline failures with owners and reports every changed captured signature as `NEW_UI_DIFF` with a nonzero exit. The approved STAND delta registry contains only the exact preview control and three disabled links on this fixture. There is no auto-record or acceptance shortcut; changes to the registry require review of the actual rendered difference. New product code that has not yet been exercised, including T17's eventual adapter, remains OPEN.

The mutation run takes a no-op snapshot on the **same page and route** before each change and requires it to equal the registered case. It then checks that only the target case differs. Its 16 probes cover a dynamic label, light DOM visibility, readOnly, required, hidden native select option, new control, new ShadowRoot host, the visible Bitazza `/api/rates` value, and existing ShadowRoot control hide/reveal, ancestor display, host display/visibility/hidden, custom option visibility and hidden native select option. The extractor walks the composed ancestor chain through each shadow host. It records visible shadow text/labels/controls separately from all native select contracts and their visibility flags. The workflow installs dependencies before starting the fenced app/browser run, emits no DOM/screenshots as public CI artifacts, and uses only synthetic fixtures. Private screenshots/DOM are deleted when the runner exits.

`source_review.py` remains only a supplementary source review signal. It can flag changed HTML/JS, including a new separate JS adapter, but its hashes are never called rendered UI parity. It has no `--record` option. The browser gate above is the required CI parity check. The raw-dump audit remains necessary to cover real data shapes and every workflow state.
