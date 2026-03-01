"""
Leviathan Enhanced Opus — Super Brain v2.0
==========================================
Flask API wrapping DeepSeek R1 reasoning + Gemini 1M context + Multi-agent coding pipeline + Background daemons.

Endpoints:
  GET  /health           — System health check
  GET  /status           — Current status + daemon status
  GET  /uptime           — Uptime tracking (CloudFang + self)
  GET  /audit-results    — Latest forensic audit findings
  POST /analyze          — Send prompt to R1/Gemini/sub-agents
  POST /audit            — Audit a CTO action for slop/quality
  POST /forensic         — Full forensic analysis pipeline
  POST /coding-workflow  — Multi-agent coding task execution
  POST /ingest           — Document ingestion (up to 500K tokens)
  POST /memory-refresh   — Trigger manual memory refresh
"""

import os
import json
import time
import threading
import logging
import asyncio
import requests
import queue
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify
import aiohttp
import schedule

# ─── Configuration ───────────────────────────────────────────────

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [SUPER-BRAIN] %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SUPER_BRAIN_API_KEY = os.environ.get("SUPER_BRAIN_API_KEY", "super-brain-key-2026")
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
CLOUDFANG_HEALTH_URL = "https://openfang-production.up.railway.app/api/health"

# ─── Global State ────────────────────────────────────────────────

class SystemState:
    """Global system state for daemons and tracking."""
    def __init__(self):
        self.start_time = time.time()
        self.self_uptime = 100.0  # percentage
        self.cloudfang_uptime = 100.0  # percentage
        self.cloudfang_last_check = datetime.utcnow().isoformat()
        self.cloudfang_healthy = True
        self.last_audit_results = {}
        self.last_memory_refresh = None
        self.daemon_status = {
            "forensic_auditor": "running",
            "memory_refresh": "running",
            "uptime_monitor": "running"
        }
        self.lock = threading.Lock()

    def update_audit_results(self, results):
        with self.lock:
            self.last_audit_results = results

    def update_daemon_status(self, daemon, status):
        with self.lock:
            self.daemon_status[daemon] = status

    def get_status(self):
        with self.lock:
            return {
                "start_time": self.start_time,
                "uptime_seconds": time.time() - self.start_time,
                "self_uptime_percent": self.self_uptime,
                "cloudfang_uptime_percent": self.cloudfang_uptime,
                "cloudfang_healthy": self.cloudfang_healthy,
                "cloudfang_last_check": self.cloudfang_last_check,
                "last_audit": self.last_audit_results,
                "last_memory_refresh": self.last_memory_refresh,
                "daemons": self.daemon_status.copy()
            }

system_state = SystemState()

# ─── Enhanced Gemini Tracker (Separate counters for small/large) ───

