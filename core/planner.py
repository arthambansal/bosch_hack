"""AI experiment planner.

1. Generate every SAFE candidate experiment from the dependency map (service x fault type).
2. Give each a deterministic risk score (fallback ranking, and context for the AI).
3. Ask the LLM to pick and order the most informative experiments, with a reason for each,
   optionally combining two candidates into a combined failure.
4. VALIDATE the AI answer: it may only reference candidate ids we generated. The AI proposes,
   the code disposes - it can never invent a target outside the sandbox.
"""
import json

from .common import LIVE, PLAN_FILE, dependents_closure, probes_affected, save_json
from .faults import FAULT_TYPES
from .llm import ask_json

FAULT_WEIGHT = {"kill": 3, "partition": 3, "pause": 2, "latency": 2, "spike": 2}

HYPOTHESIS = {
    "kill": "Callers fail fast (no hang), the service recovers after restart, and no accepted data is lost.",
    "pause": "Callers time out quickly instead of hanging; the guard should catch it within seconds.",
    "partition": "Callers detect the lost dependency and recover once the network returns (DNS re-resolves).",
    "latency": "Added latency degrades response time proportionally without causing errors.",
    "spike": "The entry point absorbs a burst without 5xx errors; latency rises but recovers.",
}


def candidates(cfg, graph):
    out = []
    for name, svc in graph["services"].items():
        types = ["kill", "pause", "partition"]
        if svc["stateful"]:
            types.append("latency")
        if svc["role"] == "entrypoint" and any(p["entry"] == name for p in cfg["probes"]):
            types.append("spike")
        dependents = sorted(dependents_closure(graph, name))
        for f in types:
            predicted = probes_affected(cfg, graph, [name])
            risk = (2 * len(dependents) + 3 * svc["stateful"] + 2 * (svc["role"] == "entrypoint")
                    + FAULT_WEIGHT[f] + 2 * len(predicted))
            out.append({"id": f"{f}:{name}", "type": f, "target": name, "risk_score": risk,
                        "dependents": dependents, "predicted_probes": predicted})
    return sorted(out, key=lambda c: -c["risk_score"])


def _reason(c, graph):
    svc = graph["services"][c["target"]]
    deps = ", ".join(c["dependents"]) or "nothing"
    seen = ("is predicted to break " + ", ".join(c["predicted_probes"])) if c["predicted_probes"] \
        else "touches no user-facing probe, so a failure here could go unnoticed"
    state = " and holds state" if svc["stateful"] else ""
    return f"{c['target']} is relied on by {deps}{state}; a {c['type']} here {seen}."


def _experiment(i, cands, delays, reason, hypothesis, cfg, graph, name=None):
    targets = [c["target"] for c in cands]
    return {
        "id": f"E{i}",
        "name": name or " + ".join(f"{c['type']} {c['target']}" for c in cands),
        "steps": [{"type": c["type"], "target": c["target"], "delay_s": d} for c, d in zip(cands, delays)],
        "reason": reason, "hypothesis": hypothesis,
        "risk_score": sum(c["risk_score"] for c in cands),
        "predicted_probes": probes_affected(cfg, graph, targets),   # always computed by us, never by the AI
    }


def heuristic_plan(cfg, graph, cands, n):
    """Fallback: highest risk first, but at most one experiment per fault type in the first pass."""
    picked = []
    def n_on(target):
        return sum(p["target"] == target for p in picked)
    # Pass 1: one experiment per fault type, spreading across DIFFERENT services where possible.
    for ftype in dict.fromkeys(c["type"] for c in cands):
        options = [c for c in cands if c["type"] == ftype]
        picked.append(min(options, key=lambda c: (n_on(c["target"]), -c["risk_score"])))
    # Pass 2: fill remaining slots with the riskiest unpicked candidates (max 2 per service).
    for c in cands:
        if len(picked) >= n - 1:
            break
        if c not in picked and n_on(c["target"]) < 2:
            picked.append(c)
    exps = [_experiment(i + 1, [c], [0], _reason(c, graph), HYPOTHESIS[c["type"]], cfg, graph)
            for i, c in enumerate(picked[:n - 1])]

    # Combined failure: crash a consumer, then crash the queue it reads from while work is backed up.
    by_id = {c["id"]: c for c in cands}
    for qname, q in graph["services"].items():
        consumers = [u for u in q["used_by"] if graph["services"][u]["role"] == "consumer"]
        if q["role"] == "queue" and consumers and f"kill:{consumers[0]}" in by_id:
            exps.append(_experiment(
                len(exps) + 1, [by_id[f"kill:{consumers[0]}"], by_id[f"kill:{qname}"]], [0, 8],
                f"{consumers[0]} drains {qname}. With {consumers[0]} down, accepted work piles up inside {qname}; "
                f"crashing {qname} at that moment tests whether buffered data survives.",
                "Every vote the user saw accepted should still reach the database.", cfg, graph,
                name=f"COMBINED: {consumers[0]} down, then {qname} crash"))
            break
    return exps


