# CalcCRM test network fence (T19)

Run Python tests with Python 3.11 on macOS:

```sh
/tmp/qa-t15b/.venv311/bin/python scripts/run_fenced_pytest.py -q --disable-warnings --tb=short
```

Run the repository JavaScript tests:

```sh
/tmp/qa-t15b/.venv311/bin/python scripts/run_fenced_js.py
```

Both launchers require `sandbox-exec`. They start the test process inside a
fresh OS profile that denies network syscalls except a run-specific, checked
pool of exact localhost TCP ports and private test PostgreSQL Unix sockets.
The Python launcher clears the inherited environment, sets a synthetic SQLite
URL, disables dotenv and startup pollers, and loads `sitecustomize` before any
application import. Python child processes inherit it even when a test passes
its own `env` to `subprocess.Popen`. Plain pytest collection refuses to run
without this bootstrap. Test-specific fake integrations are installed by
`tests/conftest.py` before each test; their lower transports never see a real
external destination.

The Python audit hook rejects external DNS, connect, sendto and sendmsg before
the corresponding Python socket operation. It writes only PID, test ID, source
location, operation and expected flag to a private append-only JSONL ledger.
The launcher exits nonzero when any unexpected entry exists, including errors
caught by background threads or child processes. `--verify-fail-closed`
intentionally exercises that outcome and must exit 1. `expect_blocked()` is
for a single intentional negative probe; it does not disable the barrier.
Reports are retained with mode 0600 in `/tmp/calccrm-t19-fence-reports`.
`--verify-plain-refusal` runs collection under the OS sandbox without the
Python bootstrap and confirms that `conftest.py` stops before app import.

Native code, `python -I -S`, `env -i`, and Node still inherit the macOS sandbox,
which blocks their external and foreign-loopback syscalls. **Their denials do
not enter the Python ledger.** A native process that catches `EPERM` can still
return 0; native denied-attempt auditing remains open. The OS layer proves
prevention for the tested paths, while the Python ledger proves fail-run only
for operations that reach its audit hook. The port pool is selected after a
free-port check, but the OS does not prove that a newly bound service in the
pool belongs to this test process. Keep unrelated local listeners out of the
run's reported pool.

Inventory of test subprocess entry points: `test_stand_egress.py`,
`test_stand_read_channels.py`, `test_stand_gate.py`,
`test_stand_lk_transport.py`, `test_prod_schema.py`,
`test_stand_sber_mirror.py`, `test_stand_copy_prod.py`,
`test_crash_audit.py`, `test_doc_routes.py` and the LibreOffice conversion in
`test_docgen.py`. `test_stand_egress.py` and `test_stand_read_channels.py`
construct independent environments; the bootstrap is injected by the parent
Popen wrapper. Native PostgreSQL tests use only own temporary local endpoints.

App import startup sources: reestr sync, payin address backfill, TronScan warm,
Metrika channel traffic, payment link poll, KYC retention, stand transfer
poll, stand Telegram updates (including `getMe`/webhook preflight), and Sber
mirror. Every default test environment sets their enable flags to `0` before
import. Tests of a poller opt in explicitly with a fake lower transport.
Production behavior with unset flags is unchanged.

The shared checkout's unversioned Git `pre-commit` hook still invokes plain
pytest. For this worktree, use `git -c core.hooksPath=/dev/null commit` only
after a separate fenced run. The versioned `.githooks/pre-commit` is a safe
replacement for an explicitly configured worktree; it refuses to run if the
OS sandbox or Python 3.11 is unavailable. Never rely on the shared unversioned
hook as a test gate.
To opt in for one commit, set `CALCCRM_TEST_PYTHON` to the Python 3.11 venv
binary and run `git -c core.hooksPath=.githooks commit ...`; this does not
change another worktree's Git configuration. The hook runs the fenced full
suite. The T19 commit itself may use `git -c core.hooksPath=/dev/null commit`
after the independently recorded full fenced run, because the shared legacy
hook is unsafe.

Four LibreOffice PDF conversion checks are skipped inside the mandatory OS
profile: LibreOffice exits 0 without writing a PDF under that profile. The
remaining document-generation tests still run. PDF conversion needs a
separate, independently reviewed local-only sandbox setup before those checks
can count as passed.
