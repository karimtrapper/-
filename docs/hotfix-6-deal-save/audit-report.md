# Hotfix 6: read-only оценка денежных полей

Исходные архивы не изменялись. Восстановлены целиком в отдельном локальном PostgreSQL 17 (Unix socket `/tmp/calccrm-hotfix6-audit/socket`, TCP выключен), затем включён `default_transaction_read_only=on`. Аудит дополнительно открывает read-only транзакцию. Приложение и миграции на восстановленных базах не запускались. Исправлений данных нет.

Стенд: `stand_prodcopy_20260928-before-hotfix4-20261014-1909.sql.gz` (14.10.2026 19:10). Прод: `prod-readonly-20260928-010255.sql.gz` (28.09.2026). Это снимки, а не актуальное состояние живых баз.

Критерии являются признаками для проверки, а не доказательством конкретного неверного значения. `created_at=00:00:00` само по себе не доказывает порчу. Прямое связанное событие в тот же день усиливает подозрение; событие другого дня — только слабый сигнал. Время события нельзя автоматически подставлять как время создания. `updated_at` не используется как доказательство.

Связи событий: прямые FK/ID сделки в таблицах платежей, аллокаций, агентов и операций; никаких догадок по клиенту. Для кассы проверены и `deals.cash_batch_id`, и FIFO `cash_allocations.batch_id → cash_batches.id`. NULL источника учитывается как не `FOUNDER_PERSONAL`.

## Стенд

Всего сделок: **496**. Полночь: **234**; из них есть прямые связанные события с ненулевым временем: **131** (тот же день: **64**, только другие дни: **67**). Без таких свидетельств: **103** — не включены в список временных подозрений. Неверный контекст Андрея: **52**. Касса без партии: **3**. Объединение всех трёх критериев, включая слабые временные признаки: **152** уникальных ID.

### Андрей при другом/пустом источнике

| ID | Источник | Основание |
|---|---|---|
| 5 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 6 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 19 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 20 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 25 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 29 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 31 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 32 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 34 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 35 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 36 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 37 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 38 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 39 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 42 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 50 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 61 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 87 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 109 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 110 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 325 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 462 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 463 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 464 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 479 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 480 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 484 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 494 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 495 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 500 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 503 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 504 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 507 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 519 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 522 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 531 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 538 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 558 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 564 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 565 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 576 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 577 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 580 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 581 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 584 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 594 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 606 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 617 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 618 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 620 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 621 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 656 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |

### Касса без подтверждённой партии

| ID | cash_batch_id | Статус | THB | Основание |
|---|---|---|---|---|
| 61 | NULL | VERIFIED | 100000.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |
| 109 | NULL | COMPLETED | 5500.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |
| 110 | NULL | COMPLETED | 5000.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |

### Полночь + связанное событие в тот же день