PLANNER_SYSTEM = """You are a senior Site Reliability Engineer planning chaos-engineering experiments
against a sandboxed, containerised application. You choose the most informative and riskiest
experiments first, using the dependency map and the observed baseline.
Rules:
- You may ONLY use candidate ids from the provided list. Never invent services or fault types.
- Each experiment has 1 step, or 2 steps for a combined failure (second step delayed 3-15 s).
- Include at least 3 different fault types and exactly one combined failure.
- Order experiments from most to least valuable.
- Reasons must cite concrete facts from the dependency map (who depends on what, stateful or not,
  which health probe would notice).
Reply with JSON only, no prose."""

PLANNER_USER = """Dependency map:
{graph}

Baseline under steady load (per health probe):
{baseline}

Candidate experiments (id = fault:service, with a heuristic risk score):
{cands}

Return at most {n} experiments as:
{{"experiments": [
  {{"name": "short title",
    "steps": [{{"candidate": "kill:redis", "delay_s": 0}}],
    "reason": "one or two sentences: why this is informative / risky",
    "hypothesis": "what a resilient system SHOULD do"}}
]}}"""


def ai_plan(cfg, graph, baseline, cands, n, offline):
    compact_graph = {name: {k: s[k] for k in ("role", "stateful", "depends_on", "used_by")}
                     for name, s in graph["services"].items()}
    user = PLANNER_USER.format(
        graph=json.dumps({"services": compact_graph, "data_flows": graph["data_flows"]}, indent=1),
        baseline=json.dumps((baseline or {}).get("probes", {}), indent=1),
        cands="\n".join(f"- {c['id']} (risk {c['risk_score']}, would break probes: {c['predicted_probes'] or 'none'})"
                        for c in cands),
        n=n)
    data, source = ask_json("plan", PLANNER_SYSTEM, user, offline=offline)
    if not data:
        return None, source

    by_id, exps = {c["id"]: c for c in cands}, []
    for e in data.get("experiments", [])[:n]:
        steps = [s for s in e.get("steps", [])[:2] if s.get("candidate") in by_id]
        if not steps:
            continue   # AI referenced something we didn't offer -> silently dropped (safety)
        delays = [max(0, min(15, int(s.get("delay_s", 0)))) for s in steps]
        exps.append(_experiment(len(exps) + 1, [by_id[s["candidate"]] for s in steps], delays,
                                str(e.get("reason", ""))[:400], str(e.get("hypothesis", ""))[:300],
                                cfg, graph, name=str(e.get("name", ""))[:80] or None))
    return (exps if len(exps) >= 3 else None), source


def build_plan(cfg, graph, baseline, offline=False):
    n = cfg.get("max_experiments", 6)
    cands = candidates(cfg, graph)
    exps, source = ai_plan(cfg, graph, baseline, cands, n, offline)
    if not exps:
        source = "heuristic"
        exps = heuristic_plan(cfg, graph, cands, n)
    plan = {"source": source, "experiments": exps, "candidates_considered": len(cands)}
    save_json(PLAN_FILE, plan)
    LIVE.set(queue=[{"id": e["id"], "name": e["name"], "reason": e["reason"], "status": "planned",
                     "score": None} for e in exps])
    LIVE.event("ai", f"Plan ready ({source}): {len(exps)} experiments from {len(cands)} candidates")
    for e in exps:
        LIVE.event("ai", f"  {e['id']} {e['name']}  -- {e['reason']}")
    return plan
