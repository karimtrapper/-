# Рефакторинг конвертаций — план с метриками

**Дата:** 2026-08-19
**Повод:** за день на конвертации легло ~12 итераций подряд, каждая правилась «по месту».
**Подход:** метрики берём из DORA (latency/change failure rate/lead time), измеряем ДО и ПОСЛЕ.

---

## 1. Замеры «как есть» (факт, не мнение)

Прод, два подряд вызова:

| Эндпоинт | 1-й | 2-й |
|---|---:|---:|
| `/api/sber-incomes?with_conversion=1` | 3,59 с | 2,69 с |
| `/api/sber-incomes` | 2,21 с | 2,03 с |
| `/api/reestr/all` | 3,98 с | 0,53 с |
| `/api/conversions` | 0,40 с | 0,39 с |

Счётчик SQL на синтетике (300 приходов, 30 пачек):

| Эндпоинт | SQL-запросов |
|---|---:|
| `/api/sber-incomes` | **601** |
| `/api/sber-incomes?with_conversion=1` | **663** |
| `/api/reestr/all` | **605** |

601 запрос на 300 строк — классический N+1: `SberIncome.to_dict()` зовёт
`converted_rub()` и `free_rub()`, каждый делает свой запрос. На SQLite это 66 мс,
на Postgres в Railway каждый round-trip ~4 мс → те самые 2–3 секунды.

## 2. Метрики, на которые влияем

| Метрика | Было | Стало | Цель | Как меряем |
|---|---:|---:|---|
| Latency экрана «Поступления» | 2,7 с | **0,54 с** | < baseline+200 мс | `curl -w %{time_total}` ×4, минимум |
| SQL-запросов на список приходов | 601 | **2** | ≤ 5 | счётчик `before_cursor_execute`, 300 строк |
| SQL на список с конвертациями | 663 | **6** | ≤ 10 | то же |
| SQL на `/api/reestr/all` | 605 | **2** | ≤ 15 | то же |
| Сетевые вызовы внутри GET | 1 (TronScan) | **0** | 0 | тест падает, если вернутся |
| Копий расчёта доли USDT | 4 | **1** | 1 | `conversion_shares_for` |
| Расчётное ядро вне `app.py` | 0 строк | **87** | отдельный файл | `conversions_core.py` |
| Тестов на конвертации | 16 | **38** | — | `test_conversions*.py` |

Базовая сетевая задержка до Railway — 0,35–0,46 с на пустом эндпоинте, поэтому
цель «< 400 мс» изначально была недостижима из-за географии, а не кода.
Честная метрика — надбавка над baseline: было +2,3 с, стало **+0,1 с**.

Три бага для честности: `UnboundLocalError` в `list_sber_incomes` (поймал
существующий тест), молчаливая привязка нулевой доли, рублёвая маржа под знаком `$`.

## 3. Что именно чинить

### Ф1. Убить N+1 (главная победа по латенси)

`converted_rub()` / `free_rub()` / `used_usdt()` / `used_rub()` ходят в БД из `to_dict()`.
Решение — считать агрегаты **одним** запросом на список и прокидывать в `to_dict(agg=...)`,
оставив методы для одиночных объектов (их зовут карточки и тесты).

```python
def _converted_by_income(session, ids):
    """Σ долей по приходам одним запросом вместо запроса на строку."""
    rows = session.query(ConversionSource.sber_income_id,
                         func.sum(ConversionSource.amount_rub)).join(
        Conversion, ConversionSource.conversion_id == Conversion.id).filter(
        ConversionSource.sber_income_id.in_(ids),
        Conversion.status != ConversionStatus.CANCELLED).group_by(
        ConversionSource.sber_income_id).all()
    return {i: round(v or 0, 2) for i, v in rows}
```

### Ф2. Вынести конвертации из `app.py`

`conversions.py`: модели, `_conversion_shares`, `_match_wl_deal`, `_attach_*`,
`_apply_conversion_shares`, эндпоинты (Blueprint). `app.py` их только регистрирует.
Критерий: файл < 600 строк, тесты не переписываются (импорты через `app`).

### Ф3. Сетевые вызовы вон из чтения

`GET /api/conversions/<id>` дёргает TronScan, если у перевода нет адреса. Чтение не
должно зависеть от внешней сети: перенести в фоновой догон (как `_payment_link_poll_loop`)
или в момент привязки. Пока адрес не подтянут — показываем «уточняется».

### Ф4. Один источник правды по доле USDT

Сейчас доля считается в четырёх местах (`list_sber_incomes`, `get_conversion`,
`_apply_conversion_shares`, `_conversions_by_wl`). Свести к одной функции
`conversion_breakdown(conv)` → `{income_id: {rub, usdt, deal, wl}}`, остальные зовут её.

### Ф5. Индексы

`conversion_sources.sber_income_id`, `conversion_debits.sber_debit_id`,
`sber_incomes.operation_date` — под фильтры и джойны, которые появились сегодня.

## 4. Порядок и проверка

1. Ф1 → замер SQL и латенси, до/после в одной таблице
2. Ф5 (дёшево, усиливает Ф1)
3. Ф4 → тесты на равенство долей во всех четырёх местах
4. Ф2 → прогон полного набора без правки тестов
5. Ф3 → проверка, что карточка открывается при недоступном TronScan

Каждый шаг: тесты зелёные + замер + отдельный коммит. Прод трогаем только
после полного прогона (911 тестов).

## 5. Чего НЕ делаем

Фронт (`crm.html`, 11 981 строка) не трогаем в этот заход: он не влияет на
измеряемые метрики, а риск сломать живую CRM высокий. Отдельной задачей.

## Источники по метрикам

- [DORA — software delivery performance metrics](https://dora.dev/guides/dora-metrics/)
- [DORA metrics: полный гид (getdx)](https://getdx.com/blog/dora-metrics/)
- [Understanding the 4 DORA metrics (Octopus Deploy)](https://octopus.com/devops/metrics/dora-metrics/)
