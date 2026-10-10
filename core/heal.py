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
    "postgres-healthcheck": {"file": "postgres-healthcheck.yml",
                             "why": "Worker and result can start before Postgres is ready. Add a Postgres readiness check and make dependent services wait for a healthy database."},
    "postgres-recovery": {"file": "postgres-recovery.yml",
                          "why": "Worker and result exited during the Postgres outage and did not recover within the timeout. Restart them on failure."},
}


def select_fixes(rows, results, graph):
    """Return [{id, file, why, rows:[experiment ids that triggered it]}] for rows with Action Priority != Low."""
    by_id = {r["id"]: r for r in results}
    chosen = {}

    def pick(fix_id, row_id):
        chosen.setdefault(fix_id, {"id": fix_id, **CATALOG[fix_id], "rows": []})["rows"].append(row_id)

    for row in rows:
        res = by_id.get(row["id"], {})
        steps = res.get("steps", [])

        if row["action_priority"] == "Low":
            continue
        lost = (res.get("delivery") or {}).get("lost") or 0
        if lost > 0 and any(graph["services"].get(s["target"], {}).get("role") == "queue" for s in steps):
            pick("redis-durable", row["id"])
        if any(s["type"] == "kill" for s in steps) or res.get("stuck_services"):
            pick("restart-policy", row["id"])
    return list(chosen.values())


def fix_entries(fixes):
    """Convert applied catalog fixes into contract-compatible entries."""
    entries = []

    for fix in fixes:
        if not isinstance(fix, dict) or fix.get("status") != "applied":
            continue

        entries.append({
            "id": fix.get("id", "unknown"),
            "title": fix.get("title", fix.get("id", "Applied fix")),
            "kind": fix.get("kind", "compose"),
            "for": fix.get("for", fix.get("rows", [])),
            "why": fix.get("why", ""),
            "diff": fix.get("diff"),
            "status": "applied",
            "rpn": fix.get("rpn", []),
        })

    return entries


def apply_fixes(fixes, cfg):
    cmd = ["docker", "compose", "-f", BASE_COMPOSE]

    for fix in fixes:
        filename = fix.get("file", "")
        if not isinstance(filename, str) or not filename:
            LIVE.event("warn", "[Remediator] rejected fix with missing filename")
            return False

        path = os.path.realpath(os.path.join(FIX_DIR, filename))
        if os.path.commonpath([os.path.realpath(FIX_DIR), path]) != os.path.realpath(FIX_DIR):
            LIVE.event("warn", "[Remediator] rejected path outside fix directory")
            return False

        if not os.path.isfile(path):
            LIVE.event("warn", f"[Remediator] fix file not found: {filename}")
            return False

        cmd += ["-f", path]

    try:
        result = subprocess.run(cmd + ["up", "-d"], check=False, timeout=180)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as exc:
        LIVE.event("warn", f"[Remediator] compose apply failed: {exc}")
        return False


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

# ---------------------------------------------------------------------------
# AI-GENERATED REMEDIATION: strict whitelist, validated before Docker sees it.
# Generated overrides are JSON, which is also valid YAML.
# ---------------------------------------------------------------------------

import hashlib

GENERATED_DIR = os.path.join(FIX_DIR, "generated")

ALLOWED_SERVICES = {"vote", "result", "worker", "redis", "db"}
ALLOWED_KEYS = {
    "restart",
    "deploy",
    "depends_on",
    "healthcheck",
}

