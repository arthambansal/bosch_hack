"""Mystery mode, verify-with-rollback and contract shapes. No Docker, no network.
Run: PYTHONPATH=. python3 tests/test_mystery.py"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.mystery as M  # noqa: E402
from agentic.nodes import diagnostician, execute  # noqa: E402
from agentic.nodes.governor import policy_check  # noqa: E402
from core import contract_v5 as C  # noqa: E402
from core.common import LIVE, load_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = load_config()
graph = json.load(open(os.path.join(ROOT, "dependencies.json")))
tmp = tempfile.mkdtemp()
M.TRIALS_FILE = os.path.join(tmp, "trials.jsonl")
M.REQUEST_FILE = os.path.join(tmp, "req.json")
M.REVEAL_PAUSE_S = 0
checks = {}

# ---- menu
items = M.menu(cfg)
ids = {m["id"] for m in items}
checks["menu has the 8 required faults"] = {"M-kill-redis", "M-kill-db", "M-kill-worker", "M-kill-result", "M-pause-redis",
                                           "M-pause-db", "M-partition-worker", "M-latency-redis"} <= ids
checks["every menu item passes the Safety Governor"] = all(
    policy_check({"steps": [{"type": m["fault"], "target": m["target"], "delay_s": 0}]}, graph) == [] for m in items)

# ---- scoring
ans = {"fault": "kill", "target": "redis"}
checks["score exact"] = M.score({"fault": "kill", "target": "redis", "top3": []}, ans) == {"top1": True, "top3": True, "target": True}
checks["score top3 only"] = M.score({"fault": "pause", "target": "redis",
                                     "top3": [{"fault": "pause", "target": "redis"}, {"fault": "kill", "target": "redis"}]},
                                    ans) == {"top1": False, "top3": True, "target": True}
checks["score target only"] = M.score({"fault": "pause", "target": "redis", "top3": [{"fault": "pause", "target": "redis"}]},
                                      ans) == {"top1": False, "top3": False, "target": True}
checks["score wrong / no guess"] = M.score({"fault": "kill", "target": "db", "top3": []}, ans)["target"] is False \
    and M.score(None, ans) == {"top1": False, "top3": False, "target": False}

# ---- redaction
res = {"id": "M1", "name": "kill redis", "steps": [{"type": "kill", "target": "redis"}], "faults_injected": ["KILL -> redis"],
       "reason": "hidden redis", "hypothesis": "h", "prediction": {"x": 1}, "prediction_check": {}, "predicted_probes": ["vote_write"],
       "status": "aborted", "abort_reason": "KILL SWITCH: redis unreachable", "probes": {"vote_write": {"error_rate": 1.0}},
       "stuck_services": ["redis"], "delivery": {"sent": 5, "delivered": 5, "lost": 0}, "recovery_s": 3.0}
red = M.redact(res, "redis")
checks["redaction drops every answer-revealing field"] = not (set(red) & M.HIDE_KEYS - {"name"}) and red["name"] == "Mystery fault"
checks["redaction scrubs the target from abort_reason"] = "redis" not in red["abort_reason"]
checks["redaction keeps the evidence"] = red["stuck_services"] == ["redis"] and "probes" in red and "delivery" in red


# ---- full trial with a fake engine and a canned diagnosis
class FakeEngine:
    def run_experiment(self, exp):
        assert exp["hidden"] is True and exp["name"] == "Mystery fault"
        LIVE.set(faulted=[{"target": "hidden", "type": "hidden"}])
        time.sleep(0.6)
        LIVE.set(faulted=[], guard={"tripped": True})
        return {**res, "id": exp["id"], "guard_log": [{"t": 1.0, "reasons": ["errors"]}]}


seen = {}


def fake_blind(r, c, g, offline=False):
    seen["redacted"] = json.dumps(r)
    seen["mystery_during"] = json.loads(json.dumps(LIVE.state.get("mystery")))
    return {"fault": "kill", "target": "redis", "confidence": 0.8, "root_cause": "redis died", "evidence": ["x"],
            "memory_hit": False, "top3": [{"fault": "kill", "target": "redis", "confidence": 0.8}]}


remembered = []
diagnostician.diagnose_blind = fake_blind
diagnostician.remember_confirmed = lambda r, f, rc: remembered.append(f)
st = M._State(cfg, 1)
item = next(m for m in items if m["id"] == "M-kill-redis")
line = M._run_one(FakeEngine(), cfg, graph, item, 1, True, "judge", st)
mys = LIVE.state["mystery"]
checks["final mystery state is revealed and valid"] = mys["state"] == "revealed" and C.validate_mystery(mys, list(cfg["services"])) == []
checks["answer/correct were null until the reveal"] = seen["mystery_during"]["answer"] is None and seen["mystery_during"]["correct"] is None \
    and seen["mystery_during"]["state"] in ("injected", "detected")
checks["diagnostician never saw the fault name"] = "faults_injected" not in seen["redacted"] and "KILL ->" not in seen["redacted"]
checks["trial scored top-1 and logged"] = line["correct"]["top1"] and M.accuracy(M.load_trials()) == {"trials": 1, "top1": 1, "top3": 1, "target": 1}
checks["detection recorded"] = line["detected_by"] in ("kill switch", "probes", "truth oracle", "container state") and line["seconds_to_detect"] is not None
checks["confirmed signature saved on a correct guess"] = remembered == [ans]
checks["no hidden target in events before reveal"] = not any("redis" in e["msg"].lower() and "REVEAL" not in e["msg"]
                                                              for e in LIVE.state["events"] if "[Mystery]" in e["msg"])

# ---- request file
valid = {m["id"] for m in items}
open(M.REQUEST_FILE, "w").write(json.dumps({"choice_id": "M-kill-redis", "by": "dashboard"}))
checks["valid request consumed and file deleted"] = M._read_request(valid) == "M-kill-redis" and not os.path.exists(M.REQUEST_FILE)
open(M.REQUEST_FILE, "w").write(json.dumps({"choice_id": "rm -rf /"}))
checks["bad choice_id rejected and file deleted"] = M._read_request(valid) is None and not os.path.exists(M.REQUEST_FILE)
open(M.REQUEST_FILE, "w").write("{not json")
checks["corrupt request file ignored and deleted"] = M._read_request(valid) is None and not os.path.exists(M.REQUEST_FILE)
open(M.REQUEST_FILE, "w").write(json.dumps({"choice_id": "random"}))
checks["'random' accepted"] = M._read_request(valid) == "random"
try:
    M._pick(items, "nope")
    checks["unknown choice raises"] = False
except ValueError:
    checks["unknown choice raises"] = True

# ---- rollback decisions
fixes = [{"id": "restart-policy", "rows": ["E1", "E2"], "file": "a.yml", "why": "w"},
         {"id": "bad-fix", "rows": ["E3"], "file": "b.yml", "why": "w"},
         {"id": "meh-fix", "rows": ["E4"], "file": "c.yml", "why": "w"}]
cmp = [{"id": "E1", "rpn_before": 270, "rpn_after": 30, "reduction_pct": 89}, {"id": "E2", "rpn_before": 90, "rpn_after": 60, "reduction_pct": 33},
       {"id": "E3", "rpn_before": 630, "rpn_after": 700, "reduction_pct": -11}, {"id": "E4", "rpn_before": 50, "rpn_after": 50, "reduction_pct": 0}]
stat = execute.fix_statuses(fixes, cmp)
checks["improved fix is verified"] = stat["restart-policy"]["status"] == "verified"
checks["a fix that makes a row worse is rolled back"] = stat["bad-fix"]["status"] == "rolled_back" and stat["bad-fix"]["worse"]["id"] == "E3"
checks["unchanged fix is not_improved"] = stat["meh-fix"]["status"] == "not_improved"
checks["missing re-test counts as not_improved"] = execute.fix_statuses(fixes, cmp[:1])["restart-policy"]["status"] == "not_improved"
entries = execute.publish_fixes(fixes, stat, cmp)
checks["published fixes pass the contract"] = C.validate_fixes(entries) == [] and \
    next(e for e in entries if e["id"] == "bad-fix")["rpn"] == [{"id": "E3", "before": 630, "after": 700}]
checks["format_table runs"] = "top-1 1/1" in M.format_table(M.load_trials())

for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
