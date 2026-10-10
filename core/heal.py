"""Closed-loop healing: FMEA finding -> pick a fix from a SAFE CATALOG -> apply -> re-run -> re-score.

The AI never edits files or runs arbitrary commands. Fixes are pre-written compose overrides in
sandbox/fixes/; we only choose WHICH ones to apply, using rules on measured evidence.
"""
import os
import subprocess

import json

from .common import LIVE, ROOT
from .llm import ask_json

FIX_DIR = os.path.join(ROOT, "sandbox", "fixes")
BASE_COMPOSE = os.path.join(ROOT, "sandbox", "docker-compose.yml")

CATALOG = {
    "redis-durable": {"file": "redis-durable.yml",
                      "why": "The queue lost accepted work when it crashed. Turn on append-only persistence (fsync always)."},
    "restart-policy": {"file": "restart-policy.yml",
                       "why": "Crashed containers stayed down until a human restarted them. Add `restart: unless-stopped`."},
}


def select_fixes(rows, results, graph):
    """Return [{id, file, why, rows:[experiment ids that triggered it]}] for rows with Action Priority != Low."""
    by_id = {r["id"]: r for r in results}
    chosen = {}

    def pick(fix_id, row_id):
        chosen.setdefault(fix_id, {"id": fix_id, **CATALOG[fix_id], "rows": []})["rows"].append(row_id)

    for row in rows:
        if row["action_priority"] == "Low":
            continue
        res = by_id.get(row["id"], {})
        steps = res.get("steps", [])
        lost = (res.get("delivery") or {}).get("lost") or 0
        if lost > 0 and any(graph["services"].get(s["target"], {}).get("role") == "queue" for s in steps):
            pick("redis-durable", row["id"])
        if any(s["type"] == "kill" for s in steps) or res.get("stuck_services"):
            pick("restart-policy", row["id"])
    return list(chosen.values())


def apply_fixes(fixes, cfg):
    cmd = ["docker", "compose", "-f", BASE_COMPOSE]
    for f in fixes:
        cmd += ["-f", os.path.join(FIX_DIR, f["file"])]
    return subprocess.run(cmd + ["up", "-d"]).returncode == 0


FIX_SYSTEM = """You are a senior SRE reviewing chaos-experiment findings (an FMEA table). You are given a CATALOG of safe,
automated fixes. Choose which catalog fixes to apply and explain why, citing numbers from the findings.
Also give extra manual recommendations that are NOT in the catalog (code or architecture changes).
Rules: use ONLY catalog ids; reference only experiment ids that appear in the findings; JSON only."""

FIX_USER = """Findings (S=severity, O=occurrence, D=detection, rpn=risk, ordered worst first):
{rows}

CATALOG of automated fixes:
{catalog}

Reply:
{{"fixes": [{{"id": "<catalog id>", "for": ["E1"], "why": "one or two sentences with numbers"}}],
  "extra_recommendations": [{{"problem": "...", "recommendation": "..."}}]}}"""


def advise_fixes(rows, results, graph, offline=False):
    """AI picks + explains catalog fixes; falls back to rules. Returns (fixes, extra_recommendations, source).

    The AI can only choose catalog ids (validated here). It never writes or runs code.
    Extra recommendations are shown to humans only and are never applied automatically."""
    rule_based = select_fixes(rows, results, graph)
    by_id = {r["id"]: r for r in results}
    compact = [{**{k: r[k] for k in ("id", "failure_mode", "effect", "S", "O", "D", "rpn", "action_priority")},
                "cascade_crashed": by_id.get(r["id"], {}).get("stuck_services")} for r in rows]
    user = FIX_USER.format(rows=json.dumps(compact, indent=1),
                           catalog="\n".join(f"- {k}: {v['why']}" for k, v in CATALOG.items()))
    data, source = ask_json("fixes", FIX_SYSTEM, user, offline=offline, max_tokens=900)
    if not data:
        return rule_based, [], "rules"
    actionable = {r["id"] for r in rows if r["action_priority"] != "Low"}
    chosen = []
    for f in data.get("fixes", []):
        if f.get("id") in CATALOG:
            targets = [i for i in f.get("for", []) if i in actionable] or sorted(actionable)
            chosen.append({"id": f["id"], **CATALOG[f["id"]], "why": str(f.get("why") or CATALOG[f["id"]]["why"])[:300],
                           "rows": targets})
    if not chosen:
        return rule_based, [], "rules"
    extras = [e for e in data.get("extra_recommendations", []) if isinstance(e, dict)][:5]
    return chosen, extras, source