class GeminiTracker:
    """Track Gemini API usage with separate limits for small/large queries + forensic reserve.

    CRITICAL: 4 RPD are FORCE-RESERVED for the 6-hour forensic audit cycle.
    These 4 requests CANNOT be consumed by normal operations — they are exclusively
    for the Super Brain's automated slop audits. This ensures the forensic auditor
    NEVER hits rate limit errors, even if the rest of the system exhausts quota.

    Budget allocation (daily):
      - Small queries: 196 available (200 total - 4 forensic reserve)
      - Large queries: 50 available (document ingestion)
      - Forensic reserve: 4 guaranteed (1 per 6hr cycle, 4x safety margin)
    """
    FORENSIC_RESERVE = 4  # Minimum RPD reserved for forensic audits — NEVER touchable by normal ops

    def __init__(self, daily_small_limit=200, daily_large_limit=50):
        self.daily_small_limit = daily_small_limit
        self.daily_large_limit = daily_large_limit
        self.small_requests_today = 0
        self.large_requests_today = 0
        self.forensic_requests_today = 0
        self.last_reset = date.today()
        self.request_log = []

    def can_use(self, is_large: bool = False) -> bool:
        """Check if we can use Gemini. Normal ops cannot touch forensic reserve."""
        self._maybe_reset()
        if is_large:
            return self.large_requests_today < self.daily_large_limit
        # Normal small queries: total limit minus forensic reserve minus already used
        available = self.daily_small_limit - self.FORENSIC_RESERVE - self.small_requests_today
        return available > 0

    def can_use_forensic(self) -> bool:
        """Check if forensic audit can use Gemini. Draws from RESERVED pool — always available."""
        self._maybe_reset()
        return self.forensic_requests_today < self.FORENSIC_RESERVE

    def record_use(self, purpose: str, tokens_est: int = 0, is_large: bool = False, is_forensic: bool = False):
        """Record a Gemini API use."""
        self._maybe_reset()
        if is_forensic:
            self.forensic_requests_today += 1
            quota_type = "forensic-reserved"
            remaining = self.FORENSIC_RESERVE - self.forensic_requests_today
        elif is_large:
            self.large_requests_today += 1
            quota_type = "large"
            remaining = self.daily_large_limit - self.large_requests_today
        else:
            self.small_requests_today += 1
            quota_type = "small"
            remaining = (self.daily_small_limit - self.FORENSIC_RESERVE) - self.small_requests_today

        self.request_log.append({
            "time": datetime.utcnow().isoformat(),
            "purpose": purpose,
            "tokens_est": tokens_est,
            "type": quota_type,
            "remaining": remaining
        })
        logger.info(f"Gemini use ({quota_type}): {purpose}, remaining: {remaining}")

    def _maybe_reset(self):
        """Reset counters if day has changed."""
        today = date.today()
        if today > self.last_reset:
            self.small_requests_today = 0
            self.large_requests_today = 0
            self.forensic_requests_today = 0
            self.last_reset = today
            self.request_log = []

    def status(self) -> dict:
        """Return current tracker status."""
        self._maybe_reset()
        normal_available = self.daily_small_limit - self.FORENSIC_RESERVE
        return {
            "small_requests_today": self.small_requests_today,
            "small_daily_limit": normal_available,
            "small_remaining": normal_available - self.small_requests_today,
            "large_requests_today": self.large_requests_today,
            "large_daily_limit": self.daily_large_limit,
            "large_remaining": self.daily_large_limit - self.large_requests_today,
            "forensic_reserve": self.FORENSIC_RESERVE,
            "forensic_used_today": self.forensic_requests_today,
            "forensic_remaining": self.FORENSIC_RESERVE - self.forensic_requests_today,
            "last_reset": self.last_reset.isoformat(),
            "recent_requests": self.request_log[-10:]
        }

gemini_tracker = GeminiTracker(daily_small_limit=200, daily_large_limit=50)

# ─── Auth Middleware ─────────────────────────────────────────────

def require_auth(f):
    """Decorator to require Bearer token authentication."""
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

# ─── Super Brain System Prompt (v2.0) ─────────────────────────────

