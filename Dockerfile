# Dockerfile для Railway с Playwright
FROM python:3.11-slim

# Установка системных зависимостей для Chromium
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxshmfence1 \
    libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements и устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Playwright Chromium
RUN playwright install chromium

# Копируем весь проект
COPY . .

# Запуск через gunicorn (Railway сам установит $PORT).
# --threads 8 (gthread): без него 1 sync-воркер сериализует ВСЕ запросы —
# обход TronScan или Playwright precise фризил CRM для всех менеджеров.
# workers строго 1: in-memory локи и кэши рассчитаны на один процесс.
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 120
