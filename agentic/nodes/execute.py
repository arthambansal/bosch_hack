"""EXECUTOR, EVALUATOR and VERIFIER. Deterministic code, no AI. Owner: Artham.

execute  : runs the approved experiment through core/engine.py (fault injection + Guard kill switch + recovery +
           cascade check + data-delivery audit).
evaluate : FMEA scoring of everything so far; decides whether the last result needs an investigation.
verify   : after fixes are applied, re-runs the experiments the fixes targeted and compares RPN before/after.
"""
import os

from core.common import LIVE, STOP_FILE, save_json
from core.fmea import build_fmea, compare_fmea

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


def evaluate_node(state):
    LIVE.set(agent_active="evaluator")
    results = state["results"]
    rows = build_fmea(results, state.get("baseline", {}))
    save_json(os.path.join(run_dir(), "results.json"), results)
    save_json(os.path.join(run_dir(), "fmea.json"), rows)
    LIVE.set(fmea=rows, queue=[{"id": r["id"], "name": r["name"], "status": r["status"], "reason": r.get("reason"),
                                "root_cause": (state.get("investigations") or {}).get(r["id"], {}).get("root_cause")}
                               for r in results])
    return {"fmea": rows}


def needs_investigation(state):
    return "diagnostician" if anomalous(state["results"][-1]) else "experimenter"


def verify_node(state):
    LIVE.set(agent_active="verifier")
    ids = sorted({i for f in state.get("fixes", []) for i in f.get("rows", [])})
    by_id = {r["id"]: r for r in state["results"]}
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
    improved = bool(cmp) and all(c["rpn_after"] < c["rpn_before"] for c in cmp)
    for c in cmp:
        LIVE.event("ok" if c["rpn_after"] < c["rpn_before"] else "warn",
                   f"[Verifier] {c['id']} RPN {c['rpn_before']} -> {c['rpn_after']} ({c['reduction_pct']}% lower)")
    save_json(os.path.join(run_dir(), "verification.json"), {"compare": cmp, "results": after})
    LIVE.set(fmea_compare=cmp)
    return {"verification": {"compare": cmp, "improved": improved, "results": after}, "pending_fix": False}
