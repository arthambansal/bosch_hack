"""Authorized sandbox pause/kill collection. Produces unconfirmed real cases."""
import copy
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.common import BASELINE_FILE, LIVE, STOP_FILE, docker, load_config
from core.engine import Engine
from core.faults import Fault
from agentic.nodes.governor import policy_check


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    if Path(STOP_FILE).exists():
        raise SystemExit("STOP exists; collection refused. It has not been removed.")
    config = copy.deepcopy(load_config())
    config["experiment_defaults"].update(warmup_s=3, duration_s=8, recovery_timeout_s=20, cooldown_s=3)
    config["safety"]["max_experiment_s"] = min(config["safety"]["max_experiment_s"], 15)
    graph = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8-sig"))
    for kind in ("pause", "kill"):
        Fault(kind, "redis", config)  # validate sandbox membership before any change
    for name, service in config["services"].items():
        ok, project = docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', service["container"])
        if not ok or project.strip() != config["project"]:
            raise SystemExit(f"Sandbox membership not verified for {name}")
    tag = uuid.uuid4().hex[:10]
    directory = ROOT / "runs" / f"actual_rag_cases_{tag}"
    directory.mkdir()
    LIVE.log_path = str(directory / "events.log")
    engine = Engine(config, graph)
    baseline_path = Path(BASELINE_FILE)
    original_baseline = baseline_path.read_bytes() if baseline_path.exists() else None
    results = []
    try:
        stopped = engine._stopped()
        save(directory / "provenance.json", {"source": "actual local Docker experiments; test votes submitted",
            "preexisting_stopped": stopped, "manual_confirmation": False,
            "fault_duration_limit_s": 8, "hard_limit_s": config["safety"]["max_experiment_s"]})
        if stopped:
            engine._start_services(stopped)
        if engine._stopped():
            raise RuntimeError("Services did not stay running; no experiment injected")
        baseline = engine.baseline(seconds=8)
        save(directory / "baseline.json", baseline)
        delivery = baseline["delivery"]
        if any(p["n"] == 0 or p["error_rate"] != 0 for p in baseline["probes"].values()) or not delivery["sent"] or delivery["delivered"] != delivery["sent"]:
            raise RuntimeError("Healthy end-to-end baseline not established; no fault injected")
        for kind in ("pause", "kill"):
            if Path(STOP_FILE).exists():
                break
            proposal = {"id": f"ACTUAL-RAG-{kind.upper()}-{tag}", "name": f"Measured Redis {kind}",
                "steps": [{"type": kind, "target": "redis", "delay_s": 0}],
                "reason": "Collect real measured evidence for manual failure-case review",
                "hypothesis": "Redis interruption may affect vote writes; recovery and delivery must be measured",
                "predicted_probes": ["vote_write"]}
            reasons = policy_check(proposal, graph)
            if reasons:
                raise RuntimeError(f"Governor refused: {reasons}")
            save(directory / f"{kind}_proposal.json", proposal)
            result = engine.run_experiment(proposal)
            results.append(result)
            save(directory / "results.json", results)
            save(directory / f"{kind}.json", result)
            if result.get("status") == "refused" or "injection failed" in str(result.get("abort_reason")):
                raise RuntimeError("Injection was refused or failed; inspect saved evidence")
    finally:
        engine.prober.stop()
        engine._restore_all()
        stopped = engine._stopped()
        if stopped:
            engine._start_services(stopped)
        ok, ping = docker("exec", config["services"]["redis"]["container"], "redis-cli", "PING")
        save(directory / "restoration.json", {"stopped_services": engine._stopped(),
            "redis_ping_ok": ok and ping.strip() == "PONG", "redis_ping_output": ping})
        if original_baseline is not None:
            baseline_path.write_bytes(original_baseline)
        elif baseline_path.exists():
            baseline_path.unlink()
        print("Actual evidence saved:", directory)
        print("No causes have been marked confirmed.")


if __name__ == "__main__":
    main()
