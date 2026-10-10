"""Measure the single safe scenario used by manual resilience CI.

Run after `chaospilot.py up`, `map`, and `baseline`. The production Engine keeps
the sandbox label check, Guard, STOP, restoration, and delivery audit in force.
"""
import json
import math
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.common import DEPS_FILE, LIVE, RUNS_DIR, STOP_FILE, load_config, load_json, save_json  # noqa: E402
from core.engine import Engine  # noqa: E402


def measured_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def main():
    if os.path.exists(STOP_FILE):
        raise SystemExit("STOP exists. Run `python chaospilot.py panic`, review the sandbox, then retry.")
    cfg = load_config()
    graph = load_json(DEPS_FILE)
    if not graph:
        raise SystemExit("dependencies.json is unavailable. Run `python chaospilot.py map` first.")

    run_id = "ci_measure_" + time.strftime("%Y%m%d_%H%M%S")
    run_dir = pathlib.Path(RUNS_DIR) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    LIVE.log_path = str(run_dir / "events.log")
    exp = {
        "id": "CI-RESULT-PAUSE",
        "name": "pause result for CI validation",
        "reason": "Measure recovery of the non-stateful result service for safe CI replay.",
        "hypothesis": "The result page fails temporarily, then recovers without accepted vote loss.",
        "steps": [{"type": "pause", "target": "result", "delay_s": 0}],
        "predicted_probes": ["result_page"],
    }
    engine = Engine(cfg, graph)
    result = None
    try:
        engine.prober.start()
        result = engine.run_experiment(exp)
    finally:
        engine._restore_all()
        engine.prober.stop()
    save_json(str(run_dir / "results.json"), [result])

    recovery = result.get("recovery_s")
    delivery = result.get("delivery") or {}
    lost = delivery.get("lost")
    stuck = result.get("stuck_services")
    abort = (result.get("abort_reason") or "").lower()
    valid = (result.get("status") in ("completed", "aborted")
             and "injection failed" not in abort
             and measured_number(recovery)
             and measured_number(lost) and lost == 0
             and isinstance(stuck, list) and not stuck)
    if not valid:
        raise SystemExit(
            f"Measurement did not qualify: status={result.get('status')}, recovery_s={recovery!r}, "
            f"lost={lost!r}, stuck={stuck!r}. Evidence kept in runs/{run_id}; no scenario written."
        )

    # Measured margin for scheduler jitter; derived from this run and never below 5 s.
    recovery_limit = max(5, math.ceil(recovery * 2))
    probe = (result.get("probes") or {}).get("result_page") or {}
    scenario = {
        "id": "result-pause-ci",
        "name": "Result service pause recovery",
        "steps": exp["steps"],
        "invariants": ["no_vote_loss", f"recovers_within_s:{recovery_limit}"],
        "from_run": f"runs/{run_id}",
        "evidence": [
            f"Measured delivery: {delivery.get('sent')} accepted, {delivery.get('delivered')} delivered, {lost} lost",
            f"Measured recovery_s={recovery}; result_page error_rate={probe.get('error_rate')}",
        ],
    }
    scenario_path = ROOT / "scenarios" / "result-pause-ci.json"
    if scenario_path.exists():
        raise SystemExit(f"{scenario_path} exists; review it instead of overwriting measured evidence.")
    scenario_path.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
    print(f"PASS measured safe scenario: {scenario_path}")
    print(f"Measurement: recovery_s={recovery}, recovery limit={recovery_limit}, lost={lost}, stuck={stuck}")
    print(f"Raw evidence: {run_dir / 'results.json'} and {run_dir / 'events.log'}")


if __name__ == "__main__":
    main()