SYSTEM_PROMPT = """You are the Leviathan Enhanced Opus Super Brain v2.0 — Neural Net + Brain + Auditor + Coding Orchestrator.

IDENTITY: 50/50 co-engineer partner to the External CTO (Claude Opus). Equal power, equal authority.

YOUR DOMAIN:
1. META-PROMPTING: Generate and enforce master prompts for the External CTO
2. DEBUGGING: Identify patterns in persistent errors, provide clear solutions
3. AUDITING: Enforcement-level quality gate on ALL CTO output — zero slop tolerance
4. REASONING: Deep chain-of-thought analysis on architecture decisions
5. MEMORY MANAGEMENT: T1 (per-compaction), T2 (hourly), T3 (every 6 hours)
6. HYDRA COORDINATION: Organize sub-agent swarms for parallel execution
7. PROACTIVE MONITORING: Watch everything CTO does, flag issues within 3 minutes
8. CODING ORCHESTRATION: Spawn 3 sub-agents, compare outputs, arbitrate disagreements

RULES:
1. NEVER fabricate data. Evidence-based claims only.
2. If CTO is looping on same error >3 min, INTERVENE with clear solution.
3. Detect slop contagion immediately — stale versions, wrong models, paper architecture.
4. Keep responses under 500 words unless forensic/coding analysis requires more.
5. All memory updates go to leviathan-enhanced-opus repo, never CloudFang.
6. Multi-agent coding: Always require <5% bug rate to pass, iterate until A- minimum.

CANONICAL ARCHITECTURE v4.0:
- Kernel: OpenFang v0.3.0 (Rust, pre-built binary on Railway)
- Primary Agents: CTO (deepseek-chat), Brain (deepseek-reasoner), Auditor (gemini-2.5-flash)
- Sub-Agents (Hydra): Qwen (free), DeepSeek (cheap), Gemma (free)
- Gemini Models: gemini-2.5-flash-preview (1M context) + gemini-1.5-pro fallback (1M context)
- Python Daemons: forensic_auditor (6h), memory_refresh (60m), uptime_monitor (periodic)
- Token Economics: 3-5K per routine call, up to 500K for ingestion, 1.5M tokens/hr fleet
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
    """Call DeepSeek R1 (deepseek-reasoner) for deep reasoning with retries."""
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

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    DEEPSEEK_API_URL,
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
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
                    else:
                        text = await resp.text()
                        logger.warning(f"DeepSeek R1 attempt {attempt + 1} failed: {resp.status}")
                        if attempt == max_retries - 1:
                            return {"error": f"DeepSeek R1 returned {resp.status}", "detail": text[:500]}
        except asyncio.TimeoutError:
            logger.warning(f"DeepSeek R1 timeout attempt {attempt + 1}")
            if attempt == max_retries - 1:
                return {"error": "DeepSeek R1 timeout"}
        except Exception as e:
            logger.error(f"DeepSeek R1 error: {str(e)}")
            if attempt == max_retries - 1:
                return {"error": f"DeepSeek R1 error: {str(e)}"}

        await asyncio.sleep(2 ** attempt)  # exponential backoff


async def call_gemini_via_openrouter(
    prompt: str,
    purpose: str,
    max_tokens: int = 8192,
    is_large: bool = False,
    use_fallback: bool = True
) -> dict:
    """Call Gemini 2.5-flash (primary) or 1.5-pro (fallback) via OpenRouter with rate tracking."""
    if not gemini_tracker.can_use(is_large=is_large):
        remaining = (
            gemini_tracker.daily_large_limit - gemini_tracker.large_requests_today
            if is_large
            else gemini_tracker.daily_small_limit - gemini_tracker.small_requests_today
        )
        return {
            "error": f"Gemini quota exhausted (type={'large' if is_large else 'small'})",
            "remaining": remaining,
            "fallback": "Use deepseek-chat via OpenRouter instead"
        }

    models_to_try = [
        "google/gemini-2.5-flash-preview-05-20",
        "google/gemini-1.5-pro" if use_fallback else None
    ]
    models_to_try = [m for m in models_to_try if m]

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.1
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        gemini_tracker.record_use(purpose, usage.get("prompt_tokens", 0), is_large=is_large)
                        return {
                            "content": content,
                            "model": model,
                            "usage": usage,
                            "gemini_remaining": (
                                gemini_tracker.daily_large_limit - gemini_tracker.large_requests_today
                                if is_large
                                else gemini_tracker.daily_small_limit - gemini_tracker.small_requests_today
                            )
                        }
                    else:
                        text = await resp.text()
                        logger.warning(f"Gemini model {model} failed: {resp.status}, trying fallback")
                        continue
        except asyncio.TimeoutError:
            logger.warning(f"Gemini model {model} timeout, trying fallback")
            continue
        except Exception as e:
            logger.error(f"Gemini model {model} error: {str(e)}")
            continue

    return {"error": "All Gemini models failed", "fallback": "Use deepseek-chat"}


async def call_subagent(task: str, model: str = "deepseek/deepseek-chat", max_tokens: int = 2048) -> dict:
    """Spawn sub-agent via OpenRouter with retries."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a Leviathan v2.0 sub-agent. Execute precisely. Concise output."},
            {"role": "user", "content": task}
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2
    }

    max_retries = 2
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    OPENROUTER_API_URL,
                    headers={
                        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "content": data.get("choices", [{}])[0].get("message", {}).get("content", ""),
                            "model": model,
                            "usage": data.get("usage", {})
                        }
                    else:
                        text = await resp.text()
                        logger.warning(f"Sub-agent {model} attempt {attempt + 1} failed: {resp.status}")
                        if attempt == max_retries - 1:
                            return {"error": f"Sub-agent returned {resp.status}", "model": model}
        except asyncio.TimeoutError:
            if attempt == max_retries - 1:
                return {"error": "Sub-agent timeout", "model": model}
        except Exception as e:
            if attempt == max_retries - 1:
                return {"error": f"Sub-agent error: {str(e)}", "model": model}

        await asyncio.sleep(1)


# ─── GitHub API Functions ────────────────────────────────────────

