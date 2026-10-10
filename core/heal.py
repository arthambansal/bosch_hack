"""Closed-loop healing: FMEA finding -> pick a fix from a SAFE CATALOG -> apply -> re-run -> re-score.

The AI never edits files or runs arbitrary commands. Fixes are pre-written compose overrides in
sandbox/fixes/; we only choose WHICH ones to apply, using rules on measured evidence.
"""
import os
import subprocess

from .common import ROOT

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
        if any(s["type"] == "kill" for s in steps):
            pick("restart-policy", row["id"])
    return list(chosen.values())


def apply_fixes(fixes, cfg):
    cmd = ["docker", "compose", "-f", BASE_COMPOSE]
    for f in fixes:
        cmd += ["-f", os.path.join(FIX_DIR, f["file"])]
    return subprocess.run(cmd + ["up", "-d"]).returncode == 0
