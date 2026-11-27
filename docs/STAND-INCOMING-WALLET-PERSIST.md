# Сохранение фактического кошелька брокера — 13.10.2026

Ветка `stand/incoming-wallet-persist` от свежего `origin/stage` **894eace**.
Живой стенд не использовался, записи сделок не менялись. Push и деплой не выполнялись.

## Причина и исправление

В `stand_incoming_wallet` был `db.commit()`, но `current_role()` перед ним получал
ту же `scoped_session` через `get_session()` и закрывал её. Первый вызов внутри
формирования журнала откатывал транзакцию и отсоединял `StandState` от сессии.
Дальнейшие изменения `row.data`/`row.version` оставались в памяти отсоединённого
объекта. Поэтому POST отвечал новой версией и кошельком, а пустой commit ничего
не сохранял. Это детерминированный откат своей транзакции, а не конкурирующая
перезапись и не другая запись БД.

Исправлен сам `current_role()`: чтение роли использует отдельную `SessionLocal()`
и закрывает только её. Роль по-прежнему читается из актуальной БД при каждом вызове;
cookie с ролью не является источником прав, кеширование не добавлено.

**Найден второй затронутый путь:** GET `/api/stand/state` собирал `role` тем же
помощником между изменением флага DEMO и commit миграции. Его запись также терялась.
Общее исправление устраняет оба случая. 1473 с DEMO-историей по-прежнему сохраняет
флаг и предупреждение; тест миграции использует только синтетическую копию без
тестовых денег.

Прежние API-тесты подменяли `current_role()` лямбдой, поэтому не закрывали общую
сессию и пропускали ошибку. Новые тесты используют настоящий помощник, действующих
пользователей БД и изменение их роли в отдельной сессии. Проверяются POST, новый
GET и независимое чтение БД. До правки: **5 failed**; после — все эти случаи и
дополнительный тест смены роли проходят.

## Аудит всех POST /api/stand/*

Проверены все **27 зарегистрированных POST-обработчиков** и вызываемые ими
помощники записи/закрытия сессий. Других случаев того же отката или веток,
выдающих новую запись за сохранённую без commit, не обнаружено.

| POST-путь (префикс /api/stand) | Где сохраняется изменение / почему записи нет |
| --- | --- |
| /channels/sync | commit в обработчике, rollback при ошибке |
| /channels/export | commit в обработчике, rollback при ошибке |
| /tg-bind | `stand_notify.create_bind`: собственная SessionLocal, INSERT и commit до выдачи ссылки |
| /notify-test/:id | Не меняет доску: возвращает статус отправки/подавления уведомления |
| /assignee/take | commit перед уведомлениями и ответом |
| /quote | commit перед уведомлениями и ответом |
| /payto/reopen | commit сброса поручения перед уведомлениями и ответом |
| /deals/:id/close-evidence | commit подтверждения до success |
| /deals/:id/crm-close | Общая транзакция доски/CRM; `_create_deal_impl(..., defer_commit=True)` не закрывает переданную сессию, commit у обработчика |
| /deals/:id/crm-close-lose | Собственная SessionLocal, commit у обработчика; вложенное чтение роли прежде закрывало другую scoped-сессию |
| /deals/:id/bitrix-close-retry | При уже выполненной синхронизации возвращает сохранённое; новые статусы пишет помощник в своей SessionLocal с commit |
| /reset | commit до ответа |
| /deals/:id/freehold-loss-ack | commit до ответа |
| /prepay | commit запуска/отмены до ответа |
| /prepay/reimburse | Чтение и проверка сети отдельно; commit возмещения под повторной блокировкой |
| /transfers/review | commit ручного решения до запуска проверки переводов |
| /transfers/check | Запись в `_stand_discover_outgoing` / `_stand_check_transfers`; commit при изменениях, при отсутствии изменений возвращается существующее состояние |
| /transfers/demo | commit исхода DEMO перед общей проверкой, без разрешающего окружения отказ |
| /incoming/wallet | Исправленный дефект: вложенное чтение роли больше не закрывает транзакцию; commit до success |
| /incoming/check | Проверка сети вне записи, commit подтверждённого прихода до ответа |
| /prod-agents | Всегда stand_blocked, success не выдаётся |
| /incoming/unlink | commit отвязки до ответа |
| /payin/check | Проверка сети вне записи, commit привязки до ответа |
| /manual-bank-receipt | commit на успешных ветках создания/обновления; при повторе возвращается сохранённая запись |
| /manual-bank-receipt/:id/confirm | commit подтверждения/прихода/перехода до ответа; повтор возвращает сохранённое |
| /docs/issue | Генераторы работают с commit=False, commit документов и доски у обработчика до success |
| /docs/upload | Отдельные commit файла и привязки к доске, success только после второго |

