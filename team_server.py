#!/usr/bin/env python3
"""
Leviathan Super Brain Dev Team v5.0 — STAGED PIPELINE
=====================================================
Sequential multi-stage workflow. Each model has ONE job. No wasted calls.

BUILD PIPELINE (full staged workflow for software creation):
  Stage 1: Gemma receives input (FREE)
  Stage 2: Opus designs architecture → DeepSeek validates/improves → Opus finalizes
  Stage 3: Grok rapid-prototypes from architecture blueprints
  Stage 4: Codex production-hardens the prototype
  Stage 5: Opus final review (can invoke DeepSeek if needed)
  Stage 6: Gemma presents to user (FREE)

LIGHTWEIGHT PATHS (skip the full pipeline):
  Chat        → Gemma only (FREE)
  Research    → DeepSeek only (cheapest paid)
  Debug       → Grok only (2M context)
  Quick code  → Grok only (rapid prototype, no production hardening needed)
"""

import os
import json
import time
import re
import logging
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import requests
from flask import Flask, render_template_string, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s [BRAIN] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ─── Token Budget Management ─────────────────────────────────
# Prevents runaway credit burn. Tracks cumulative spend per build and per day.

class TokenBudget:
    """Thread-safe token + cost tracker. Prevents runaway builds."""

    # Cost per million tokens (approximate, from provider pricing)
    COST_PER_M = {
        'deepseek-chat': {'input': 0.27, 'output': 1.10},
        'deepseek-reasoner': {'input': 0.55, 'output': 2.19},
        'claude-opus-4-6': {'input': 15.00, 'output': 75.00},
        'grok-4-1-fast-reasoning': {'input': 3.00, 'output': 15.00},
        'gpt-5.3-codex': {'input': 2.00, 'output': 8.00},
        'google/gemma-3-27b-it': {'input': 0.00, 'output': 0.00},  # FREE
    }

    def __init__(self, daily_cap_usd=20.0, build_cap_usd=15.0):
        self.daily_cap = daily_cap_usd
        self.build_cap = build_cap_usd
        self.lock = threading.Lock()
        self.daily_spend = 0.0
        self.daily_reset_date = datetime.now().date()
        self.current_build_spend = 0.0
        self.total_tokens = {'input': 0, 'output': 0}

    def estimate_cost(self, model, input_tokens, output_tokens):
        """Estimate USD cost for a call."""
        rates = self.COST_PER_M.get(model, {'input': 1.0, 'output': 3.0})
        return (input_tokens * rates['input'] + output_tokens * rates['output']) / 1_000_000

    def record(self, model, input_tokens, output_tokens):
        """Record token usage. Returns estimated cost."""
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        with self.lock:
            today = datetime.now().date()
            if today != self.daily_reset_date:
                self.daily_spend = 0.0
                self.daily_reset_date = today
            self.daily_spend += cost
            self.current_build_spend += cost
            self.total_tokens['input'] += input_tokens
            self.total_tokens['output'] += output_tokens
        return cost

    def can_proceed(self):
        """Check if we're within budget."""
        with self.lock:
            today = datetime.now().date()
            if today != self.daily_reset_date:
                self.daily_spend = 0.0
                self.daily_reset_date = today
            return self.daily_spend < self.daily_cap and self.current_build_spend < self.build_cap

    def reset_build(self):
        """Reset build-level spend counter for a new build."""
        with self.lock:
            self.current_build_spend = 0.0

    def status(self):
        with self.lock:
            return {
                'daily_spend_usd': round(self.daily_spend, 4),
                'daily_cap_usd': self.daily_cap,
                'build_spend_usd': round(self.current_build_spend, 4),
                'build_cap_usd': self.build_cap,
                'total_tokens': self.total_tokens.copy(),
                'budget_ok': self.daily_spend < self.daily_cap,
            }

# Budget: $25/model × 5 models = $125 total. Cap conservatively.
# Build cap = $100 (one mega-build). Daily cap = $100.
# Adjustable via Railway env vars if needed.
budget = TokenBudget(
    daily_cap_usd=float(os.environ.get('DAILY_BUDGET_USD', '100.0')),
    build_cap_usd=float(os.environ.get('BUILD_BUDGET_USD', '100.0')),
)

# ─── API Configuration ────────────────────────────────────────

