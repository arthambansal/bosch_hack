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

from core.common import BASELINE_FILE, DEPS_FILE, LIVE, RUNS_DIR, STOP_FILE, load_config, save_json  # noqa: E402

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
    # --- human gate: unique token, expiry, stale/duplicate decisions ignored, nothing lost, request always cleared ---
    import threading
    import agentic.gate as GT

    nap = lambda secs: threading.Event().wait(secs)     # real sleep (time.sleep is patched to a no-op above)  # noqa: E731

    def submit(body):                                   # what the dashboard server does: atomic write
        tmp = GT.APPROVAL_FILE + ".tmp"
        json.dump(body, open(tmp, "w"))
        os.replace(tmp, GT.APPROVAL_FILE)

    def run_gate(action, timeout=8):
        out = {}
        th = threading.Thread(target=lambda: out.update(a=real_ask_human(
            {"id": "E6", "name": "n", "question": "q", "reason": "r", "steps": []}, timeout_s=timeout)))
        th.start()
        gate = None
        for _ in range(100):
            gate = LIVE.state.get("approval_request")
            if gate:
                break
            nap(0.02)
        t0 = time.time()
        action(gate)
        th.join(15)
        return out.get("a"), gate, time.time() - t0

    submit({"approved": True})                           # an OLD decision lying around must not approve the next gate
    os.utime(GT.APPROVAL_FILE, (1, 1))
    ans_a, gate_a, _ = run_gate(lambda g: submit({"gate_id": g["gate_id"], "approved": False}))     # decision right after publish
    result_a = LIVE.state.get("approval_result") or {}
    cleared_a = LIVE.state.get("approval_request") is None and not os.path.exists(GT.APPROVAL_FILE)
    ans_b, gate_b, took_b = run_gate(lambda g: (submit({"gate_id": "oldgate123", "approved": True}), nap(0.8),
                                                submit({"gate_id": g["gate_id"], "approved": True})))   # wrong token ignored
    submit({"gate_id": gate_b["gate_id"], "approved": True})                                          # duplicate of a finished gate
    ans_c, gate_c, _ = run_gate(lambda g: None, timeout=1)                                            # nobody answers
    result_c = LIVE.state.get("approval_result") or {}
    expiry_fields = all(k in gate_a for k in ("gate_id", "created_at", "expires_at")) and gate_a["expires_at"] > gate_a["created_at"]

    # --- STOP ends an approval wait immediately ---
    open(STOP_FILE, "w").close()
    t0 = time.time()
    stop_wait_answer = real_ask_human({"question": "q", "reason": "r"}, timeout_s=30)
    stop_wait_s = time.time() - t0
    os.remove(STOP_FILE)
    stop_cleared = LIVE.state.get("approval_request") is None and (LIVE.state.get("approval_result") or {}).get("source") == "stop"
    # --- STOP halts the whole autopilot run at the next node and still writes a report ---
    STOPTEST["on"] = True
    # --- shared cross-process gate lock: server-side submit_decision() and the orchestrator never race ---
    sync_out = {}
    LIVE.set(approval_request=None)
    sync_out["none"] = GT.submit_decision("abc", True)[0]                                    # nothing pending -> 409
    LIVE.set(approval_request={"gate_id": "old", "expires_at": time.time() - 1})
    sync_out["expired"] = GT.submit_decision("old", True)                                    # expired -> 409
    LIVE.set(approval_request=None)

    def run_gate_sync():
        res, gate = {}, None
        t = threading.Thread(target=lambda: res.setdefault("a", GT.ask_human({"id": "S", "name": "n", "question": "q?", "reason": "r"}, timeout_s=8)))
        t.start()
        for _ in range(100):
            gate = LIVE.state.get("approval_request")
            if gate:
                break
            nap(0.05)
        codes = []
        sync_out["stale"] = GT.submit_decision("wrong", True)[0]
        ws = [threading.Thread(target=lambda: codes.append(GT.submit_decision(gate["gate_id"], True)[0])) for _ in range(8)]
        [w.start() for w in ws]
        [w.join() for w in ws]
        t.join(10)
        sync_out["codes"] = sorted(codes)
        sync_out["answer"] = res.get("a")
        sync_out["late"] = GT.submit_decision(gate["gate_id"], False)[0]                      # gate closed -> 409
    run_gate_sync()
    held_busy = False
    with GT.gate_lock():
        try:
            with GT.gate_lock(timeout=0.2):
                pass
        except GT.GateLockTimeout:
            held_busy = True
    os.makedirs(GT.LOCK_DIR)
    old = time.time() - 60
    os.utime(GT.LOCK_DIR, (old, old))
    with GT.gate_lock(timeout=1):                                                           # stale lock left by a crash is broken
        stale_broken = True
    lock_released = not os.path.exists(GT.LOCK_DIR)
    sync_published = (LIVE.state.get("gate_sync") or {}).get("version") == 1
    sync_ok = (sync_out["none"] == 409 and sync_out["expired"][0] == 409 and sync_out["expired"][1].get("error") == "expired"
               and sync_out["stale"] == 409 and sync_out["codes"] == [200] + [409] * 7
               and sync_out["answer"] == "yes" and sync_out["late"] == 409)

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
        "STOP clears the pending approval request": stop_cleared,
        "gate: decision right after publish is not lost; old decision file does not leak in":
            ans_a == "no" and cleared_a and result_a.get("gate_id") == gate_a["gate_id"] and result_a.get("source") == "dashboard",
        "gate: wrong/stale token ignored, right token accepted": ans_b == "yes" and took_b >= 0.7 and gate_a["gate_id"] != gate_b["gate_id"],
        "gate: unique token + expiry published": expiry_fields,
        "gate: duplicate decision for a finished gate ignored, expiry denies":
            ans_c == "no" and result_c.get("source") == "timeout" and gate_c["gate_id"] not in (gate_a["gate_id"], gate_b["gate_id"]),
        "gate sync: stale/expired/no_pending give 409; 8 simultaneous submits -> exactly one 200; late submit 409": sync_ok,
        "gate sync: lock excludes a second holder, breaks a stale lock, always released": held_busy and stale_broken and lock_released,
        "gate sync: live_state advertises gate_sync v1": sync_published,
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
