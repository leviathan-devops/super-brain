# Leviathan Super Brain Dev Team v5.0 — Staged Pipeline
# Gemma(I/O) → Opus+DeepSeek(arch) → Grok×2(prototype) → Codex×2(production) → Opus(review) → Gemma(deliver)
FROM python:3.11-slim

RUN pip install --no-cache-dir flask gunicorn requests "discord.py>=2.3"

WORKDIR /app
COPY team_server.py /app/team_server.py

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "2", "--threads", "4", "team_server:app"]
