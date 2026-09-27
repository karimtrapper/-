-- Санация кандидат-базы (копии прод-данных) перед тем, как её увидит стенд.
--
-- Запускается ОДНОЙ транзакцией (`psql -v ON_ERROR_STOP=1 -1 -f`) сразу после
-- restore прод-дампа в свежесозданную базу `stand_prodcopy_<дата>`. Если что-то
-- упадёт — вся санация откатывается целиком, кандидат остаётся неконсистентным
-- и restore-candidate обязан завершиться ошибкой (никакого «частично санировано»).
--
-- Колонки login_disabled/notify_enabled у AdminUser — задача T2 (миграция
-- `stage`, идемпотентная ALTER ... ADD COLUMN). Прод-дамп снят со старой схемы
-- (main), где этих колонок нет вовсе, поэтому санация сама их создаёт: имена и
-- типы (Boolean default false) совпадают с миграцией T2, поэтому когда T2
-- сведётся в ту же ветку, повторный ALTER ... IF NOT EXISTS будет no-op.
BEGIN;

ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS login_disabled boolean NOT NULL DEFAULT false;
ALTER TABLE admin_users ADD COLUMN IF NOT EXISTS notify_enabled boolean NOT NULL DEFAULT false;

-- ── Перевыпуск токенов, дающих доступ без логина ────────────────────────────
-- Только те колонки, что открывают чужой кабинет/данные по одной ссылке
-- (`/api/partner/<token>`, `/api/ref/<token>`, `/api/kyc/status/<token>`).
-- Платёжные идентификаторы (payment_link_orders.order_id/payment_id) —
-- бухгалтерский след внешнего провайдера, а не секрет: их не трогаем,
-- переход по ним снаружи блокирует gate/UI, не отзыв номера заказа.
-- md5(random()::text || clock_timestamp()::text || id::text) — 32 hex-символа,
-- pgcrypto не нужен; уникальность гарантирует id (у каждой строки свой),
-- предсказать новое значение по старому невозможно.
UPDATE partners
   SET token = md5(random()::text || clock_timestamp()::text || id::text || 'partner')
 WHERE token IS NOT NULL;

UPDATE referrers
   SET token = md5(random()::text || clock_timestamp()::text || id::text || 'referrer')
 WHERE token IS NOT NULL;

-- kyc_requests.token — 64 символа (String(64)), склеиваем два md5.
UPDATE kyc_requests
   SET token = md5(random()::text || clock_timestamp()::text || id::text || 'kyc1')
            || md5(random()::text || clock_timestamp()::text || id::text || 'kyc2')
 WHERE token IS NOT NULL;

-- ── Одноразовые коды входа через бота ───────────────────────────────────────
-- Нонсы живут 10 минут и без матчинга с прод-ботом бесполезны, но это ровно
-- тот тип «доступ без логина», от которого санация обязана избавиться целиком.
DELETE FROM login_nonces;

-- ── Прод-админы: аккаунт остаётся (на него ссылаются сделки), вход — нет ────
-- login_disabled=true отключает пароль, tg-login, tg-poll и поиск по @username
-- (гейт T2 проверяет флаг во всех путях входа). Отключённые аккаунты не
-- должны считаться «активными админами» нигде (в т.ч. в guard «последний
-- админ» — это ответственность T2/кода приложения, санация только чистит данные).
UPDATE admin_users
   SET login_disabled = true,
       notify_enabled = false,
       telegram_user_id = NULL,
       -- Синтаксически невалидный bcrypt-хэш: не начинается с '$2b$', поэтому
       -- check_password() идёт по legacy-ветке (sha256-сравнение строк) и
       -- всегда возвращает False — ни исключения, ни случайного совпадения.
       password_hash = 'sanitized:' || md5(random()::text || clock_timestamp()::text || id::text);

-- Логины, совпадающие с реальными сотрудниками стенда — переименовываем,
-- чтобы пять стендовых аккаунтов (заводит _stand_seed_users) не столкнулись
-- с одноимённой прод-строкой на UNIQUE(username).
UPDATE admin_users
   SET username = 'prod_' || username
 WHERE lower(username) IN ('karim', 'marina', 'artem', 'vitaliy', 'teodor')
   AND username NOT LIKE 'prod_%';

-- ── Хранимые в БД вебхуки/чаты/настройки исходящих ─────────────────────────
-- В текущей схеме (app.py) все адреса вебхуков, chat_id и API-ключи интеграций
-- живут в env (WL_BOT_URL, DOVERKA_WEBHOOK_URL, STAND_TG_CHAT, ...), в БД для
-- них отдельных таблиц/колонок нет — очищать нечего. Если такая таблица
-- появится, добавить сюда её TRUNCATE/UPDATE и обновить итоговый отчёт T4.

-- ── Доска задачника стенда ───────────────────────────────────────────────────
-- Историческая доска (тестовые сделки 25-27.09) архивируется отдельным JSON
-- ДО этого restore (см. Этап 3 плана); здесь — просто пустое состояние.
-- Таблица StandState — фича самого стенда, в прод-дампе (main) её может не
-- быть вовсе, поэтому действуем через DO-блок с to_regclass().
DO $$
BEGIN
    IF to_regclass('public.stand_state') IS NOT NULL THEN
        DELETE FROM stand_state;
        INSERT INTO stand_state (id, data, version, updated_by, updated_at, notified)
        VALUES (1, '{}', 0, NULL, now(), '[]');
    END IF;
END $$;

COMMIT;
