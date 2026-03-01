# Leviathan Enhanced Opus — Super Brain v1.0
# DeepSeek R1 reasoning engine + Gemini context ingestion + OpenRouter sub-agents
# Separate Railway instance from CloudFang Leviathan ecosystem
FROM python:3.11-slim

RUN pip install --no-cache-dir aiohttp flask gunicorn requests

WORKDIR /app
COPY . /app/

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "--workers", "2", "server:app"]
