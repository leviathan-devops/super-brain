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
        'role': 'Chat Bridge + Synthesis',
        'provider': 'openrouter',
        'model': 'google/gemma-3-27b-it',
        'max_tokens': 1000,
        'cost': 'free',
    },
    'grok': {
        'name': 'Grok',
        'role': 'Lead Engineer + Debugger + Reviewer (2M context)',
        'provider': 'xai',
        'model': 'grok-3',
        'max_tokens': 1500,
        'cost': 'paid',
    },
    'codex': {
        'name': 'Codex',
        'role': 'Engineer + Reviewer',
        'provider': 'openai',
        'model': 'gpt-4o',
        'max_tokens': 1500,
        'cost': 'paid',
    },
    'opus': {
        'name': 'Opus',
        'role': 'Architect (design decisions only)',
        'provider': 'anthropic',
        'model': 'claude-opus-4-6-20251101',
        'max_tokens': 1500,
        'cost': 'paid',
    },
    'deepseek': {
        'name': 'DeepSeek',
        'role': 'Research + Reasoning',
        'provider': 'deepseek',
        'model': 'deepseek-chat',
        'max_tokens': 1500,
        'cost': 'paid',
    },
}

# ─── Unified API Client ───────────────────────────────────────

API_TIMEOUTS = {
    'openrouter': 30,   # Gemma (free) — fast
    'anthropic': 60,    # Opus — slow but worth the wait for architecture
    'openai': 45,       # Codex — production hardening takes time
    'xai': 45,          # Grok — prototyping can be heavy
    'deepseek': 40,     # DeepSeek — reasoning takes a moment
}


def call_model(model_key, system_prompt, user_message, max_tokens=None):
    """Call any model. Returns (text, token_info) or (None, error_string)."""
    cfg = MODELS[model_key]
    provider = cfg['provider']
    model = cfg['model']
    mt = max_tokens or cfg['max_tokens']
    timeout = API_TIMEOUTS.get(provider, 30)

    try:
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
            return d['choices'][0]['message']['content'], {
                'input': d.get('usage', {}).get('prompt_tokens', 0),
                'output': d.get('usage', {}).get('completion_tokens', 0),
            }

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
            return d['content'][0]['text'], {
                'input': d.get('usage', {}).get('input_tokens', 0),
                'output': d.get('usage', {}).get('output_tokens', 0),
            }

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
            return d['choices'][0]['message']['content'], {
                'input': d.get('usage', {}).get('prompt_tokens', 0),
                'output': d.get('usage', {}).get('completion_tokens', 0),
            }

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
            return d['choices'][0]['message']['content'], {
                'input': d.get('usage', {}).get('prompt_tokens', 0),
                'output': d.get('usage', {}).get('completion_tokens', 0),
            }

        elif provider == 'deepseek':
            resp = requests.post(
                'https://api.deepseek.com/chat/completions',
                headers={'Authorization': f'Bearer {API_KEYS["deepseek"]}', 'Content-Type': 'application/json'},
                json={'model': model, 'max_tokens': mt, 'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_message},
                ]},
                timeout=timeout,
            )
            resp.raise_for_status()
            d = resp.json()
            return d['choices'][0]['message']['content'], {
                'input': d.get('usage', {}).get('prompt_tokens', 0),
                'output': d.get('usage', {}).get('completion_tokens', 0),
            }

    except Exception as e:
        logger.error(f"[{model_key}] API error: {e}")
        return None, str(e)


# ─── Core Pipeline v5.0 — Staged Sequential Workflow ──────────

executor = ThreadPoolExecutor(max_workers=5)

# ─── Classification Keywords ─────────────────────────────────
# BUILD triggers the full 6-stage pipeline. Everything else is lightweight single-model.
BUILD_KEYWORDS = ['build', 'create', 'implement', 'make', 'develop', 'program', 'app', 'application',
                  'software', 'platform', 'tool', 'service', 'project', 'startup', 'product', 'saas',
                  'i want', 'i need', 'can you make', 'build me', 'create me']
DEBUG_KEYWORDS = ['debug', 'error', 'crash', 'trace', 'stacktrace', 'exception', 'broken', 'failing',
                  'diagnose', 'root cause', 'scan', 'bug', 'not working', 'fix']
RESEARCH_KEYWORDS = ['research', 'compare', 'explain', 'what is', 'how does', 'best practice',
                     'alternative', 'library', 'framework', 'benchmark', 'why', 'difference', 'tradeoff']
