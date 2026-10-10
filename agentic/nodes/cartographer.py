"""CARTOGRAPHER AGENT (understand + hypothesise). Owner: Tejas. See docs/PROJECT_BLUEPRINT.md 6.1.

Job: understand the app BEFORE attacking it. Output -> state["threat_model"].
Now: recon_agent below (tool-using ReAct agent: container status, logs, config, dependencies), with a rule-based
fallback so the graph always completes.
Upgrade (Tejas): add SOURCE-CODE tools (core/code_tools.py). Clone github.com/dockersamples/example-voting-app into sandbox/app-src and
give the agent read_file(path) + grep(pattern) tools limited to that folder, so it can say "worker/Program.cs has no
retry when the redis hostname fails to resolve" BEFORE we test it. Code-informed hypotheses, confirmed by experiment.
"""
import os
import re
from collections import Counter
from pathlib import PurePosixPath, PureWindowsPath

from core.agentkit import ReActAgent
from core.common import LIVE, ROOT, save_json
from core.tools import make_tools
from core.code_tools import make_code_tools, read_file

from ..runtime import cfg

THREAT_FILE = os.path.join(ROOT, "threat_model.json")


def SOURCE_AVAILABLE():
    return os.path.isfile(os.path.join(ROOT, "sandbox", "app-src", "worker", "Program.cs"))

RECON_SCHEMA = {"single_points_of_failure": ["service"],
                "risks": [{"service": "...", "weakness": "...", "evidence": "..."}],
                "hypotheses_to_test": ["what might break, phrased as a testable claim"]}

HYPOTHESIS_KEYS = {"id", "statement", "source", "evidence", "affected", "priority", "status"}
MAX_HYPOTHESES = 20
MAX_CITATIONS = 12
CITATION = re.compile(r"([^:\r\n]+):([1-9][0-9]{0,6}):[ \t]*(\S[^\r\n]*)")


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
    """Validate Section 8.2 shape without changing the shared schema or state."""
    if not isinstance(items, list) or len(items) > MAX_HYPOTHESES:
        return False
    ids = set()
    for h in items:
        if not isinstance(h, dict) or set(h) != HYPOTHESIS_KEYS:
            return False
        if any(not isinstance(h[k], str) or not h[k].strip() for k in HYPOTHESIS_KEYS - {"evidence", "affected"}):
            return False
        if len(h["id"]) > 80 or len(h["statement"]) > 2000:
            return False
        if h["id"] in ids or h["source"] != "code" or h["status"] != "open" or h["priority"] not in ("high", "medium", "low"):
            return False
        ids.add(h["id"])
        if any(not isinstance(h[k], list) or not h[k] or len(h[k]) > MAX_CITATIONS
               or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in h[k])
               for k in ("evidence", "affected")):
            return False
    return True


def valid_citation(evidence):
    """Check a relative file:line:exact-source-line citation against current disk contents.

    This verifies the quoted text, not the causal claim. All hypotheses stay open.
    The existing read-only source tool enforces size, binary and resolved-path limits.
    """
    if not isinstance(evidence, str) or len(evidence) > 2000:
        return False
    match = CITATION.fullmatch(evidence)
    if not match:
        return False
    path, number, quote = match.groups()
    posix = PurePosixPath(path.replace("\\", "/"))
    windows = PureWindowsPath(path)
    if posix.is_absolute() or windows.drive or windows.root or ".." in posix.parts:
        return False
    try:
        line = int(number)
        actual = read_file(path, line, line)
    except (OSError, ValueError, UnicodeError):
        return False
    # Only ignore outer indentation; fabricated explanations and partial quotes fail.
    return bool(actual) and actual.partition(":")[2].strip() == quote.strip()


def verified_hypotheses(items, graph):
    """Retain independently valid findings, so one bad citation cannot erase others."""
    if not isinstance(items, list) or len(items) > MAX_HYPOTHESES:
        return []
    shaped = [h for h in items if valid_hypotheses([h])]
    counts = Counter(h["id"] for h in shaped)
    services = graph.get("services", {})
    accepted = []
    for h in shaped:
        # Reused IDs are ambiguous; do not arbitrarily select one of those records.
        if counts[h["id"]] != 1 or any(s not in services for s in h["affected"]):
            continue
        if all(valid_citation(e) for e in h["evidence"]):
            accepted.append(h)
    return accepted