| ID | created_at | Свидетельство | Время события |
|---|---|---|---|
| 369 | 2026-06-10 00:00:00 | deal_agents.created_at | 2026-06-10T15:19:29.056692 |
| 394 | 2026-06-26 00:00:00 | deal_agents.created_at | 2026-06-26T17:10:25.042738 |
| 412 | 2026-07-09 00:00:00 | sber_incomes.created_at | 2026-07-09T08:42:22.986578 |
| 415 | 2026-07-08 00:00:00 | sber_incomes.created_at | 2026-07-08T15:11:58.194851 |
| 427 | 2026-07-17 00:00:00 | sber_incomes.created_at | 2026-07-17T19:47:43.052998 |
| 447 | 2026-07-24 00:00:00 | sber_incomes.created_at | 2026-07-24T10:34:12.462586 |
| 452 | 2026-07-28 00:00:00 | deal_agents.created_at | 2026-07-28T12:58:27.084989 |
| 455 | 2026-08-04 00:00:00 | sber_incomes.created_at | 2026-08-04T13:19:25.814309 |
| 456 | 2026-08-04 00:00:00 | deal_agents.created_at | 2026-08-04T13:14:43.164648 |
| 460 | 2026-08-04 00:00:00 | sber_incomes.created_at | 2026-08-04T13:15:02.956659 |
| 463 | 2026-08-06 00:00:00 | deal_agents.created_at | 2026-08-06T12:04:06.528749 |
| 469 | 2026-08-10 00:00:00 | sber_incomes.created_at | 2026-08-10T08:43:11.269964 |
| 481 | 2026-08-11 00:00:00 | sber_incomes.created_at | 2026-08-11T06:33:32.100035 |
| 494 | 2026-08-12 00:00:00 | deal_agents.created_at | 2026-08-12T09:01:15.541343 |
| 498 | 2026-08-12 00:00:00 | sber_incomes.created_at | 2026-08-12T10:55:07.989194 |
| 500 | 2026-08-12 00:00:00 | card_allocations.created_at | 2026-08-12T17:20:18.998167 |
| 501 | 2026-08-14 00:00:00 | sber_incomes.created_at | 2026-08-14T09:05:40.945026 |
| 503 | 2026-08-14 00:00:00 | payin_tx_uses.created_at | 2026-08-14T13:57:21.413868 |
| 507 | 2026-08-17 00:00:00 | payin_tx_uses.created_at | 2026-08-17T13:14:39.716255 |
| 509 | 2026-08-17 00:00:00 | sber_incomes.created_at | 2026-08-17T11:14:08.801583 |
| 522 | 2026-08-19 00:00:00 | sber_incomes.created_at | 2026-08-19T07:48:47.169573 |
| 525 | 2026-08-19 00:00:00 | sber_incomes.created_at | 2026-08-19T12:45:11.422752 |
| 529 | 2026-08-20 00:00:00 | sber_incomes.created_at | 2026-08-20T11:28:03.301809 |
| 531 | 2026-08-20 00:00:00 | payin_tx_uses.created_at | 2026-08-20T14:45:02.226228 |
| 532 | 2026-08-21 00:00:00 | payin_tx_uses.created_at | 2026-08-21T06:56:35.787058 |
| 534 | 2026-08-23 00:00:00 | sber_incomes.created_at | 2026-08-23T08:17:55.525154 |
| 538 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T10:31:14.931639 |
| 540 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T12:34:09.38023 |
| 541 | 2026-08-25 00:00:00 | sber_incomes.created_at | 2026-08-25T05:08:58.003475 |
| 542 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T15:46:19.550401 |
| 543 | 2026-08-25 00:00:00 | sber_incomes.created_at | 2026-08-25T12:16:14.99426 |
| 545 | 2026-08-25 00:00:00 | payin_tx_uses.created_at | 2026-08-25T15:20:44.005563 |
| 546 | 2026-08-27 00:00:00 | sber_incomes.created_at | 2026-08-27T05:41:57.312721 |
| 550 | 2026-08-27 00:00:00 | payin_tx_uses.created_at | 2026-08-27T13:42:25.638691 |
| 558 | 2026-08-27 00:00:00 | payin_tx_uses.created_at | 2026-08-27T15:45:04.297408 |
| 566 | 2026-08-31 00:00:00 | payin_tx_uses.created_at | 2026-08-31T04:41:04.341785 |
| 576 | 2026-08-31 00:00:00 | payin_tx_uses.created_at | 2026-08-31T12:55:19.019454 |
| 578 | 2026-08-31 00:00:00 | sber_incomes.created_at | 2026-08-31T14:34:59.577186 |
| 580 | 2026-09-01 00:00:00 | payin_tx_uses.created_at | 2026-09-01T11:36:04.299796 |
| 584 | 2026-09-02 00:00:00 | deal_agents.created_at | 2026-09-02T09:16:56.75591 |
| 593 | 2026-09-03 00:00:00 | deal_agents.created_at | 2026-09-03T13:40:37.789354 |
| 594 | 2026-09-03 00:00:00 | deal_agents.created_at | 2026-09-03T12:41:51.150819 |
| 597 | 2026-09-03 00:00:00 | sber_incomes.created_at | 2026-09-03T06:24:26.588112 |
| 605 | 2026-09-07 00:00:00 | payin_tx_uses.created_at | 2026-09-07T08:05:06.356847 |
| 607 | 2026-09-08 00:00:00 | sber_incomes.created_at | 2026-09-08T08:02:04.653209 |
| 612 | 2026-09-11 00:00:00 | sber_incomes.created_at | 2026-09-11T06:32:10.072315 |
| 613 | 2026-09-11 00:00:00 | payin_tx_uses.created_at | 2026-09-11T12:40:40.692145 |
| 615 | 2026-09-11 00:00:00 | sber_incomes.created_at | 2026-09-11T04:48:38.241768 |
| 617 | 2026-09-14 00:00:00 | card_allocations.created_at | 2026-09-14T07:25:26.577555 |
| 618 | 2026-09-14 00:00:00 | card_allocations.created_at | 2026-09-14T07:26:29.894255 |
| 621 | 2026-09-14 00:00:00 | sber_incomes.created_at | 2026-09-14T12:47:47.838336 |
| 626 | 2026-09-15 00:00:00 | sber_incomes.created_at | 2026-09-15T06:53:34.039221 |
| 627 | 2026-09-15 00:00:00 | payin_tx_uses.created_at | 2026-09-15T15:28:13.904817 |
| 629 | 2026-09-16 00:00:00 | sber_incomes.created_at | 2026-09-16T11:19:06.717156 |
| 637 | 2026-09-17 00:00:00 | sber_incomes.created_at | 2026-09-17T06:16:47.918825 |
| 639 | 2026-09-18 00:00:00 | sber_incomes.created_at | 2026-09-18T12:23:32.018715 |
| 644 | 2026-09-21 00:00:00 | sber_incomes.created_at | 2026-09-21T05:18:34.779479 |
| 652 | 2026-09-23 00:00:00 | payin_tx_uses.created_at | 2026-09-23T07:19:21.831529 |
| 656 | 2026-09-23 00:00:00 | payin_tx_uses.created_at | 2026-09-23T07:42:18.904678 |
| 657 | 2026-09-23 00:00:00 | deal_agents.created_at | 2026-09-23T10:18:56.512269 |
| 660 | 2026-09-24 00:00:00 | payout_tx_uses.created_at | 2026-09-24T08:21:09.165172 |
| 664 | 2026-09-23 00:00:00 | sber_incomes.created_at | 2026-09-23T13:46:54.256383 |
| 665 | 2026-09-25 00:00:00 | payin_tx_uses.created_at | 2026-09-25T17:37:29.641607 |
| 667 | 2026-09-25 00:00:00 | payout_tx_uses.created_at | 2026-09-25T18:21:36.058956 |

