# Реферальный кабинет: вход через Telegram (per-referrer)

**Дата:** 2026-07-06
**Проект:** CalcCRM (`Dev/CalcCRM/`)
**Статус:** дизайн утверждён, готов к плану

## Проблема

Кабинет реферера `/ref/<token>` сейчас открыт **любому по ссылке** — авторизации нет.
Нужен переключатель режима входа на уровне каждого реферера.

## Режимы входа (новое поле `auth_mode`)

- `link` (дефолт, как сейчас) — кабинет открыт по ссылке.
- `telegram` — вход только через Telegram Login Widget; TG-аккаунт должен
  совпасть с реферером.

## Бот виджета

**@dealsgrusha_bot** — тот, что уже в `TELEGRAM_BOT_TOKEN` (нотификатор CalcCRM,
шлёт заявки в группу). Его токен подписывает Login Widget.

**Ручной шаг (юзер):** один раз в @BotFather → `/setdomain` →
`grusha.up.railway.app` у @dealsgrusha_bot. Без этого виджет не отрендерится.
Username бота код берёт сам через `getMe` (кэш в памяти).

## Модель данных

`Referrer` (+2 колонки, миграция idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
как у `is_test`):

- `auth_mode VARCHAR(20) DEFAULT 'link'` — `'link'` | `'telegram'`
- `telegram_user_id BIGINT` (nullable) — привязанный числовой TG id

`to_dict()` отдаёт `auth_mode` и `telegram_user_id`.

## Backend

### Хелпер `get_bot_username()`
`getMe` по `TELEGRAM_BOT_TOKEN`, результат кэшируется в модульной переменной.
Возвращает username без `@`. При отсутствии токена → `None`.

### `GET /api/ref/<token>/stats` (правка)
Если `referrer.auth_mode == 'telegram'` и в `session['ref_auth']` нет валидной
привязки для этого токена → `401 {success:false, auth_required:true, bot_username:<...>}`.
Иначе — как сейчас.

### `POST /api/ref/<token>/tg-login` (новый)
Тело — данные виджета: `id, first_name, username?, photo_url?, auth_date, hash`.

1. **Проверка подписи** (Telegram spec):
   - `secret_key = sha256(bot_token_bytes)`
   - `data_check_string` = отсортированные `k=v` (кроме `hash`), склеены через `\n`
   - `hmac_sha256(secret_key, data_check_string).hexdigest() == hash`, иначе `403`
   - `auth_date` не старше 24ч (защита от replay), иначе `403`
2. **Привязка (trust-on-first-login):**
   - `telegram_user_id` задан → пришедший `id` обязан совпасть, иначе `403`
   - иначе `referrer.telegram` (@username) задан → сверка `username`
     (без `@`, регистронезависимо); совпал → сохраняем `telegram_user_id = id`,
     иначе `403`
   - иначе (нет ни id, ни username) → привязываем первый вошедший `id`
3. **Успех** → `session['ref_auth'] = {..., token: id}`, сессия
   `permanent = True` (TTL 30 дней через `PERMANENT_SESSION_LIFETIME`),
   вернуть `{success:true}`.

### Гейт прямых API в telegram-режиме
`POST /api/ref/<token>/payout-request` и
`POST /api/ref/<token>/payout-request/<id>/cancel`: если `auth_mode=='telegram'`
и сессия невалидна → `401`. Иначе API дёргается напрямую по токену в обход виджета.

Вынести проверку в хелпер `_ref_authorized(referrer, token) -> bool`.

## Frontend — `static/referrer/index.html`

- Загрузка: `fetch(/stats)`. При `401 auth_required` — прячем контент, показываем
  экран «Войдите через Telegram» + официальный виджет:
  `<script src="https://telegram.org/js/telegram-widget.js?22"
   data-telegram-login="<bot_username>" data-onauth="onTgAuth(user)"
   data-request-access="write">`.
- `onTgAuth(user)` → `POST /tg-login` с `user` → при `success` `location.reload()`,
  иначе показать ошибку (не тот аккаунт / протухло).

## CRM — `static/crm/crm.html`

В `referrerModal` (форма реферера) — селект **«Вход в кабинет»**:
- `По ссылке` (`link`)
- `Через Telegram` (`telegram`)

Значение шлётся в существующие `POST /api/referrers` и `PUT /api/referrers/<id>`;
эндпоинты читают `auth_mode` из тела (валидация: только `link`|`telegram`,
иначе `link`).

## Безопасность

- HMAC обязателен, `auth_date` TTL 24ч.
- Сессия — подписанный cookie (Flask `SECRET_KEY` уже есть).
- Прямые API по токену гейтятся в telegram-режиме.
- `telegram_user_id` в API-ответах наружу не светим клиенту (только внутр. логика).

## Тесты (`tests/test_referral.py` или новый)

Unit (без сети, HMAC считаем локально валидным ключом тест-токена):
- подпись валидна → 200; невалидна → 403; `auth_date` протух → 403
- привязка: pre-bound id совпал/не совпал; username совпал/не совпал; пустой → bind
- `stats` в telegram-режиме без сессии → 401; в link-режиме → 200

## E2E (вручную на проде, после деплоя)

1. Юзер: `/setdomain grusha.up.railway.app` у @dealsgrusha_bot.
2. Юзер в CRM создаёт тестового реферера: `auth_mode=telegram`, Telegram=свой @username.
3. Открывает `/ref/<token>` → видит виджет → жмёт → попадает в кабинет.
4. Проверка отказа: заходит другим TG-аккаунтом → `403`.

## Вне scope (YAGNI)

- Смена/сброс привязки из UI (пока правится в БД/через CRM обнулением поля).
- Магик-линки, OTP, вход по телефону.
