FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_CHROMIUM_USE_HEADLESS_SHELL=0 \
    BOT_REDIS_HOST=redis

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python -m playwright install --with-deps --no-shell chromium

COPY main.py /app/main.py
COPY config.example.py /app/config.example.py
COPY private_key.example.py /app/private_key.example.py
COPY README.md /app/README.md
COPY src /app/src
COPY plugins /app/plugins
COPY tools /app/tools
COPY docs /app/docs
COPY config /app/config

RUN mkdir -p /app/data /app/logs

CMD ["python", "main.py"]
