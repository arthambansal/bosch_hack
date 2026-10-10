"""DIAGNOSTICIAN AGENT (evidence-based root-cause analysis). Owner: Dipen. See blueprint 6.3 and 11.

Runs only after a suspicious result (crash cascade, lost votes, no recovery, kill switch, wrong prediction).
Now: investigate() below (ReAct agent with READ-ONLY tools: logs, container state, queue depth, DB count,
config), with a rule-based fallback. Output -> state["investigations"][experiment_id]; the Experimenter reads it.
Upgrade (Dipen): give it a timeline tool (events.log for this experiment) and a "compare with baseline" tool;
make it state confidence honestly and list what evidence would change its mind.
"""
from core.agentkit import ReActAgent
from core.common import LIVE
from core.tools import make_tools

from ..runtime import cfg

INVESTIGATION_SCHEMA = {"root_cause": "one or two sentences", "evidence": ["quote or number from a tool"],
                        "affected_services": ["service"], "confidence": "high|medium|low",
                        "suggested_fix": "one concrete change"}


def investigate(cfg, graph, res, offline=False):
    facts = {k: res.get(k) for k in ("name", "status", "abort_reason", "recovery_s", "stuck_services",
                                     "stuck_details", "delivery", "prediction", "prediction_check")}
    # what was REALLY injected (e.g. "LATENCY 400ms -> redis"). The raw step field delay_s is only the wait before the
    # step starts, so it is NOT passed: a model once read delay_s=0 as "no latency was injected".
    facts["faults_injected"] = res.get("faults_injected") or [f"{s['type']} -> {s['target']}" for s in res.get("steps", [])]
    facts["note"] = ("Faults were injected for the fault window and then removed. If an injected fault shows no effect, "
                     "the system tolerated it; do not claim the fault was missing unless a tool shows that. 'KILL SWITCH' in the "
                     "logs is OUR safety system restoring services after the error rate got too high; it never causes "
                     "failures. delivery.lost is the number of lost votes: do not claim more than that.")
    facts["error_rate_by_probe"] = {k: v.get("error_rate") for k, v in (res.get("probes") or {}).items()}
    agent = ReActAgent(
        "Diagnostician",
        "an SRE doing root-cause analysis right after a chaos experiment. Use read-only tools (logs, container "
        "state, queue depth, database count, config) to explain WHY the system behaved the way it did",
        make_tools(cfg, graph), INVESTIGATION_SCHEMA, max_steps=5, offline=offline,
        starters=[("list_containers", {})] + [("container_logs", {"service": n, "lines": 20}) for n in
                                              (res.get("stuck_services") or [st["target"] for st in res.get("steps", [])])[:3]])
    final, trace = agent.run(f"Explain the root cause of what happened in experiment {res.get('id')}.", facts)
    return {"final": final, "tool_calls": len(trace), "trace": trace}


def rule_based(res):
    stuck, details = res.get("stuck_services") or [], res.get("stuck_details") or {}
    lost = (res.get("delivery") or {}).get("lost") or 0
    if stuck:
        ev = [f"{s} exit code {details.get(s, {}).get('exit_code', '?')}" for s in stuck]
        ev += [line for s in stuck for line in details.get(s, {}).get("last_logs", [])[-2:]]
        return {"root_cause": f"{', '.join(stuck)} crashed during the fault and has no restart policy, so it stayed down",
                "evidence": ev, "affected_services": stuck, "confidence": "medium",
                "suggested_fix": "restart: unless-stopped, plus reconnect-with-retry in the client"}
    if lost:
        return {"root_cause": f"{lost} accepted votes never reached the database; the queue does not persist data",
                "evidence": [f"delivery audit: {res['delivery']}"], "affected_services": [s["target"] for s in res["steps"]],
                "confidence": "medium", "suggested_fix": "enable Redis append-only persistence"}
    return {"root_cause": res.get("abort_reason") or "behaviour differed from the prediction",
            "evidence": [str(res.get("prediction_check"))], "affected_services": [s["target"] for s in res["steps"]],
            "confidence": "low", "suggested_fix": "investigate manually"}


def diagnostician_node(state):
    LIVE.set(agent_active="diagnostician")
    res = state["results"][-1]
    out = investigate(cfg(), state["graph"], res, offline=state.get("offline", False))
    final = out.get("final")
    cause = str((final or {}).get("root_cause", "")).strip()
    if not final or len(cause) < 25 or cause.upper().startswith("KILL SWITCH"):   # empty or just a copied log line
        final = None
    final = final or rule_based(res)
    final["by"] = "agent" if out.get("final") and final is out.get("final") else "rules"
    LIVE.event("ai", f"[Diagnostician] {res['id']} root cause: {final.get('root_cause')}")
    inv = dict(state.get("investigations") or {})
    inv[res["id"]] = final
    return {"investigations": inv}