### Полночь + событие только другого дня (слабый признак)

| ID | created_at | Свидетельство | Время события |
|---|---|---|---|
| 31 | 2026-01-17 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.377512 |
| 32 | 2026-01-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.381774 |
| 34 | 2026-01-15 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.387853 |
| 35 | 2026-01-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.369469 |
| 36 | 2026-01-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.390212 |
| 37 | 2026-01-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.392634 |
| 42 | 2026-01-26 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.385894 |
| 50 | 2026-01-28 00:00:00 | wallet_operations.created_at | 2026-01-29T10:36:42.676928 |
| 61 | 2026-02-06 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.410771 |
| 64 | 2026-02-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.406113 |
| 66 | 2026-02-13 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.403535 |
| 73 | 2026-01-31 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.426468 |
| 77 | 2026-02-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.414786 |
| 83 | 2026-02-24 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.428584 |
| 87 | 2026-03-01 00:00:00 | wallet_operations.created_at | 2026-03-02T18:57:15.904494 |
| 90 | 2026-02-27 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.430654 |
| 92 | 2026-02-27 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.432754 |
| 101 | 2026-03-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.422233 |
| 107 | 2026-03-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.435017 |
| 108 | 2026-03-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.437943 |
| 116 | 2026-03-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.424224 |
| 118 | 2026-03-13 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.416816 |
| 121 | 2026-03-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.442126 |
| 129 | 2026-03-14 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.444063 |
| 138 | 2026-03-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.448474 |
| 142 | 2026-03-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.450603 |
| 149 | 2026-03-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.440046 |
| 152 | 2026-03-30 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.452983 |
| 164 | 2026-04-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.446404 |
| 285 | 2026-04-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.471356 |
| 308 | 2026-04-28 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.482781 |
| 309 | 2026-04-28 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.464227 |
| 311 | 2026-05-01 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.473169 |
| 319 | 2026-05-11 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.486484 |
| 323 | 2026-05-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.477367 |
| 330 | 2026-05-18 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.484699 |
| 338 | 2026-05-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.490512 |
| 346 | 2026-05-17 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.517825 |
| 356 | 2026-06-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.528464 |
| 357 | 2026-06-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.563537 |
| 359 | 2026-06-01 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.526523 |
| 360 | 2026-06-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.532618 |
| 371 | 2026-06-11 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.536816 |
| 378 | 2026-06-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.55498 |
| 382 | 2026-06-21 00:00:00 | deal_agents.created_at | 2026-06-24T07:19:32.670552 |
| 384 | 2026-06-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.520003 |
| 387 | 2026-06-25 00:00:00 | deal_agents.created_at | 2026-07-02T11:25:05.259595 |
| 388 | 2026-06-25 00:00:00 | deal_agents.created_at | 2026-07-02T11:08:07.832653 |
| 393 | 2026-06-24 00:00:00 | deal_agents.created_at | 2026-06-26T17:05:14.66793 |
| 396 | 2026-06-26 00:00:00 | deal_agents.created_at | 2026-06-29T20:21:32.699237 |
| 398 | 2026-07-01 00:00:00 | deal_agents.created_at | 2026-07-31T13:31:25.649429 |
| 406 | 2026-07-02 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.56543 |
| 411 | 2026-07-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.552845 |
| 413 | 2026-07-08 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.499281 |
| 419 | 2026-07-13 00:00:00 | deal_agents.created_at | 2026-07-23T14:08:35.540728 |
| 422 | 2026-07-09 00:00:00 | sber_incomes.created_at | 2026-07-10T14:33:06.222438 |
| 425 | 2026-07-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.559047 |
| 453 | 2026-07-30 00:00:00 | sber_incomes.created_at | 2026-07-29T14:15:08.062761 |
| 458 | 2026-08-03 00:00:00 | deal_agents.created_at | 2026-08-05T10:25:43.918334 |
| 461 | 2026-08-04 00:00:00 | payin_tx_uses.created_at | 2026-08-31T15:13:03.493492 |
| 462 | 2026-08-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.324101 |
| 464 | 2026-08-03 00:00:00 | sber_incomes.created_at | 2026-08-04T13:19:25.814312 |
| 470 | 2026-08-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.327626 |
| 484 | 2026-08-10 00:00:00 | card_allocations.created_at | 2026-08-11T09:48:48.917115 |
| 495 | 2026-08-12 00:00:00 | sber_incomes.created_at | 2026-08-11T08:27:11.923921 |
| 537 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-22T14:53:39.215897 |
| 638 | 2026-09-18 00:00:00 | sber_incomes.created_at | 2026-09-17T11:30:29.247139 |

