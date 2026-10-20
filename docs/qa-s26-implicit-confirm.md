# QA: неявное подтверждение чека завершением s26 (СД-1483)

Независимый QA, ветка `fix/s26-implicit-invoice-confirm`, дерево на момент прогона:
`app.py` sha256 `8e1578f4e556f463…`, `static/stand/tasks.html` `0669cb89fbe5e3ca…`
(незакоммиченное дерево реализации). QA ничего в приложении не правил, не коммитил, не деплоил.

## Вердикт

**ПРИНЯТО (по моей части).** На копии реального дампа СД-1483 закрывается менеджером (201), оба
негативных условия блокируют, подделка отметки завершения с сервера не проходит, UI рисует
«проверено · операционист NAME · время s26» без кнопки. Фенс: 0 неожиданных попыток сети.
Полные Python/JS прогоны и сравнение с baseline завершены родительским тредом (ниже).

Прогон на архиве `HEAD` (до правок) красный там, где должен: `positive_real` (receipt
`operator_receipt_acceptance_missing`, crm-close 409 `close_evidence_missing`),
`live_s26_via_api` (нет серверной фиксации завершения).

## Дамп и восстановление

- Файл: `stand_prodcopy_20260928-before-js-6-fails-20261020-091747.sql.gz`
  (самый свежий по mtime среди `stand_prodcopy_20260928-before-*`, выбирается динамически),
  mtime `2026-10-20T09:18:29`, sha256
  `ddfc032e858f147814a24f487a397c595d68ad5b0384c4dc547463c96fbe3422`.
- Восстановление: одноразовый Postgres 17 (Homebrew), только Unix-сокет, `/tmp/claude/s26`,
  0 ошибок restore, 498 CRM-сделок. Нужен `LC_ALL=C`; `initdb` не стартует внутри песочницы
  Claude (shmget) — запускать вне неё.
- Состояние стенда — одна строка `stand_state.data` (JSON); СД-1483 = `deals[id=1483]`.
  Сырой дамп, `state.json` и отчёты прогонов (ПДн) — только в `/tmp/claude/s26`, не в репозитории.

## Реальная форма СД-1483 в дампе

`step=s27`, `pay.invoicePaid=true`, `postConv=ipps_swift`, freehold, `files.receipt =
[fet-218-MT103.pdf]` (PDF 52 722 Б, `stand_files.content_valid=t`), перевод 138 239,27 USDT TRC-20
подтверждён. В `stand_close_evidence` для 1483 — **только `sent`** (manager_attestation,
2026-10-20 06:17 UTC); строки `receipt` нет — именно она блокировала закрытие.

Журнал завершения s26 (`deal.log`, по порядку):

1. `{at, ts:"19.10, 12:49", role:operator, text:"Приложен файл: receipt · fet-218-MT103.pdf"}` — без author/kind (пишет сервер);
2. `{role:operator, author:"Артём", kind:comment, text:"Комментарий · Артём: Подтверждение от IPPS: MT103 приложен — …"}`;
3. то же, `text:"Комментарий · Артём: MT103 подтверждён, чек у менеджера — отправить клиенту и закрыть"` (`go()` s26→s27);
4. `{role:operator, text:"Шаг передан дальше"}` — без author/ts/kind.

Записи «Переход s26 → s27» нет. `at` — UTC epoch ms (19.10.2026 05:50:14 UTC для шага 3);
`ts` — локальная строка и есть не везде, поэтому время берётся из `at`.

## Повторение

```
python3 scripts/qa_s26_dump_repro.py restore            # свежий *before-* дамп → scratch PG
python3 scripts/qa_s26_dump_repro.py run                # все сценарии (код выхода ≠ 0 при провале)
python3 scripts/qa_s26_dump_repro.py run --root <ДЕРЕВО> # например git archive HEAD — красный прогон
python3 scripts/qa_s26_dump_repro.py ui                 # node под sandbox-exec на реальных фактах 1483
```