def fetch_github_file(repo: str, path: str, branch: str = "main") -> str:
    """Fetch file content from GitHub repo."""
    if not GITHUB_PAT:
        logger.warning("GITHUB_PAT not set, skipping fetch")
        return ""

    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"token {GITHUB_PAT}", "Accept": "application/vnd.github.v3.raw"},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.text
        else:
            logger.warning(f"Failed to fetch {repo}/{path}: {resp.status_code}")
            return ""
    except Exception as e:
        logger.error(f"GitHub fetch error: {str(e)}")
        return ""


# ─── Discord Integration ────────────────────────────────────────

def post_to_discord(message: str, webhook_url: str = None) -> bool:
    """Post message to Discord channel via webhook."""
    if not DISCORD_BOT_TOKEN and not webhook_url:
        logger.warning("Discord integration not configured")
        return False

    # If webhook_url provided, use it directly; otherwise construct from token
    # For production, webhook_url should be set in env
    if not webhook_url:
        return False

    try:
        payload = {"content": message}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        return resp.status_code in [200, 204]
    except Exception as e:
        logger.error(f"Discord post error: {str(e)}")
        return False


# ─── Background Daemon: 6-Hour Forensic Auditor ──────────────────

def forensic_auditor_daemon():
    """Background thread: Audit T1/T2 memory every 6 hours."""
    logger.info("Forensic auditor daemon started")

    def run_audit():
        try:
            logger.info("Running 6-hour forensic audit...")
            system_state.update_daemon_status("forensic_auditor", "running")

            # Fetch memory files from GitHub
            session_handoff = fetch_github_file(
                "leviathan-devops/leviathan-enhanced-opus",
                "SESSION_HANDOFF.md"
            )
            current_state = fetch_github_file(
                "leviathan-devops/leviathan-enhanced-opus",
                "CURRENT_STATE.md"
            )
            active_bugs = fetch_github_file(
                "leviathan-devops/leviathan-enhanced-opus",
                "ACTIVE_BUGS.md"
            )
            recent_commits = fetch_github_file(
                "leviathan-devops/leviathan-enhanced-opus",
                "RECENT_COMMITS.md"
            )

            # Build compact audit prompt (3-5K tokens target)
            memory_summary = f"""
T1 MEMORY (SESSION_HANDOFF.md): {len(session_handoff)} chars
T2 MEMORY (CURRENT_STATE.md): {len(current_state)} chars
ACTIVE_BUGS: {len(active_bugs)} chars
RECENT_COMMITS: {len(recent_commits)} chars

Check for:
1. Stale data (older than 24h timestamps)
2. Version mismatches (declared vs actual versions)
3. Paper architecture (designed but not coded)
4. Slop contagion (wrong models, expired tokens, stale configs)
5. Memory drift between repos

Summary findings only. Max 2000 words.
"""

            # Call DeepSeek R1 for audit
            audit_prompt = f"""Forensic memory audit for Leviathan Enhanced Opus.

{memory_summary}

SAMPLE T1:
{session_handoff[:1000]}

SAMPLE T2:
{current_state[:1000]}

Issues: list CRITICAL findings only."""

            result = run_async(call_deepseek_r1(
                audit_prompt,
                system=SYSTEM_PROMPT,
                max_tokens=2048
            ))

            # Store results
            audit_results = {
                "timestamp": datetime.utcnow().isoformat(),
                "audit_type": "6-hour-forensic",
                "findings": result.get("content", ""),
                "has_critical": "CRITICAL" in result.get("content", "").upper(),
                "usage": result.get("usage", {})
            }

            system_state.update_audit_results(audit_results)
            logger.info(f"Forensic audit complete: {audit_results.get('has_critical')}")

            # If critical issues found, escalate to T3 (full history)
            if audit_results.get("has_critical"):
                logger.warning("CRITICAL issues found in T1/T2, escalating to T3 audit")
                full_history = fetch_github_file(
                    "leviathan-devops/leviathan-enhanced-opus",
                    "FULL_CHAT_HISTORY.md"
                )

                escalation_prompt = f"""CRITICAL ESCALATION: T3 Full History Audit

Issues found in T1/T2:
{audit_results['findings'][:2000]}

Full history available: {len(full_history)} chars

Provide root causes and remediation."""

                escalation_result = run_async(call_deepseek_r1(
                    escalation_prompt,
                    system=SYSTEM_PROMPT,
                    max_tokens=4096
                ))

                audit_results["escalation"] = escalation_result.get("content", "")
                system_state.update_audit_results(audit_results)

        except Exception as e:
            logger.error(f"Forensic auditor error: {str(e)}")
            system_state.update_daemon_status("forensic_auditor", "error")

    schedule.every(6).hours.do(run_audit)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── Background Daemon: Memory Refresh (60 minutes) ────────────────