## Прод

Всего сделок: **484**. Полночь: **234**; из них есть прямые связанные события с ненулевым временем: **131** (тот же день: **64**, только другие дни: **67**). Без таких свидетельств: **103** — не включены в список временных подозрений. Неверный контекст Андрея: **52**. Касса без партии: **3**. Объединение всех трёх критериев, включая слабые временные признаки: **152** уникальных ID.

### Андрей при другом/пустом источнике

| ID | Источник | Основание |
|---|---|---|
| 5 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 6 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 19 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 20 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 25 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 29 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 31 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 32 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 34 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 35 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 36 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 37 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 38 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 39 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 42 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 50 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 61 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 87 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 109 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 110 | CASH_BATCH | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 325 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 462 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 463 | BINANCE | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 464 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 479 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 480 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 484 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 494 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 495 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 500 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 503 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 504 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 507 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 519 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 522 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 531 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 538 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 558 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 564 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 565 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 576 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 577 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 580 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 581 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 584 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 594 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 606 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 617 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 618 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 620 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 621 | BANK_CARD | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |
| 656 | NULL | `payout_founder_name=Андрей`, источник не `FOUNDER_PERSONAL` |

### Касса без подтверждённой партии

| ID | cash_batch_id | Статус | THB | Основание |
|---|---|---|---|---|
| 61 | NULL | VERIFIED | 100000.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |
| 109 | NULL | COMPLETED | 5500.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |
| 110 | NULL | COMPLETED | 5000.0 | `CASH_BATCH`, нет связанной партии ни напрямую, ни через FIFO |

### Полночь + связанное событие в тот же день

