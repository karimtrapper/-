# Сведение стенда 13.10

Ветка `stand/release-1013` создана от `origin/stage` **9a3c86a**.
Живые сделки не изменялись; push в stage и деплой не выполнялись.

## Порядок слияния

| Ветка | Принятая верхушка | Merge-коммит |
| --- | --- | --- |
| stand/freehold-e2e-fixes-a | 2190746 | e1baa3b |
| stand/freehold-e2e-fixes-b | f76eea7 | 6b84684 |
| stand/board-concurrency-fix | 5fe2b20 | f4d56eb |

Все три верхушки являются предками релизной ветки. Слияния выполнены через
`merge --no-ff` в заданном порядке, без переписывания исходных веток.

**Текстовых конфликтов не было.** При втором merge автоматически объединены
`app.py` и `static/stand/tasks.html`; при третьем — `tasks.html`.
Проверено сохранение обеих групп изменений в общих местах:

- s14: ручной приход подтверждается сервером; переход s18 / s14m, назначение
  исполнителя, документы и защищённые банковские поля сохраняются из fixes-b.
- s18: легитимная привязка ручного прихода к пачке своей сделки из fixes-b
  работает вместе с независимым `prepay.brokerStep` из fixes-a.
- s24→s26: нормализация `payout: null` из fixes-a остаётся вместе со сбросом
  назначения прежней роли из fixes-b.
- s26→s27: узкое исключение первого `paySrc=ipps_swift` из fixes-a остаётся;
  чужой маршрут и неподтверждённые реквизиты не разрешаются.
- Сохранение доски: исключение локального `income.sel` из снимка fixes-b
  сохранено вместе с защитой от старого GET и слиянием независимых правок
  сделки из board-concurrency-fix.

## Исправление тестовой инфраструктуры при сведении

Первый совместный запуск дал 308 passed и 3 ошибки запуска HTTP-сервера тестов
гонки: первый порт разрешённого пула был занят после предшествующих HTTP-тестов.
Коммит **2513f1c** меняет только фикстуру `board_server`: порт 0 разрешает сетевому
барьеру выбрать свободный порт из того же разрешённого пула; адрес для Node берётся
из реально открытого сокета. Ограничения сети не менялись. После этого все
311 целевых Python-тестов проходят вместе в указанном порядке.

## Целевые сценарии на объединённом коде

| Сценарий | Тест | Результат |
| --- | --- | --- |
| Обычный фрихолд s14→CRM | test_full_freehold_s14_to_crm_via_api_only[sequential_multisig] | PASS |
| Наперёд, Теодор, другой кошелёк прихода, возмещение→CRM | test_full_freehold_s14_to_crm_via_api_only[prepay_teodor_refund] | PASS |
| Копия СД-1484, s23, 5507.16, до закрытия | test_live_1484_snapshot_s23_to_close_via_api_only | PASS |
| СД-1485: передача ручного прихода, Flowsole, подтверждение→s18→s18w | test_1485_handoff_operator_selects_flowsole_and_acknowledges_documents | PASS |
| Две ролевые HTTP-сессии, старый GET / 409 с независимыми полями | test_two_role_sessions_keep_new_deal_and_quotes[late_poll/conflict_fields] | PASS |
| Устаревшая/неполная доска не удаляет сохранённую сделку | test_stale_or_incomplete_board_cannot_delete_persisted_deal | PASS |

Целевая Python-группа: **311 passed**, `NETWORK_FENCE attempts=0 unexpected=0`.
Также прошли все целевые JS-файлы трёх веток: freehold_close_roles, assignee_take,
income_conv_form, log_legacy, manual_receipt_confirm_ui, board_concurrency.

Команда целевого прогона:

```sh
.venv/bin/python scripts/run_fenced_pytest.py \
  tests/test_stand_freehold_e2e_fixes.py tests/test_stand_freehold_server.py \
  tests/test_stand_prepay.py tests/test_stand_outgoing_review.py \
  tests/test_stand_transfers.py tests/test_stand_manual_bank_receipt.py \
  tests/test_stand_lk_channel.py tests/test_stand_board_concurrency.py -q
```

## Полный прогон и сравнение с базой

Базовый полный прогон **9a3c86a**: Python 2409 passed / 11 failed / 35 skipped;
JS 29 passed / 6 failed. Использованы сохранённые полные логи этой же базы;
`origin/stage` при начале сведения проверен и по-прежнему указывает на 9a3c86a.

- Полный JS релизной ветки: **35 passed / 6 failed**. Набор падений прежний.
- Полный Python релизной ветки: **2445 passed / 11 failed / 35 skipped**.
  Набор из 11 падений по именам тестов совпадает с базой точно; новых нет.
  `NETWORK_FENCE attempts=8 unexpected=0` — только ожидаемые пробы тестов барьера.
- `git diff --check` и проверка генератора CRM draft: успешно.

Шесть старых JS-падений: `test_stand_leasehold.js` / `test_stand_ops.js` — regex
не извлекает async act; `test_stand_mobile_tasks_nav.js` — отсутствует жёстко
заданный путь Playwright; `test_stand_no_prod_links_ui.js` /
`test_stand_remaining_links.js` — в VM нет applyStandMobileNav;
`test_t34_parallel.js` — в VM нет prepayPanel.

Одиннадцать старых Python-падений: две фикстуры CRM-close без поручения IPPS;
четыре теста удалённого канала exgreen_thb_bank_rates; два ожидания старой заявки
IPPS на s25; два теста файлов с конфликтующими ID пользователей; один тест общей
таблицы каналов, содержащей записи предыдущих тестов. Подробности и имена —
`docs/STAND-FREEHOLD-E2E-FIXES-A.md`.

Логи: `/tmp/release-1013-target-python.log`, `/tmp/release-1013-python.log`,
`/tmp/release-1013-js.log`, `/tmp/release-1013-js.json`.
База: `/tmp/freehold-e2e-a-baseline-python.log`,
`/tmp/freehold-e2e-a-baseline-js.log`, `/tmp/freehold-e2e-a-baseline-js.json`.
