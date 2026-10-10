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
         regression=[1], events=[{"msg": "old"}], graph={"services": {"vote": {}}}, thresholds={"max": 1},
         probes={"vote_write": {"n": 99, "p95_ms": 987}}, truth={"status": "diverged"}, faulted=[{"target": "db"}],
         experiment={"id": "E9"}, queue=[1], cleanup={"done": True}, report_path="x", approval_result={"a": 1},
         some_future_key="old", gate_sync=True)
LIVE.reset_run({"fresh": 1})
s = LIVE.state
gone = all(k not in s for k in ("fixes", "fmea_compare", "impact", "predictions", "plan_ranking", "threat_model", "memory", "mystery", "regression"))
checks["run evidence cleared"] = gone and s["findings"] is None and s["score"] is None and s["guard"] == {} and s["events"] == []
checks["old probe measurements and unknown keys dropped"] = (s["probes"] == {} and "truth" not in s and s["faulted"] == []
    and s["experiment"] is None and s["queue"] == [] and "cleanup" not in s and "report_path" not in s
    and "approval_result" not in s and "some_future_key" not in s and s["gate_sync"] is True)
checks["baseline replaced, graph/thresholds kept"] = s["baseline"] == {"fresh": 1} and s["graph"]["services"] and s["thresholds"] == {"max": 1}

# 2) a rollback that docker could not perform is NOT published as rolled_back
import agentic.nodes.execute as ex  # noqa: E402
import core.heal as heal  # noqa: E402

published, sent = {}, []
ORIG_PUBLISH = ex.publish_fixes
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
from core.contract_v5 import validate_fixes  # noqa: E402
entry = {"id": "F1", "title": "t", "kind": "compose", "for": ["E1"], "why": "w", "diff": None, "status": "applied", "rpn": []}
ex.publish_fixes = ORIG_PUBLISH
heal.fix_entries = lambda fs: [dict(entry) for f in fs]
import core.patches as patches  # noqa: E402
patches.suggest_patches = lambda *a, **k: []
pub = ex.publish_fixes([{"id": "F1"}], {"F1": {"status": "applied", "rollback_failed": True, "worse": row}}, [row])
checks["dashboard entry carries rollback_failed + worse"] = (pub[0]["rollback_failed"] is True and pub[0]["status"] == "applied"
    and pub[0]["worse"] == {"id": "E1", "before": 100, "after": 200} and validate_fixes(pub) == [])
pub = ex.publish_fixes([{"id": "F1"}], {"F1": {"status": "verified"}}, [row])
checks["normal entry has rollback_failed false, worse null"] = pub[0]["rollback_failed"] is False and pub[0]["worse"] is None and validate_fixes(pub) == []
checks["contract rejects rollback_failed on a rolled_back entry"] = validate_fixes([dict(entry, status="rolled_back", rollback_failed=True, worse={})]) != []
ex.publish_fixes = lambda fixes, statuses, cmp, inv=None, res=(): published.update(statuses)
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