API_KEYS = {
    'anthropic': os.environ.get('ANTHROPIC_API_KEY', ''),
    'openai': os.environ.get('OPENAI_API_KEY', ''),
    'deepseek': os.environ.get('DEEPSEEK_API_KEY', ''),
    'xai': os.environ.get('XAI_API_KEY', ''),
    'openrouter': os.environ.get('OPENROUTER_API_KEY', ''),
}

# ─── Model Definitions ────────────────────────────────────────

MODELS = {
    'gemma': {
        'name': 'Gemma 3 27B',
        'role': 'Chat Bridge + Synthesis (FREE I/O)',
        'provider': 'openrouter',
        'model': 'google/gemma-3-27b-it',
        'max_tokens': 1000,
        'cost': 'free',
    },
    'grok': {
        'name': 'Grok 4.1 Reasoning',
        'role': 'Lead Engineer + Debugger + Reviewer (2M context)',
        'provider': 'xai',
        'model': 'grok-4-1-fast-reasoning',
        'max_tokens': 16384,
        'cost': 'paid',
    },
    'codex': {
        'name': 'GPT Codex 5.3',
        'role': 'Production Engineer + Code Review',
        'provider': 'openai',
        'model': 'gpt-5.3-codex',
        'max_tokens': 16384,
        'cost': 'paid',
    },
    'opus': {
        'name': 'Claude Opus 4.6',
        'role': 'Systems Architect (design decisions only)',
        'provider': 'anthropic',
        'model': 'claude-opus-4-6',
        'max_tokens': 4096,
        'cost': 'paid',
    },
    'deepseek_reason': {
        'name': 'DeepSeek R1',
        'role': 'Deep Reasoning + Verification',
        'provider': 'deepseek',
        'model': 'deepseek-reasoner',
        'max_tokens': 8192,
        'cost': 'paid',
    },
    'deepseek_chat': {
        'name': 'DeepSeek V3',
        'role': 'Research + Fast Intent Classification',
        'provider': 'deepseek',
        'model': 'deepseek-chat',
        'max_tokens': 1500,
        'cost': 'paid-cheap',
    },
}

# ─── Unified API Client ───────────────────────────────────────

API_TIMEOUTS = {
    'openrouter': 30,   # Gemma (free) — fast
    'anthropic': 60,    # Opus — slow but worth the wait for architecture
    'openai': 90,        # Codex 5.3 — production hardening can be heavy
    'xai': 90,           # Grok 4.1 reasoning — can take 30-60s for code generation
    'deepseek': 90,     # DeepSeek R1 reasoning can take 40-60s
}