Каждый сценарий — клон базы-шаблона, приложение под `sandbox-exec (deny network*)` (разрешён
только наш сокет) + питоновский `network_fence`; любая неожиданная попытка сети = провал.
Внешняя доставка заглушена как в `tests/conftest.py`: `get_gsheet_client→None`,
`requests.get/post` на нелокальные хосты — синтетический отказ, `stand_egress.read_get`
(TronScan) — 404 «не проиндексирован». Логика close/readiness не отключалась.
Авторизация — Flask session `user_id` реальных manager/operator из дампа.

## Результат (финальный прогон: 17 сценариев, 73 проверки, fence_unexpected = 0)

| Сценарий | Что проверяет | Итог |
|---|---|---|
| `positive_real` | 1483 как есть: manager и operator → `missing=[]`, receipt `ready`, `implicit`, `confirmed_by`=автор записи 3, роль operator, `checked_at`=`at` записи 3 (2026-10-19T05:50:14Z); GET не создаёт receipt-строку (без бэкфилла); **manager `crm-close` → 201**, сделка closed + `crmDealId`; после закрытия receipt-строки по-прежнему нет | PASS |
| `operator_cannot_close` | operator `crm-close` → 403 | PASS |
| `neg_no_receipt_file` | нет `files.receipt` → receipt not ready, close 409 `receipt_missing`, сделка открыта | PASS |
| `neg_no_s26_completion` | убраны записи 3 и 4 → блок | PASS |
| `neg_stale_explicit_no_completion` | нет завершения + устаревшая (чужой fingerprint) явная receipt-строка → блок | PASS |
| `explicit_receipt_without_completion` | нет завершения + явный operator POST `close-evidence receipt` (HTTP 200) → всё равно блок | PASS |
| `neg_file_added_after_completion` | s26 завершён БЕЗ файла, запись о файле — после «Шаг передан дальше» → блок | PASS |
| `neg_manager_authored_completion` | запись завершения с role=manager → блок | PASS |
| `neg_no_step_marker` / `neg_no_attach_entry` | нет «Шаг передан дальше» / нет записи о приложенном чеке → блок | PASS |
| `neg_invoice_not_paid` / `neg_step_s26` | `invoicePaid=false` / `step=s26` → блок | PASS |
| `receipt_swapped_after_completion` | после s26 чек подменён другим валидным файлом → блок | PASS |
| `spoof_manager_put` | менеджер шлёт PUT с поддельным `s26Done`, записью `kind:s26_completed` и «операторскими» строками журнала → ни одна не сохраняется с ролью operator/admin и kind `s26_completed`, закрытие блок | PASS |
| `live_s26_via_api` | живой путь: откат клона на s26 → operator PUT s26→s27 с поддельным `s26Done` в теле → сервер пишет структурную запись `kind:s26_completed` (`byId`=оператор, `role`=operator, `receipts`=sha256, `at`=сейчас), подделка стёрта; manager отмечает «чек отправлен» → `missing=[]` → **crm-close 201** | PASS |
| `live_forged_by_manager` | менеджер «завершает» s26 сам (PUT 409) → чек не принят | PASS |
| `regression_all_deals` | receipt-факт по всем открытым недвижимостям дампа (1473, 1483, 1488–1491), base vs кандидат: отличается только 1483 (not ready → ready, implicit); остальные без изменений | PASS |

## UI (`scripts/qa_s26_ui_check.js`, настоящие функции `tasks.html` + реальный ответ API по 1483)

Для manager/operator/admin: `проверено · операционист Артём · 19.10.2026, 08:50:14`
(`toLocaleString`, время браузера: 05:50:14Z = 08:50:14 МСК), блокеров нет, **кнопки подтверждения нет**;
для не принятого чека (`operator_receipt_acceptance_missing`, `invoice_payment_or_receipt_missing`) —
причина без кнопки. Ручные факты payin/payout сохраняют кнопку оператора (покрыто JS-тестом реализации).
Реальный браузерный E2E не гонялся (репо-тест `tests/test_stand_s26_implicit_receipt.js` и этот
vm-рендер, оба под фенсом/без сети).

## Контроль подделки на сервере

