# QA: legacy `originMode=manual` («Внести целиком») — приход USDT только по hash

Отдельный отчёт follow-up к hash-only изменению. Отчёты `docs/qa-payout-receipt-implicit.md` (core `dd2af95`) и `docs/qa-manual-payin-hash-only.md` (`85b19ec`) не менялись. Независимый Claude qa-tester; Python-прогоны fenced-раннером выполнял родитель, я писал тесты, ревьюил дифф и интерпретировал логи. Производственный код и чужие тесты я не менял.

**Статус: ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для legacy hash-only.**

## Scope
- Закрытие legacy-сделки `originMode=manual` («Внести целиком») через `crm-close` теперь требует приходный hash USDT; сеть проверяет его сама (тот же native-путь `_stand_override_payin_verify` с `observe_recipient`, что и в `manualOverride`), получатель — наш активный кошелёк реестра (`_stand_payin_wallet_problem`, включая выбранный `walletId` и `custom`).
- Явные `from` / `to` / сумма на доске сверяются с наблюдённым в сети и не отбрасываются; TRON-адреса регистрозависимы, ERC-20 — нет. Свободной суммы нет: сумма CRM обязана совпасть с сетью.
- Серверный writeback: `verified`, `verifiedAt`, `from`, `amount` берутся из ответа сети; если сеть не отдала отправителя, `from` сбрасывается и ставится `unknownSender` (введённому не верят). Фрихолд получает `verified` только от сети.
- Не менялось: обычный s27, `manualOverride`, выплата по чеку, роли.

## Тесты (мои, независимые)
`tests/test_stand_legacy_manual_payin_hash_qa.py` — реальный маршрут `/api/stand/deals/<id>/crm-close`, настоящий `stand_transfers.verify_transfer`, фейковый `get` (TronScan), свой реестр кошельков, без внешней сети. Использует `install_native_verifier`, `tronscan`, `make_wallet_flags` из `tests/test_stand_manual_payin_hash_only_qa.py`.
- **`test_legacy_manual_payin_native_contract` (24):**
  - Позитивы (6): raw-hash без суммы, raw с суммой на доске, явные from+to (строгая сверка), только from, только to, выбранный `walletId` совпадает → `201`, на доске серверные `verified/verifiedAt/from/amount`, сделка+связь +1.
  - Отказы (18): получатель вне реестра / неактивный / `accepts_payin=False`; sender не совпал; receiver — другой наш кошелёк; TRON-receiver с изменённым регистром; сеть 50 против CRM 100; сумма на доске ≠ сети; сумма CRM в допуске 5, но ≠ сети; pending; несколько получателей; выбранный кошелёк — другой / несуществующий; CRM-hash ≠ hash доски; нет hash; пустая строка; невалидный формат; hash чужой сделки. Точные коды проверены там, где контракт известен (`payin_hash_unverified`, `payin_amount_mismatch`, `payin_hash_already_used`, `payin_facts_mismatch`, `payin_hash_required`, `payin_hash_invalid`).
  - После каждого отказа неизменны: сырая доска (`StandState.data`) и версия, `Deal`, `StandCrmLink`, `PayinTx`, `PayinTxUse`, `StandCloseEvidence`.
- **Повтор:** второй submit после успеха → `200 duplicate`, число сетевых вызовов не растёт, ledger не меняется.
- **Откат writeback:** hash сверен, но CRM расходится по выплате → на доске нет `verified`/`from`, ledger и версия прежние.
- **Фрихолд HTTP (4):** сырой hash + подтверждение сети → `201` с серверными `verified/from`; `verified:true` на доске при pending сети → `422`; `payerWallet` ≠ сетевой отправитель → `409 payin_basis_unverified`; введённый `from`, которого сеть не подтвердила → `422 payin_hash_unverified`.

## Результаты
| Прогон | Результат |
|---|---|
| **Targeted2** (мои legacy + hash-only + core QA и связанные) | **353 passed, 0 failed**, `NETWORK_FENCE attempts=0 unexpected=0` |
| **Full Python** | **3460 passed, 77 skipped, 0 failed**, 285.94 s, `NETWORK_FENCE attempts=8 unexpected=0` (8 ожидаемых заблокированных попыток) |
| **Сравнение с baseline `85b19ec`** (`comparison-py.json`) | baseline 3422 passed / 77 skipped; `changed = {}`, `failed = []`, added 41, removed 3; 3422 + 41 − 3 = 3460 |
| **Full JS** | 74 passed / 2 failed (те же два известных baseline-падения), `changed = {}` |

Замечание о цифрах: в сообщении координатора фигурировало «added 40»; в файле `/tmp/calccrm-legacy-manual-validation/comparison-py.json` — `added 41`, и только с 41 арифметика сходится с 3460. В отчёте использованы числа из файла.

**Заменённые тесты (removed 3, старые ожидания по новому scope, не потеря покрытия):**
- `test_manual_origin_close_still_works_without_override` — закрытие legacy без hash; заменён `test_manual_origin_close_works_with_network_verified_payin_hash` и негативами.
- Два параметра `test_manual_close_requires_route_money_on_saved_board` (exchange payin и Фрихолд): ожидание `payin_basis_missing` / прежнее имя теперь `payin_hash_required`.

## Независимое ревью диффа (read-only, `app.py` legacy-ветка `stand_crm_close`)
Блокеров нет. Подтверждено: единый native-verifier и единая проверка реестра с `manualOverride`; частичные явные ограничения не теряются; сумма CRM привязана к сети после writeback (`_stand_crm_fact_problem`); запись идёт в локальную копию `state` и не сохраняется при отказе; повтор уходит в ветку `duplicate` до проверки сети.

Замечания (не блокеры):
1. У legacy-сделки с `walletId` старого вида (`grusha`, `vitaly` и т. п.) негодный выбор теперь даёт `payin_selected_wallet_invalid`; у сделок без `walletId` поведение прежнее.
2. Допуск суммы двойной: до 0,01 на hash при указанной сумме и до 5 USDT суммарно против суммы CRM, если суммы hash на доске нет; после writeback CRM сверяется с сетью точно (0,01).
3. Для sender/receiver, введённых менеджером, но не подтверждённых сетью, отказ приходит как `payin_hash_unverified` (422), а не как `payin_basis_unverified` (409) — отказ при сверке hash раньше правила фрихолда.

## Ограничения (не проверено)
- Браузерный E2E; legacy UI-поток ввода hash проверен только JS-тестами исполнителя (`test_stand_crm_push_close.js`, hash_preview).
- ERC-20 native-тест (регистронезависимость только по коду и unit-тестам исполнителя).
- Legacy-сделки с `cnvId` / приходом через `convs[].txs` (accepted_conversion): guard читает только `payinHashes` доли; отдельного моего теста на такую форму нет.
- Живые интеграции, прод-данные, реальный Etherscan/TronScan.

## Вердикт
**ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для legacy `originMode=manual` hash-only.** Основания: targeted2 353/0 (fence 0), полный Python 3460 passed / 77 skipped / 0 failed против baseline `85b19ec` (`changed = {}`, added 41, removed 3), полный JS 74/2 = baseline, неожиданных сетевых попыток 0, блокеров в независимом ревью диффа нет. Ограничения выше не блокируют.
