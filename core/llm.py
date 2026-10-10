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
import hashlib
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


NO_REASONING_PARAM = {"on": False}   # set when a provider rejects reasoning_effort


def _call(system, user, max_tokens, json_mode=True, model=None):
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
    model = model or os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    reasoning = "gpt-oss" in model or os.getenv("LLM_REASONING_EFFORT")
    body = {"model": model, "temperature": 0.2,
            # reasoning models (gpt-oss) spend tokens THINKING first; a small budget leaves the answer empty
            "max_tokens": max(max_tokens, 1500) if reasoning else max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if reasoning and not NO_REASONING_PARAM["on"]:
        body["reasoning_effort"] = os.getenv("LLM_REASONING_EFFORT", "low")
    if json_mode:
        # JSON mode forces a valid JSON object. Without it, some models answer in their own tool-call syntax,
        # which Groq rejects with HTTP 400 or which contains no JSON at all.
        body["response_format"] = {"type": "json_object"}
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"},
        json=body, timeout=90)
    r.raise_for_status()
    choice = r.json()["choices"][0]
    msg = choice["message"]
    content = msg.get("content") or ""
    if not content.strip() and msg.get("tool_calls"):
        # the model used its NATIVE function calling instead of our JSON protocol: translate it
        try:
            fn = msg["tool_calls"][0]["function"]
            return json.dumps(_call_to_protocol(fn["name"], fn.get("arguments") or "{}"))
        except (KeyError, IndexError, ValueError, TypeError):
            pass
    if not content.strip():
        # some reasoning models leave the answer in a separate 'reasoning' field
        reasoning_text = msg.get("reasoning") or msg.get("reasoning_content") or ""
        if "{" in reasoning_text and "}" in reasoning_text:
            return reasoning_text
        raise ValueError(f"empty reply: finish_reason={choice.get('finish_reason')}, message fields={sorted(msg)}, "
                         f"reasoning starts: {reasoning_text[:150]!r}")
    return content


def extract_json(text):
    """Models sometimes wrap JSON in prose or ```fences```, or print two objects. Return the FIRST valid object."""
    text = re.sub(r"```(json)?", "", text)
    dec, pos = json.JSONDecoder(), 0
    while True:
        start = text.find("{", pos)
        if start == -1:
            raise ValueError("no JSON object in model reply")
        try:
            obj, _ = dec.raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        pos = start + 1


def _call_to_protocol(name, args):
    """Turn a native function call into OUR protocol {"thought","tool","args"} (or {"thought","final"}).
    gpt-oss often nests our whole JSON reply inside its call, e.g. name=container_logs with
    args={"thought": "...", "tool": "list_containers", "args": {}}. The nested tool name is the real intent."""
    if isinstance(args, str):
        args = json.loads(args or "{}")
    name = str(name or "").split(".")[-1].strip()
    thought = "(requested a tool call)"
    if isinstance(args, dict) and isinstance(args.get("final"), dict):
        return {"thought": str(args.get("thought") or "(final answer)"), "final": args["final"]}
    if isinstance(args, dict) and isinstance(args.get("tool"), str) and args["tool"].strip():
        thought = str(args.get("thought") or thought)
        name = args["tool"].split(".")[-1].strip()
        args = args.get("args")
    if not name or not isinstance(args, dict):
        args = args if isinstance(args, dict) else {}
    return {"thought": thought, "tool": name, "args": args}


def _salvage_tool_call(resp):
    """Some models ignore our JSON protocol and try their own native function call. Groq then answers HTTP 400
    'tool_use_failed' but includes what the model wanted in error.failed_generation, e.g.
    {"name": "repo_browser.list_containers", "arguments": {}} or <function=list_containers>{}</function>.
    Convert that into OUR protocol {"tool": ..., "args": ...} so the agent can carry on. Returns None if not possible."""
    try:
        err = resp.json().get("error", {})
        if err.get("code") != "tool_use_failed":
            return None
        text = err.get("failed_generation") or ""
        m = re.search(r"<function=([\w.]+)[^{]*(\{.*\})", text, re.S)
        if m:
            name, args = m.group(1), json.loads(m.group(2))
        else:
            call = extract_json(text)
            name, args = call.get("name") or call.get("tool"), call.get("arguments", call.get("args", {}))
        out = _call_to_protocol(name, args)
        if out.get("final") or out.get("tool"):
            return out
    except Exception:  # noqa: BLE001 - salvage is best effort
        pass
    return None