def call_model(model_key, system_prompt, user_message, max_tokens=None):
    """Call any model. Returns (text, token_info) or (None, error_string).
    Tracks token usage against budget. Refuses if budget exceeded."""
    cfg = MODELS[model_key]
    provider = cfg['provider']
    model = cfg['model']
    mt = max_tokens or cfg['max_tokens']
    timeout = API_TIMEOUTS.get(provider, 30)

    # Budget gate — skip free models (Gemma)
    if cfg.get('cost') != 'free' and not budget.can_proceed():
        logger.warning(f"[BUDGET] Budget exceeded — refusing {model_key} call. {budget.status()}")
        return None, "BUDGET_EXCEEDED"

    def _record_and_return(text, tok_dict):
        """Record budget and return."""
        if isinstance(tok_dict, dict) and cfg.get('cost') != 'free':
            cost = budget.record(model, tok_dict.get('input', 0), tok_dict.get('output', 0))
            logger.info(f"[BUDGET] {model_key}: ${cost:.4f} | Build: ${budget.current_build_spend:.4f} | Daily: ${budget.daily_spend:.4f}")
        return text, tok_dict

    try:
        text_out = None
        tok_out = {'input': 0, 'output': 0}

        if provider == 'openrouter':
            resp = requests.post(
                'https://openrouter.ai/api/v1/chat/completions',
                headers={'Authorization': f'Bearer {API_KEYS["openrouter"]}', 'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message},
                ]},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            text_out = d['choices'][0]['message']['content']
            tok_out = {'input': d.get('usage', {}).get('prompt_tokens', 0),
                       'output': d.get('usage', {}).get('completion_tokens', 0)}

        elif provider == 'anthropic':
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'x-api-key': API_KEYS['anthropic'], 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'system': system_prompt,
                      'messages': [{'role': 'user', 'content': user_message}]},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            text_out = d['content'][0]['text']
            tok_out = {'input': d.get('usage', {}).get('input_tokens', 0),
                       'output': d.get('usage', {}).get('output_tokens', 0)}

        elif provider == 'openai':
            resp = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {API_KEYS["openai"]}', 'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message},
                ]},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            text_out = d['choices'][0]['message']['content']
            tok_out = {'input': d.get('usage', {}).get('prompt_tokens', 0),
                       'output': d.get('usage', {}).get('completion_tokens', 0)}

        elif provider == 'xai':
            resp = requests.post(
                'https://api.x.ai/v1/chat/completions',
                headers={'Authorization': f'Bearer {API_KEYS["xai"]}', 'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message},
                ]},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            text_out = d['choices'][0]['message']['content']
            tok_out = {'input': d.get('usage', {}).get('prompt_tokens', 0),
                       'output': d.get('usage', {}).get('completion_tokens', 0)}

        elif provider == 'deepseek':
            # DeepSeek Reasoner (R1) doesn't support system messages — merge into user
            if model == 'deepseek-reasoner':
                messages = [{'role': 'user', 'content': f"{system_prompt}\n\n{user_message}"}]
            else:
                messages = [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message},
                ]
            resp = requests.post(
                'https://api.deepseek.com/chat/completions',
                headers={'Authorization': f'Bearer {API_KEYS["deepseek"]}', 'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'messages': messages},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            msg = d['choices'][0]['message']
            text_out = msg.get('content') or msg.get('reasoning_content') or ''
            tok_out = {'input': d.get('usage', {}).get('prompt_tokens', 0),
                       'output': d.get('usage', {}).get('completion_tokens', 0)}

        else:
            return None, f"unknown_provider: {provider}"

        # Record budget
        return _record_and_return(text_out, tok_out)

    except Exception as e:
        logger.error(f"[{model_key}] API error: {e}")
        return None, str(e)


# ─── Core Pipeline v5.0 — Staged Sequential Workflow ──────────

executor = ThreadPoolExecutor(max_workers=5)

# ─── BUILD GATE — SLASH COMMAND ONLY ─────────────────────────
# Build pipeline ONLY triggers if the message starts with /build.
# Everything else defaults to Gemma → DeepSeek fast-path (cheap, low latency).

# Secondary keywords — only checked for debug routing
DEBUG_KEYWORDS = ['debug', 'error', 'crash', 'trace', 'stacktrace', 'exception', 'broken', 'failing',
                  'diagnose', 'root cause', 'scan', 'bug', 'not working']


def parse_build_command(msg):
    """Check if message starts with /build. Returns (is_build, cleaned_message)."""
    stripped = msg.strip()
    if stripped.lower().startswith('/build'):
        # Strip the /build prefix and return the actual instruction
        remainder = stripped[6:].strip()
        return True, remainder if remainder else stripped
    return False, stripped


def check_debug_keywords(msg):
    """Check if message contains debug-related keywords anywhere."""
    m = msg.lower()
    return any(kw in m for kw in DEBUG_KEYWORDS)


def _track(result, model_name, text, tokens):
    """Helper to accumulate token tracking."""
    result['models_used'].append(model_name)
    if isinstance(tokens, dict):
        result['tokens']['input'] += tokens.get('input', 0)
        result['tokens']['output'] += tokens.get('output', 0)


def run_pipeline(user_message):
    """
    v5.3 Workflow — Credit-Conservative Staged Pipeline.

    DEFAULT PATH (99% of messages):
      Gemma (FREE) → DeepSeek Chat V3 (cheap) → Gemma (FREE) → user
      Total cost: ~$0.001 per message. Low latency.

    BUILD PATH (only if message starts with /build):
      Gemma (FREE intake) → DeepSeek R1 (master prompt) → Opus (architecture)
      → Grok x2 parallel (prototype) → Codex x2 parallel (production hardening)
      → DeepSeek R1 (verification) → [loop if needed] → Gemma (FREE delivery)

    DEBUG PATH (keyword triggered):
      Gemma → Grok (2M context, surgical fix) → Gemma
    """
    start = time.time()
    build_gate, user_message = parse_build_command(user_message)
    is_debug = check_debug_keywords(user_message)
    words = len(user_message.split())

    result = {
        'task_type': 'pending',
        'models_used': [],
        'tokens': {'input': 0, 'output': 0},
        'stages': [],
        'stage_detail': [],
    }

    def _timed_call(label, model_key, system_prompt, user_msg, max_tok=None):
        """Call a model and record timing + token telemetry."""
        t0 = time.time()
        text, tok = call_model(model_key, system_prompt, user_msg, max_tok)
        elapsed = time.time() - t0
        _track(result, label, text, tok)
        result['stage_detail'].append({
            'agent': label,
            'model': MODELS[model_key]['model'],
            'time': f"{elapsed:.2f}s",
            'chars': len(text) if text else 0,
            'tokens': tok if isinstance(tok, dict) else {},
            'preview': (text[:150] + '...') if text and len(text) > 150 else (text or 'FAILED'),
        })
        logger.info(f"[PIPELINE] {label}: {elapsed:.1f}s, {len(text) if text else 0} chars")
        return text, tok

    # ═══════════════════════════════════════════════════════════════
    # LARGE INPUT (>500 words) — Grok ingests with 2M context
    # ═══════════════════════════════════════════════════════════════
    if words > 500 and not build_gate:
        result['task_type'] = 'large_input'
        result['stages'].append('grok_ingest')
        text, tok = _timed_call('Grok (2M ingest)', 'grok',
            "Analyze this large input. Structured summary + action plan. Be thorough but concise.",
            user_message, 2048)
        result['response'] = text or "Failed to process large input."
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # DEBUG PATH — Grok solo (surgical debugging)
    # ═══════════════════════════════════════════════════════════════
    if is_debug and not build_gate:
        result['task_type'] = 'debug'
        result['stages'].append('grok_debug')
        text, tok = _timed_call('Grok (debugger)', 'grok',
            "Lead debugger. 2M context window. Find the root cause. Show the fix. "
            "Code-first. Surgical — don't rewrite everything, just fix what's broken.",
            user_message, 2048)
        result['response'] = text or "Could not diagnose."
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # DEFAULT PATH — Gemma → DeepSeek Chat → Gemma (CHEAP + FAST)
    # No build/deploy/create in first 10 tokens = no frontier models
    # ═══════════════════════════════════════════════════════════════
    if not build_gate:
        result['task_type'] = 'fast_path'
        result['stages'].append('deepseek_reply')
        logger.info(f"[FAST-PATH] No build gate triggered. DeepSeek handles directly.")

        # DeepSeek Chat V3 handles it — cheapest paid model
        ds_text, ds_tok = _timed_call('DeepSeek V3 (fast reply)', 'deepseek_chat',
            "You are the Leviathan dev team's research and reasoning engine. "
            "Answer the user's question directly, concisely, and accurately. "
            "If it's a technical question, give a technical answer. "
            "If it's casual, be brief and helpful. Do NOT suggest building anything unless asked.",
            user_message, 1500)

        if not ds_text:
            # Fallback to Gemma if DeepSeek fails
            ds_text, ds_tok = call_model('gemma',
                "Answer directly and concisely.", user_message, 800)
            result['models_used'].append('Gemma 3 (fallback)')

        result['response'] = ds_text or "I'm here. What do you need?"
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # BUILD PATH — Full staged pipeline (build/deploy/create detected)
    # ═══════════════════════════════════════════════════════════════
    result['task_type'] = 'build'
    budget.reset_build()  # Fresh build budget counter
    logger.info(f"[BUILD] *** FULL PIPELINE TRIGGERED *** for: {user_message[:100]}...")

    MAX_FIX_ROUNDS = 2  # Max verification-fix loops before shipping

    # ── STAGE 1: DeepSeek R1 generates master prompt for Opus ──
    result['stages'].append('master_prompt')
    logger.info("[BUILD] Stage 1: DeepSeek R1 generates master architecture prompt")

    master_prompt, _ = _timed_call('DeepSeek R1 (master prompt)', 'deepseek_reason',
        "You are the master prompt engineer. The user wants to BUILD something. "
        "Your job: analyze the user's request and generate a DETAILED master prompt "
        "for a systems architect (Claude Opus 4.6). The master prompt must include:\n"
        "- Clear problem statement\n"
        "- Technical requirements extracted from user intent\n"
        "- Constraints and edge cases to consider\n"
        "- Performance/scalability requirements\n"
        "- Security considerations\n"
        "- Deployment target (if mentioned)\n\n"
        "Output ONLY the master prompt. No preamble. The architect will receive it directly.",
        user_message, 2048)

    if not master_prompt:
        master_prompt = user_message  # Fallback: raw user input goes to Opus

    # ── STAGE 2: Opus designs architecture from master prompt ──
    result['stages'].append('architecture')
    logger.info("[BUILD] Stage 2: Opus architects from DeepSeek's master prompt")

    arch_text, _ = _timed_call('Opus (architecture)', 'opus',
        "You are the systems architect. Design a complete software architecture from this prompt.\n"
        "Output a structured blueprint with:\n"
        "- Components, modules, data flow\n"
        "- Tech stack choices with reasoning\n"
        "- Complete file structure\n"
        "- API contracts / interfaces / data models\n"
        "- Security considerations\n"
        "- Deployment strategy\n\n"
        "This goes directly to engineers. Make it actionable: file names, function signatures, "
        "data models, API routes. Zero ambiguity.",
        master_prompt, 2048)

    if not arch_text:
        result['response'] = "Architecture stage failed. Opus did not respond."
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    final_arch = arch_text

    # ── STAGE 3: Grok rapid-prototypes (PARALLEL WORKERS) ──
    result['stages'].append('prototype')
    logger.info("[BUILD] Stage 3: Grok x2 parallel rapid prototype")
    stage3_start = time.time()

    grok_futures = {
        executor.submit(call_model, 'grok',
            "Rapid prototyper. Write the BACKEND code from this blueprint. "
            "Server, API routes, data models, business logic, database schema. "
            "Every file, every function. Complete, runnable code. No prose filler.",
            f"USER REQUEST:\n{user_message}\n\nARCHITECTURE BLUEPRINT:\n{final_arch}\n\nFOCUS: Backend / server-side code only.",
            4096): 'backend',
        executor.submit(call_model, 'grok',
            "Rapid prototyper. Write the FRONTEND/CLI/client code from this blueprint. "
            "UI, client logic, config files, Dockerfile, README, setup scripts, CI/CD. "
            "Every file, every function. Complete, runnable code. No prose filler.",
            f"USER REQUEST:\n{user_message}\n\nARCHITECTURE BLUEPRINT:\n{final_arch}\n\nFOCUS: Frontend / client / config / deployment files only.",
            4096): 'frontend',
    }

    prototype_parts = {}
    grok_timings = {}
    for future in as_completed(grok_futures, timeout=180):
        part_name = grok_futures[future]
        try:
            text, tok = future.result(timeout=120)
            elapsed = time.time() - stage3_start
            if text:
                prototype_parts[part_name] = text
                grok_timings[part_name] = elapsed
                _track(result, f'Grok ({part_name})', text, tok)
                result['stage_detail'].append({
                    'agent': f'Grok ({part_name})',
                    'model': MODELS['grok']['model'],
                    'time': f"{elapsed:.2f}s",
                    'chars': len(text),
                    'tokens': tok if isinstance(tok, dict) else {},
                })
                logger.info(f"[BUILD] Grok ({part_name}): {elapsed:.1f}s, {len(text)} chars")
        except Exception as e:
            logger.warning(f"[Grok {part_name}] failed: {e}")

    if not prototype_parts:
        result['response'] = f"Architecture complete but prototype failed.\n\nARCHITECTURE:\n{final_arch}"
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ── STAGE 4: Codex production-hardens (PARALLEL WORKERS) ──
    result['stages'].append('production')
    logger.info("[BUILD] Stage 4: Codex x2 parallel production hardening")
    stage4_start = time.time()

    codex_futures = {
        executor.submit(call_model, 'codex',
            "Production engineer. Overhaul this BACKEND prototype into production-grade code. "
            "Full error handling, input validation, type safety, security hardening, "
            "logging, clean imports, no dead code, proper documentation. "
            "Output COMPLETE, production-ready backend code. Every file, every line.",
            f"ARCHITECTURE:\n{final_arch}\n\nBACKEND PROTOTYPE:\n{prototype_parts.get('backend', 'N/A')}",
            4096): 'backend',
        executor.submit(call_model, 'codex',
            "Production engineer. Overhaul this FRONTEND/CONFIG prototype into production-grade code. "
            "Full error handling, edge cases, security, clean README with setup instructions, "
            "proper Dockerfile, CI config, environment management. "
            "Output COMPLETE, production-ready frontend/config code. Every file, every line.",
            f"ARCHITECTURE:\n{final_arch}\n\nFRONTEND/CONFIG PROTOTYPE:\n{prototype_parts.get('frontend', 'N/A')}",
            4096): 'frontend',
    }

    production_parts = {}
    codex_timings = {}
    for future in as_completed(codex_futures, timeout=180):
        part_name = codex_futures[future]
        try:
            text, tok = future.result(timeout=120)
            elapsed = time.time() - stage4_start
            if text:
                production_parts[part_name] = text
                codex_timings[part_name] = elapsed
                _track(result, f'Codex ({part_name})', text, tok)
                result['stage_detail'].append({
                    'agent': f'Codex ({part_name})',
                    'model': MODELS['codex']['model'],
                    'time': f"{elapsed:.2f}s",
                    'chars': len(text),
                    'tokens': tok if isinstance(tok, dict) else {},
                })
                logger.info(f"[BUILD] Codex ({part_name}): {elapsed:.1f}s, {len(text)} chars")
        except Exception as e:
            logger.warning(f"[Codex {part_name}] failed: {e}")

    production_text = "\n\n".join(
        [production_parts.get('backend', prototype_parts.get('backend', '')),
         production_parts.get('frontend', prototype_parts.get('frontend', ''))]
    ).strip()

    if not production_parts:
        production_text = "\n\n".join(prototype_parts.values()).strip()

    # ── STAGE 5: DeepSeek R1 verification loop ──
    result['stages'].append('verification')
    logger.info("[BUILD] Stage 5: DeepSeek R1 verification")

    for fix_round in range(MAX_FIX_ROUNDS + 1):
        verify_text, _ = _timed_call(f'DeepSeek R1 (verify round {fix_round})', 'deepseek_reason',
            "You are the quality verification engine. You generated the original master prompt. "
            "Now review the finished production code against the user's request.\n\n"
            "VERDICT OPTIONS:\n"
            "- If the code is A+ quality and satisfies the request: respond with EXACTLY 'APPROVED' on the first line, "
            "  followed by a brief explanation of why it's ready.\n"
            "- If the code needs fixes: respond with EXACTLY 'FIX_NEEDED' on the first line, "
            "  followed by a DETAILED fix prompt that specifies exactly what's wrong and how to fix it. "
            "  This fix prompt will go to the architect to redesign the failing parts.",
            f"ORIGINAL USER REQUEST:\n{user_message}\n\n"
            f"MASTER PROMPT GENERATED:\n{master_prompt}\n\n"
            f"ARCHITECTURE:\n{final_arch}\n\n"
            f"PRODUCTION CODE:\n{production_text[:8000]}",  # Cap context to avoid blowout
            2048)

        if not verify_text or 'APPROVED' in (verify_text or '').upper().split('\n')[0]:
            logger.info(f"[BUILD] DeepSeek R1 APPROVED at round {fix_round}")
            break

        if 'FIX_NEEDED' in verify_text.upper().split('\n')[0] and fix_round < MAX_FIX_ROUNDS:
            logger.info(f"[BUILD] FIX ROUND {fix_round + 1}: DeepSeek flagged issues, sending to Opus→Grok→Codex")
            result['stages'].append(f'fix_round_{fix_round + 1}')

            # Opus re-architects the fix
            fix_arch, _ = _timed_call(f'Opus (fix arch r{fix_round+1})', 'opus',
                "The code reviewer found issues. Re-architect ONLY the parts that need fixing. "
                "Output a targeted fix blueprint — what files to change, what functions to modify, "
                "what to add/remove. Be surgical, don't redo everything.",
                f"VERIFICATION FEEDBACK:\n{verify_text}\n\nCURRENT ARCHITECTURE:\n{final_arch}",
                1500)

            # Grok implements the fix
            fix_code, _ = _timed_call(f'Grok (fix impl r{fix_round+1})', 'grok',
                "Implement ONLY the fixes described. Don't rewrite unrelated code. Surgical fix.",
                f"FIX BLUEPRINT:\n{fix_arch or verify_text}\n\nCURRENT CODE:\n{production_text[:6000]}",
                4096)

            # Codex hardens the fix
            if fix_code:
                hardened_fix, _ = _timed_call(f'Codex (fix harden r{fix_round+1})', 'codex',
                    "Production-harden this fix. Error handling, edge cases, security. "
                    "Output the COMPLETE updated code incorporating the fix.",
                    f"ARCHITECTURE:\n{final_arch}\n\nFIX CODE:\n{fix_code}\n\nPREVIOUS PRODUCTION CODE:\n{production_text[:6000]}",
                    4096)
                if hardened_fix:
                    production_text = hardened_fix
        else:
            break  # Either approved or max rounds hit

    # ── STAGE 6: Gemma presents to user (FREE) ──
    result['stages'].append('delivery')
    logger.info("[BUILD] Stage 6: Delivery (Gemma)")

    delivery_text, del_tok = call_model('gemma',
        "Present the dev team's completed work to the user.\n"
        "Structure:\n"
        "1. Brief summary of what was built\n"
        "2. The COMPLETE production code (keep ALL code blocks intact — do not truncate)\n"
        "3. Setup/install instructions\n"
        "4. Verification status\n"
        "Keep it clean. User should be able to copy-paste and run.",
        f"USER REQUEST:\n{user_message}\n\n"
        f"PRODUCTION CODE:\n{production_text}\n\n"
        f"VERIFICATION: {verify_text[:500] if verify_text else 'Approved'}",
        max_tokens=1500)

    result['response'] = delivery_text or production_text
    result['processing_time'] = f"{time.time() - start:.2f}s"
    result['fix_rounds'] = fix_round if 'fix_round' in dir() else 0
    result['budget'] = budget.status()
    return result


# ─── Flask Routes ──────────────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
def api_chat():
    try:
        data = request.json
        msg = data.get('message', '').strip()
        if not msg:
            return jsonify({'error': 'Empty message'}), 400
        result = run_pipeline(msg)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'version': '5.3-slash', 'timestamp': datetime.now().isoformat()})


