"""Run the WHOLE multi-agent graph with Docker and the AI simulated. Takes ~1 second, needs no API key.

    python3 tests/test_graph_mock.py

Run it after every change to agentic/ or core/ before pushing. If it prints "ALL CHECKS PASSED", the graph wiring
(routing, human approval, investigation, fix, verify, report, safety rejection) still works.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # noqa: E402
import time  # noqa: E402

from core.common import BASELINE_FILE, DEPS_FILE, RUNS_DIR, STOP_FILE, load_config, save_json  # noqa: E402

backups = {}
for f in (DEPS_FILE, BASELINE_FILE):
    if os.path.exists(f):
        backups[f] = f + ".bak_test"
        shutil.copy(f, backups[f])

cfg = load_config()
EDGES = [("vote", "redis"), ("worker", "redis"), ("worker", "db"), ("result", "db")]
save_json(DEPS_FILE, {"services": {n: {"role": s["role"], "stateful": s["stateful"], "blast_radius": [],
                                       "depends_on": sorted(b for a, b in EDGES if a == n),
                                       "used_by": sorted(a for a, b in EDGES if b == n)}
                                   for n, s in cfg["services"].items()},
                      "edges": [], "data_flows": ["vote -> redis -> worker -> db -> result"]})
save_json(BASELINE_FILE, {"probes": {"vote_write": {"p95_ms": 40}, "result_page": {"p95_ms": 30}}})

import agentic.graph as G  # noqa: E402
import agentic.nodes.diagnostician as I  # noqa: E402
import agentic.nodes.cartographer as R  # noqa: E402
import agentic.nodes.remediator as M  # noqa: E402
import agentic.runtime as rt  # noqa: E402
import core.agent as CA  # noqa: E402
import core.heal as CH  # noqa: E402
from agentic.nodes.governor import governor_node  # noqa: E402

FIXED = {"on": False}
STOPTEST = {"on": False}


class FakeProber:
    def start(self): pass
    def stop(self): pass


class FakeEngine:
    """Pretends: killing redis crashes the worker and loses 14 votes, unless fixes were applied."""
    def __init__(self, cfg, graph): self.prober = FakeProber()
    def _restore_all(self): pass

    def run_experiment(self, exp):
        if STOPTEST["on"]:                       # the operator presses STOP while this experiment runs
            open(STOP_FILE, "w").close()
        kill_redis = any(s["type"] == "kill" and s["target"] == "redis" for s in exp["steps"])
        bad = kill_redis and not FIXED["on"]
        return {"id": exp["id"], "name": exp["name"], "steps": exp["steps"], "reason": exp.get("reason"),
                "hypothesis": exp.get("hypothesis"), "predicted_probes": exp.get("predicted_probes", []),
                "status": "aborted" if kill_redis else "completed", "recovery_s": 0.5,
                "probes": {"vote_write": {"error_rate": 0.75 if kill_redis else 0.0,
                                          "time_to_first_error_s": 0.5 if kill_redis else None, "p95_ms": 60}},
                "delivery": {"lost": 14 if bad else 0}, "stuck_services": ["worker"] if bad else [],
                "stuck_details": {"worker": {"exit_code": "1", "last_logs": ["Name or service not known"]}} if bad else {}}


def fake_apply(fixes, cfg):
    FIXED["on"] = True
    return True


rt.Engine = FakeEngine
rt.panic = lambda c: None                        # never touch real Docker in this test
real_ask_human = G.ask_human
R.recon_agent = lambda *a, **k: {"final": None}
I.investigate = lambda *a, **k: {"final": None}
CA.ask_json = lambda *a, **k: (None, "none")
CH.ask_json = lambda *a, **k: (None, "none")
M.apply_fixes, M.time.sleep = fake_apply, (lambda s: None)
asked = []
G.ask_human = lambda req: asked.append(req["question"]) or "y"

try:
    rt.RT["cfg"] = cfg
    final = G.run(goal="what if redis dies?", require_approval=True)
    rej = governor_node({"graph": {"services": {n: {"stateful": s["stateful"]} for n, s in cfg["services"].items()}},
                       "proposal": {"id": "EX", "name": "double kill",
                                    "steps": [{"type": "kill", "target": "redis"}, {"type": "kill", "target": "db"}]}})
    # --- approval file formats (CONTRACT.md: {"approved": bool}; legacy {"answer": "yes"}) ---
    ap = os.path.join(RUNS_DIR, "approval.json")
    fmt = {}
    for label, body in (("true", {"approved": True}), ("false", {"approved": False}), ("legacy", {"answer": "yes"})):
        json.dump(body, open(ap, "w"))
        fmt[label] = G._read_answer(ap)
    os.remove(ap)
    # --- evidence rule: a ReAct agent may not conclude before 2 real tool calls ---
    import core.agentkit as AK
    from core.agentkit import ReActAgent, Tool
    script = iter([{"thought": "t", "final": {"root_cause": "guess"}},          # premature: must be rejected
                   {"thought": "t", "final": {"root_cause": "guess again"}},    # premature again: rejected again
                   {"thought": "t", "tool": "probe", "args": {"a": 1}},
                   {"thought": "t", "tool": "probe", "args": {"a": 2}},
                   {"thought": "t", "final": {"root_cause": "evidence-based"}}])
    real_ask = AK.ask_json
    AK.ask_json = lambda *a, **k: (next(script), "fake")
    tools = {"probe": Tool("probe", "d", ["a"], lambda a: "observation")}
    ev_final, ev_trace = ReActAgent("T", "r", tools, {"root_cause": "x"}, max_steps=6).run("g", {})
    # --- a repeated identical call is skipped (not counted, not run again) ---
    runs = []
    script2 = iter([{"thought": "t", "tool": "probe", "args": {"a": 1}},
                    {"thought": "t", "tool": "probe", "args": {"a": 1}},        # repeat: skipped
                    {"thought": "t", "tool": "nope", "args": {}},               # unknown tool: not counted
                    {"thought": "t", "tool": "probe2", "args": {}},
                    {"thought": "t", "final": {"root_cause": "ok"}}])
    AK.ask_json = lambda *a, **k: (next(script2), "fake")
    tools2 = {"probe": Tool("probe", "d", ["a"], lambda a: runs.append(a) or "obs"), "probe2": Tool("probe2", "d", [], lambda: "obs2")}
    rep_final, rep_trace = ReActAgent("T2", "r", tools2, {"root_cause": "x"}, max_steps=5).run("g", {})
    # --- model wastes 3 steps (unknown + repeated tools): code gathers evidence, agent still concludes ---
    script3 = iter([{"thought": "t", "tool": "exec", "args": {"cmd": "ls"}}] * 3 + [{"thought": "t", "final": {"root_cause": "from-evidence"}}])
    AK.ask_json = lambda *a, **k: (next(script3), "fake")
    tools3 = {"probe": Tool("probe", "d", ["a"], lambda a: "obs-" + str(a)), "probe2": Tool("probe2", "d", [], lambda: "obs2")}
    st_final, st_trace = ReActAgent("T3", "r", tools3, {"root_cause": "x"}, max_steps=5,
                                    starters=[("probe", {"a": 1}), ("probe2", {})]).run("g", {})
    AK.ask_json = real_ask
    # --- STOP ends an approval wait immediately ---
    open(STOP_FILE, "w").close()
    t0 = time.time()
    stop_wait_answer = real_ask_human({"question": "q", "reason": "r"}, timeout_s=30)
    stop_wait_s = time.time() - t0
    os.remove(STOP_FILE)
    # --- STOP halts the whole autopilot run at the next node and still writes a report ---
    STOPTEST["on"] = True
    stopped = G.run(goal="", require_approval=False)
    STOPTEST["on"] = False
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    checks = {
        "agent cannot conclude without 2 real tool calls":
            (ev_final or {}).get("root_cause") == "evidence-based" and sum(1 for t in ev_trace if t["tool"] == "probe") == 2,
        "repeated call skipped, unknown tool not counted":
            len(runs) == 1 and (rep_final or {}).get("root_cause") == "ok" and sum(1 for t in rep_trace if t["tool"] in tools2) == 2,
        "after 3 wasted steps, code gathers evidence and agent concludes":
            (st_final or {}).get("root_cause") == "from-evidence" and sum(1 for t in st_trace if t["tool"] in tools3) == 2,
        "approval {approved:true/false} and legacy {answer} formats":
            fmt == {"true": "yes", "false": "no", "legacy": "yes"},
        "STOP ends an approval wait at once": stop_wait_answer == "no" and stop_wait_s < 3,
        "STOP halts the whole run after the current experiment": len(stopped["results"]) == 1,
        "partial report written after STOP": os.path.exists((stopped.get("report") or {}).get("path_md", "")),
        "ran 3+ experiments": len(final["results"]) >= 3,
        "human approval was asked": len(asked) >= 1,
        "diagnostician ran on bad results": len(final.get("investigations", {})) >= 1,
        "fixes applied": len(final.get("fixes", [])) >= 1,
        "verification improved": bool((final.get("verification") or {}).get("improved")),
        "report written": os.path.exists((final.get("report") or {}).get("path_md", "")),
        "safety rejects double data-store kill": rej["review"]["approved"] is False,
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
finally:
    for f, b in backups.items():
        shutil.move(b, f)
    for f in (DEPS_FILE, BASELINE_FILE):
        if f not in backups and os.path.exists(f):
            os.remove(f)
