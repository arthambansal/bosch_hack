"""EXPERIMENTER AGENT (design + adapt experiments). Owner: Artham. See blueprint 6.2.

Job: choose the next experiment (or stop). Reads Cartographer hypotheses, investigations, reviewer feedback and the user's goal.
It can only pick from candidates generated from OUR dependency map (validated in core/agent.py).
"""
from core.agent import Agent
from core.common import LIVE

from ..runtime import cfg


def sig(steps):
    return "+".join(f"{s['type']}:{s['target']}" for s in steps)


def experimenter_node(state):
    LIVE.set(agent_active="experimenter")
    c, results = cfg(), state.get("results", [])
    if len(results) >= c.get("max_experiments", 6):
        return {"proposal": None, "done_reason": "experiment budget used"}
    review = state.get("review") or {}
    extra = {"user_goal": state.get("goal") or None,
             "cartographer": state.get("threat_model"),
             "investigations": state.get("investigations"),
             "last_rejection": review.get("reasons") if review and not review.get("approved") else None}
    agent = Agent(c, state["graph"], state.get("baseline", {}), offline=state.get("offline", False), extra=extra)
    agent.n = len(results)                                   # next id = E{len+1}
    agent.used = {tuple(f"{s['type']}:{s['target']}" for s in r["steps"]) for r in results}
    agent.used |= {tuple(x.split("+")) for x in state.get("rejected_sigs", [])}
    exp = agent(results)
    if not exp:
        return {"proposal": None, "done_reason": "experimenter decided enough was learned"}
    return {"proposal": exp, "review": None}
