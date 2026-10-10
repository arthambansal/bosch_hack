"""EXECUTOR, EVALUATOR and VERIFIER. Deterministic code, no AI. Owner: Artham.

execute  : runs the approved experiment through core/engine.py (fault injection + Guard kill switch + recovery +
           cascade check + data-delivery audit).
evaluate : FMEA scoring of everything so far; decides whether the last result needs an investigation.
verify   : after fixes are applied, re-runs the experiments the fixes targeted and compares RPN before/after.
"""
import os
import time

from core.common import LIVE, STOP_FILE, save_json
from core.fmea import build_fmea, compare_fmea
from core.knowledge import load_observation

from ..runtime import engine, run_dir


def anomalous(res):
    """True when a result looks suspicious enough to send to the Diagnostician."""
    d = res.get("delivery") or {}
    check = res.get("prediction_check") or {}
    return bool(res.get("stuck_services") or (d.get("lost") or 0) > 0 or res.get("recovery_s") is None
                or res.get("status") == "aborted" or False in check.values())


def execute_node(state):
    LIVE.set(agent_active="executor")
    res = engine().run_experiment(state["proposal"])
    return {"results": state.get("results", []) + [res], "proposal": None}


def predictions_summary(results):
    """live_state.predictions (contract 4.6). An item is correct only if no field of the check is false."""
    items = []
    for r in results:
        check = r.get("prediction_check")
        if not check:
            continue
        items.append({"id": r["id"], "predicted": r.get("prediction") or {}, "check": check,
                      "correct": all(v is not False for v in check.values())})
    return {"items": items, "right": sum(1 for i in items if i["correct"]), "total": len(items)}


def evaluate_node(state):
    LIVE.set(agent_active="evaluator")
    results = state["results"]
    LIVE.set(predictions=predictions_summary(results))
    rows = build_fmea(results, state.get("baseline", {}))
    save_json(os.path.join(run_dir(), "results.json"), results)
    save_json(os.path.join(run_dir(), "fmea.json"), rows)
    LIVE.set(fmea=rows, queue=[{"id": r["id"], "name": r["name"], "status": r["status"], "reason": r.get("reason"),
                                "root_cause": (state.get("investigations") or {}).get(r["id"], {}).get("root_cause")}
                               for r in results])
    return {"fmea": rows}


def needs_investigation(state):
    result = state["results"][-1]
    observed = load_observation(result.get("id")) or {}
    exited = any(e.get("event") == "die" and str(e.get("exit_code", "0")) != "0"
                 for e in observed.get("events") or [])
    return "diagnostician" if anomalous(result) or exited else "experimenter"


def fix_statuses(fixes, cmp):
    """Per-fix verdict from the FMEA before/after comparison, judged on the rows each fix is responsible for.
    rolled_back = a row got WORSE; verified = every row improved; not_improved = anything else."""
    by_row = {c["id"]: c for c in cmp}
    out = {}
    for f in fixes:
        rows = [by_row[r] for r in f.get("rows", []) if r in by_row]
        worse = [c for c in rows if c["rpn_after"] > c["rpn_before"]]
        if worse:
            out[f["id"]] = {"status": "rolled_back", "worse": worse[0]}
        elif rows and len(rows) == len(f.get("rows", [])) and all(c["rpn_after"] < c["rpn_before"] for c in rows):
            out[f["id"]] = {"status": "verified"}
        else:
            out[f["id"]] = {"status": "not_improved"}
    return out


def publish_fixes(fixes, statuses, cmp, investigations=None, results=()):
    """live_state.fixes (contract 4.4): applied catalog fixes with their verdict and RPN, plus code suggestions (proposed only)."""
    from core.heal import fix_entries
    from core.patches import suggest_patches
    by_row = {c["id"]: c for c in cmp}
    entries = fix_entries([{**f, "status": "applied"} for f in fixes])   # state fixes carry no status; fix_entries only lists applied ones
    for e in entries:
        verdict = statuses.get(e["id"]) or {}
        e["status"] = verdict.get("status", e.get("status", "applied"))
        e["rollback_failed"] = bool(verdict.get("rollback_failed"))      # made things worse AND docker could not undo it
        worse = verdict.get("worse") if e["rollback_failed"] else None
        e["worse"] = {"id": worse["id"], "before": worse["rpn_before"], "after": worse["rpn_after"]} if worse else None
        e["rpn"] = [{"id": r, "before": by_row[r]["rpn_before"], "after": by_row[r]["rpn_after"]}
                    for r in e.get("for", []) if r in by_row]
    try:
        entries += [dict(x, status="proposed", rollback_failed=False, worse=None) for x in (suggest_patches(investigations or {}, list(results)) or [])]
    except Exception as exc:  # noqa: BLE001 - suggestions are a bonus
        LIVE.event("warn", f"[Verifier] code suggestions skipped ({type(exc).__name__})")
    LIVE.set(fixes=entries)
    return entries


