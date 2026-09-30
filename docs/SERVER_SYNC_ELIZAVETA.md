# ТЗ: Серверная интеграция аккаунтов Елизаветы (Railway)

Клиентский менеджер Елизавета общается с клиентами, поэтому интеграция её каналов (Telegram и WhatsApp) обязательна. 
Архитектура состоит из ОДНОГО Railway Worker сервиса (без публичного домена), который объединяет Go WA-bridge и Python TG-sync-worker через `supervisord`. Оба процесса используют общий Persistent Volume `/data` для хранения SQLite БД WhatsApp и файла сессии Telegram.

## 1. Архитектура в Railway (`ChannelsWorker`)
- **Единый сервис**: Разворачивается из папки `ChannelsWorker`.
- **Persistent Volume**: Подключается в Railway с Mount Path `/data`.
- **Go WA-bridge**: Бинарник `wa-bridge` (собранный из `whatsapp-mcp/main.go`). В Dockerfile настроен симлинк `ln -s /data/store /app/store`, чтобы мост, пишущий в `./store`, сохранял данные на Volume.
- **Python Sync Worker**: Скрипт `sync_channels_to_stand.py`, который запускается параллельно, читает Telegram-сообщения (Telethon), WhatsApp БД (`/data/store/messages.db`) и Bitrix webhook, и отправляет обновления в `https://grusha-new.up.railway.app`.

## 2. Развёртывание в Railway

1. Создать новый **Empty Service** в Railway (в проекте `grusha-stand`) или привязать к репозиторию (с Root Directory `/ChannelsWorker`).
   *(Убедитесь, что исходники `whatsapp-mcp` скопированы в `ChannelsWorker/whatsapp-mcp` перед коммитом).*
2. Добавить **Volume** к сервису:
   - Mount Path: `/data`
3. Отключить Public Domain.
4. Задать переменные окружения:
   ```env
   STAND_BASE_URL=https://grusha-new.up.railway.app
   STAND_CHANNEL_SYNC_KEY=<STAND_SYNC_KEY>
   SYNC_LOOP_INTERVAL=300
   
   # Пути к данным (используют Volume)
   SYNC_TG_SESSION_FILE_ELIZAVETA=/data/elizaveta.session
   SYNC_TG_API_ID_ELIZAVETA=<API_ID>
   SYNC_TG_API_HASH_ELIZAVETA=<API_HASH>
   SYNC_WA_DB_PATH_ELIZAVETA=/data/store/messages.db
   SYNC_BITRIX_WEBHOOK=<URL>
   ```

## 3. Авторизация (Елизавета)

Авторизация происходит однократно через безопасный терминал Railway без вывода кодов в публичный интернет.

### WhatsApp
1. Открыть **Railway Web Terminal** сервиса (или посмотреть логи).
2. При старте `wa-bridge` выведет QR-код в консоль (и запишет в `/data/store/qr_code.txt`, который можно прочитать командой `cat /data/store/qr_code.txt`).
3. Елизавета сканирует QR-код из приложения WhatsApp. База `messages.db` начнёт наполняться.

### Telegram
1. В том же **Railway Web Terminal** запустить скрипт для авторизации:
   ```bash
   python3 -c '
   import os, asyncio; from telethon import TelegramClient
   async def main():
       client = TelegramClient("/data/elizaveta.session", int(os.environ["SYNC_TG_API_ID_ELIZAVETA"]), os.environ["SYNC_TG_API_HASH_ELIZAVETA"])
       await client.start()
       print("✅ Сессия Telegram успешно сохранена!")
   asyncio.run(main())
   '
   ```
2. Скрипт попросит номер телефона и код из Telegram.
3. Елизавета вводит данные прямо в консоль.
4. После успеха нажать `Restart` сервиса, чтобы фоновый `sync_channels_to_stand.py` подхватил готовую сессию и базу WA.