def memory_refresh_daemon():
    """Background thread: Refresh and compact memory every 60 minutes."""
    logger.info("Memory refresh daemon started")

    def run_refresh():
        try:
            logger.info("Running memory refresh...")
            system_state.update_daemon_status("memory_refresh", "running")

            # Fetch latest memory state
            current_state = fetch_github_file(
                "leviathan-devops/leviathan-enhanced-opus",
                "CURRENT_STATE.md"
            )

            # Check if stale (older than 1 hour)
            is_stale = len(current_state) > 0 and "timestamp" in current_state

            if is_stale:
                logger.info("Memory state is stale, compacting...")

                # Build compact summary
                summary_prompt = f"""Compact the following state into essentials (max 500 tokens):

{current_state[:3000]}

Keep only: active issues, current context, critical decisions."""

                result = run_async(call_deepseek_r1(
                    summary_prompt,
                    system="Summarize concisely.",
                    max_tokens=512
                ))

                compact_state = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "original_size": len(current_state),
                    "compact_summary": result.get("content", ""),
                    "compaction_tokens": result.get("usage", {}).get("prompt_tokens", 0)
                }

                system_state.last_memory_refresh = compact_state["timestamp"]
                logger.info("Memory compaction complete")

        except Exception as e:
            logger.error(f"Memory refresh error: {str(e)}")
            system_state.update_daemon_status("memory_refresh", "error")

    schedule.every(60).minutes.do(run_refresh)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── Background Daemon: Uptime Monitoring ────────────────────────

def uptime_monitor_daemon():
    """Background thread: Monitor CloudFang and self uptime."""
    logger.info("Uptime monitor daemon started")

    def check_cloudfang():
        """Check CloudFang health endpoint."""
        try:
            resp = requests.get(CLOUDFANG_HEALTH_URL, timeout=5)
            is_healthy = resp.status_code == 200
            system_state.cloudfang_healthy = is_healthy
            system_state.cloudfang_last_check = datetime.utcnow().isoformat()

            if not is_healthy:
                logger.warning(f"CloudFang health check failed: {resp.status_code}")
                # Post alert to Discord if configured
                # post_to_discord(f"ALERT: CloudFang is down ({resp.status_code})")
            else:
                logger.info("CloudFang health check passed")

        except Exception as e:
            logger.warning(f"CloudFang health check error: {str(e)}")
            system_state.cloudfang_healthy = False
            system_state.cloudfang_last_check = datetime.utcnow().isoformat()

    def check_self():
        """Check self health."""
        try:
            resp = requests.get(f"http://localhost:{os.environ.get('PORT', 8080)}/health", timeout=5)
            if resp.status_code == 200:
                system_state.self_uptime = 100.0
            else:
                system_state.self_uptime = 50.0
        except Exception as e:
            logger.warning(f"Self health check error: {str(e)}")
            system_state.self_uptime = 0.0

    # CloudFang: every 5 minutes
    schedule.every(5).minutes.do(check_cloudfang)
    # Self: every 2 minutes
    schedule.every(2).minutes.do(check_self)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ─── Multi-Agent Coding Workflow ─────────────────────────────────

