"""One real dashboard fault check; production nodes, no planner or applied fixes."""
import argparse
import copy
import json
from pathlib import Path
import sys
import threading
import time
import uuid
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.common import LIVE, STOP_FILE, load_config, save_json
from core.engine import Engine
from agentic import runtime
from agentic.nodes.cartographer import cartographer_node
from agentic.nodes.governor import governor_node
from agentic.nodes.execute import execute_node, evaluate_node
from agentic.nodes.diagnostician import diagnostician_node
from agentic.nodes.reporter import reporter_node


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fault", choices=["pause", "kill"])
    args = parser.parse_args()
    if Path(STOP_FILE).exists():
        raise SystemExit("STOP exists; refused without removing it")
    requests.get("http://127.0.0.1:5173/state", timeout=3).raise_for_status()
    config = copy.deepcopy(load_config())
    config["experiment_defaults"].update(warmup_s=5, duration_s=8, recovery_timeout_s=20)
    config["safety"]["max_experiment_s"] = min(15, config["safety"]["max_experiment_s"])
    graph = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8-sig"))
    runtime.RT["cfg"] = config
    snapshots, errors = [], []
    done = threading.Event()

    def poll():
        while not done.is_set():
            try:
                response = requests.get("http://127.0.0.1:5173/state", timeout=2)
                response.raise_for_status()
                snapshots.append({"received_at": time.time(), "state": response.json()})
            except (requests.RequestException, ValueError) as exc:
                errors.append(type(exc).__name__)
            done.wait(0.25)

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    baseline_engine = Engine(config, graph)
    directory = None
    try:
        if baseline_engine._stopped():
            raise RuntimeError("Stopped services found; no fault injected")
        baseline = baseline_engine.baseline(seconds=8)
        baseline_engine.prober.stop()
        if any(p["n"] == 0 or p["error_rate"] != 0 for p in baseline["probes"].values()):
            raise RuntimeError("Healthy HTTP baseline not established")
        if Path(STOP_FILE).exists():
            raise RuntimeError("STOP requested during baseline; no fault injected")
        directory = runtime.start(graph)
        identifier = f"DASH-REDIS-{args.fault.upper()}-{uuid.uuid4().hex[:8]}"
        proposal = {"id": identifier, "name": f"Dashboard live Redis {args.fault}",
            "steps": [{"type": args.fault, "target": "redis", "delay_s": 0}],
            "reason": "User requested a real fault while watching the dashboard",
            "hypothesis": "Redis interruption may impair vote writes; measure errors and restoration",
            "predicted_probes": ["vote_write"]}
        state = {"graph": graph, "baseline": baseline, "offline": False, "results": [],
            "investigations": {}, "proposal": proposal, "skip_heal": True}
        state.update(governor_node(state))
        if not state["review"]["approved"]:
            raise RuntimeError("Governor refused the experiment")
        save_json(str(Path(directory) / "baseline.json"), baseline)
        LIVE.set(queue=[dict(id=identifier, name=proposal["name"], status="planned", reason=proposal["reason"])])
        state.update(cartographer_node(state))
        state.update(execute_node(state))
        state.update(evaluate_node(state))
        state.update(diagnostician_node(state))
        state["done_reason"] = "Single actual dashboard fault check; no fixes applied"
        state.update(reporter_node(state))
        LIVE.set(report_path=state["report"]["path_md"])
        save_json(str(Path(directory) / "final_state.json"), state)
        print("ACTUAL DASHBOARD REPORT:", state["report"]["path_md"])
    finally:
        baseline_engine.prober.stop()
        if runtime.RT.get("engine"):
            runtime.finish()
        time.sleep(1)
        done.set()
        thread.join(timeout=3)
        if directory:
            save_json(str(Path(directory) / "dashboard_snapshots.json"),
                {"provenance": "Actual HTTP polling through Vite /state proxy; no browser rendering assertion",
                 "poll_errors": errors, "snapshots": snapshots})
            print("Dashboard HTTP snapshots:", len(snapshots), "poll errors:", len(errors))


if __name__ == "__main__":
    main()
