# ТЗ: LOSE-сделки в CalcCRM + revive-логика + конверсия в дашборде

**Дата:** 2026-07-20
**Затрагивает:** CalcCRM (модель, API, дашборд) + DealCloser (закрытие LOSE, revive-флоу)
**Методология:** конверсия по Красинскому — CR = покупатели/обратившиеся, когорта первого касания, разделение новые/повторные.

## 1. Модель (принятые решения)

- **Эпизод** = обращение клиента (цепочка касаний до WON или брошено).
  - WON-эпизод: completed-сделка + привязанные к ней LOSE (`revived_by_deal_id`).
  - Проигранный эпизод: каждая непривязанная LOSE-сделка.
- **Новый/повторный:** эпизод повторный, если у клиента (client_id или client_name без регистра) была completed-сделка ДО первого касания эпизода. Вычисляется на лету, не хранится.
- **CR новых** — главная метрика; **CR повторных** — отдельно (прокси удержания).
- **Когорта** = месяц первого касания эпизода, revive без срока давности.
- Исторические LOSE из Bitrix — не бэкфиллим.
- Revive: при WON бот ищет LOSE по имени клиента → юзер решает кнопкой (все / выбрать / новое обращение). Один WON может забрать несколько LOSE.

## 2. Изменения CalcCRM

### 2.1 Модель / миграция
- `DealStatus.LOSE = "lose"` + автокоммит-миграция `ALTER TYPE dealstatus ADD VALUE IF NOT EXISTS 'LOSE'` (паттерн как payinmethod/SBER_WL, вне транзакции).
- Новые колонки `deals` (ALTER TABLE ... IF NOT EXISTS):
  - `lose_reason VARCHAR(300)` — причина отказа из LLM-анализа бота;
  - `bitrix_deal_id INTEGER` — id сделки Bitrix (дедуп + трейсинг);
  - `revived_by_deal_id INTEGER REFERENCES deals(id)` — WON-сделка, забравшая этот LOSE.
- `to_dict()` отдаёт все три поля.

### 2.2 POST /api/deals (status=lose)
- Принимает `status="lose"`, `lose_reason`, `bitrix_deal_id`.
- **Идемпотентность:** если существует lose-сделка с тем же `bitrix_deal_id` → вернуть её (200), не создавать дубль.
- **НЕ создавать клиента** для lose (линкуем только существующего) — иначе список клиентов замусоривается непокупателями.
- **НЕ навешивать реферера** и не пересчитывать финансы для lose.

### 2.3 Новые эндпоинты
- `GET /api/deals/lose-candidates?client_name=X` — непривязанные lose-сделки клиента (точный матч имени без регистра + по client_id, если клиент найден). Ответ: `[{id, created_at, lose_reason, payin_amount_rub, payin_amount_usdt}]`.
- `POST /api/deals/<won_id>/revive` `{lose_ids:[...]}` — валидации: won-сделка не lose/не cancelled; каждая lose_id — статус lose и ещё не привязана. Ставит `revived_by_deal_id`.
- `POST /api/deals/<won_id>/unrevive` `{lose_ids:[...]}` — откат ошибочной привязки (пустой список = отвязать все).
- `GET /api/analytics/conversion?months=N|date_from&date_to` — помесячно: `{month, new_total, new_won, new_cr, repeat_total, repeat_won, repeat_cr, avg_touches_to_won, lost_profit_est_usdt}` + `lose_list` (клиент, дата, причина, revived или нет) + `totals`.
  - `lost_profit_est_usdt` = число проигранных эпизодов × средний `profit_usdt` completed-сделок периода (оценка по Красинскому: эффект в деньгах).

