"""Day 2 contract check: every interface exists with the agreed signature, every live_state shape validates.
No Docker, no network. Run: PYTHONPATH=. python3 tests/test_contract_v5.py"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import contract_v5 as C  # noqa: E402
from core.common import load_config  # noqa: E402

cfg = load_config()
SERVICES = set(cfg["services"])
checks = {}


def params(fn):
    return list(inspect.signature(fn).parameters)


def sig(name, fn, expected):
    checks[f"signature {name}{tuple(expected)}"] = params(fn)[:len(expected)] == expected


from core.truth import TruthOracle  # noqa: E402
from core import patches, regression, notify, mystery, heal, report_extras  # noqa: E402
from agentic.nodes import diagnostician  # noqa: E402

sig("TruthOracle.__init__", TruthOracle.__init__, ["self", "cfg", "prober", "interval_s", "grace_s"])
sig("TruthOracle.window", TruthOracle.window, ["self", "t_start", "t_end"])
sig("patches.suggest_patches", patches.suggest_patches, ["investigations", "results"])
sig("heal.fix_entries", heal.fix_entries, ["fixes"])
sig("diagnostician.diagnose_blind", diagnostician.diagnose_blind, ["res", "cfg", "graph", "offline"])
sig("diagnostician.remember_confirmed", diagnostician.remember_confirmed, ["res", "fault", "root_cause"])
sig("report_extras.impact_of", report_extras.impact_of, ["result"])
sig("report_extras.scorecard", report_extras.scorecard, ["results", "verification", "trials"])
sig("report_extras.postmortem", report_extras.postmortem, ["result", "investigation", "impact"])
sig("regression.export_scenario", regression.export_scenario, ["result", "investigation", "run_dir"])
sig("regression.replay", regression.replay, ["path", "cfg"])
sig("regression.list_scenarios", regression.list_scenarios, [])
sig("notify.notify", notify.notify, ["kind", "title", "text", "fields"])
sig("mystery.menu", mystery.menu, ["cfg"])
sig("mystery.run_trial", mystery.run_trial, ["choice_id", "cfg", "graph", "offline", "chosen_by"])
sig("mystery.wait_loop", mystery.wait_loop, ["cfg", "graph", "offline"])

# shapes produced by the (stub or real) implementations
oracle = TruthOracle(cfg)
checks["truth snapshot shape"] = C.validate_truth(oracle.snapshot()) == []
checks["truth window keys"] = set(oracle.window(0, 1)) >= {"sent", "stored", "suspected_lost", "diverged"}
fake = {"id": "E1", "delivery": {"sent": 10, "delivered": 8, "lost": 2}, "stuck_services": ["worker"], "probes": {},
        "recovery_s": None, "fault_window_s": 20.0, "status": "completed"}
checks["impact_of shape"] = C.validate_impact(report_extras.impact_of(fake)) == []
checks["fix_entries shape"] = C.validate_fixes(heal.fix_entries([{"id": "restart-policy", "rows": ["E1"], "why": "x"}])) == []
checks["suggest_patches shape"] = C.validate_fixes(patches.suggest_patches({}, [fake])) == []
checks["regression list shape"] = C.validate_regression(regression.list_scenarios()) == []
checks["notify without webhook is a silent no-op"] = (os.environ.get("DISCORD_WEBHOOK_URL") is not None
                                                       or notify.notify("report", "t", "x") is False)
redacted = {k: v for k, v in fake.items()}
guess = diagnostician.diagnose_blind(redacted, cfg, {}, offline=True)
checks["diagnose_blind shape"] = C.validate_guess(guess, SERVICES) == [] and "seconds" in guess
rep = regression.replay("scenarios/does-not-exist.json", cfg)
checks["replay never raises, returns passed flag"] = isinstance(rep, dict) and "passed" in rep
menu = mystery.menu(cfg)
checks["mystery menu items valid"] = all(not C._need(m, ["id", "label", "fault", "target"], "m") for m in menu)

# fixtures used by the dashboard must match the contract
fx_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "fixtures")
for name in sorted(os.listdir(fx_dir)) if os.path.isdir(fx_dir) else []:
    if not name.endswith(".json"):
        continue
    s = json.load(open(os.path.join(fx_dir, name)))
    problems = []
    for key, fn in (("truth", C.validate_truth), ("memory", C.validate_memory), ("fixes", C.validate_fixes),
                    ("impact", C.validate_impact), ("predictions", C.validate_predictions),
                    ("regression", C.validate_regression), ("plan_ranking", C.validate_plan_ranking)):
        if key in s:
            problems += fn(s[key])
    if "mystery" in s:
        problems += C.validate_mystery(s["mystery"], SERVICES)
    checks[f"fixture {name} matches contract"] = problems == []
    if problems:
        print("   ", name, problems[:5])

# validators really reject bad data
checks["validator rejects diverged while monitoring degraded"] = bool(C.validate_truth(
    {"status": "diverged", "monitoring": "degraded", "canaries": {"sent": 1, "stored": 1, "pending": 0,
     "suspected_lost": 0, "last_lag_s": None, "grace_s": 10}, "invariants": [], "diverged_at": None, "updated_at": 0}))
checks["validator rejects applied code suggestion"] = bool(C.validate_fixes([{"id": "p", "title": "t",
    "kind": "code_suggestion", "for": [], "why": "", "diff": "", "status": "applied", "rpn": []}]))
checks["validator rejects early answer"] = bool(C.validate_mystery({"state": "diagnosed", "trial": 1, "menu": [],
    "chosen_by": None, "injected_at": None, "detected_at": None, "diagnosed_at": None, "detected_by": None,
    "guess": None, "answer": {"fault": "kill", "target": "db"}, "correct": None,
    "accuracy": {"trials": 0, "top1": 0, "top3": 0, "target": 0}}))
checks["canary votes excluded from delivery count"] = "canary-" in " ".join(cfg["delivery_check"]["cmd"])

for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print("ALL CHECKS PASSED" if all(checks.values()) else "SOME CHECKS FAILED")
sys.exit(0 if all(checks.values()) else 1)
