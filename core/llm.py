"""Tiny LLM client (plain `requests`, no SDK).

Pick a provider with environment variables:
  Anthropic (Claude API):   export ANTHROPIC_API_KEY=sk-ant-...            [LLM_MODEL optional]
  Any OpenAI-compatible API: export OPENAI_API_KEY=...  OPENAI_BASE_URL=...  LLM_MODEL=...
      e.g. Groq free tier:  OPENAI_BASE_URL=https://api.groq.com/openai/v1
      e.g. local Ollama:    OPENAI_BASE_URL=http://localhost:11434/v1  OPENAI_API_KEY=ollama
  No key at all -> returns None and ChaosPilot uses its built-in rule-based fallback.

Every successful answer is cached in runs/llm_cache/last_<kind>.json. `--offline` replays that
cached answer, so the live demo never depends on venue Wi-Fi or API rate limits.
"""
import json
import os
import re
import time

import requests

from .common import LIVE, RUNS_DIR, load_json, save_json

CACHE_DIR = os.path.join(RUNS_DIR, "llm_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def provider():
    p = os.getenv("LLM_PROVIDER")
    if p:
        return p
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


def _call(system, user, max_tokens, json_mode=True):
    if provider() == "anthropic":
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": os.getenv("LLM_MODEL", "claude-haiku-5-5"), "max_tokens": max_tokens,
                  "system": system, "messages": [{"role": "user", "content": user}]},
            timeout=90)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    body = {"model": os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"), "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        # JSON mode forces a valid JSON object. Without it, Llama models on Groq sometimes answer in their own
        # tool-call syntax, which Groq rejects with HTTP 400 or which contains no JSON at all.
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"},
        json=body, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def extract_json(text):
    """Models sometimes wrap JSON in prose or ```fences```; grab the outermost {...}."""
    text = re.sub(r"```(json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start:end + 1])


def ask_json(kind, system, user, offline=False, max_tokens=2500):
    """Returns (parsed_json_or_None, source) where source is the provider, 'cache' or 'none'."""
    cache = os.path.join(CACHE_DIR, f"last_{kind}.json")
    if offline:
        cached = load_json(cache)
        return (cached, "cache") if cached else (None, "none")
    if provider() == "none":
        return None, "none"
    try:
        LIVE.event("ai", f"AI ({provider()}) thinking about: {kind} ...")
        json_mode, text, data = True, None, None
        for wait in (3, 8, 0, 0):                       # free tiers rate-limit: back off and retry on HTTP 429
            try:
                text = _call(system, user, max_tokens, json_mode)
                try:
                    data = extract_json(text)
                except ValueError:                   # no JSON in the reply: ask once more without JSON mode
                    if json_mode:
                        json_mode = False
                        data = extract_json(_call(system, user, max_tokens, False))
                    else:
                        raise
                break
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else None
                if code == 400 and json_mode:        # provider rejected JSON mode or the generation: retry plain
                    LIVE.event("warn", f"AI 400: {e.response.text[:200]} -> retrying without JSON mode")
                    json_mode = False
                    continue
                if code != 429 or not wait:
                    if e.response is not None:
                        LIVE.event("warn", f"AI error body: {e.response.text[:300]}")
                    raise
                LIVE.event("warn", f"AI rate-limited, retrying in {wait}s")
                time.sleep(wait)
        if data is None:
            raise RuntimeError("no usable AI reply after retries")
        save_json(cache, data)
        return data, provider()
    except Exception as e:   # network, auth, rate limit, bad JSON: all fall back gracefully
        LIVE.event("warn", f"AI call failed ({e}); using cached/rule-based fallback")
        cached = load_json(cache)
        return (cached, "cache") if cached else (None, "none")
