# QA: чек выплаты подтверждает выплату сам (payout receipt implicit confirm)

**Статус: ФИНАЛЬНЫЙ PASS для scoped API/JS и полного набора (см. «Прогоны» и оговорку).** Ветка `fix/payout-receipt-implicit-confirm`, база `e165aee`.
Роль: независимый Claude qa-tester. Исполнитель кода и запуск раннеров — родитель/исполнитель; я писал тесты и разбирал логи.

## Как проверялось и чего нет
- Python: `tests/test_payout_receipt_independent_qa.py` через `scripts/run_fenced_pytest.py` (запускал родитель, мой `sandbox-exec` вложенно не работает). Вызовы API идут через Flask test client на реальных маршрутах (`/api/stand/files`, `/api/stand/deals/<id>/close-evidence`, `/crm-close`), загрузка файлов — настоящая, не правка доски.
- JS: `tests/test_payout_receipt_independent_qa.js` — реальные функции из `static/stand/tasks.html`, вырезанные в `vm`. Сначала dry-run обычным `node`, затем fenced-прогон (full JS, см. ниже) — PASS.
- **Браузерного E2E (Chromium) НЕ проводилось.** UI проверен только на уровне функций (`hasReceipt`, `receiptDocs`, `noncryptoPayout`, `crmEvidenceParts`, `crmCloseReason`, `manualClosePayload`).
- Живые интеграции не использовались; `NETWORK_FENCE attempts=0 unexpected=0` в прогоне 3.

## Прогоны (финальные)
- **Мой файл изолированно (qa-isolated-final3.log/xml): 41 passed, 0 failed, `NETWORK_FENCE attempts=0 unexpected=0`.** Включает три исправленных теста подделки (сценарий 6).
- **Целевой набор раньше (qa-targeted4.log): 219 passed, 0 failed, `NETWORK_FENCE attempts=0 unexpected=0`.**
- **Полный Python (candidate-py-final.log/xml): 3348 passed, 77 skipped, 0 failed, `NETWORK_FENCE attempts=8 unexpected=0`** (8 ожидаемых заблокированных попыток, неожиданных нет). Baseline: 3269 passed, 77 skipped, 0 failed. По именам общих тестов статусы идентичны; +80 новых тестов; один тест заменён: `test_rejects_missing_evidence_for_non_crypto_payin` → `test_non_crypto_payin_needs_no_evidence_hash_or_file` (новый scope `manualOverride`).
- **Полный JS: 73 passed / 2 failed** (`mobile_tasks_nav`, `owner_summary` — те же baseline-падения) против baseline 71 passed / 2 failed; новых падений нет.
- Четыре падения `test_stand_prepay` в промежуточном прогоне — baseline-падения при изолированном запуске (baseline-prepay.log: 4 failed / 104 passed) и загрязнение общей БД моим файлом; к hotfix не относятся. В финальном полном прогоне 0 failed.
- **Оговорка:** полный Python-прогон собран ДО последних правок моего QA-файла (fixture-изоляция и тесты подделки). Эти правки затрагивают только `tests/test_payout_receipt_independent_qa.py`, production не менялся; их подтверждает отдельный прогон 41 passed (final3), выполненный после full.

## Сценарии
| # | Сценарий | Результат |
|---|---|---|
| 1 | Обычный путь: чек в слоте «Чек» → payout ready, автор/роль/дата с сервера | PASS |
| 2 | То же, чек через «+ Загрузить ещё» (`extra=1`, `documentType=receipt`) — признан без перезагрузки | PASS |
| 3 | Обычный путь, реальный `201` на `crm-close` (инвойс 455000 в доске и CRM), оба слота; CRM-сделка создаётся ровно одна | PASS |
| 4 | Нет чека → блок (`409`), CRM-сделка не создаётся | PASS |
| 5 | Crypto-маршрут (`postConv=coins`, `paySrc=client`) без hash при наличии чека → блок, сделка не создаётся | PASS |
| 6 | Подделка через `PUT /api/stand/state`, три теста: (а) вложение без байтов + чужой `uploadedById` + поддельный `payoutFact` → блок; (б) валидные байты, но чужой `uploadedById` → поддельный автор не появляется (блок допустим, если принято — автор из сессии); (в) настоящий uid + поддельные имя/роль в metadata и журнале → автор и роль берутся с сервера (`T24 Manager`/`manager`) | PASS (final3) |
| 7 | Невалидные файлы (текст под видом PDF, EXE, HTML под видом PNG) → `400`; `additional` с типом `other` выплату не подтверждает | PASS |
| 8 | Приоритет автора новой загрузки над старой записью `s26_completed` | PASS |
| 9 | s27, `invoicePaid=false` + чек менеджера → `201` | PASS |
| 10 | `manualOverride` СД-1489-like: bank / founder / cash, чек в `additional` → `201`, `payoutFact.receiptBy` = загрузивший | PASS |
| 11 | `manualOverride`, слот «Чек» на s27 | PASS |
| 12 | BLOCKER: слот «Чек» из формы ручного переноса на раннем шаге s14/s11/s4 (200 на загрузку, `201` на закрытие) | PASS (в прогоне 3; в прогоне 2 s14/s11 были `403`) |
| 13 | `manualOverride`: нет чека; булев `docs.receipt=true` без файла (в т.ч. с `mfPayout`) → блок | PASS |
| 14 | `manualOverride` с `mfPayout` и настоящим чеком → `201` | PASS |
| 15 | Недоплата vs инвойс: 454000 блок, 454999.5 проходит (допуск 1 ฿) | PASS |
| 16 | Маршрут bank поверх crypto `postConv`/`paySrc`/`transfer.sends` → `payout_route_conflict`; crypto без hash и неизвестный маршрут → блок | PASS |
| 17 | Получатель обязателен (`payout_recipient_required`) | PASS |
| 18 | Operator не может закрывать (`403`), CRM-сделка не создаётся | PASS |
| 19 | Регресс СД-1489, scope «без подтверждений людей», вариант `rub-cash`: один submit → 201, сверка `cancelled`, ноты оператора закрыты, журнал «закрыто вручную менеджером … · без подтверждений операциониста · вне задачника» | PASS (qa-targeted4) |
| 20 | То же, `cash-partner` (наличные, `cashPartnerUsdt`, без hash) | PASS (qa-targeted4) |
| 21 | То же, `cash-partner-hash` (свежий hash, сверяется сервером) | PASS (qa-targeted4) |
| 22 | JS: `hasReceipt`/`receiptDocs` (оба слота, индексы для `docOpen`, булев `docs.receipt` не чек), `noncryptoPayout` (12 вариантов), «чек приложен · автор · дата» у выплаты и чека, `manualClosePayload` (route/amountThb/recipient, без hash) | PASS (fenced) |