| ID | created_at | Свидетельство | Время события |
|---|---|---|---|
| 369 | 2026-06-10 00:00:00 | deal_agents.created_at | 2026-06-10T15:19:29.056692 |
| 394 | 2026-06-26 00:00:00 | deal_agents.created_at | 2026-06-26T17:10:25.042738 |
| 412 | 2026-07-09 00:00:00 | sber_incomes.created_at | 2026-07-09T08:42:22.986578 |
| 415 | 2026-07-08 00:00:00 | sber_incomes.created_at | 2026-07-08T15:11:58.194851 |
| 427 | 2026-07-17 00:00:00 | sber_incomes.created_at | 2026-07-17T19:47:43.052998 |
| 447 | 2026-07-24 00:00:00 | sber_incomes.created_at | 2026-07-24T10:34:12.462586 |
| 452 | 2026-07-28 00:00:00 | deal_agents.created_at | 2026-07-28T12:58:27.084989 |
| 455 | 2026-08-04 00:00:00 | sber_incomes.created_at | 2026-08-04T13:19:25.814309 |
| 456 | 2026-08-04 00:00:00 | deal_agents.created_at | 2026-08-04T13:14:43.164648 |
| 460 | 2026-08-04 00:00:00 | sber_incomes.created_at | 2026-08-04T13:15:02.956659 |
| 463 | 2026-08-06 00:00:00 | deal_agents.created_at | 2026-08-06T12:04:06.528749 |
| 469 | 2026-08-10 00:00:00 | sber_incomes.created_at | 2026-08-10T08:43:11.269964 |
| 481 | 2026-08-11 00:00:00 | sber_incomes.created_at | 2026-08-11T06:33:32.100035 |
| 494 | 2026-08-12 00:00:00 | deal_agents.created_at | 2026-08-12T09:01:15.541343 |
| 498 | 2026-08-12 00:00:00 | sber_incomes.created_at | 2026-08-12T10:55:07.989194 |
| 500 | 2026-08-12 00:00:00 | card_allocations.created_at | 2026-08-12T17:20:18.998167 |
| 501 | 2026-08-14 00:00:00 | sber_incomes.created_at | 2026-08-14T09:05:40.945026 |
| 503 | 2026-08-14 00:00:00 | payin_tx_uses.created_at | 2026-08-14T13:57:21.413868 |
| 507 | 2026-08-17 00:00:00 | payin_tx_uses.created_at | 2026-08-17T13:14:39.716255 |
| 509 | 2026-08-17 00:00:00 | sber_incomes.created_at | 2026-08-17T11:14:08.801583 |
| 522 | 2026-08-19 00:00:00 | sber_incomes.created_at | 2026-08-19T07:48:47.169573 |
| 525 | 2026-08-19 00:00:00 | sber_incomes.created_at | 2026-08-19T12:45:11.422752 |
| 529 | 2026-08-20 00:00:00 | sber_incomes.created_at | 2026-08-20T11:28:03.301809 |
| 531 | 2026-08-20 00:00:00 | payin_tx_uses.created_at | 2026-08-20T14:45:02.226228 |
| 532 | 2026-08-21 00:00:00 | payin_tx_uses.created_at | 2026-08-21T06:56:35.787058 |
| 534 | 2026-08-23 00:00:00 | sber_incomes.created_at | 2026-08-23T08:17:55.525154 |
| 538 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T10:31:14.931639 |
| 540 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T12:34:09.38023 |
| 541 | 2026-08-25 00:00:00 | sber_incomes.created_at | 2026-08-25T05:08:58.003475 |
| 542 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-24T15:46:19.550401 |
| 543 | 2026-08-25 00:00:00 | sber_incomes.created_at | 2026-08-25T12:16:14.99426 |
| 545 | 2026-08-25 00:00:00 | payin_tx_uses.created_at | 2026-08-25T15:20:44.005563 |
| 546 | 2026-08-27 00:00:00 | sber_incomes.created_at | 2026-08-27T05:41:57.312721 |
| 550 | 2026-08-27 00:00:00 | payin_tx_uses.created_at | 2026-08-27T13:42:25.638691 |
| 558 | 2026-08-27 00:00:00 | payin_tx_uses.created_at | 2026-08-27T15:45:04.297408 |
| 566 | 2026-08-31 00:00:00 | payin_tx_uses.created_at | 2026-08-31T04:41:04.341785 |
| 576 | 2026-08-31 00:00:00 | payin_tx_uses.created_at | 2026-08-31T12:55:19.019454 |
| 578 | 2026-08-31 00:00:00 | sber_incomes.created_at | 2026-08-31T14:34:59.577186 |
| 580 | 2026-09-01 00:00:00 | payin_tx_uses.created_at | 2026-09-01T11:36:04.299796 |
| 584 | 2026-09-02 00:00:00 | deal_agents.created_at | 2026-09-02T09:16:56.75591 |
| 593 | 2026-09-03 00:00:00 | deal_agents.created_at | 2026-09-03T13:40:37.789354 |
| 594 | 2026-09-03 00:00:00 | deal_agents.created_at | 2026-09-03T12:41:51.150819 |
| 597 | 2026-09-03 00:00:00 | sber_incomes.created_at | 2026-09-03T06:24:26.588112 |
| 605 | 2026-09-07 00:00:00 | payin_tx_uses.created_at | 2026-09-07T08:05:06.356847 |
| 607 | 2026-09-08 00:00:00 | sber_incomes.created_at | 2026-09-08T08:02:04.653209 |
| 612 | 2026-09-11 00:00:00 | sber_incomes.created_at | 2026-09-11T06:32:10.072315 |
| 613 | 2026-09-11 00:00:00 | payin_tx_uses.created_at | 2026-09-11T12:40:40.692145 |
| 615 | 2026-09-11 00:00:00 | sber_incomes.created_at | 2026-09-11T04:48:38.241768 |
| 617 | 2026-09-14 00:00:00 | card_allocations.created_at | 2026-09-14T07:25:26.577555 |
| 618 | 2026-09-14 00:00:00 | card_allocations.created_at | 2026-09-14T07:26:29.894255 |
| 621 | 2026-09-14 00:00:00 | sber_incomes.created_at | 2026-09-14T12:47:47.838336 |
| 626 | 2026-09-15 00:00:00 | sber_incomes.created_at | 2026-09-15T06:53:34.039221 |
| 627 | 2026-09-15 00:00:00 | payin_tx_uses.created_at | 2026-09-15T15:28:13.904817 |
| 629 | 2026-09-16 00:00:00 | sber_incomes.created_at | 2026-09-16T11:19:06.717156 |
| 637 | 2026-09-17 00:00:00 | sber_incomes.created_at | 2026-09-17T06:16:47.918825 |
| 639 | 2026-09-18 00:00:00 | sber_incomes.created_at | 2026-09-18T12:23:32.018715 |
| 644 | 2026-09-21 00:00:00 | sber_incomes.created_at | 2026-09-21T05:18:34.779479 |
| 652 | 2026-09-23 00:00:00 | payin_tx_uses.created_at | 2026-09-23T07:19:21.831529 |
| 656 | 2026-09-23 00:00:00 | payin_tx_uses.created_at | 2026-09-23T07:42:18.904678 |
| 657 | 2026-09-23 00:00:00 | deal_agents.created_at | 2026-09-23T10:18:56.512269 |
| 660 | 2026-09-24 00:00:00 | payout_tx_uses.created_at | 2026-09-24T08:21:09.165172 |
| 664 | 2026-09-23 00:00:00 | sber_incomes.created_at | 2026-09-23T13:46:54.256383 |
| 665 | 2026-09-25 00:00:00 | payin_tx_uses.created_at | 2026-09-25T17:37:29.641607 |
| 667 | 2026-09-25 00:00:00 | payout_tx_uses.created_at | 2026-09-25T18:21:36.058956 |