def _notify(kind, title, text, fields=None):
    try:
        from core.notify import notify
        notify(kind, title, text, fields)
    except Exception:  # noqa: BLE001 - a notification can never change the verdict
        pass


def verify_node(state):
    LIVE.set(agent_active="verifier")
    fixes = list(state.get("fixes", []))
    ids = sorted({i for f in fixes for i in f.get("rows", [])})
    by_id = {r["id"]: r for r in state["results"]}
    publish_fixes(fixes, {}, [], state.get("investigations"), state["results"])        # shown as "applied" while we re-test
    after = []
    for i in ids:
        r = by_id.get(i)
        if not r:
            continue
        if os.path.exists(STOP_FILE):                 # STOP between verification experiments: do not start the next one
            LIVE.event("guard", f"[Verifier] STOP requested: skipping {i} and the rest")
            break
        exp = {k: r.get(k) for k in ("id", "name", "steps", "reason", "hypothesis", "predicted_probes")}
        LIVE.event("info", f"[Verifier] re-running {i} against the fixed system")
        after.append(engine().run_experiment(exp))
    before_rows = [row for row in state["fmea"] if row["id"] in ids]
    cmp = compare_fmea(before_rows, build_fmea(after, state.get("baseline", {})))
    for c in cmp:
        LIVE.event("ok" if c["rpn_after"] < c["rpn_before"] else "warn",
                   f"[Verifier] {c['id']} RPN {c['rpn_before']} -> {c['rpn_after']} ({c['reduction_pct']}% lower)")

    statuses = fix_statuses(fixes, cmp)
    rolled = [f for f in fixes if statuses[f["id"]]["status"] == "rolled_back"]
    kept = [f for f in fixes if statuses[f["id"]]["status"] != "rolled_back"]
    if rolled and not os.path.exists(STOP_FILE):
        from core.heal import apply_fixes
        for f in rolled:
            w = statuses[f["id"]]["worse"]
            LIVE.event("guard", f"[Verifier] {f['id']} made {w['id']} worse ({w['rpn_before']} -> {w['rpn_after']}): rolling back")
        done = apply_fixes(kept, engine().cfg)        # an empty list restores the base compose
        if done:
            time.sleep(12)                            # let recreated containers come up
        else:
            LIVE.event("warn", "[Verifier] rollback: docker compose could not re-apply the kept fixes")
        for f in rolled:                              # tell people only AFTER the rollback has really finished (or failed)
            w = statuses[f["id"]]["worse"]
            if not done:                              # the fix is STILL running: never publish it as rolled back
                statuses[f["id"]] = {"status": "applied", "worse": w, "rollback_failed": True}
            if done:
                _notify("fix_rolled_back", f"Fix rolled back: {f['id']}",
                        f"{f['id']} made {w['id']} worse (RPN {w['rpn_before']} -> {w['rpn_after']}), so ChaosPilot undid it.",
                        {"fix": f["id"], "experiment": w["id"]})
            else:
                _notify("fix_rollback_failed", f"Rollback FAILED: {f['id']}",
                        f"{f['id']} made {w['id']} worse but docker compose could not undo it. Check the sandbox by hand.",
                        {"fix": f["id"], "experiment": w["id"]})
    elif rolled:                                      # STOP file present: nothing was undone, so do not claim it was
        for f in rolled:
            statuses[f["id"]] = {"status": "applied", "worse": statuses[f["id"]]["worse"], "rollback_failed": True}
    for f in kept:
        if statuses[f["id"]]["status"] == "verified":
            rows = [c for c in cmp if c["id"] in f.get("rows", [])]
            _notify("fix_verified", f"Fix verified: {f['id']}",
                    "; ".join(f"{c['id']} RPN {c['rpn_before']} -> {c['rpn_after']}" for c in rows),
                    {"fix": f["id"]})

    failed = [f for f in rolled if statuses[f["id"]].get("rollback_failed")]      # still applied, could not be undone
    rolled = [f for f in rolled if f not in failed]
    kept = kept + failed
    improved = bool(kept) and all(statuses[f["id"]]["status"] == "verified" for f in kept)
    summary = {f["id"]: statuses[f["id"]]["status"] for f in fixes}
    save_json(os.path.join(run_dir(), "verification.json"), {"compare": cmp, "results": after, "fix_status": summary})
    LIVE.set(fmea_compare=cmp)
    publish_fixes(fixes, statuses, cmp, state.get("investigations"), state["results"])
    return {"verification": {"compare": cmp, "improved": improved, "results": after, "fix_status": summary},
            "fixes": kept, "rolled_back": sorted(set(state.get("rolled_back", [])) | {f["id"] for f in rolled}),
            "rollback_failed": sorted(set(state.get("rollback_failed", [])) | {f["id"] for f in failed}),
            "pending_fix": False}
