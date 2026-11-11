FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Встроенному Node Playwright нужен libatomic до запуска `scrapling install`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && scrapling install

COPY rate_fetchers.py worker.py ./

CMD ["python", "-u", "worker.py"]