### Полночь + событие только другого дня (слабый признак)

| ID | created_at | Свидетельство | Время события |
|---|---|---|---|
| 31 | 2026-01-17 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.377512 |
| 32 | 2026-01-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.381774 |
| 34 | 2026-01-15 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.387853 |
| 35 | 2026-01-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.369469 |
| 36 | 2026-01-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.390212 |
| 37 | 2026-01-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.392634 |
| 42 | 2026-01-26 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.385894 |
| 50 | 2026-01-28 00:00:00 | wallet_operations.created_at | 2026-01-29T10:36:42.676928 |
| 61 | 2026-02-06 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.410771 |
| 64 | 2026-02-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.406113 |
| 66 | 2026-02-13 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.403535 |
| 73 | 2026-01-31 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.426468 |
| 77 | 2026-02-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.414786 |
| 83 | 2026-02-24 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.428584 |
| 87 | 2026-03-01 00:00:00 | wallet_operations.created_at | 2026-03-02T18:57:15.904494 |
| 90 | 2026-02-27 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.430654 |
| 92 | 2026-02-27 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.432754 |
| 101 | 2026-03-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.422233 |
| 107 | 2026-03-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.435017 |
| 108 | 2026-03-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.437943 |
| 116 | 2026-03-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.424224 |
| 118 | 2026-03-13 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.416816 |
| 121 | 2026-03-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.442126 |
| 129 | 2026-03-14 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.444063 |
| 138 | 2026-03-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.448474 |
| 142 | 2026-03-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.450603 |
| 149 | 2026-03-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.440046 |
| 152 | 2026-03-30 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.452983 |
| 164 | 2026-04-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.446404 |
| 285 | 2026-04-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.471356 |
| 308 | 2026-04-28 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.482781 |
| 309 | 2026-04-28 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.464227 |
| 311 | 2026-05-01 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.473169 |
| 319 | 2026-05-11 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.486484 |
| 323 | 2026-05-12 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.477367 |
| 330 | 2026-05-18 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.484699 |
| 338 | 2026-05-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.490512 |
| 346 | 2026-05-17 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.517825 |
| 356 | 2026-06-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.528464 |
| 357 | 2026-06-04 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.563537 |
| 359 | 2026-06-01 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.526523 |
| 360 | 2026-06-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.532618 |
| 371 | 2026-06-11 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.536816 |
| 378 | 2026-06-16 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.55498 |
| 382 | 2026-06-21 00:00:00 | deal_agents.created_at | 2026-06-24T07:19:32.670552 |
| 384 | 2026-06-25 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.520003 |
| 387 | 2026-06-25 00:00:00 | deal_agents.created_at | 2026-07-02T11:25:05.259595 |
| 388 | 2026-06-25 00:00:00 | deal_agents.created_at | 2026-07-02T11:08:07.832653 |
| 393 | 2026-06-24 00:00:00 | deal_agents.created_at | 2026-06-26T17:05:14.66793 |
| 396 | 2026-06-26 00:00:00 | deal_agents.created_at | 2026-06-29T20:21:32.699237 |
| 398 | 2026-07-01 00:00:00 | deal_agents.created_at | 2026-07-31T13:31:25.649429 |
| 406 | 2026-07-02 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.56543 |
| 411 | 2026-07-07 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.552845 |
| 413 | 2026-07-08 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.499281 |
| 419 | 2026-07-13 00:00:00 | deal_agents.created_at | 2026-07-23T14:08:35.540728 |
| 422 | 2026-07-09 00:00:00 | sber_incomes.created_at | 2026-07-10T14:33:06.222438 |
| 425 | 2026-07-20 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.559047 |
| 453 | 2026-07-30 00:00:00 | sber_incomes.created_at | 2026-07-29T14:15:08.062761 |
| 458 | 2026-08-03 00:00:00 | deal_agents.created_at | 2026-08-05T10:25:43.918334 |
| 461 | 2026-08-04 00:00:00 | payin_tx_uses.created_at | 2026-08-31T15:13:03.493492 |
| 462 | 2026-08-05 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.324101 |
| 464 | 2026-08-03 00:00:00 | sber_incomes.created_at | 2026-08-04T13:19:25.814312 |
| 470 | 2026-08-10 00:00:00 | payin_tx_uses.created_at | 2026-08-14T11:51:55.327626 |
| 484 | 2026-08-10 00:00:00 | card_allocations.created_at | 2026-08-11T09:48:48.917115 |
| 495 | 2026-08-12 00:00:00 | sber_incomes.created_at | 2026-08-11T08:27:11.923921 |
| 537 | 2026-08-24 00:00:00 | sber_incomes.created_at | 2026-08-22T14:53:39.215897 |
| 638 | 2026-09-18 00:00:00 | sber_incomes.created_at | 2026-09-17T11:30:29.247139 |

## origin/main

Проверен локальный ref `origin/main@7b0a86b0501f69d70a271f9a42e9c74afa793fd2` без fetch/push. База хотфикса — `origin/stage@631d02623dbbaac08820ca0c0dfe3a0f09f734c7`.

**Да, код production-ветки потенциально затронут тем же багом A.** В `static/crm/crm.html`: `created_at` — `type=date` (строка 1885), заполнение через `.split("T")[0]` (5291), полная `FormData` (8628), отправка всего `data` через PUT (8766). В select источника (1671) первый вариант `cash_batch`, в select фаундера (1751) — Андрей, пустого варианта нет. Кастомный редактор также отправляет дату и весь объект (5530–5584). Это сравнение кода ref, не проверка реально развёрнутого build.

Полные свидетельства по каждому ID: [audit-results.json](audit-results.json). Воспроизводимый read-only запрос: [audit.py](audit.py).
