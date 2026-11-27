# Независимая сверка design-gate — 15.10.2026

Повторный запуск `run.py check` на локальном сервере `127.0.0.1:59109`, восстановленная копия `stand_prodcopy_20260928-before-hotfix4-20261014-1909.sql.gz`, роль `karim`. Обязательные снимки «до» (375 и 1280) скопированы без изменений из ранее сохранённых `machine-crm-deals` и `machine-crm-referrers`. Новые снимки «после» созданы именно этим повторным запуском.

| Экран | Полный stdout | Сырой Markdown | Сырой JSON | Результат |
|---|---|---|---|---|
| Сделки | [stdout](../qa-recheck-20261015-deals-stdout.md) | [check-after.md](deals/check-after.md) | [check-after.json](deals/check-after.json) | PASS, 6/6 гейтов, 375/768/1280/1920 |
| Рефереры | [stdout](../qa-recheck-20261015-referrers-stdout.md) | [check-after.md](referrers/check-after.md) | [check-after.json](referrers/check-after.json) | PASS, 6/6 гейтов, 375/768/1280/1920 |

Оба экрана загружены с реальными записями: 50 строк Сделок и 25 карточек Рефереров. На каждом из четырёх размеров gate нашёл одну главную кнопку.
