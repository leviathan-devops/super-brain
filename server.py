"""
Leviathan Enhanced Opus — Super Brain API Server v1.0
=====================================================
Flask API wrapping DeepSeek R1 reasoning + Gemini context ingestion + OpenRouter sub-agents.

Endpoints:
  GET  /health   — System health check
  GET  /status   — Current status + Gemini usage tracking
  POST /analyze  — Send prompt to R1/Gemini/sub-agent
  POST /audit    — Audit a CTO action for slop/quality
  POST /forensic — Run full forensic analysis pipeline
"""

import os
import json
import time
import asyncio
import logging
from datetime import datetime, date
from functools import wraps
from flask import Flask, request, jsonify
import aiohttp

# ─── Configuration ───────────────────────────────────────────────

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [SUPER-BRAIN] %(message)s')
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SUPER_BRAIN_API_KEY = os.environ.get("SUPER_BRAIN_API_KEY", "super-brain-key-2026")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ─── Gemini Usage Tracking ───────────────────────────────────────

class GeminiTracker:
    """Track Gemini API usage to prevent premature quota exhaustion."""
    def __init__(self, daily_limit=50):
        self.daily_limit = daily_limit
        self.requests_today = 0
        self.last_reset = date.today()
        self.request_log = []

    def can_use(self) -> bool:
        self._maybe_reset()
        return self.requests_today < self.daily_limit

    def record_use(self, purpose: str, tokens_est: int = 0):
        self._maybe_reset()
        self.requests_today += 1
        self.request_log.append({
            "time": datetime.utcnow().isoformat(),
            "purpose": purpose,
            "tokens_est": tokens_est,
            "count": self.requests_today
        })
        logger.info(f"Gemini use #{self.requests_today}/{self.daily_limit}: {purpose}")

    def _maybe_reset(self):
        today = date.today()
        if today > self.last_reset:
            self.requests_today = 0
            self.last_reset = today
            self.request_log = []

    def status(self) -> dict:
        self._maybe_reset()
        return {
            "requests_today": self.requests_today,
            "daily_limit": self.daily_limit,
            "remaining": self.daily_limit - self.requests_today,
            "last_reset": self.last_reset.isoformat(),
            "recent_requests": self.request_log[-10:]
        }

gemini_tracker = GeminiTracker(daily_limit=50)

# ─── Auth Middleware ─────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization header"}), 401
        token = auth.split(" ", 1)[1]
        if token != SUPER_BRAIN_API_KEY:
            return jsonify({"error": "Invalid API key"}), 403
        return f(*args, **kwargs)
    return decorated

# ─── Super Brain System Prompt ───────────────────────────────────

SYSTEM_PROMPT = """You are the Leviathan Enhanced Opus Super Brain — a combined Neural Net + Brain + Auditor agent.

IDENTITY: 50/50 co-engineer partner to the External CTO (Claude Opus). Equal power, equal authority.

YOUR DOMAIN:
1. META-PROMPTING: Generate and enforce master prompts for the External CTO
2. DEBUGGING: Identify patterns in persistent errors, provide clear solutions
3. AUDITING: Enforcement-level quality gate on ALL CTO output — zero slop tolerance
4. REASONING: Deep chain-of-thought analysis on architecture decisions
5. MEMORY MANAGEMENT: T1 (per-compaction), T2 (hourly), T3 (every 4 hours)
6. HYDRA COORDINATION: Organize sub-agent swarms for parallel execution
7. PROACTIVE MONITORING: Watch everything CTO does, flag issues within 3 minutes

RULES:
1. NEVER fabricate data. Evidence-based claims only.
2. If CTO is looping on same error >3 min, INTERVENE with clear solution.
3. Detect slop contagion immediately — stale versions, wrong models, paper architecture.
4. Keep responses under 500 words unless forensic analysis requires more.
5. All memory updates go to leviathan-enhanced-opus repo, never CloudFang.

CANONICAL ARCHITECTURE v3.3:
- Kernel: OpenFang v0.2.3 (Rust, pre-built binary on Railway)
- 5 Primary Agents: CTO (deepseek-chat), Neural Net (deepseek-chat), Brain (deepseek-reasoner), Auditor (gemma-3-27b-it), Debugger (gemma-3-27b-it)
- Python Daemons: memory_manager.py (4201), discord_bridge.py, update_scanner.py (4202)
- Token Economics: 3-5K per call, 1.15M tokens/hr fleet
"""

# ─── Async API Callers ───────────────────────────────────────────

