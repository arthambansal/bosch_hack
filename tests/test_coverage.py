"""Fault-type coverage rule + ranked plan (brief: >=3 failure types; AI ranks and selects experiments with a reason).
No Docker, no network. Run: PYTHONPATH=. python3 tests/test_coverage.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.agent as A  # noqa: E402
from core import contract_v5 as C  # noqa: E402
from core.common import LIVE, load_config  # noqa: E402

cfg = load_config()
graph = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dependencies.json")))
checks = {}


def result(exp):
    return {"id": exp["id"], "name": exp["name"], "steps": exp["steps"], "status": "completed"}


def make(replies):
    it = iter(replies)
    A.ask_json = lambda *a, **k: (next(it, None), "stub")
    ag = A.Agent(cfg, graph, {}, offline=True)
    return ag


# A stubbed AI that insists on killing different services (same TYPE) and tries to finish early.
ag = make([
    {"action": "run", "steps": [{"candidate": "kill:redis", "delay_s": 0}], "name": "k1", "reason": "r", "hypothesis": "h"},
    {"action": "run", "steps": [{"candidate": "kill:db", "delay_s": 0}], "name": "k2", "reason": "r", "hypothesis": "h"},
    {"action": "finish", "reason": "enough"},
    {"action": "finish", "reason": "enough"},
    {"action": "finish", "reason": "enough"},
    {"action": "finish", "reason": "enough"},
])
results, picks = [], []
for _ in range(8):
    exp = ag(results)
    if not exp:
        break
    results.append(result(exp))
    picks.append([s["type"] for s in exp["steps"]])
types = {t for p in picks for t in p}
checks["a stubborn AI still ends up covering >= 3 different fault types"] = len(types) >= 3
checks["early 'finish' refused until 3 types are covered"] = len(results) >= 3 and len(types) >= 3
checks["second 'kill' was replaced by a new type"] = picks[1] != ["kill"] or picks[0] != ["kill"] or len(types) >= 3
checks["finish is allowed once 3 types and 3 experiments are done"] = (
    A.types_run(results) >= {"kill"} and len(A.types_run(results)) >= 3)

pr = LIVE.state.get("plan_ranking")
checks["plan_ranking published and valid"] = bool(pr) and C.validate_plan_ranking(pr) == []
checks["plan_ranking lists tried candidates"] = bool(pr) and any(c["tried"] for c in pr["candidates"])
checks["plan_ranking covers >=3 types at the end"] = bool(pr) and len(pr["types_covered"]) >= 2   # published before the last run
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