NUDGE = "\n\nYour previous reply was not valid JSON. Reply with exactly ONE JSON object and no other text."


def _key(kind, system, user):
    return hashlib.sha1((kind + system + user).encode()).hexdigest()[:12]


def ask_json(kind, system, user, offline=False, max_tokens=2500, tool_agent=False):
    """Returns (parsed_json_or_None, source) where source is the provider, 'cache' or 'none'.

    Online: a failed call returns (None, 'none') so the caller uses its rule-based fallback. It NEVER serves an old
    cached answer as if it were new (that once showed experiment E1's diagnosis for E3).
    --offline: replays the answer cached for the identical prompt, else the last answer of that kind.
    tool_agent=True (used by ReAct agents): skip JSON mode (models then try native function calls anyway) and turn a
    rejected native tool call into our {"tool", "args"} protocol."""
    last = os.path.join(CACHE_DIR, f"last_{kind}.json")
    exact = os.path.join(CACHE_DIR, f"{kind}_{_key(kind, system, user)}.json")
    if offline:
        cached = load_json(exact) or load_json(last)
        return (cached, "cache") if cached else (None, "none")
    if provider() == "none":
        return None, "none"
    try:
        LIVE.event("ai", f"AI ({provider()}) thinking about: {kind} ...")
        # attempt 1: JSON mode. attempt 2: plain. attempt 3: plain plus a reminder. HTTP 429 waits and repeats.
        attempts = ([(False, user), (False, user + NUDGE)] if tool_agent
                    else [(True, user), (False, user), (False, user + NUDGE)])
        rate_waits, net_waits, i, data = [3, 8, 15, 20], [2, 5, 10], 0, None
        # optional separate model for the tool-using agents (export LLM_AGENT_MODEL=...); the Experimenter keeps LLM_MODEL
        extra = {"model": os.environ["LLM_AGENT_MODEL"]} if tool_agent and os.getenv("LLM_AGENT_MODEL") else {}
        while i < len(attempts) and data is None:
            json_mode, prompt = attempts[i]
            try:
                data = extract_json(_call(system, prompt, max_tokens, json_mode, **extra))
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else None
                if code == 400 and tool_agent and e.response is not None:
                    data = _salvage_tool_call(e.response)
                    if data:
                        break
                if code == 429 and rate_waits:
                    wait = rate_waits.pop(0)
                    try:                              # Groq says how long to wait ("retry-after" seconds): use it
                        wait = min(max(float(e.response.headers.get("retry-after")) + 0.5, wait), 25)
                    except (TypeError, ValueError, AttributeError):
                        pass
                    LIVE.event("warn", f"AI rate-limited, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                body = e.response.text[:200] if e.response is not None else ""
                if code == 400 and "reasoning_effort" in body.lower() and not NO_REASONING_PARAM["on"]:
                    NO_REASONING_PARAM["on"] = True          # this provider does not know the parameter: drop it
                    continue
                if code in (401, 403, 404) or i == len(attempts) - 1:
                    LIVE.event("warn", f"AI error body: {body}")
                    raise
                LIVE.event("warn", f"AI HTTP {code}: {body} -> retry {i + 2}/{len(attempts)}")
                i += 1
            except (requests.ConnectionError, requests.Timeout) as e:
                if net_waits:                       # Wi-Fi blip / DNS hiccup: wait and try the same request again
                    wait = net_waits.pop(0)
                    LIVE.event("warn", f"AI network problem ({type(e).__name__}), retrying in {wait}s")
                    time.sleep(wait)
                    continue
                raise
            except ValueError as e:
                more = i + 1 < len(attempts)
                LIVE.event("warn", f"AI reply unusable ({str(e)[:300]})" + (f" -> retry {i + 2}/{len(attempts)}" if more else ""))
                i += 1
        if data is None:
            raise RuntimeError("no usable AI reply after retries")
        save_json(last, data)
        save_json(exact, data)
        return data, provider()
    except Exception as e:   # network, auth, rate limit, bad JSON: the caller falls back to its rules
        LIVE.event("warn", f"AI call failed ({e}); using the rule-based fallback")
        return None, "none"
