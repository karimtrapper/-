FROM golang:1.25-bookworm AS builder
WORKDIR /src
# Ожидается, что исходники whatsapp-mcp лежат в подпапке whatsapp-mcp (пользователь должен их туда положить)
COPY whatsapp-mcp/ ./
RUN go build -o /wa-bridge main.go

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y supervisor sqlite3 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем бинарник WA
COPY --from=builder /wa-bridge /app/wa-bridge

# Скрипт синхронизации из основного репо
COPY sync_channels_to_stand.py /app/sync_channels_to_stand.py
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Persistent volume будет монтироваться в /data
# Делаем симлинк, т.к. Go bridge пишет в ./store от своей рабочей директории
RUN ln -s /data/store /app/store

# Создаём /data/store в рантайме (чтобы пережить монтирование пустого volume в /data), затем стартуем supervisor
CMD ["/bin/sh", "-c", "mkdir -p /data/store && exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf"]
