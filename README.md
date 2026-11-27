# CalcCRM - Unified Calculator + CRM Service

Объединённый сервис калькулятора обмена валют и CRM для Railway.

## Структура

```
CalcCRM/
├── app.py              # Основной сервер (Flask)
├── calculator.py       # Логика калькулятора
├── broker_detailed.py  # Брокерский калькулятор
├── static/
│   ├── calculator/     # Фронтенд калькулятора
│   └── crm/            # Фронтенд CRM
├── Procfile            # Для Railway/Heroku
├── requirements.txt    # Зависимости Python
└── runtime.txt         # Версия Python
```

## URLs

- `/` - Калькулятор (главная)
- `/crm` - CRM система

## API Endpoints

### Калькулятор
- `GET /api/rates` - Актуальные курсы
- `POST /api/calculate` - Расчёт обмена
- `POST /api/webhook/doverka` - Webhook от Doverka

### CRM
- `GET /api/deals` - Список сделок
- `POST /api/deals` - Создать сделку
- `PUT /api/deals/<id>` - Обновить сделку
- `GET /api/cash/batches` - Партии кассы
- `GET /api/managers` - Менеджеры
- `GET /api/analytics/dashboard` - Дашборд

## Компании-агенты документов

Договор, допсоглашение (Приложения 1–2) и счёт выпускает та компания, на чьи реквизиты платит клиент:
MF Corporation (`mf_corp`) или Flow Sole (`flow_sole`). Всё, что у компаний различается (название,
юрисдикция, рег./налоговый номер, адрес, директор, телефон, место, логотип, подпись, печать, футер,
подписи «менеджер X» и «Комиссия Агента»), лежит в одном месте — `doc_agents.py`.

Счёт прихода → агент: `sber` → `mf_corp`, `flow_sole` → `flow_sole`; всё прочее (чужие custom-счета,
USDT, наличные, СБП) → `mf_corp`. Стенд берёт счёт из `rubReceivingAccount`, раздел «Документы» CRM —
по ИНН/счёту в `payin_recipient` / `payin_details`. Агент входит в маршрут договора
(`RUB_THB:bank` для MF, `RUB_THB:bank:flow_sole` для остальных): платёж на другую компанию
оформляется новым договором, а не допником. Нумерация документов (`MF-…`) от агента не зависит.

Добавить новую компанию:
1. запись в `AGENTS` (`doc_agents.py`) по образцу `flow_sole`;
2. папка ассетов `doc_templates/assets/<key>/` — `logo.png`, `signature.png`, `stamp.png` (прозрачный фон);
3. строка в `PAYIN_ACCOUNT_AGENT` (счёт прихода → ключ агента) и, если счёт надо узнавать по тексту
   реквизитов, строка в `ACCOUNT_REQUISITES`.

Шаблоны `doc_templates/*.docx` остаются фирменными шаблонами MF: шапку, футер, логотип и тексты других
агентов `docgen` собирает из профиля при выпуске. Больше нигде править не нужно.

## Деплой на Railway

1. Создайте новый сервис в Railway
2. Подключите эту папку (или GitHub репо)
3. Добавьте PostgreSQL addon
4. Настройте переменные окружения:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
DOVERKA_API_KEY=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
CRM_WEBHOOK_URL=xxx (опционально)
```

5. Railway автоматически задеплоит при push

## Локальный запуск

```bash
cd Dev/CalcCRM
pip install -r requirements.txt
python app.py
```

Откройте:
- http://localhost:5000 - Калькулятор
- http://localhost:5000/crm - CRM
