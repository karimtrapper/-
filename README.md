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
