# QA: manualOverride — приход USDT по одному hash, получатель — наш активный кошелёк из реестра

Отдельный отчёт срочного hash-only изменения. Core-отчёт `docs/qa-payout-receipt-implicit.md` (коммит `dd2af95`) не менялся. Независимый Claude qa-tester; Python-прогоны через fenced-раннер выполнял родитель, я писал тесты и интерпретировал логи.

**Статус: ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для hash-only (scoped API/JS и полный Python).**

## Scope
- `manualOverride`: менеджер вводит приход одним hash (+ метод и сумму); сеть сама наблюдает отправителя, получателя и сумму (`observe_recipient`). Явно введённые sender / receiver / amount сверяются с наблюдённым, а не отбрасываются.
- Получатель обязан быть активным кошельком реестра (`Wallet.active` и `accepts_payin`) нужной сети. Выбранный на сделке `walletId` (в том числе `custom` + `payinCustom`) сохраняет ограничение. TRON-адреса регистрозависимы, ERC-20 — нет.
- Кнопка «проверить hash» (`/api/stand/manual-close/verify-hash`, payin) использует тот же контракт.
- Выплата bank/founder/cash по чеку без hash, запрет закрытия operator и обычный s27 не менялись. Legacy `originMode=manual` — отдельным коммитом (патч сохранён).

## Тесты
`tests/test_stand_manual_payin_hash_only_qa.py` (30 кейсов): настоящий `stand_transfers.verify_transfer`, фейковый `get` с ответом TronScan, свой реестр кошельков; ничего не уходит во внешнюю сеть. Основа — `rental_board` / `override` / `upload` ядра QA.
- **Hash-only (10):** позитив raw `{hash, network}`, форма пула (`amount`, `receiver:''`, `sender:''`), явные верные sender+receiver; отказ: активный-но-неактивный получатель в реестре, получатель вне реестра, sender не совпал, receiver — другой наш кошелёк, сумма по сети ≠ заявленной (`422 payin_amount_mismatch`), pending (`422 payin_hash_unverified`), несколько получателей.
- **Частичные ограничения, реестр, walletId, регистр (10, у каждого сверяется и preview):** только sender / только receiver (позитив и негатив), выбранный `walletId` совпадает / другой наш кошелёк / несуществующий, `accepts_payin=False`, TRON receiver и адрес реестра с изменённым регистром.
- **Preview (5):** одиночный hash → `from`, `to`, сумма; чужой получатель по сети, явный чужой receiver, сумма, pending → `422`; доска не меняется.
- **`walletId='custom'` (4):** адрес в реестре и совпадает с сетью → `201`; адрес не в реестре, перевод на другой наш кошелёк, неактивный адрес → отказ.
- **Operator (1):** `403`.
- Во всех отказах доска (сырой `StandState.data`) и версия не меняются, число `Deal`/`StandCrmLink` не растёт.

`tests/test_stand_override_payin_observe.py` добавляет ещё 13 проверок самого observe-контракта, суммы и выбранного кошелька. В первой полной серии четыре ошибки setup были из-за постоянных тестовых адресов, уже созданных другими тестами; заменили на уникальные синтетические адреса. Итоговые 43 новых теста в сравнении проходят.

Адаптация ядра QA (55 кейсов): `payin_hash()` даёт явные `sender` и `receiver` (строгая сверка с echo-стабом), `rental_board` регистрирует получателя через `tests/payin_registry.py`. Ожидания отказов и позитивов не ослаблялись, слабых fallback в моках нет.

## Результаты
| Прогон | Результат |
|---|---|
| Native preliminary (11 кейсов) | 11 passed, `NETWORK_FENCE attempts=0 unexpected=0` |
| Native QA (30) + `test_stand_override_payin_observe.py` после адресного fix исполнителя | 43 passed, 0 failed, fence 0 |
| **Targeted2** (native 30 + core 55 + route/atomic/hash_preview/override и др.) | **286 passed, 0 failed**, `attempts=0 unexpected=0`, 10.30 s |
| **Full Python** (`candidate-py.log/xml`) | **3422 passed, 77 skipped, 0 failed**, 287.63 s, `NETWORK_FENCE attempts=8 unexpected=0` (8 ожидаемых заблокированных попыток) |
| **Сравнение с baseline `dd2af95`** (`comparison-py.json`) | baseline 3379 passed / 77 skipped; `changed = {}`, `failed = []`, added 43, removed 0; арифметика сходится: 3379 + 43 − 0 = 3422 |
| **Full JS** | 74 passed / 2 baseline failed, `changed = {}`, добавлен только `test_stand_manual_close_hash_preview.js` |