QUICK_CODE_KEYWORDS = ['function', 'script', 'snippet', 'regex', 'query', 'one-liner', 'helper',
                       'util', 'convert', 'parse', 'format']


def classify_task(msg):
    """Classify into: build (full pipeline), debug, research, quick_code, or chat."""
    m = msg.lower()
    words = len(msg.split())

    # Large input → Grok ingests first (2M context)
    if words > 500:
        return 'large_input'

    # BUILD: user describing an idea/project/software to create → full staged pipeline
    if any(kw in m for kw in BUILD_KEYWORDS):
        return 'build'

    # Debug → Grok solo
    if any(kw in m for kw in DEBUG_KEYWORDS):
        return 'debug'

    # Research → DeepSeek solo
    if any(kw in m for kw in RESEARCH_KEYWORDS):
        return 'research'

    # Quick code (small utility, not a full project) → Grok solo
    if any(kw in m for kw in QUICK_CODE_KEYWORDS):
        return 'quick_code'

    # Default → Gemma (free chat)
    return 'chat'


def _track(result, model_name, text, tokens):
    """Helper to accumulate token tracking."""
    result['models_used'].append(model_name)
    if isinstance(tokens, dict):
        result['tokens']['input'] += tokens.get('input', 0)
        result['tokens']['output'] += tokens.get('output', 0)