def validate_generated_override(override):
    """Accept only a small, explicit Docker Compose override schema."""
    if not isinstance(override, dict) or set(override) != {"services"}:
        return False, "Expected exactly one top-level 'services' object"

    services = override["services"]
    if not isinstance(services, dict) or not services:
        return False, "Services must be a non-empty object"

    for service, config in services.items():
        if service not in ALLOWED_SERVICES or not isinstance(config, dict):
            return False, f"Invalid service or configuration: {service}"

        if not config:
            return False, f"Empty configuration for {service}"

        for key, value in config.items():
            if key not in ALLOWED_KEYS:
                return False, f"Forbidden key: {key}"

            if key == "restart":
                if value not in {"no", "always", "on-failure", "unless-stopped"}:
                    return False, "Invalid restart policy"

            elif key == "healthcheck":
                if not isinstance(value, dict) or not value:
                    return False, "healthcheck must be a non-empty object"
                if set(value) - {"test", "interval", "timeout", "retries", "start_period", "disable"}:
                    return False, "Forbidden healthcheck field"
                if "test" in value and (
                    not isinstance(value["test"], list)
                    or not value["test"]
                    or not all(isinstance(x, str) for x in value["test"])
                ):
                    return False, "healthcheck.test must be a list of strings"

            elif key == "deploy":
                if service not in ALLOWED_SERVICES or not isinstance(value, dict):
                    return False, "deploy must be an object"
                if set(value) != {"resources"} or not isinstance(value["resources"], dict):
                    return False, "Only deploy.resources is allowed"
                resources = value["resources"]
                if set(resources) - {"limits", "reservations"}:
                    return False, "Only resource limits/reservations are allowed"
                for section in resources.values():
                    if not isinstance(section, dict) or set(section) - {"cpus", "memory"}:
                        return False, "Only CPU and memory limits are allowed"
                    if any(not isinstance(v, (str, int, float)) for v in section.values()):
                        return False, "Resource values must be strings or numbers"

            elif key == "depends_on":
                if not isinstance(value, dict) or not value:
                    return False, "depends_on must be an object"
                for dependency, condition in value.items():
                    if dependency not in ALLOWED_SERVICES or not isinstance(condition, dict):
                        return False, "Invalid dependency"
                    if set(condition) != {"condition"} or condition["condition"] not in {
                        "service_started", "service_healthy", "service_completed_successfully"
                    }:
                        return False, "Invalid dependency condition"

        # 'command' is allowed only for Redis and only for a fixed safe pattern.
        # It is deliberately not included in ALLOWED_KEYS above; handle it
        # separately only after an explicit Redis-specific check.

    return True, "valid"


def draft_ai_remediation(rows, results, graph, existing_fixes, offline=False):
    """Draft one safe compose override and one human-readable, unapplied code patch."""
    actionable = [r for r in rows if r.get("action_priority") != "Low"]
    if not actionable:
        return None, None

    # Keep the feature bounded and avoid repeatedly applying the same generated fix.
    if any(f.get("id") == "ai-generated-override" for f in existing_fixes):
        return None, None

    evidence = []
    result_by_id = {r.get("id"): r for r in results}
    for row in actionable[:5]:
        result = result_by_id.get(row.get("id"), {})
        evidence.append({
            "id": row.get("id"),
            "failure_mode": row.get("failure_mode"),
            "effect": row.get("effect"),
            "rpn": row.get("rpn"),
            "steps": result.get("steps", []),
            "lost": (result.get("delivery") or {}).get("lost", 0),
            "stuck_services": result.get("stuck_services", []),
        })

    system = """
You are a cautious site reliability engineer. Propose ONE minimal Docker Compose
override that may reduce the observed failure risk.

Return JSON only:
{
  "override": {"services": {"service_name": {"allowed_key": "value"}}} or null,
  "why": "evidence-based explanation",
  "code_patch": {"problem": "...", "diff": "...", "recommendation": "..."} or null
}

Allowed services: vote, result, worker, redis, db.
Allowed keys: restart, deploy.resources, depends_on.condition.
Never include command, healthcheck, ports, volumes, environment,
build, image, privileged, network, shell scripts, or other keys.
The code patch is a suggestion only. It will NEVER be executed or applied.
Use evidence from the supplied findings. If no safe useful override exists,
return override=null. Do not claim a fix is proven before verification.
"""

    user = json.dumps({"findings": evidence, "services": graph.get("services", {})})
    data, source = ask_json(
        "remediation_draft", system, user, offline=offline, max_tokens=1200
    )
    if not data:
        return None, None

    override = data.get("override")
    if override is None:
        return None, data.get("code_patch")

    ok, reason = validate_generated_override(override)
    if not ok:
        LIVE.event("warn", f"[Remediator] rejected generated override: {reason}")
        return None, data.get("code_patch")

    row_ids = [r["id"] for r in actionable if r.get("id")]
    if not row_ids:
        return None, data.get("code_patch")

    os.makedirs(GENERATED_DIR, exist_ok=True)
    path = os.path.join(GENERATED_DIR, "ai-override.yml")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(override, handle, indent=2)

    fix = {
        "id": "ai-generated-override",
        "file": "generated/ai-override.yml",
        "why": str(data.get("why") or "AI-generated override based on FMEA evidence")[:300],
        "rows": row_ids,
    }
    LIVE.event("ai", f"[Remediator] validated AI override using {source}")
    return fix, data.get("code_patch")