@app.route('/budget')
def budget_status():
    return jsonify(budget.status())


@app.route('/status')
def status():
    return jsonify({
        'version': '5.3-slash',
        'architecture': 'Gemma bridge + paid model execution',
        'models': {k: {'name': v['name'], 'role': v['role'], 'cost': v['cost']} for k, v in MODELS.items()},
        'api_keys': {k: bool(v) for k, v in API_KEYS.items()},
    })


# ─── Chat UI ──────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leviathan Dev Team</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0a0e27;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}
header{background:#111830;border-bottom:1px solid #2a3550;padding:16px 20px}
h1{font-size:20px;background:linear-gradient(135deg,#00d4ff,#7c3aed);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{font-size:11px;color:#666;margin-top:4px}
#msgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:75%;padding:10px 14px;border-radius:8px;font-size:14px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word}
.msg.u{align-self:flex-end;background:#5b21b6;color:#fff}
.msg.a{align-self:flex-start;background:#1a2332;border:1px solid #2a3550}
.meta{font-size:10px;color:#00d4ff;margin-top:6px;opacity:.7}
.bar{background:#111830;border-top:1px solid #2a3550;padding:12px 16px;display:flex;gap:8px}
.bar input{flex:1;background:#1a2332;border:1px solid #2a3550;color:#e0e0e0;padding:10px 14px;border-radius:6px;font-size:14px;outline:none}
.bar input:focus{border-color:#7c3aed}
.bar button{background:#7c3aed;border:none;color:#fff;padding:10px 20px;border-radius:6px;cursor:pointer;font-size:14px}
.bar button:disabled{opacity:.4}
.dot{display:inline-block;width:6px;height:6px;background:#00d4ff;border-radius:50%;animation:p 1s infinite}
.dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
@keyframes p{0%,100%{opacity:.2}50%{opacity:1}}
</style>
</head>
<body>
<header>
<h1>Leviathan Dev Team</h1>
<div class="sub">Gemma 3 (bridge) · Grok · Codex · Opus · DeepSeek &nbsp;|&nbsp; <span style="color:#7c3aed">/build</span> to activate full pipeline</div>
</header>
<div id="msgs"></div>
<div class="bar">
<input id="inp" placeholder="Chat normally, or type /build to activate the full dev pipeline..." autocomplete="off">
<button id="btn" onclick="send()">Send</button>
</div>
<script>
const msgs=document.getElementById('msgs'),inp=document.getElementById('inp'),btn=document.getElementById('btn');
function add(text,isUser,meta){
  const d=document.createElement('div');d.className='msg '+(isUser?'u':'a');
  d.textContent=text;
  if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}
  msgs.appendChild(d);msgs.scrollTop=msgs.scrollHeight;
}
async function send(){
  const m=inp.value.trim();if(!m)return;
  add(m,true);inp.value='';btn.disabled=true;
  const ld=document.createElement('div');ld.className='msg a';
  ld.innerHTML='<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  msgs.appendChild(ld);msgs.scrollTop=msgs.scrollHeight;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:m})});
    const d=await r.json();msgs.removeChild(ld);
    const meta=d.models_used?.length?d.models_used.join(' · ')+' · '+d.processing_time:'';
    add(d.response||d.error||'No response',false,meta);
  }catch(e){msgs.removeChild(ld);add('Error: '+e.message,false)}
  btn.disabled=false;
}
inp.addEventListener('keypress',e=>{if(e.key==='Enter')send()});
</script>
</body>
</html>"""


@app.route('/')
def index():
    return HTML


# ─── Discord Bot ─────────────────────────────────────────────

DISCORD_TOKEN = os.environ.get('DISCORD_BOT_TOKEN_DEVTEAM', '')
DISCORD_GUILD_ID = 1477804209842815382

discord_bot = None
_discord_lock_file = None

def start_discord_bot():
    """Run Discord bot in background thread alongside Flask.
    Uses file lock so only ONE gunicorn worker runs the bot (prevents duplicate replies).
    """
    global discord_bot, _discord_lock_file
    if not DISCORD_TOKEN:
        logger.warning("No DISCORD_BOT_TOKEN_DEVTEAM set, skipping Discord bot")
        return

    # ── Guard: only one worker gets the lock ──
    import fcntl
    try:
        _discord_lock_file = open('/tmp/discord_bot.lock', 'w')
        fcntl.flock(_discord_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _discord_lock_file.write(str(os.getpid()))
        _discord_lock_file.flush()
        logger.info(f"Discord bot lock acquired by PID {os.getpid()}")
    except (IOError, OSError):
        logger.info(f"PID {os.getpid()} — another worker owns the Discord bot, skipping")
        return

    try:
        import discord
    except ImportError:
        logger.error("discord.py not installed, skipping Discord bot")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    bot = discord.Client(intents=intents)
    discord_bot = bot

    @bot.event
    async def on_ready():
        logger.info(f"Discord bot connected as {bot.user} (ID: {bot.user.id})")
        guild = bot.get_guild(DISCORD_GUILD_ID)
        if guild:
            logger.info(f"Connected to guild: {guild.name}")
        else:
            logger.warning(f"Guild {DISCORD_GUILD_ID} not found — bot may not be invited yet")

    @bot.event
    async def on_message(message):
        # Ignore own messages
        if message.author == bot.user:
            return

        # Strip mentions if present
        content = message.content
        if bot.user in (message.mentions or []):
            content = content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        if content.startswith('!team'):
            content = content[5:].strip()

        if not content:
            await message.reply("What do you need? Send me a message and the dev team will handle it.")
            return

        # Show typing while processing
        async with message.channel.typing():
            # Run pipeline in thread pool (it uses blocking requests)
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, run_pipeline, content)
                response_text = result.get('response', 'No response generated.')
                models = result.get('models_used', [])
                proc_time = result.get('processing_time', '?')

                # Build footer
                footer = f"\n-# {' · '.join(models)} · {proc_time}" if models else ""

                full_response = response_text + footer

                # Discord max is 2000 chars — chunk if needed
                if len(full_response) <= 2000:
                    await message.reply(full_response)
                else:
                    # Send in chunks, reply first, then follow-up
                    chunks = []
                    while full_response:
                        if len(full_response) <= 2000:
                            chunks.append(full_response)
                            break
                        # Find a good split point
                        split_at = full_response.rfind('\n', 0, 1990)
                        if split_at < 500:
                            split_at = 1990
                        chunks.append(full_response[:split_at])
                        full_response = full_response[split_at:].lstrip()

                    for i, chunk in enumerate(chunks):
                        if i == 0:
                            await message.reply(chunk)
                        else:
                            await message.channel.send(chunk)

            except Exception as e:
                logger.error(f"Discord pipeline error: {e}", exc_info=True)
                await message.reply(f"Error processing your request: {str(e)[:200]}")

    def _run_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(bot.start(DISCORD_TOKEN))
        except Exception as e:
            logger.error(f"Discord bot crashed: {e}", exc_info=True)

    thread = threading.Thread(target=_run_bot, daemon=True, name="discord-bot")
    thread.start()
    logger.info("Discord bot thread started")


# Auto-start Discord bot when module loads (works with gunicorn)
start_discord_bot()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Super Brain Dev Team v5.3 starting on :{port}")
    logger.info(f"Models: Gemma (bridge) + Grok + Codex + Opus + DeepSeek")
    logger.info(f"Discord: {'enabled' if DISCORD_TOKEN else 'disabled (no token)'}")
    app.run(host='0.0.0.0', port=port)