Дополнительно просмотрены `_stand_payin_target` и `_stand_doc_request`: они
заимствуют scoped-сессию, но не закрывают её. Уведомления вызываются после commit
и используют отдельные сессии. GET-миграция описана выше и покрыта регрессией.

## Проверки

Новые сценарии:

- POST смены кошелька с username в cookie и без него → новая версия и адрес в
  независимой сессии БД → повторный GET показывает то же значение.
- Идемпотентная миграция ошибочного DEMO-флага с настоящим чтением роли.
- Предоплата Теодора → приход на третий кошелёк → проверенное возмещение → закрытие
  через API ролей; закрытие и фактический кошелёк проверены в БД.
- Вложенное чтение роли не отсоединяет изменённый ORM-объект и не откатывает запись.
- Изменение роли в БД действует сразу; cookie role=operator не даёт прав менеджеру.

**Целевой прогон: 62 passed**, `NETWORK_FENCE attempts=0 unexpected=0`.
В него вошли новые проверки, исходные сценарии DEMO/кошелька, гонки доски,
E2E фрихолда и совместный сценарий release-1013b.

Полные прогоны на одинаковом окружении:

| Версия | Python | JS |
| --- | --- | --- |
| Чистый origin/stage 894eace | 2472 passed / 11 failed / 35 skipped | 37 passed / 6 failed |
| Исправление + 6 новых сценариев | 2478 passed / 11 failed / 35 skipped | 37 passed / 6 failed |

Наборы падений Python и результаты каждого JS-файла совпадают с базой;
новых падений нет. В обоих Python-прогонах `NETWORK_FENCE attempts=8 unexpected=0`
(ожидаемые пробы самого барьера). У JS обёртка не предоставляет native attempt audit.

Старые падения Python: два `test_stand_crm_close_atomic` с неполными фикстурами
поручения IPPS; четыре `test_stand_thb_bank_rates` для удалённого канала exgreen;
по одному `test_t34_parallel_drafts` / `test_t34_pay_confirm` со старым порядком s25;
два `test_t35_stand_files_payload` с пересечением идентификаторов пользователей;
один `test_t36_stand_channels_sync_regressions` с общим счётчиком таблицы.
Старые падения JS: `test_stand_leasehold` / `test_stand_ops` не извлекают async act
старым regexp; `test_stand_mobile_tasks_nav` требует отсутствующий путь Playwright;
`test_stand_no_prod_links_ui` / `test_stand_remaining_links` не включают
applyStandMobileNav в VM; `test_t34_parallel` не включает prepayPanel в VM.
Предыдущий разбор: [STAND-DEMO-AND-BROKER-WALLET.md](STAND-DEMO-AND-BROKER-WALLET.md).

Команды:

```sh
.venv/bin/python scripts/run_fenced_pytest.py -q
.venv/bin/python scripts/run_fenced_js.py
.venv/bin/python scripts/run_fenced_pytest.py \
  tests/test_stand_incoming_wallet_persist.py tests/test_stand_demo_and_broker_wallet.py \
  tests/test_stand_board_concurrency.py tests/test_stand_freehold_e2e_fixes.py \
  tests/test_stand_release_1013b.py -q
```

Полные тесты базы 894eace отдельно запущены из чистого `git archive origin/stage`
в изолированной временной копии внутри рабочего каталога, с тем же Python 3.11,
временной БД и сетевым барьером. Секреты/БД/окружение локального стенда не копировались.

Логи: `/tmp/incoming-wallet-persist-red.log`, `/tmp/incoming-wallet-persist-focused.log`,
`/tmp/incoming-wallet-persist-python.log`, `/tmp/incoming-wallet-persist-js.log`,
`/tmp/incoming-wallet-persist-baseline-python.log`, `/tmp/incoming-wallet-persist-baseline-js.log`.