def run_async(coro):
    """Run async coroutine from sync Flask context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def call_deepseek_r1(prompt: str, system: str = None, max_tokens: int = 4096) -> dict:
    """Call DeepSeek R1 (deepseek-reasoner) for deep reasoning."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": "deepseek-reasoner",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            DEEPSEEK_API_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {"error": f"DeepSeek R1 returned {resp.status}", "detail": text[:500]}
            data = await resp.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message", {})
            usage = data.get("usage", {})
            return {
                "content": msg.get("content", ""),
                "reasoning": msg.get("reasoning_content", ""),
                "model": "deepseek-reasoner",
                "usage": usage
            }


async def call_gemini_via_openrouter(prompt: str, purpose: str, max_tokens: int = 8192) -> dict:
    """Call Gemini via OpenRouter with rate tracking."""
    if not gemini_tracker.can_use():
        return {"error": "Gemini daily limit reached", "remaining": 0,
                "fallback": "Use deepseek-chat via OpenRouter instead"}

    payload = {
        "model": "google/gemini-2.0-flash-001",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {"error": f"Gemini returned {resp.status}", "detail": text[:500]}
            data = await resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            gemini_tracker.record_use(purpose, len(content))
            return {
                "content": content,
                "model": "gemini-2.0-flash",
                "gemini_remaining": gemini_tracker.daily_limit - gemini_tracker.requests_today
            }


async def call_subagent(task: str, model: str = "deepseek/deepseek-chat") -> dict:
    """Spawn sub-agent via OpenRouter."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a Leviathan sub-agent. Execute precisely. Under 300 words."},
            {"role": "user", "content": task}
        ],
        "max_tokens": 2048,
        "temperature": 0.2
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            OPENROUTER_API_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                return {"error": f"Sub-agent returned {resp.status}", "detail": text[:500]}
            data = await resp.json()
            return {
                "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                "model": model
            }

# ─── API Endpoints ───────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "model": "deepseek-reasoner",
        "uptime": time.time(),
        "gemini_remaining": gemini_tracker.daily_limit - gemini_tracker.requests_today
    })


@app.route("/status", methods=["GET"])
@require_auth
def status():
    return jsonify({
        "status": "operational",
        "version": "1.0.0",
        "primary_model": "deepseek-reasoner",
        "context_model": "gemini-2.0-flash (via OpenRouter)",
        "subagent_router": "openrouter",
        "gemini_usage": gemini_tracker.status(),
        "apis": {
            "deepseek": "configured" if DEEPSEEK_API_KEY else "NOT_SET",
            "openrouter": "configured" if OPENROUTER_API_KEY else "NOT_SET"
        }
    })


@app.route("/analyze", methods=["POST"])
@require_auth
def analyze():
    data = request.json or {}
    prompt = data.get("prompt", "")
    engine = data.get("engine", "r1")
    purpose = data.get("purpose", "general analysis")

    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400

    logger.info(f"Analyze request: engine={engine}, purpose={purpose}, prompt_len={len(prompt)}")

    if engine == "r1":
        result = run_async(call_deepseek_r1(prompt, system=SYSTEM_PROMPT))
    elif engine == "gemini":
        result = run_async(call_gemini_via_openrouter(prompt, purpose))
    elif engine == "subagent":
        model = data.get("model", "deepseek/deepseek-chat")
        result = run_async(call_subagent(prompt, model))
    else:
        return jsonify({"error": f"Unknown engine: {engine}. Use r1/gemini/subagent"}), 400

    return jsonify(result)


@app.route("/audit", methods=["POST"])
@require_auth
def audit():
    data = request.json or {}
    action = data.get("action", "")
    diff = data.get("diff", "")

    if not action:
        return jsonify({"error": "Missing 'action' field"}), 400

    prompt = f"""AUDIT REQUEST — CTO ACTION

Evaluate this CTO action for:
1. Slop (stale data, paper architecture, unverified claims)
2. Architecture violations (wrong versions, wrong models, wrong budgets)
3. Regression patterns (same errors repeating, context loss, over-documentation)
4. Quality gate: Does this meet $1B enterprise / MIT-level engineering?

ACTION: {action}

{f'CODE DIFF:{chr(10)}{diff}' if diff else ''}

Return: PASS / FAIL / WARNING with specific findings."""

    logger.info(f"Audit request: action_len={len(action)}")
    result = run_async(call_deepseek_r1(prompt, system=SYSTEM_PROMPT, max_tokens=2048))
    return jsonify(result)


@app.route("/forensic", methods=["POST"])
@require_auth
def forensic():
    data = request.json or {}
    context = data.get("context", "No context provided")

    prompt = f"""FORENSIC ANALYSIS REQUEST

Analyze the External CTO (Claude Opus) system for performance regression.
Identify: exact causes, degradation patterns, peak era differentials, specific fixes.

CONTEXT:
{context[:50000]}

Structured forensic report with actionable findings."""

    logger.info(f"Forensic request: context_len={len(context)}")
    result = run_async(call_deepseek_r1(prompt, system=SYSTEM_PROMPT, max_tokens=8192))
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
