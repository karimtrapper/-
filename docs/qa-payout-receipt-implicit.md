# QA: чек выплаты подтверждает выплату сам + приход USDT всегда с hash

Ветка `fix/payout-receipt-implicit-confirm`, исходная база `e165aee`; актуальный baseline для сравнения (поправки) — `10a4d7e`. Независимый Claude qa-tester. Python-прогоны через fenced-раннер выполнял родитель (мой `sandbox-exec` вложенно недоступен); я писал `tests/test_payout_receipt_independent_qa.py` / `.js` и интерпретировал логи.

**Статус: ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для core-коммита (scope: чек выплаты + приход USDT всегда с hash). Legacy `originMode=manual` — отдельным следующим коммитом.**

## Актуальный scope
1. Чек выплаты, приложенный manager/operator/admin (слот «Чек» или «+ Загрузить ещё» с типом «чек»), сам подтверждает выплату; автор и дата берутся из серверной записи; тесты подделки автора и байтов блокируют ложное подтверждение. Bank/founder/cash выплата — без blockchain hash, по чеку + сумме + получателю. Crypto-выплата без hash — блок. Закрытие operator запрещено.
2. `manualOverride` (СД-1489): никаких подтверждений других людей; висящая ручная сверка прихода снимается.
3. **Правка Карима: приход USDT ВСЕГДА требует hash** (наличные / банк / крипта; `manualOverride` и обычный s27); сверка сетью без подписи человека.

## Прогоны (финальные)
| Прогон | Результат |
|---|---|
| Мой файл (qa-targeted2 и targeted6) | 55 passed, 0 failed, `NETWORK_FENCE attempts=0 unexpected=0` |
| `wave-final3` / `t24-final` | 47 passed / 10 passed, 0 failed |
| **Full Python (candidate-py.log/xml)** | **3379 passed, 77 skipped, 0 failed**, 281.62 s, `NETWORK_FENCE attempts=8 unexpected=0` (8 ожидаемых заблокированных попыток) |
| **Сравнение с baseline `10a4d7e`** (comparison-py.json) | baseline 3350 passed / 77 skipped; `changed = {}`, `failed = []`; added 41, removed 12; арифметика сходится: 3350 + 41 − 12 = 3379 |
| **Full JS** | 73 passed / 2 failed (`mobile_tasks_nav`, `owner_summary`) = baseline 73/2, `changed = {}` |

**Заменённые тесты (removed 12 — старые ожидания по новому scope, не потерянное покрытие):**
- Мои 3 старых варианта регресса СД-1489 без hash (`rub-cash`, `cash-partner`, `cash-partner-hash` в прежней логике) → заменены тестами «приход с hash закрывается одним submit» и «без hash — негатив».
- 5 старых параметров `test_cash_payin_requires_persisted_basis` (рублёвый cash без hash закрывался `201`) → заменены 10 новыми t24-тестами (5 HTTP-негативов + 5 unit-проверок формулы RUB/курс).
- 4 старых теста исполнителя, ожидавших закрытие без hash или подпись прихода оператором (`test_operator_confirmation_creates_immutable_manual_provenance` — переименован в `test_manual_bank_confirmation_cannot_be_signed_as_payin_close_evidence`, `test_cash_partner_payin_is_not_forced_to_crypto_hash`, `test_non_crypto_payin_needs_no_evidence_hash_or_file`, `test_payin_cash_still_needs_operator_signoff`) → заменены тестами нового scope.
- Четыре теста `test_stand_prepay` (partial_loss/full_profit) прошли. Артефакты прогонов: `/Users/karimamirov/.bb/thread-storage/thr_7tepwzzr5m/payin-hash-validation`.
- Added 41: 17 в моём файле, 10 `test_t24_missing_facts_admission`, 9 `test_stand_manual_close_override`, 3 `test_stand_payout_receipt_implicit`, по 1 в `test_stand_crm_close_atomic` и `test_stand_manual_bank_receipt`.

## Сценарии (мой файл + JS)
Все PASS по прогонам выше.
1. Чек в слоте «Чек» и через `additional` признаётся без перезагрузки; автор/роль/дата с сервера.
2. Реальный `201` на `crm-close` обычного пути (инвойс 455000), оба слота; одна сделка. Нет чека → `409`, сделки нет. Crypto-маршрут без hash → блок.
3. Подделка `PUT /api/stand/state`: (а) без байтов + чужой `uploadedById` + поддельный `payoutFact` → блок; (б) валидные байты + чужой id → подложный автор не появляется; (в) настоящий uid + поддельные имя/роль → берутся с сервера.
4. Невалидные файлы → `400`; `additional` не-«чек» выплату не подтверждает; приоритет новой загрузки над старым `s26_completed`; s27 с `invoicePaid=false` + чек менеджера → `201`.
5. `manualOverride` bank/founder/cash с чеком → `201`; слот «Чек» из формы ручного переноса на s14/s11/s4 грузится (был BLOCKER); `docs.receipt=true` без файла — не чек; `mfPayout` + реальный чек → `201`; недоплата vs инвойс (454000 блок, 454999.5 проходит); bank поверх crypto → `payout_route_conflict`; crypto без hash / неизвестный маршрут / нет получателя → блок; operator → `403`.
6. **Приход с hash:** регресс СД-1489 (hash партнёра + висящая RUB-сверка → один submit `201`, сверка `cancelled`, нот оператора нет, нет `operator_attestation`, журнал «вне задачника … без подтверждений операциониста»; spy `verify_transfer` доказывает автоматическую сетевую сверку hash/сети/суммы; повтор не дублирует сделку).
7. **Приход без hash — негатив:** без hash / пустая строка / невалидный (в CRM тот же hash) / pending / сумма по сети не сошлась / чужой hash → отказ (`payin_hash_required|invalid`, `422 payin_hash_unverified|payin_amount_mismatch|payin_hash_already_used`), сделка не создаётся, сверка остаётся pending.
8. Обычный s27: приход `verified_network`, `system`, без подписи → `201`; без hash (Наличные/СБП/Банк) — причина НЕ `operator_confirmation_missing`, `required_role` не `operator`, POST `close-evidence` по приходу отказывает и подпись не создаёт, `crm-close` `409`; `verified:true` с пустой строкой hash → реальный отказ.
9. JS: `hasReceipt`/`receiptDocs`, `noncryptoPayout` (12 вариантов), «чек приложен · автор · дата», `manualClosePayload` (route/amountThb/recipient/hashes), ввод «Хеш прихода» для cash/bank/СБП/cash-partner.