def _valid_recon(tm):
    if not isinstance(tm, dict) or not all(isinstance(tm.get(k), list) for k in RECON_SCHEMA):
        return False
    return (all(isinstance(x, str) for k in ("single_points_of_failure", "hypotheses_to_test") for x in tm[k])
            and all(isinstance(r, dict) and all(isinstance(r.get(k), str)
                    for k in ("service", "weakness", "evidence")) for r in tm["risks"]))


def _compact_graph(graph):
    return {n: {k: s[k] for k in ("role", "stateful", "depends_on", "used_by")} for n, s in graph["services"].items()}


def recon_agent(cfg, graph, offline=False):
    agent = ReActAgent(
        "Cartographer",
        "a reliability engineer doing reconnaissance on a containerised app BEFORE chaos testing. Inspect the running "
        "services to find single points of failure and risky configuration (no restart policy, no persistence or "
        "volumes, no healthcheck, components with no redundancy). Read application source with the tools. "
        "New source-backed hypotheses beyond the supplied fallback example are welcome. "
        "Each evidence string MUST be relative/path:line_number: exact complete source line copied from "
        "read_file or grep (no ellipsis or added explanation). Cite function declarations as well as the "
        "mechanism lines where possible. Put reasoning in statement, not in the quoted evidence. "
        "Use unique IDs and only affected services from the dependency map. source must be code, status "
        "must be open, priority high/medium/low. At most 20 hypotheses and 12 citations each. "
        "A source citation is not experimental confirmation; never claim an unmeasured result",
        {**make_tools(cfg, graph), **make_code_tools()},
        {**RECON_SCHEMA, "hypotheses": [{"id": "H1", "statement": "testable claim", "source": "code",
          "evidence": ["worker/Program.cs:15: public static int Main(string[] args)"],
          "affected": ["service"], "priority": "high", "status": "open"}]},
        max_steps=6, offline=offline, time_budget_s=60)
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
    final = out.get("final") if isinstance(out, dict) else None
    hypotheses = verified_hypotheses(final.get("hypotheses"), state["graph"]) if _valid_recon(final) else []
    if hypotheses:
        # Project onto the existing blackboard fields. Typed messages stay separate.
        tm = {k: final[k] for k in RECON_SCHEMA}
        save_json(os.path.join(ROOT, "runs", "cartographer_hypotheses.json"), hypotheses)
        tm["hypotheses_to_test"] = [h["statement"] + " [FROM SOURCE; HYPOTHESIS] " + "; ".join(h["evidence"]) for h in hypotheses]
        tm["source"] = "agent"
    elif _valid_recon(final) and (final.get("single_points_of_failure") or final.get("risks")):
        # The AI's live reconnaissance (config, restart policy, healthchecks) is real evidence even without
        # source-code citations: keep it instead of throwing it away.
        tm = {k: final[k] for k in RECON_SCHEMA}
        tm["single_points_of_failure"] = [s for s in tm["single_points_of_failure"] if s in state["graph"]["services"]]
        tm["source"] = "agent"
        if not SOURCE_AVAILABLE():
            LIVE.event("warn", "[Cartographer] app source not found in sandbox/app-src (clone it for code-cited "
                               "hypotheses); keeping the AI's configuration-based reconnaissance")
    else:
        LIVE.event("warn", "[Cartographer] no valid AI reconnaissance; using rule fallback"
                   + ("" if SOURCE_AVAILABLE() else " (tip: clone the app source into sandbox/app-src)"))
        tm = rule_based(state["graph"])
        tm["source"] = "rules"
    LIVE.event("ai", f"[Cartographer] ({tm['source']}) single points of failure: {tm.get('single_points_of_failure')}")
    for r in (tm.get("risks") or [])[:4]:
        LIVE.event("ai", f"[Cartographer] risk: {r.get('service')}: {str(r.get('weakness'))[:160]}")
    LIVE.set(threat_model=tm)
    return {"threat_model": tm}
