# Leviathan Super Brain Dev Team v5.5 — Hydra Execution + Persistent Memory
# Fast path: Generals (DeepSeek V3) handles directly
# Build path: Brain→Emperor→Generals×2→Auditor×2→Brain(verify)→Bridge
# Memory: SQLite WAL + per-agent logs + shared brain files
FROM python:3.11-slim

RUN pip install --no-cache-dir flask gunicorn requests "discord.py>=2.3"

WORKDIR /app
COPY team_server.py /app/team_server.py

# Persistent memory directory — mount a Railway volume here for cross-deploy persistence
RUN mkdir -p /data/hydra-memory/agents /data/hydra-memory/shared-brain

ENV PYTHONUNBUFFERED=1
ENV HYDRA_MEMORY_DIR=/data/hydra-memory

EXPOSE 8080

# timeout=0 disables worker timeout — allows multi-hour builds
# graceful-timeout=7200 gives workers 2hrs to finish before hard kill on redeploy
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "0", "--graceful-timeout", "7200", "--workers", "2", "--threads", "4", "team_server:app"]