### Отменено (старые формулировки)
- Приход без hash в `manualOverride` / `cash-partner` без hash — **отменено** правкой Карима, теперь негатив (п. 7).
- «Область `manualOverride`: проверка прихода снята» — **отменено**.
- Подпись прихода оператором (`sber_mirror`, `manual_bank_confirmed`, `operator_attestation`) — **отменено**: `close-evidence` по приходу отказывает для всех не-сетевых источников.
- Прежние итоги «3348 passed / 0 failed» и «qa-targeted4: 219» относились к старому scope и не используются.

## Закрытые дефекты по ходу QA
1. Слот «Чек» из формы ручного переноса на раннем шаге давал `403` — исправлено.
2. Висящая `manualBankReceipt` блокировала ручное закрытие (`409`) — исправлено (`cancelled` + `resolvedBy/At/Reason`).
3. Свежий cash-partner hash падал с «Недостаточно резерва пачки» — исправлено (`pre_override_payin_keys`: резервы только у hash, бывших на доске; свежий учитывается как обычный перевод с проверкой дублей).
4. Обычный путь не сравнивал факт выплаты с инвойсом — `_stand_noncrypto_payout_basis` отклоняет `transfer.thb`/`payout.thb` меньше инвойса.
5. `close-evidence` по приходу с `sber_mirror` давал `200`; пустой/невалидный hash давал `payin_facts_mismatch` — исправлено (`payin_hash_required` / `payin_hash_invalid`).
6. Загрязнение общей БД моими `crm-close` (116 падений) — исправлено autouse-fixture в моём файле (чистит только созданные строки, восстанавливает `stand_state`, уникальные hash).

## Независимое ревью диффа и тестовых хелперов
- `_crm()`/`_seeded_payin()` в `test_stand_crm_close_atomic.py` копируют hash из доски; подмену прикрывает отдельный независимый негатив `test_forged_payin_hash_in_crm_payload_is_rejected_and_valid_one_closes` (случайный hash в CRM → `409 payin_facts_mismatch`). Подмена только суммы прихода в обычном s27 отдельным негативом не покрыта (для `manualOverride` покрыта).
- `wave_a`: убыточный THB→RUB оставлен сетевым негативом (`409 не хватает 49.83 USDT`, счётчики неизменны) + отдельный позитив с покрытой экономикой (курс 2,5, 1529,99 USDT при входе 1602,56); замена на `cash` отклонена.
- `test_t24_missing_facts_admission`: исходные входные данные сохранены (рублёвый cash без hash на доске); HTTP: `close-evidence` по приходу → `409 payin_hash_required`, `crm-close` → `409 close_evidence_missing` с `verified_payin_missing`, счётчики неизменны; формула RUB/курс вынесена в unit-тест на `_stand_crm_fact_problem` (5 параметров, те же причины). Подмены проверяемого факта нет. Замечание: unit-тест формулы допускает «позитив» без hash — это формула суммы, не допуск закрытия; закрытие без hash блокирует HTTP-тест.
- Заметки без блокеров: `chain()` в `test_wallet_roles_manual_close` подтверждает приход эхом (сумма прихода там не проверяется); `_stand_manual_close_resolve_tasks` помечает прочитанными все ноты сделки и пишет `role: 'manager'` даже при admin.

## Ограничения (не проверено)
- Браузерный E2E (Chromium) не проводился; UI проверен только функциями `tasks.html` через `vm`.
- Cash-partner в обычном s27 — только readiness (полный `crm-close` требует резерва партии наличных в ledger); `accepted_conversion` покрыт позитивом исполнителя (`test_stand_payout_receipt_implicit.py`), не моим файлом.
- **Legacy `originMode=manual` («Внести целиком») по решению координатора ОТЛОЖЕН следующим коммитом.** Шесть тестов + helper + `H_L` сохранены в `/tmp/calccrm-payin-hash-validation/legacy-qa.patch`; план усиления: независимый CRM-hash ≠ hash доски и неверная сумма по сети (повтор, rollback, receiver — существующими тестами исполнителя). В этом коммите legacy не проверен.
- Живые интеграции и прод-данные не использовались.

## Вердикт
**ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для core-коммита.** Основания: мой файл 55/55; полный Python 3379 passed / 77 skipped / 0 failed против baseline `10a4d7e` (changed = {}, failed = []); полный JS 73/2 = baseline; сеть: 0 неожиданных попыток; независимое ревью диффа и тестовых хелперов — блокеров нет. Старые ожидания (приход без hash, подпись прихода оператором) заменены по новому scope правки Карима и перечислены выше.

**Вне этого коммита:** legacy `originMode=manual` («Внести целиком») — отдельным следующим коммитом (патч `/tmp/calccrm-payin-hash-validation/legacy-qa.patch`); браузерный E2E не проводился; cash-partner в обычном s27 проверен только по readiness.
