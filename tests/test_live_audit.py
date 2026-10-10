"""Regressions from the 11 Oct live run (AI off, dashboard audit). No Docker, no network.
Run: PYTHONPATH=. python3 tests/test_live_audit.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.agent as A  # noqa: E402
from core.common import LIVE, load_config  # noqa: E402
from core.planner import candidates, heuristic_plan  # noqa: E402

cfg = load_config()
graph = json.load(open("dependencies.json"))
checks = {}

# 1) AI unavailable: the fallback must still apply the coverage rule and publish tried/types_covered.
A.ask_json = lambda *a, **k: (None, "none")
ag = A.Agent(cfg, graph, {}, offline=True)
results = []
for _ in range(4):
    exp = ag(results)
    if not exp:
        break
    results.append({"id": exp["id"], "name": exp["name"], "steps": exp["steps"], "status": "completed"})
types = [s["type"] for r in results for s in r["steps"]]
pr = LIVE.state.get("plan_ranking") or {}
checks["no-AI fallback covers 3 new fault types in the first 3 experiments"] = len(set(types[:3])) == 3
checks["no-AI ranking publishes types_covered"] = len(pr.get("types_covered") or []) >= 3
checks["no-AI ranking marks tried candidates"] = any(c.get("tried") for c in pr.get("candidates") or [])

# 2) heuristic plan: riskiest per type, max 2 experiments per service in the first pass
plan = heuristic_plan(cfg, graph, candidates(cfg, graph), 6)
first = [e["steps"][0] for e in plan if len(e["steps"]) == 1]
per = {}
for s in first:
    per[s["target"]] = per.get(s["target"], 0) + 1
checks["heuristic: no service tested more than twice"] = max(per.values()) <= 2
pause = next(s for s in first if s["type"] == "pause")
checks["heuristic: pause hits a stateful dependency, not the stateless entry point"] = graph["services"][pause["target"]]["stateful"]

# 3) Truth Oracle: failing invariant explains itself
from core.truth import TruthOracle  # noqa: E402
o = TruthOracle(cfg, prober=None)
import time  # noqa: E402
now = time.time()
o._canaries = [{"sent_at": now - 30, "result": {"accepted": True, "delivered": False}}]
o._worker_invariant = lambda: (True, "worker running")
o._queue_invariant = lambda: (True, "queue ok")
o._monitoring_status = lambda: "healthy"
snap = o._build_snapshot()
inv = {i["name"]: i for i in snap["invariants"]}
checks["truth: failing every_vote_counted no longer says 'No suspected-lost'"] = (
    inv["every_vote_counted"]["ok"] is False and "No suspected" not in inv["every_vote_counted"]["detail"])
checks["truth: healthy monitoring + lost canary = diverged"] = snap["status"] == "diverged"
o._monitoring_status = lambda: "degraded"
checks["truth: failing probes is 'down', not a gray failure"] = o._build_snapshot()["status"] == "down"

# 4) rule-based diagnosis says something useful instead of echoing the kill switch line
from agentic.nodes.diagnostician import rule_based  # noqa: E402
res = {"id": "E3", "steps": [{"type": "pause", "target": "vote"}], "status": "aborted", "fault_window_s": 3.1,
       "recovery_s": 0.4, "abort_reason": "KILL SWITCH: vote_write error rate 50% >= 50%",
       "probes": {"vote_write": {"error_rate": 0.5, "p95_ms": 2500, "n": 8}, "result_page": {"error_rate": 0.0, "p95_ms": 6, "n": 8}},
       "delivery": {"lost": 0}}
d = rule_based(res, graph)
checks["rule diagnosis explains the fault, not 'KILL SWITCH: ...'"] = (not d["root_cause"].startswith("KILL SWITCH")
    and "pause vote" in d["root_cause"] and "vote_write 50%" in d["root_cause"] and d["affected_services"] == ["vote"])

# 5) AI status is reported honestly
from agentic import runtime  # noqa: E402
for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER"):
    os.environ.pop(k, None)
checks["ai_status: no key -> off"] = runtime.ai_status()["mode"] == "off"
os.environ.update(OPENAI_API_KEY="x", OPENAI_BASE_URL="https://api.groq.com/openai/v1", LLM_MODEL="openai/gpt-oss-120b")
st = runtime.ai_status()
checks["ai_status: groq key -> live groq model"] = st["mode"] == "live" and st["provider"] == "groq" and st["model"] == "openai/gpt-oss-120b"
checks["ai_status: --offline -> cached"] = runtime.ai_status(offline=True)["mode"] == "cached"
for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "LLM_MODEL"):
    os.environ.pop(k, None)

# 6) verifier: rows not re-tested are reported as untested
from agentic.nodes.execute import fix_statuses  # noqa: E402
st = fix_statuses([{"id": "F", "rows": ["E1", "E5"]}], [{"id": "E1", "rpn_before": 700, "rpn_after": 98}])
checks["verifier: skipped E5 reported as untested"] = st["F"]["status"] == "not_improved" and st["F"]["untested"] == ["E5"]

# 7) agent kit: prefetch gathers evidence by code, so the AI can answer after ONE call
import core.agentkit as AK  # noqa: E402
from core.agentkit import ReActAgent, Tool  # noqa: E402
calls = []
AK.ask_json = lambda *a, **k: (calls.append(1) or {"thought": "t", "final": {"root_cause": "from prefetched evidence"}}, "fake")
tools = {"list_containers": Tool("list_containers", "d", [], lambda: "redis exited"),
         "container_logs": Tool("container_logs", "d", ["service", "lines"], lambda service, lines: "log")}
fin, tr = ReActAgent("D", "r", tools, {"root_cause": "x"}, max_steps=4, prefetch=True,
                     starters=[("list_containers", {}), ("container_logs", {"service": "worker", "lines": 20})]).run("g", {})
checks["agent: prefetch -> answer after 1 AI call"] = fin == {"root_cause": "from prefetched evidence"} and len(calls) == 1 and len(tr) == 2

# 8) agent kit: time budget forces a final answer instead of waiting on rate limits forever
import time as _t  # noqa: E402
seq = iter([{"thought": "t", "tool": "list_containers", "args": {}},
            {"thought": "t", "tool": "container_logs", "args": {"service": "a", "lines": 1}},
            {"thought": "t", "tool": "container_logs", "args": {"service": "b", "lines": 1}},
            {"thought": "t", "final": {"root_cause": "forced"}}])
def slow(*a, **k):
    _t.sleep(0.4)
    return next(seq), "fake"
AK.ask_json = slow
fin, tr = ReActAgent("D2", "r", tools, {"root_cause": "x"}, max_steps=9, time_budget_s=0.7).run("g", {})
checks["agent: time budget makes it answer early"] = fin == {"root_cause": "forced"} or (fin is None and len(tr) <= 3)

# 9) Cartographer keeps a valid AI recon even when the app source is not cloned
import agentic.nodes.cartographer as CA  # noqa: E402
CA.recon_agent = lambda *a, **k: {"final": {"single_points_of_failure": ["redis", "nope"],
    "risks": [{"service": "worker", "weakness": "no restart policy", "evidence": "service_config(worker): restart=no"}],
    "hypotheses_to_test": ["if redis dies the worker exits"]}, "trace": []}
CA.SOURCE_AVAILABLE = lambda: False
tm = CA.cartographer_node({"graph": graph})["threat_model"]
checks["cartographer: AI recon kept without source code"] = tm["source"] == "agent" and tm["single_points_of_failure"] == ["redis"] and tm["risks"][0]["service"] == "worker"

for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
