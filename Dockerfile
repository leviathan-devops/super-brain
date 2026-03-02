# Leviathan Super Brain Dev Team v5.2 — Gated Pipeline
# Fast path: Gemma→DeepSeek V3→Gemma (FREE/cheap)
# Build path: DeepSeek R1→Opus→Grok×N→Codex×N→DeepSeek R1(verify)→Gemma
FROM python:3.11-slim

RUN pip install --no-cache-dir flask gunicorn requests "discord.py>=2.3"

WORKDIR /app
COPY team_server.py /app/team_server.py

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# timeout=0 disables worker timeout — allows multi-hour builds
# graceful-timeout=7200 gives workers 2hrs to finish before hard kill on redeploy
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "0", "--graceful-timeout", "7200", "--workers", "2", "--threads", "4", "team_server:app"]
