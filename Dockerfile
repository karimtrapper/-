# Dockerfile для Railway с Playwright
FROM python:3.11-slim

# Установка системных зависимостей для Chromium
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libxshmfence1 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxext6 \
    fonts-liberation \
    libexpat1 \
    libgobject-2.0-0 \
    libgio-2.0-0 \
    libnssutil3 \
    libsmime3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем requirements и устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Playwright Chromium
RUN playwright install chromium

# Копируем весь проект
COPY . .

# Запуск через gunicorn (Railway сам установит $PORT)
CMD gunicorn app:app --bind 0.0.0.0:${PORT:-8080}