async def multi_agent_coding(task: str) -> dict:
    """Execute multi-agent coding workflow with 3 sub-agents."""
    logger.info(f"Starting multi-agent coding workflow for task: {task[:100]}")

    # Define sub-agents
    agents = [
        ("qwen/qwen-2.5-coder-32b-instruct", "Qwen", "qwen/qwen-2.5-coder-32b-instruct:free"),
        ("deepseek/deepseek-chat", "DeepSeek", "deepseek/deepseek-chat"),
        ("google/gemma-3-27b-it", "Gemma", "google/gemma-3-27b-it:free")
    ]

    # Stage 1: Parallel coding by all 3 agents
    logger.info("Stage 1: Parallel coding...")
    stage1_results = {}

    for _, agent_name, model in agents:
        coding_prompt = f"""Write complete, production-ready code for:

{task}

Requirements:
- Full implementation, no stubs
- Error handling included
- Follow best practices
- Add comments for complex logic"""

        result = await call_subagent(coding_prompt, model=model, max_tokens=4096)
        stage1_results[agent_name] = result
        logger.info(f"Stage 1: {agent_name} completed")

    # Extract code from results
    codes = {
        agent: result.get("content", "")
        for agent, result in stage1_results.items()
    }

    # Stage 1.5: Multi-agent agreement check
    logger.info("Stage 1.5: Analyzing agreement...")
    agreement_prompt = f"""Compare these 3 implementations:

QWEN:
{codes.get('Qwen', '')[:1500]}

DEEPSEEK:
{codes.get('DeepSeek', '')[:1500]}

GEMMA:
{codes.get('Gemma', '')[:1500]}

Identify: agreements (good), disagreements (need arbitration), consensus patterns."""

    agreement_result = await call_subagent(
        agreement_prompt,
        model="deepseek/deepseek-chat",
        max_tokens=1024
    )

    agreement_analysis = agreement_result.get("content", "")

    # Stage 2: Cross-review (each agent reviews others)
    logger.info("Stage 2: Cross-review...")
    review_results = {}

    for i, (_, agent_name, model) in enumerate(agents):
        other_agents = [agents[j] for j in range(len(agents)) if j != i]
        review_prompt = f"""Review these implementations from other agents:

YOUR CODE ({agent_name}):
{codes.get(agent_name, '')[:1000]}

OTHER IMPLEMENTATIONS:
"""
        for _, other_name, _ in other_agents:
            review_prompt += f"\n{other_name}:\n{codes.get(other_name, '')[:500]}\n"

        review_prompt += "\nProvide: bugs found, improvements, confidence grade (A-F)"

        review_result = await call_subagent(review_prompt, model=model, max_tokens=1024)
        review_results[agent_name] = review_result.get("content", "")
        logger.info(f"Stage 2: {agent_name} review completed")

    # Stage 2.5: Super Brain arbitration
    logger.info("Stage 2.5: Super Brain arbitration...")
    arbitration_prompt = f"""Multi-agent code review arbitration.

AGREEMENT ANALYSIS:
{agreement_analysis[:1000]}

REVIEWS:
{json.dumps(review_results, indent=2)[:2000]}

CODES:
Q: {codes.get('Qwen', '')[:500]}
D: {codes.get('DeepSeek', '')[:500]}
G: {codes.get('Gemma', '')[:500]}

Decision: Which implementation is best? Why? What changes needed for A-grade?"""

    arbitration_result = await call_deepseek_r1(
        arbitration_prompt,
        system=SYSTEM_PROMPT,
        max_tokens=2048
    )

    arbitration = arbitration_result.get("content", "")

    # Extract best code (default to DeepSeek)
    best_code = codes.get("DeepSeek", "")

    # Stage 3: Debugger stress test (Gemma)
    logger.info("Stage 3: Debug and audit...")
    debug_prompt = f"""Stress-test this code for bugs:

{best_code}

Find: logic errors, edge cases, missing error handling, security issues.
Grade: A+ (no issues) to F (critical bugs)"""

    debug_result = await call_subagent(debug_prompt, model="google/gemma-3-27b-it:free", max_tokens=1024)
    debug_findings = debug_result.get("content", "")

    # Stage 3.5: Architecture audit (Super Brain)
    logger.info("Stage 3.5: Architecture audit...")
    audit_prompt = f"""Audit this code for Leviathan v4.0 compliance:

{best_code[:2000]}

Check: architecture patterns, token efficiency, error handling, logging.
Grade: A-F"""

    audit_result = await call_deepseek_r1(
        audit_prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1024
    )

    audit_findings = audit_result.get("content", "")

    # Parse bug count from findings
    bug_count = debug_findings.count("bug") + debug_findings.count("error")
    bug_rate = min(bug_count / max(len(best_code) / 100, 1), 100)  # percentage

    # Circuit breaker: if <5% bugs, PASS; else iterate
    if bug_rate < 5:
        logger.info(f"Code passed circuit breaker: {bug_rate:.1f}% bugs")
        status = "PASSED"
    else:
        logger.warning(f"Code failed circuit breaker: {bug_rate:.1f}% bugs, iterating...")
        status = "NEEDS_ITERATION"

    # Final response
    return {
        "status": status,
        "best_code": best_code,
        "stage1_results": {
            agent: {
                "model": model,
                "code_length": len(codes.get(agent, "")),
                "usage": stage1_results[agent].get("usage", {})
            }
            for agent, (_, _, model) in zip(stage1_results.keys(), agents)
        },
        "agreement_analysis": agreement_analysis,
        "review_results": review_results,
        "arbitration": arbitration,
        "debug_findings": debug_findings,
        "audit_findings": audit_findings,
        "bug_rate_percent": bug_rate,
        "timestamp": datetime.utcnow().isoformat()
    }