## Закрытые по ходу дефекты
1. Загрузка слота «Чек» менеджером на s14/s11 из формы ручного переноса давала 403 — исправлено (сценарий 12).
2. Висящая `manualBankReceipt` pending блокировала ручное закрытие (409) — исправлено, статус → `cancelled` с `resolvedBy/At/Reason` (сценарии 19–20).
3. `Недостаточно резерва пачки` для свежего cash-partner hash — исправлено (сценарий 21). Пояснение: при закрытии cash-partner сделки старые hash доски уже имеют зарезервированный остаток пачки наличных, и перенос доли в CRM их «расходует». Свежий hash, введённый менеджером при ручном переносе, резерва не имеет, поэтому расход падал с ValueError. Теперь `pre_override_payin_keys` фиксирует hash, бывшие на доске до ручного ввода: только они переносятся как резервы, а свежие учитываются как обычный перевод с проверкой дублей (`payin_hash_already_used` для чужих сделок).
4. Обычный путь не сравнивал фактическую выплату с инвойсом — `_stand_noncrypto_payout_basis` теперь отклоняет `transfer.thb`/`payout.thb` меньше инвойса (>1 ฿); ручной путь проверяет `amountThb` из формы.

## Независимый обзор итогового диффа (замечания, не блокирующие)
- **Область изменения `manualOverride`:** проверка прихода снята для любого не-крипто способа по всем видам сделок (аренда, обмен валюты, фрихолд): достаточно метода и суммы, `payin_evidence_missing` больше не возвращается. Это прямое требование владельца («ручной перенос — никаких подтверждений других людей»), подтверждено в thr_gsii7c9mig; границы: только `manualOverride`, обычный payin-flow не менялся. Остаются роль manager/admin и причина ≥10 символов.
- Крипто-приход (`method == 'Крипта'`) и любой переданный hash по-прежнему проверяются сетью; повторное использование hash чужой сделки отклоняется (`payin_hash_already_used`). Ослабления крипто-проверки не найдено.
- Обычный payin-flow не менялся; единственное изменение обычного закрытия — `invoice_not_paid` не блокирует, если чек приложен сотрудником (требование «receipt любой роли»).
- `_stand_manual_close_resolve_tasks` помечает прочитанными все непрочитанные ноты этой сделки (любых ролей) и всегда пишет в журнал `role: 'manager'`, даже если закрыл admin. Косметика.
- Запрет закрытия operator сохранён (сценарий 18).

## Ограничения
- Python-тесты запускал родитель; мой вывод основан на их логах.
- Расхождения между тестами исполнителя (`tests/test_stand_payout_receipt_implicit.py`) и поведением кода я не разбирал.
- Не проверялось: реальный UI в браузере, живые интеграции, прод-данные.

## Вердикт
**ФИНАЛЬНЫЙ PASS** для scoped API/JS и для полного набора: мой файл 41/41, целевой набор 219/219, полный Python 3348 passed / 0 failed (baseline 3269 / 0), JS 73/2 при baseline 71/2, неожиданных сетевых попыток 0. Блокеры закрыты (загрузка слота «Чек» на раннем шаге, снятие зависшей сверки `manualBankReceipt`, резерв свежего cash-partner hash). Независимый обзор итогового диффа блокеров не выявил.

**Область изменения для сведения:** `manualOverride` больше не требует доказательства прихода для любого не-крипто способа (по всем видам сделок) — прямое требование владельца; обычный payin-flow не менялся.

**Что НЕ проверялось и не заявляется:** браузерный E2E (Chromium); живые интеграции и прод-данные. Python-тесты запускал родитель (мой `sandbox-exec` вложенно недоступен), я писал тесты и интерпретировал логи.