### 2.4 Защита существующих выборок (уязвимые места)
| Место | Риск | Фикс |
|---|---|---|
| GSheet sync | триггерится только на completed | ок, не трогаем; тест-страховка |
| Реф. вознаграждение (PUT auto-reward) | lose не должен начислять | guard: только completed |
| Возмещения `/api/reimbursements/pending` | фильтр по payout_source | у lose его нет — ок; тест |
| `/api/analytics/dashboard` | считает только COMPLETED | ок; тест что lose не влияет |
| Список сделок CRM `/api/deals` | lose замусорит основной список | дефолт исключает lose; `?status=lose` или `include_lose=1` показывает |
| Юнит-экономика когорты v5 | B/Orders только completed | тест |
| DELETE won-сделки | висячие `revived_by_deal_id` | при удалении отвязать children (NULL) |
| Переводы статусов PUT | pending→lose? lose→completed? | разрешаем; lose→completed отвязывает от revive нельзя (сама lose становится won — снять revived_by у неё) |

## 3. Изменения DealCloser

### 3.1 LOSE-закрытие (`handlers/close.py`, action=lose)
1. Закрыть Bitrix LOSE (как сейчас — приоритетная операция).
2. Затем создать lose-сделку в CalcCRM: `{status:"lose", client_name (из TITLE Bitrix), lose_reason, bitrix_deal_id, payin_amount_* если LLM извлёк, deal_type:"pay_in"}`.
3. CalcCRM упал → Bitrix НЕ откатываем, показываем «⚠️ LOSE в Bitrix закрыт, но не записан в CalcCRM — статистика неполная» (запись аналитическая, не денежная — политика обратная WON-флоу).
4. Сообщение при подтверждении меняется: `→ Bitrix LOSE + CalcCRM (lose)`.

### 3.2 Revive-флоу (action=won, после успешного закрытия)
1. После «✅ Готово» → `GET lose-candidates?client_name=`.
2. Кандидаты есть → доп. сообщение:
   `🔍 У {client} были LOSE: #214 03.07 «не устроил курс», #230 12.07 «клиент не вернулся»`
   Кнопки: `🔄 Забрать все` / `☑️ Выбрать вручную` / `🆕 Новое обращение`.
3. «Выбрать вручную» — toggle-кнопки по каждой LOSE (✅/⬜) + «Готово».
4. Callback-данные: id кандидатов хранить в storage (лимит callback_data 64 байта).
5. Ошибка revive — показать, не падать.

## 4. Уязвимые места (сводно) и контроль

1. **Postgres enum** — `ALTER TYPE ... ADD VALUE` только autocommit вне транзакции; иначе прод упадёт на старте. Проверка: локальный SQLite (enum как VARCHAR) + после деплоя `journalctl`/Railway logs + `/api/health`.
2. **Дубли LOSE** (double-tap, retry бота) — идемпотентность по `bitrix_deal_id`. Тест.
3. **Замусоривание клиентов/рефералки/GSheet** — guard'ы §2.4 + тесты.
4. **Матчинг имён** — «Иван» ≠ «Иван П.»: точный матч без регистра, кандидаты подтверждаются человеком (авто-privязки нет). Ложных склеек не будет, но возможны пропуски — приемлемо.
5. **Гонка**: WON закрыт, кандидаты показаны, юзер ушёл → LOSE остались непривязанными. Починка: `unrevive`/`revive` можно дернуть повторно; кандидаты ищутся по client_name в любой момент.
6. **DealCloser auth** — использует X-Api-Key (не протухает). Новые эндпоинты должны работать под сервисным ключом (не только cookie).
7. **UNKNOWN-вердикты** — не пишем в CalcCRM вообще (как сейчас).

## 5. Способы проверки

- **pytest CalcCRM** (`tests/test_lose_conversion.py`): создание lose, идемпотентность, не-создание клиента, revive/unrevive валидации, conversion math (фикстуры: new won, new lost, revived 2×lose→won, repeat lost), lose не попадает в dashboard/gsheet/реф.выплаты, delete won отвязывает.
- **pytest DealCloser нет** — логика в handlers тонкая, проверяем на проде.
- **Прод CalcCRM (после git push, Railway):** `/api/health` → curl с X-Api-Key: создать тестовый lose → candidates → revive → conversion → удалить тестовые записи.
- **Прод DealCloser:** scp+kill, `systemctl is-active`, journalctl 30s; следующее реальное закрытие LOSE/WON — контроль по логам.
- **Дашборд UI:** agent-browser скриншот блока конверсии (1080p) после деплоя.