- `accept_journal` превращает любую добавленную браузером запись журнала в
  `role=<реальная роль>, kind=comment, author=<имя из сессии>` — менеджер не может вписать
  операторскую запись, `s26_completed` или «Шаг передан дальше»; прошлые записи неизменяемы (`journal_problem`).
- Структурная запись `s26_completed` добавляется только сервером после `accept_journal`, при переходе
  s26→s27, актёр operator/admin, `invoicePaid`, валидный чек; поле `s26Done` из тела стирается.
- Приёмка привязана к sha256 текущих чеков (`ids <= receipts` записи): добавленный после завершения
  чек или подмена → не принято.
- Историческая запись 1483 принимается по жёсткому шаблону: роль operator/admin, текст `go()`, позже
  серверное «Шаг передан дальше», раньше серверные «Приложен файл: receipt · <имя>» для каждого
  текущего чека, и после завершения новых чеков не прикладывали. Бэкфилла нет.

## Замечания (не блокеры)

1. **Изменение поведения**: явный `POST close-evidence kind=receipt` по-прежнему отвечает 200 и пишет
   строку, но больше ничего не открывает (на `HEAD` открывал). Это соответствует правилу «без
   завершения s26 — блок»; API-клиентам ответ может показаться успешным. Низкий приоритет.
2. Историческая ветка опирается на имена файлов и текст журнала; безопасна, потому что журнал
   неизменяем и пишется сервером, но это эвристика для сделок до структурной записи.
3. Время в UI — локальное время браузера; серверное значение — `checked_at` в UTC.
4. Не покрыто QA: реальный браузер, SCB-ветка (`Оплачено, чек у менеджера…`) на живом дампе
   (в дампе только IPPS-фрихолд; ветка покрыта тестами реализации), полный Python/JS baseline —
   зона родительского треда.

## Родительский тред: полные прогоны

База после `git fetch origin stage`: `2054b7dc5e9ec8dfe3ec615056b54751984a5d7e`.
Baseline — отдельная временная копия этого дерева с Git refs для schema-тестов.
Приложение в проверенном дереве совпадает с SHA256, указанными в начале отчёта.

| Раннер | Свежий origin/stage | Исправление |
|---|---|---|
| `run_fenced_pytest.py -q --tb=short --junitxml=…` | 3238 passed, 77 skipped, 0 failed | **3256 passed, 77 skipped, 0 failed** |
| `run_fenced_js.py` | 69 passed, 2 failed | **70 passed, 2 failed** |

JUnit сравнивался по `(classname, name)`: все существующие тесты сохранили результат,
исчезнувших тестов нет, новых падений нет; добавлены 18 Python-сценариев.
В обоих полных Python-прогонах `NETWORK_FENCE unexpected=0` (8 штатных негативных проб).

JS-результаты сравнивались по имени файла. Одинаковые baseline-падения:

- `test_stand_mobile_tasks_nav.js` — `Cannot read properties of undefined (reading '1472')`
  в `render` (`S.logOpen` в тестовом состоянии).
- `test_stand_owner_summary.js` — `fetchDealFlowConfig is not defined`.

Новых JS-падений и исчезнувших тестов нет; добавлен и проходит
`test_stand_s26_implicit_receipt.js`. В обоих прогонах одинаковые Python 3.11.17,
`NODE_PATH=/opt/homebrew/lib/node_modules` и
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/Users/karimamirov/Library/Caches/ms-playwright/chromium_headless_shell-1217/chrome-headless-shell-mac-arm64/chrome-headless-shell`.
Сетевой sandbox раннеров включён; браузерные тесты общего JS-набора выполнялись в нём.

Полные логи, JUnit и сравнение имён: `/tmp/calccrm-s26-validation/`
(`baseline-py-final.*`, `candidate-py-final.*`, `baseline-js-headless.log`,
`candidate-js-final.log`, `py-comparison.json`, `js-comparison.json`).

Все изменения разработки находятся в worktree
`/Users/karimamirov/worktrees/calccrm-s26-implicit-confirm`.
Деплой и push не выполнялись; миграция/backfill для этого исправления не нужны.
