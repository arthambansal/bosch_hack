"""SAFETY GOVERNOR + HUMAN GATE (deterministic). Owner: Artham. See blueprint 13.

Two layers before anything is broken:
  1. POLICY (deterministic, cannot be argued with): sandbox-only targets, max 2 simultaneous faults,
     never more than one stateful service down at once.
  2. Human approval for high-risk experiments (combined failures) when --approve is on. Uses LangGraph interrupt():
     the graph pauses, a person answers in the terminal (or the dashboard writes runs/approval.json), the graph resumes.
Upgrade (Artham): an LLM reviewer between 1 and 2 that critiques the proposal's blast radius and can reject it.
The runtime kill switch (core/engine.py Guard) stays deterministic, always on.
"""
from langgraph.types import interrupt

from core.common import LIVE

from ..runtime import cfg
from .experimenter import sig


def policy_check(proposal, graph):
    reasons, c = [], cfg()
    steps = proposal.get("steps", [])
    if not steps:
        reasons.append("proposal has no steps")
    if len(steps) > 2:
        reasons.append("more than 2 simultaneous faults")
    for s in steps:
        if s["target"] not in c["services"]:
            reasons.append(f"{s['target']} is not a sandbox service")
    stateful_down = {s["target"] for s in steps if graph["services"].get(s["target"], {}).get("stateful")
                     and s["type"] in ("kill", "pause", "partition")}
    if len(stateful_down) > 1:
        reasons.append(f"would take down {len(stateful_down)} data stores at once ({', '.join(sorted(stateful_down))}); "
                       "policy allows one")
    return reasons


def governor_node(state):
    LIVE.set(agent_active="governor")
    p = state["proposal"]
    reasons = policy_check(p, state["graph"])
    if reasons:
        LIVE.event("guard", f"[Governor] REJECTED {p['id']} {p['name']}: {'; '.join(reasons)}")
        return {"review": {"approved": False, "reasons": reasons, "by": "policy"},
                "rejections": state.get("rejections", 0) + 1,
                "rejected_sigs": state.get("rejected_sigs", []) + [sig(p["steps"])]}
    needs_human = len(p.get("steps", [])) > 1
    LIVE.event("ok", f"[Governor] approved {p['id']} {p['name']}" + (" (needs human sign-off)" if needs_human else ""))
    return {"review": {"approved": True, "reasons": ["passes policy"], "needs_human": needs_human, "by": "policy"},
            "rejections": 0}


def approval_node(state):
    review, p = state["review"], state["proposal"]
    if not (state.get("require_approval") and review.get("needs_human")):
        return {}
    LIVE.set(agent_active="human", approval_request={"id": p["id"], "name": p["name"], "reason": p.get("reason")})
    answer = interrupt({"question": f"Approve {p['id']}: {p['name']}?", "reason": p.get("reason"),
                        "steps": p.get("steps")})
    LIVE.set(approval_request=None)
    if str(answer).strip().lower() in ("y", "yes", "approve", "approved", "true"):
        LIVE.event("ok", f"[Human] approved {p['id']}")
        return {"review": {**review, "human": "approved"}}
    LIVE.event("guard", f"[Human] denied {p['id']}")
    return {"review": {**review, "approved": False, "human": "denied", "reasons": ["denied by human operator"]},
            "rejections": state.get("rejections", 0) + 1,
            "rejected_sigs": state.get("rejected_sigs", []) + [sig(p["steps"])]}
