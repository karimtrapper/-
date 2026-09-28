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

## Dump-free CI gate

```sh
python3 scripts/ui_parity/synthetic_gate.py
python3 scripts/ui_parity/synthetic_gate.py --mutation-test
```

The first command checks exact source fingerprints for CRM sections, task form logic, calculator, referrer, login and a fixed selector registry. It prints known baseline failures explicitly. A new change prints `NEW_DIFF` and exits nonzero. The mutation test injects a new control into `section#deals` and verifies that the gate fails. This gate is a drift alarm; it does not replace the OS-fenced, real-browser runtime audit or independent QA. Update `synthetic_registry.json` only after reviewing an intended UI change and rerunning the runtime audit.