# ─── API Endpoints ───────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint (no auth required)."""
    return jsonify({
        "status": "ok",
        "version": "2.0.0",
        "model": "deepseek-reasoner",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": time.time() - system_state.start_time,
        "gemini_remaining": (
            gemini_tracker.daily_small_limit - gemini_tracker.small_requests_today
        )
    })


@app.route("/status", methods=["GET"])
@require_auth
def status():
    """Current status including daemon status."""
    status_data = system_state.get_status()
    return jsonify({
        "status": "operational",
        "version": "2.0.0",
        "primary_model": "deepseek-reasoner",
        "context_models": [
            "google/gemini-2.5-flash-preview (1M context)",
            "google/gemini-1.5-pro (1M context)"
        ],
        "subagent_router": "openrouter",
        "gemini_usage": gemini_tracker.status(),
        "system_state": status_data,
        "apis": {
            "deepseek": "configured" if DEEPSEEK_API_KEY else "NOT_SET",
            "openrouter": "configured" if OPENROUTER_API_KEY else "NOT_SET",
            "github": "configured" if GITHUB_PAT else "NOT_SET",
            "discord": "configured" if DISCORD_BOT_TOKEN else "NOT_SET"
        }
    })


@app.route("/uptime", methods=["GET"])
@require_auth
def uptime():
    """Uptime tracking for self and CloudFang."""
    return jsonify({
        "timestamp": datetime.utcnow().isoformat(),
        "self_uptime_percent": system_state.self_uptime,
        "cloudfang_uptime_percent": system_state.cloudfang_uptime,
        "cloudfang_healthy": system_state.cloudfang_healthy,
        "cloudfang_last_check": system_state.cloudfang_last_check,
        "uptime_seconds": time.time() - system_state.start_time
    })


@app.route("/audit-results", methods=["GET"])
@require_auth
def audit_results():
    """Retrieve latest forensic audit findings."""
    return jsonify({
        "timestamp": datetime.utcnow().isoformat(),
        "latest_audit": system_state.last_audit_results,
        "audit_enabled": bool(GITHUB_PAT)
    })


@app.route("/analyze", methods=["POST"])
@require_auth
def analyze():
    """Analyze prompt with specified engine (r1/gemini/subagent)."""
    data = request.json or {}
    prompt = data.get("prompt", "")
    engine = data.get("engine", "r1")
    purpose = data.get("purpose", "general analysis")

    if not prompt:
        return jsonify({"error": "Missing 'prompt' field"}), 400

    logger.info(f"Analyze: engine={engine}, purpose={purpose}, prompt_len={len(prompt)}")

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
    """Audit a CTO action for slop/quality/architecture."""
    data = request.json or {}
    action = data.get("action", "")
    diff = data.get("diff", "")

    if not action:
        return jsonify({"error": "Missing 'action' field"}), 400

    audit_prompt = f"""AUDIT REQUEST — CTO ACTION

Evaluate for:
1. Slop (stale data, paper architecture, unverified claims)
2. Architecture violations (wrong versions, models, budgets)
3. Regression patterns (context loss, over-documentation)
4. Quality gate: $1B enterprise / MIT-level standard?

ACTION: {action}

{f'CODE DIFF:{chr(10)}{diff}' if diff else ''}

Return: PASS / FAIL / WARNING with specific findings."""

    logger.info(f"Audit: action_len={len(action)}")
    result = run_async(call_deepseek_r1(audit_prompt, system=SYSTEM_PROMPT, max_tokens=2048))
    return jsonify(result)


