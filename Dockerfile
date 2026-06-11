FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KSM_HOST=127.0.0.1 \
    KSM_PORT=8900

WORKDIR /app

RUN adduser --disabled-password --gecos "" ksm

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY configs ./configs
COPY templates ./templates

RUN mkdir -p /app/data/vaults /app/data/backups && chown -R ksm:ksm /app

USER ksm

EXPOSE 8900

CMD ["sh", "-c", "uvicorn app.api.app:create_app --factory --host ${KSM_HOST:-127.0.0.1} --port ${KSM_PORT:-8900}"]