Артефакты: `/tmp/calccrm-manual-hash-discovery-validation/` (`candidate-py.log/xml`, `comparison-py.json`, `comparison-js.json`, `targeted2.log/xml`).

## Независимое ревью итогового диффа (read-only, `app.py`)
Блокеров нет. Подтверждено:
- Если заданы оба адреса — строгая сверка; иначе наблюдение, затем сверка явных sender/receiver/amount (до 0,01) с наблюдённым. Частичные ограничения не отбрасываются (`_stand_override_payin_verify`).
- `_stand_same_address`: TRON — точное сравнение, ERC-20 — без регистра; реестр ищет по `lower`, но принимает только точное совпадение для TRON.
- `_stand_payin_wallet_problem`: получатель должен быть в реестре (активен, `accepts_payin`, нужная сеть); выбранный `walletId` не может молча сниматься (несуществующий, неактивный, не принимающий приход → `payin_selected_wallet_invalid`); для `custom` адрес и сеть `payinCustom` обязаны совпасть с получателем **и** быть в реестре.
- Preview и закрытие идут через один и тот же путь; в preview реестр проверяется той же функцией.

Замечания (не блокеры):
1. Общий `_stand_manual_close_verify_hashes` теперь превращает пустой `receiver` в `None` и пишет `to` из ответа сети, **в том числе для hash выплаты** (раньше `to` равнялся введённому receiver). Для выплаты поведение совпадает при совпавшем адресе; новых отказов тесты не показали.
2. Код ошибки по сумме зависит от пути: в строгой сверке отказ приходит как `payin_hash_unverified`, в наблюдении — `payin_amount_mismatch`. Оба — отказ, имя разное.
3. Допуск суммы двойной: до 0,01 на hash и до 5 USDT суммарно против заявленной суммы прихода (прежняя семантика `manualOverride`).
4. Очистка тестового кошелька (`tests/conftest.py`): `query.delete()` по метке `test-payin-fixture` обходит ORM-каскад. **Фактически висячих ссылок в текущем наборе нет**: стенд закрывается с `defer_commit=True`, автоподстановка кошелька пропускается, `Deal.payin_wallet_id` остаётся `None` (`app.py:18561`), в тестах с `ensure_payin_wallet` поле не передаётся, `WalletOperation` на приходный кошелёк не создаётся (`app.py:18303`). Это **потенциальный риск** на будущее: если тест передаст `payin_wallet_id` на такой кошелёк, ссылка останется. Фактическую проверку запуском (`SELECT count(*) FROM deals WHERE payin_wallet_id IN (SELECT id FROM wallets WHERE label='test-payin-fixture')` перед удалением) не выполнял. `ensure_payin_wallet` не обновляет уже существующую запись с этим адресом, флаги не проверяются.
5. ERC-20 регистронезависимость проверена только ревью кода (`_stand_same_address`), native-теста нет: нужны два вызова Etherscan и ключ в фейке.

## Ограничения (не проверено)
- Браузерный E2E не проводился; UI проверен функциональными JS-тестами (`test_stand_manual_close_hash_preview.js`, `.js` ядра QA).
- ERC-20 native-тест; полный `crm-close` cash-partner с резервом ledger.
- Legacy `originMode=manual` («Внести целиком») и freehold-кейсы — в отдельном патче, не входят.
- Живые интеграции и прод-данные не использовались.

## Вердикт
**ФИНАЛЬНЫЙ НЕЗАВИСИМЫЙ PASS для hash-only изменения `manualOverride`.** Основания: targeted2 286/0 (native 30 + core 55 + executor-тесты), native + observe 43/43, полный Python 3422 passed / 77 skipped / 0 failed против baseline `dd2af95` (`changed = {}`, added 43, removed 0), полный JS 74/2 = baseline (`changed = {}`), неожиданных сетевых попыток 0. Блокеров в независимом ревью диффа нет; замечания 1–5 выше не блокируют.

**Вне этого коммита / не проверено:** legacy `originMode=manual` («Внести целиком») — отдельным коммитом; native-тест ERC-20 (только ревью кода); браузерный E2E; полный `crm-close` cash-partner с резервом ledger; живые интеграции и прод-данные.