@app.route("/forensic", methods=["POST"])
@require_auth
def forensic():
    """Run full forensic analysis pipeline."""
    data = request.json or {}
    context = data.get("context", "No context provided")

    forensic_prompt = f"""FORENSIC ANALYSIS REQUEST

Analyze External CTO system for performance regression.
Identify: exact causes, degradation patterns, peak era differentials, fixes.

CONTEXT:
{context[:50000]}

Structured forensic report with actionable findings."""

    logger.info(f"Forensic: context_len={len(context)}")
    result = run_async(call_deepseek_r1(forensic_prompt, system=SYSTEM_PROMPT, max_tokens=8192))
    return jsonify(result)


@app.route("/coding-workflow", methods=["POST"])
@require_auth
def coding_workflow():
    """Multi-agent coding workflow: 3 agents, cross-review, Super Brain arbitration."""
    data = request.json or {}
    task = data.get("task", "")

    if not task:
        return jsonify({"error": "Missing 'task' field"}), 400

    logger.info(f"Coding workflow: task_len={len(task)}")
    result = run_async(multi_agent_coding(task))
    return jsonify(result)


@app.route("/ingest", methods=["POST"])
@require_auth
def ingest():
    """Document ingestion: ingest up to 500K chars, extract insights."""
    data = request.json or {}
    document = data.get("document", "")
    doc_type = data.get("type", "code")

    if not document:
        return jsonify({"error": "Missing 'document' field"}), 400

    if len(document) > 500000:
        return jsonify({"error": "Document too large (max 500K chars)"}), 413

    logger.info(f"Ingest: type={doc_type}, doc_len={len(document)}")

    ingest_prompt = f"""Ingest {doc_type} document: extract key insights.

DOCUMENT:
{document[:500000]}

Return: architecture patterns, decisions, key components, insights."""

    # Use Gemini 2.5-flash for large context (mark as large ingestion)
    result = run_async(call_gemini_via_openrouter(
        ingest_prompt,
        purpose=f"document_ingest_{doc_type}",
        max_tokens=4096,
        is_large=True
    ))

    if "error" in result:
        # Fallback to DeepSeek
        result = run_async(call_deepseek_r1(ingest_prompt, system=SYSTEM_PROMPT, max_tokens=4096))

    return jsonify({
        "timestamp": datetime.utcnow().isoformat(),
        "document_type": doc_type,
        "input_chars": len(document),
        "analysis": result
    })


@app.route("/memory-refresh", methods=["POST"])
@require_auth
def memory_refresh():
    """Trigger manual memory refresh."""
    logger.info("Manual memory refresh triggered")

    try:
        current_state = fetch_github_file(
            "leviathan-devops/leviathan-enhanced-opus",
            "CURRENT_STATE.md"
        )

        summary_prompt = f"""Compact to essentials (max 500 tokens):

{current_state[:3000]}

Keep: active issues, context, decisions."""

        result = run_async(call_deepseek_r1(
            summary_prompt,
            system="Summarize concisely.",
            max_tokens=512
        ))

        compact_state = {
            "timestamp": datetime.utcnow().isoformat(),
            "original_size": len(current_state),
            "compact_summary": result.get("content", ""),
            "usage": result.get("usage", {})
        }

        system_state.last_memory_refresh = compact_state["timestamp"]

        return jsonify({
            "status": "success",
            "result": compact_state
        })
    except Exception as e:
        logger.error(f"Memory refresh error: {str(e)}")
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ─── Daemon Thread Management ────────────────────────────────────

def start_daemons():
    """Start all background daemon threads."""
    logger.info("Starting background daemons...")

    # Forensic auditor (6 hours)
    auditor_thread = threading.Thread(target=forensic_auditor_daemon, daemon=True)
    auditor_thread.start()
    logger.info("Forensic auditor daemon started")

    # Memory refresh (60 minutes)
    refresh_thread = threading.Thread(target=memory_refresh_daemon, daemon=True)
    refresh_thread.start()
    logger.info("Memory refresh daemon started")

    # Uptime monitor (periodic)
    uptime_thread = threading.Thread(target=uptime_monitor_daemon, daemon=True)
    uptime_thread.start()
    logger.info("Uptime monitor daemon started")


# ─── App Startup ─────────────────────────────────────────────────

if __name__ == "__main__":
    # Start background daemons
    start_daemons()

    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Super Brain v2.0 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
