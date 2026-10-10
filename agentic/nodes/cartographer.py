"""CARTOGRAPHER AGENT (understand + hypothesise). Owner: Tejas. See docs/PROJECT_BLUEPRINT.md 6.1.

Job: understand the app BEFORE attacking it. Output -> state["threat_model"].
Now: recon_agent below (tool-using ReAct agent: container status, logs, config, dependencies), with a rule-based
fallback so the graph always completes.
Upgrade (Tejas): add SOURCE-CODE tools (core/code_tools.py). Clone github.com/dockersamples/example-voting-app into sandbox/app-src and
give the agent read_file(path) + grep(pattern) tools limited to that folder, so it can say "worker/Program.cs has no
retry when the redis hostname fails to resolve" BEFORE we test it. Code-informed hypotheses, confirmed by experiment.
"""
import os

from core.agentkit import ReActAgent
from core.common import LIVE, ROOT, save_json
from core.tools import make_tools

from ..runtime import cfg

THREAT_FILE = os.path.join(ROOT, "threat_model.json")

RECON_SCHEMA = {"single_points_of_failure": ["service"],
                "risks": [{"service": "...", "weakness": "...", "evidence": "..."}],
                "hypotheses_to_test": ["what might break, phrased as a testable claim"]}


def _compact_graph(graph):
    return {n: {k: s[k] for k in ("role", "stateful", "depends_on", "used_by")} for n, s in graph["services"].items()}


def recon_agent(cfg, graph, offline=False):
    agent = ReActAgent(
        "Cartographer",
        "a reliability engineer doing reconnaissance on a containerised app BEFORE chaos testing. Inspect the running "
        "services to find single points of failure and risky configuration (no restart policy, no persistence or "
        "volumes, no healthcheck, components with no redundancy)",
        make_tools(cfg, graph), RECON_SCHEMA, max_steps=6, offline=offline)
    final, trace = agent.run("Find the weaknesses most worth testing, each backed by evidence from a tool.",
                             {"dependency_map": _compact_graph(graph), "data_flows": graph.get("data_flows")})
    result = {"final": final, "trace": trace}
    save_json(THREAT_FILE, result)
    return result


def rule_based(graph):
    svcs = graph["services"]
    spof = [n for n, s in svcs.items() if s.get("used_by") and s.get("stateful")]
    return {"single_points_of_failure": spof,
            "risks": [{"service": n, "weakness": f"stateful and relied on by {', '.join(svcs[n]['used_by'])}",
                       "evidence": "dependency map"} for n in spof],
            "hypotheses_to_test": [f"if {n} crashes, its dependents recover on their own and no data is lost"
                                   for n in spof]}


def cartographer_node(state):
    LIVE.set(agent_active="cartographer")
    out = recon_agent(cfg(), state["graph"], offline=state.get("offline", False))
    tm = out.get("final") or rule_based(state["graph"])
    tm["source"] = "agent" if out.get("final") else "rules"
    LIVE.event("ai", f"[Cartographer] single points of failure: {tm.get('single_points_of_failure')}")
    LIVE.set(threat_model=tm)
    return {"threat_model": tm}
