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
from core.code_tools import make_code_tools, read_file

from ..runtime import cfg

THREAT_FILE = os.path.join(ROOT, "threat_model.json")

RECON_SCHEMA = {"single_points_of_failure": ["service"],
                "risks": [{"service": "...", "weakness": "...", "evidence": "..."}],
                "hypotheses_to_test": ["what might break, phrased as a testable claim"]}

HYPOTHESIS_KEYS = {"id", "statement", "source", "evidence", "affected", "priority", "status"}


def source_hypotheses():
    """Derive W1 from inspected source, never from the blueprint's claimed measurements."""
    try:
        # Read the entire small worker file in bounded windows, with numbered evidence.
        code = "\n".join(read_file("worker/Program.cs", n, n + 79) for n in (1, 81, 161))
        required = ("Dns.GetHostEntryAsync(hostname)", "var ipAddress = GetIp(hostname)",
                    "catch (RedisConnectionException)", "catch (Exception ex)", "return 1;",
                    "public static int Main", "private static ConnectionMultiplexer OpenRedisConnection",
                    "private static string GetIp")
        if not all(token in code for token in required):
            return []
        evidence = [f"worker/Program.cs:{line.strip()}" for line in code.splitlines()
                    if any(token in line for token in required)]
        return [{"id": "H1", "statement": "If redis DNS resolution fails in GetIp, OpenRedisConnection does not retry it; Main returns exit code 1. Without a restart policy the worker stays down and accepted votes stop being processed.",
                 "source": "code", "evidence": evidence,
                 "affected": ["worker", "redis"], "priority": "high", "status": "open"}]
    except (OSError, ValueError, UnicodeError):
        return []


def valid_hypotheses(items):
    if not isinstance(items, list):
        return False
    ids = set()
    for h in items:
        if not isinstance(h, dict) or set(h) != HYPOTHESIS_KEYS:
            return False
        if any(not isinstance(h[k], str) or not h[k] for k in ("id", "statement", "source")):
            return False
        if h["id"] in ids or h["source"] != "code" or h["status"] != "open" or h["priority"] not in ("high", "medium", "low"):
            return False
        ids.add(h["id"])
        if any(not isinstance(h[k], list) or not h[k] or any(not isinstance(v, str) for v in h[k]) for k in ("evidence", "affected")):
            return False
    return True


def _compact_graph(graph):
    return {n: {k: s[k] for k in ("role", "stateful", "depends_on", "used_by")} for n, s in graph["services"].items()}


def recon_agent(cfg, graph, offline=False):
    agent = ReActAgent(
        "Cartographer",
        "a reliability engineer doing reconnaissance on a containerised app BEFORE chaos testing. Inspect the running "
        "services to find single points of failure and risky configuration (no restart policy, no persistence or "
        "volumes, no healthcheck, components with no redundancy)",
        {**make_tools(cfg, graph), **make_code_tools()},
        {**RECON_SCHEMA, "hypotheses": [{"id": "H1", "statement": "testable claim", "source": "code",
          "evidence": ["file:line and function"], "affected": ["service"], "priority": "high", "status": "open"}]},
        max_steps=10, offline=offline)
    final, trace = agent.run("Find the weaknesses most worth testing, each backed by evidence from a tool.",
                             {"dependency_map": _compact_graph(graph), "data_flows": graph.get("data_flows"),
                              "source_evidence": source_hypotheses()})
    result = {"final": final, "trace": trace}
    save_json(THREAT_FILE, result)
    return result


def rule_based(graph):
    svcs = graph["services"]
    spof = [n for n, s in svcs.items() if s.get("used_by") and s.get("stateful")]
    hypotheses = source_hypotheses()
    save_json(os.path.join(ROOT, "runs", "cartographer_hypotheses.json"), hypotheses)
    return {"single_points_of_failure": spof,
            "risks": [{"service": n, "weakness": f"stateful and relied on by {', '.join(svcs[n]['used_by'])}",
                       "evidence": "dependency map"} for n in spof],
            "hypotheses_to_test": [h["statement"] + " [FROM SOURCE; HYPOTHESIS] " + "; ".join(h["evidence"]) for h in hypotheses] + [f"if {n} crashes, its dependents recover on their own and no data is lost"
                                   for n in spof]}


def cartographer_node(state):
    LIVE.set(agent_active="cartographer")
    out = recon_agent(cfg(), state["graph"], offline=state.get("offline", False))
    if not isinstance(out, dict) or not isinstance(out.get("final"), (dict, type(None))):
        out = {"final": None}
    tm = out.get("final") or rule_based(state["graph"])
    if out.get("final"):
        # Keep the existing blackboard contract; typed messages are a separate artifact.
        hypotheses = tm.pop("hypotheses", [])
        grounded = source_hypotheses()
        if not hypotheses or not valid_hypotheses(hypotheses) or any(h not in grounded for h in hypotheses):
            hypotheses = grounded
        save_json(os.path.join(ROOT, "runs", "cartographer_hypotheses.json"), hypotheses)
        if not all(isinstance(tm.get(k), list) for k in RECON_SCHEMA) or any(not isinstance(x, str) for k in ("single_points_of_failure", "hypotheses_to_test") for x in tm.get(k, [])) or any(not isinstance(r, dict) or not all(isinstance(r.get(k), str) for k in ("service", "weakness", "evidence")) for r in tm.get("risks", [])):
            tm = rule_based(state["graph"])
            out["final"] = None
        else:
            tm["hypotheses_to_test"] = [h["statement"] + " [FROM SOURCE; HYPOTHESIS] " + "; ".join(h["evidence"]) for h in hypotheses]
    tm["source"] = "agent" if out.get("final") else "rules"
    LIVE.event("ai", f"[Cartographer] single points of failure: {tm.get('single_points_of_failure')}")
    LIVE.set(threat_model=tm)
    return {"threat_model": tm}
