"""Run lifecycle: per-run evidence reset, honest failed rollback, atomic + locked mystery request claim."""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, ".")
checks = {}

# 1) starting a run forgets the previous run's evidence but keeps global catalogs
from core.common import LIVE  # noqa: E402

LIVE.set(fixes=[1], fmea_compare=[1], impact={"x": 1}, predictions=[1], plan_ranking=[1], findings={"a": 1}, score=61,
         guard={"tripped": True}, baseline={"old": 1}, threat_model={"t": 1}, memory={"last_hit": 1}, mystery={"state": "revealed"},
         regression=[1], events=[{"msg": "old"}], graph={"services": {"vote": {}}}, thresholds={"max": 1})
LIVE.reset_run({"fresh": 1})
s = LIVE.state
gone = all(k not in s for k in ("fixes", "fmea_compare", "impact", "predictions", "plan_ranking", "threat_model", "memory", "mystery", "regression"))
checks["run evidence cleared"] = gone and s["findings"] is None and s["score"] is None and s["guard"] == {} and s["events"] == []
checks["baseline replaced, graph/thresholds kept"] = s["baseline"] == {"fresh": 1} and s["graph"]["services"] and s["thresholds"] == {"max": 1}

# 2) a rollback that docker could not perform is NOT published as rolled_back
import agentic.nodes.execute as ex  # noqa: E402
import core.heal as heal  # noqa: E402

published, sent = {}, []
row = {"id": "E1", "rpn_before": 100, "rpn_after": 200, "reduction_pct": -100}
ex.engine = lambda: type("E", (), {"cfg": {}, "run_experiment": lambda self, e: {"id": e["id"]}})()
ex.build_fmea = lambda *a, **k: []
ex.compare_fmea = lambda *a, **k: [dict(row)]
ex.publish_fixes = lambda fixes, statuses, cmp, inv=None, res=(): published.update(statuses)
ex._notify = lambda kind, *a, **k: sent.append(kind)
ex.save_json = lambda *a, **k: None
ex.run_dir = lambda: tempfile.mkdtemp()
ex.time.sleep = lambda s: None
state = {"fixes": [{"id": "F1", "rows": ["E1"]}], "results": [{"id": "E1", "name": "n", "steps": [], "reason": "", "hypothesis": "", "predicted_probes": []}],
         "fmea": [{"id": "E1"}], "baseline": {}, "investigations": {}}
heal.apply_fixes = lambda fixes, cfg: False
out = ex.verify_node(state)
checks["failed rollback: fix stays 'applied'"] = published["F1"]["status"] == "applied" and out["verification"]["fix_status"]["F1"] == "applied"
checks["failed rollback: not listed as rolled_back"] = out["rolled_back"] == [] and out["rollback_failed"] == ["F1"] and [f["id"] for f in out["fixes"]] == ["F1"]
checks["failed rollback: only the failure alert is sent"] = sent == ["fix_rollback_failed"]
sent.clear()
heal.apply_fixes = lambda fixes, cfg: True
out = ex.verify_node(state)
checks["good rollback: rolled_back + rolled_back alert"] = out["rolled_back"] == ["F1"] and out["fixes"] == [] and sent == ["fix_rolled_back"]

# 3) mystery request: claimed once, and the state turns non-idle before the lock is released
import core.mystery as m  # noqa: E402

d = tempfile.mkdtemp()
m.REQUEST_FILE = os.path.join(d, "mystery_request.json")
json.dump({"choice_id": "random"}, open(m.REQUEST_FILE, "w"))
results = []
threads = [threading.Thread(target=lambda: results.append(m._read_request({"x"}))) for _ in range(6)]
[t.start() for t in threads]
[t.join() for t in threads]
checks["request claimed by exactly one reader"] = sorted(r for r in results if r) == ["random"] and os.listdir(d) == []


class FakeState:
    def __init__(self):
        self.state = "idle"
        self.lock_seen = None

    def set(self, state):
        self.lock_seen = os.path.isdir(os.path.join(d, "dashboard_mystery.lock"))
        self.state = state


json.dump({"choice_id": "x"}, open(m.REQUEST_FILE, "w"))
fs = FakeState()
checks["state flips while the lock is held"] = m._read_request({"x"}, fs) == "x" and fs.state == "injected" and fs.lock_seen is True
checks["lock released afterwards"] = not os.path.exists(os.path.join(d, "dashboard_mystery.lock"))
json.dump({"choice_id": "bogus"}, open(m.REQUEST_FILE, "w"))
fs = FakeState()
checks["invalid choice leaves state idle and file removed"] = m._read_request({"x"}, fs) is None and fs.state == "idle" and os.listdir(d) == []

for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
