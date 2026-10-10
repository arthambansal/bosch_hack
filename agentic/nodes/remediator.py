"""REMEDIATOR AGENT (fix + verification plan). Owner: Pratham (with core/heal.py and sandbox/fixes/); see blueprint 6.4 and 12.

Job: turn findings into fixes, apply them IN THE SANDBOX, and hand over to the verifier.
Now: core/heal.advise_fixes (AI chooses from a safe catalog of compose overrides + gives manual recommendations),
then core/heal.apply_fixes. Max 2 attempts; if verification shows no improvement it tries fixes not yet applied.
Upgrade (Pratham, Day 2): let the agent DRAFT a new compose override (only keys: restart, healthcheck, command for redis,
deploy.resources), validate it against that whitelist, save it to sandbox/fixes/generated/, apply, and let the
verifier decide whether to keep it. Also let it draft a code-level patch suggestion (shown, never applied).
"""
import time

from core.common import LIVE
from core.heal import advise_fixes, apply_fixes, draft_ai_remediation
from ..runtime import cfg


def remediator_node(state):
    LIVE.set(agent_active="remediator")
    if state.get("skip_heal") or not state.get("fmea") or state.get("fix_attempts", 0) >= 2:
        return {"pending_fix": False}
    fixes, extras, source = advise_fixes(state["fmea"], state["results"], state["graph"],
                                         offline=state.get("offline", False))
    applied = state.get("fixes", [])

    generated_fix, code_patch = draft_ai_remediation(
        state["fmea"],
        state["results"],
        state["graph"],
        applied,
        offline=state.get("offline", False),
    )

    if code_patch:
        LIVE.event(
            "ai",
            "[Remediator] code patch suggestion (NOT applied): "
            + str(code_patch)[:700],
        )

    if generated_fix:
        fixes.append(generated_fix)

    banned = set(state.get("rolled_back", [])) | set(state.get("rollback_failed", []))     # the Verifier proved these made things worse
    new = [f for f in fixes if f["id"] not in {a["id"] for a in applied} | banned]
    for e in extras:
        LIVE.event("ai", f"[Remediator] manual recommendation: {e.get('problem')} -> {e.get('recommendation')}")
    if not new:
        LIVE.event("info", "[Remediator] no new catalog fix to try")
        return {"pending_fix": False, "recommendations": extras or state.get("recommendations", [])}
    for f in new:
        LIVE.event("ai", f"[Remediator] ({source}) applying {f['id']} for {f['rows']}: {f['why']}")
    all_fixes = applied + new
    ok = apply_fixes(all_fixes, cfg())
    if not ok and any(f["id"] == "ai-generated-override" for f in new):
        # One bad AI-drafted file must not throw away the proven catalog fixes: retry without it.
        LIVE.event("warn", "[Remediator] docker compose rejected the AI-drafted override; applying the catalog fixes without it")
        new = [f for f in new if f["id"] != "ai-generated-override"]
        all_fixes = applied + new
        ok = bool(new) and apply_fixes(all_fixes, cfg())
    if not ok:
        LIVE.event("warn", "[Remediator] docker compose could not apply the fixes; restoring the last good sandbox state")
        apply_fixes(applied, cfg())            # bring every service back (base compose + fixes that already worked)
        return {"pending_fix": False}
    time.sleep(12)   # let recreated containers come up
    return {"fixes": all_fixes, "recommendations": extras, "fix_attempts": state.get("fix_attempts", 0) + 1,
            "pending_fix": True}
