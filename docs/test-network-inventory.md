# T19 blocked-attempt inventory

All entries below were denied before the network operation. The OS sandbox
was active during every inventory run. Full sanitized per-test/PID lists are
in these private reports:

- `/tmp/calccrm-t19-fence-reports/initial-inventory.json`: 107 unexpected
  attempts in 70 tests and 3 Python processes.
- `/tmp/calccrm-t19-fence-reports/20260928T163237-82087.json`: after the
  TronScan fake transport, 50 unexpected attempts in 43 tests and 2 Python
  processes (plus 5 intentional guard-negative probes).

Observed sources and fixes:

| Source | Observation | Test isolation |
| --- | --- | --- |
| `_tron_tx_info` | Synthetic transaction hashes in deal, conversion, reimbursement, wallet and referral tests led to TronScan DNS attempts. | Endpoint-specific 404 fake in `tests/conftest.py`. |
| `send_telegram_notification` | 38 tests, mostly referral and reimbursement flows, attempted Telegram DNS using test tokens. | Endpoint-specific synthetic `ConnectionError` before transport. |
| `get_bot_username` | Two admin/referrer tests attempted Telegram `getMe`. | Same synthetic Telegram transport. |
| `send_referrer_dm` | One referrer auth test attempted Telegram DM. | Same synthetic Telegram transport. |
| `/api/rates` | One public-auth test requested Binance/Rapira/Bitazza; its assertion only concerns public access. | Fake rates and Bitazza quote in that test. |
| Stand read-channel timeout | One child connected to the deliberately unused local port 1, outside its own endpoint pool. | Uses an unused port in the run's private pool. |
| Stand egress DB/UDP policy tests | Existing probes would call the real lower socket transport. | Replaced lower transport with a call-tracking fake before installing the stand guard. |

The final full run (`20260928T164121-87858.json`) passed 1876 tests, skipped
34, and recorded 8 intentional guard-negative probes with **zero unexpected
Python attempts** in 146.29 seconds. The separate JavaScript run passed 14 of
14 files (`20260928T163500-js-85626.json`). A blocked operation is not
evidence of a real outbound request. Native denied-attempt logging is outside
the Python ledger's scope; see `test-network-fence.md`.