def run_pipeline(user_message):
    """
    v5.0 Staged Pipeline.

    BUILD workflow (sequential, each stage feeds the next):
      1. Gemma intake (free)
      2. Opus architecture → DeepSeek validates → architecture finalized
      3. Grok rapid-prototypes from blueprints
      4. Codex production-hardens the prototype
      5. Opus + optional DeepSeek final review
      6. Gemma presents to user (free)

    Lightweight paths skip straight to a single model.
    """
    start = time.time()
    task_type = classify_task(user_message)

    result = {
        'task_type': task_type,
        'models_used': [],
        'tokens': {'input': 0, 'output': 0},
        'stages': [],
    }

    # ═══════════════════════════════════════════════════════════════
    # CHAT — Gemma only (FREE)
    # ═══════════════════════════════════════════════════════════════
    if task_type == 'chat':
        text, tok = call_model('gemma',
            "Leviathan dev team interface. Direct, concise.",
            user_message, max_tokens=800)
        result['response'] = text or "I'm here. What do you need?"
        result['models_used'] = ['Gemma 3']
        if isinstance(tok, dict):
            result['tokens'] = tok
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # LARGE INPUT — Grok ingests (2M context)
    # ═══════════════════════════════════════════════════════════════
    if task_type == 'large_input':
        text, tok = call_model('grok',
            "Analyze this large input. Structured summary + action plan.",
            user_message, max_tokens=1500)
        result['response'] = text or "Failed to process."
        _track(result, 'Grok', text, tok)
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # DEBUG — Grok solo (2M context scans everything)
    # ═══════════════════════════════════════════════════════════════
    if task_type == 'debug':
        text, tok = call_model('grok',
            "Lead debugger. 2M context. Find the root cause. Show the fix. Code first.",
            user_message, max_tokens=1500)
        result['response'] = text or "Could not diagnose."
        _track(result, 'Grok', text, tok)
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # RESEARCH — DeepSeek solo (cheapest paid)
    # ═══════════════════════════════════════════════════════════════
    if task_type == 'research':
        text, tok = call_model('deepseek',
            "Researcher. Technical analysis, comparisons, reasoning. Concise.",
            user_message, max_tokens=1500)
        result['response'] = text or "Research failed."
        _track(result, 'DeepSeek', text, tok)
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # QUICK CODE — Grok solo (small utility, not a full project)
    # ═══════════════════════════════════════════════════════════════
    if task_type == 'quick_code':
        text, tok = call_model('grok',
            "Rapid prototyper. Write the code immediately. Minimal prose. Production-ready.",
            user_message, max_tokens=1500)
        result['response'] = text or "Code generation failed."
        _track(result, 'Grok', text, tok)
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # ═══════════════════════════════════════════════════════════════
    # BUILD — Full 6-stage pipeline
    # ═══════════════════════════════════════════════════════════════
    logger.info(f"[BUILD] Starting full staged pipeline for: {user_message[:100]}...")

    # ── STAGE 1: Gemma intake (FREE) — no tokens wasted ──
    result['stages'].append('intake')
    logger.info("[BUILD] Stage 1: Intake (Gemma)")

    # ── STAGE 2: Opus architects → DeepSeek validates ──
    result['stages'].append('architecture')
    logger.info("[BUILD] Stage 2: Architecture (Opus → DeepSeek → Opus)")

    # 2a: Opus generates architecture
    arch_text, arch_tok = call_model('opus',
        "You are the system architect. The user has an idea. Design a complete software architecture:\n"
        "- Components, modules, data flow\n"
        "- Tech stack choices with reasoning\n"
        "- File structure\n"
        "- API contracts / interfaces\n"
        "- Security considerations\n"
        "- Deployment strategy\n"
        "Output a structured blueprint that an engineer can immediately build from.",
        user_message, max_tokens=1500)
    _track(result, 'Opus (architecture)', arch_text, arch_tok)

    if not arch_text:
        result['response'] = "Architecture stage failed. Opus did not respond."
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    # 2b: DeepSeek validates and improves the architecture
    validation_text, val_tok = call_model('deepseek',
        "You are the validation engine. Review this software architecture for blind spots, "
        "scalability issues, missing edge cases, and potential improvements. "
        "If the architecture is solid, explain WHY it's solid so the architect can be confident. "
        "If it needs changes, be specific about what to fix and why.",
        f"ORIGINAL USER REQUEST:\n{user_message}\n\nPROPOSED ARCHITECTURE:\n{arch_text}",
        max_tokens=1500)
    _track(result, 'DeepSeek (validation)', validation_text, val_tok)

    # 2c: Opus finalizes architecture incorporating DeepSeek feedback
    final_arch, fa_tok = call_model('opus',
        "You are the system architect. You received validation feedback on your design. "
        "Incorporate any valid improvements. Output the FINAL architecture blueprint — "
        "this goes directly to the engineer. Make it actionable: file names, function signatures, "
        "data models, API routes. No ambiguity.",
        f"YOUR ORIGINAL ARCHITECTURE:\n{arch_text}\n\nVALIDATION FEEDBACK:\n{validation_text or 'No feedback — architecture approved.'}",
        max_tokens=1500)
    _track(result, 'Opus (finalized)', final_arch, fa_tok)

    if not final_arch:
        final_arch = arch_text  # Fallback to original if finalization failed

    # ── STAGE 3: Grok rapid-prototypes from blueprints (PARALLEL WORKERS) ──
    result['stages'].append('prototype')
    logger.info("[BUILD] Stage 3: Rapid Prototype (Grok x2 parallel)")

    # Split the architecture into frontend/backend or by module for parallel Grok instances
    grok_futures = {
        executor.submit(call_model, 'grok',
            "Rapid prototyper. Write the BACKEND code from this blueprint. "
            "Server, API routes, data models, business logic, database. "
            "Every file, every function. Code first. No filler.",
            f"USER IDEA:\n{user_message}\n\nARCHITECTURE BLUEPRINT:\n{final_arch}\n\nFOCUS: Backend / server-side code only.",
            1500): 'backend',
        executor.submit(call_model, 'grok',
            "Rapid prototyper. Write the FRONTEND/CLI/client code from this blueprint. "
            "UI, client logic, config files, Dockerfile, README, setup scripts. "
            "Every file, every function. Code first. No filler.",
            f"USER IDEA:\n{user_message}\n\nARCHITECTURE BLUEPRINT:\n{final_arch}\n\nFOCUS: Frontend / client / config / deployment files only.",
            1500): 'frontend',
    }

    prototype_parts = {}
    for future in as_completed(grok_futures, timeout=60):
        part_name = grok_futures[future]
        try:
            text, tok = future.result(timeout=3)
            if text:
                prototype_parts[part_name] = text
                _track(result, f'Grok ({part_name})', text, tok)
        except Exception as e:
            logger.warning(f"[Grok {part_name}] failed: {e}")

    if not prototype_parts:
        result['response'] = f"Architecture complete but prototype failed.\n\nARCHITECTURE:\n{final_arch}"
        result['processing_time'] = f"{time.time() - start:.2f}s"
        return result

    prototype_text = "\n\n--- BACKEND ---\n".join(
        [prototype_parts.get('backend', ''), "--- FRONTEND/CONFIG ---\n" + prototype_parts.get('frontend', '')]
    ).strip()

    # ── STAGE 4: Codex production-hardens (PARALLEL WORKERS) ──
    result['stages'].append('production')
    logger.info("[BUILD] Stage 4: Production Hardening (Codex x2 parallel)")

    codex_futures = {
        executor.submit(call_model, 'codex',
            "Production engineer. Overhaul this BACKEND prototype into production-grade code. "
            "Error handling, input validation, type safety, security hardening, "
            "clean imports, no dead code. Output COMPLETE production backend code.",
            f"ARCHITECTURE:\n{final_arch}\n\nBACKEND PROTOTYPE:\n{prototype_parts.get('backend', 'N/A')}",
            1500): 'backend',
        executor.submit(call_model, 'codex',
            "Production engineer. Overhaul this FRONTEND/CONFIG prototype into production-grade code. "
            "Error handling, edge cases, security, clean README with setup instructions, "
            "proper Dockerfile, CI config. Output COMPLETE production frontend/config code.",
            f"ARCHITECTURE:\n{final_arch}\n\nFRONTEND/CONFIG PROTOTYPE:\n{prototype_parts.get('frontend', 'N/A')}",
            1500): 'frontend',
    }

    production_parts = {}
    for future in as_completed(codex_futures, timeout=60):
        part_name = codex_futures[future]
        try:
            text, tok = future.result(timeout=3)
            if text:
                production_parts[part_name] = text
                _track(result, f'Codex ({part_name})', text, tok)
        except Exception as e:
            logger.warning(f"[Codex {part_name}] failed: {e}")

    production_text = "\n\n".join(
        [production_parts.get('backend', prototype_parts.get('backend', '')),
         production_parts.get('frontend', prototype_parts.get('frontend', ''))]
    ).strip()

    if not production_parts:
        production_text = prototype_text  # Fallback to prototype

    # ── STAGE 5: Opus final review ──
    result['stages'].append('review')
    logger.info("[BUILD] Stage 5: Final Review (Opus)")

    review_text, rev_tok = call_model('opus',
        "Final review. You are the architect reviewing the production code against your blueprint. "
        "Check: does it match the architecture? Any gaps? Security issues? Missing features? "
        "If APPROVED: say 'APPROVED' and list why it's ready. "
        "If NEEDS WORK: list specific issues that must be fixed. Be brief.",
        f"ARCHITECTURE:\n{final_arch}\n\nPRODUCTION CODE:\n{production_text}",
        max_tokens=1000)
    _track(result, 'Opus (review)', review_text, rev_tok)

    # ── STAGE 6: Gemma presents to user (FREE) ──
    result['stages'].append('delivery')
    logger.info("[BUILD] Stage 6: Delivery (Gemma)")

    delivery_text, del_tok = call_model('gemma',
        "You are presenting the dev team's completed work to the user. "
        "Structure your response:\n"
        "1. Brief summary of what was built\n"
        "2. The complete production code (keep ALL code blocks intact)\n"
        "3. Setup/install instructions\n"
        "4. The architect's review verdict\n"
        "Keep it clean and organized. The user should be able to copy-paste and run.",
        f"USER REQUEST:\n{user_message}\n\n"
        f"PRODUCTION CODE:\n{production_text}\n\n"
        f"ARCHITECT REVIEW:\n{review_text or 'Approved.'}",
        max_tokens=1500)

    result['response'] = delivery_text or production_text
    result['processing_time'] = f"{time.time() - start:.2f}s"
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
    return jsonify({'status': 'healthy', 'version': '5.0-staged', 'timestamp': datetime.now().isoformat()})


@app.route('/status')
def status():
    return jsonify({
        'version': '5.0-staged',
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
<div class="sub">Gemma 3 (bridge) · Grok · Codex · Opus · DeepSeek</div>
</header>
<div id="msgs"></div>
<div class="bar">
<input id="inp" placeholder="Talk to your dev team..." autocomplete="off">
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

def start_discord_bot():
    """Run Discord bot in background thread alongside Flask."""
    global discord_bot
    if not DISCORD_TOKEN:
        logger.warning("No DISCORD_BOT_TOKEN_DEVTEAM set, skipping Discord bot")
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
    logger.info(f"Super Brain Dev Team v5.0 starting on :{port}")
    logger.info(f"Models: Gemma (bridge) + Grok + Codex + Opus + DeepSeek")
    logger.info(f"Discord: {'enabled' if DISCORD_TOKEN else 'disabled (no token)'}")
    app.run(host='0.0.0.0', port=port)
