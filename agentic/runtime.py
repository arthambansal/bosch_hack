"""Process-level objects that must NOT live in graph state (they are not JSON): config, engine, run folder."""
import os
import time

from core.common import BASELINE_FILE, LATEST_FILE, LIVE, RUNS_DIR, STOP_FILE, load_config, load_json
from core.engine import Engine
from core.faults import panic
from agentic.gate import GATE_SYNC

RT = {"cfg": None, "engine": None, "run_dir": None, "oracle": None}


def cfg():
    if RT["cfg"] is None:
        RT["cfg"] = load_config()
    return RT["cfg"]


def run_dir():
    return RT["run_dir"]


def engine():
    return RT["engine"]


def ai_status(offline=False):
    """Which AI is really in use. Printed at the start of every run and shown on the dashboard, so a missing key is
    never discovered after the demo."""
    from core.llm import provider
    p = provider()
    model = os.getenv("LLM_MODEL") or ("claude-haiku-5-5" if p == "anthropic" else "llama-3.3-70b-versatile")
    if offline:
        mode = "cached"
    elif p == "none":
        mode = "off"
    else:
        mode = "live"
    base = os.getenv("OPENAI_BASE_URL", "")
    vendor = "groq" if "groq" in base else ("anthropic" if p == "anthropic" else (p if p != "openai" else (base or "openai")))
    return {"mode": mode, "provider": vendor if p != "none" else None, "model": model if p != "none" else None,
            "agent_model": os.getenv("LLM_AGENT_MODEL") or (model if p != "none" else None)}


def start(graph, offline=False):
    """Create the run folder and start background traffic. Call once before the graph runs."""
    d = os.path.join(RUNS_DIR, "auto_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    LIVE.reset_run(load_json(BASELINE_FILE, None))        # new run: drop the previous run's evidence, keep the saved baseline
    LIVE.log_path = os.path.join(d, "events.log")
    with open(LATEST_FILE, "w") as f:
        f.write(d)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    eng = Engine(cfg(), graph)
    eng.prober.start()
    oracle = start_oracle(eng)
    RT.update(engine=eng, run_dir=d, oracle=oracle)
    ai = ai_status(offline)
    if ai["mode"] == "off":
        LIVE.event("warn", "AI is OFF: no OPENAI_API_KEY / ANTHROPIC_API_KEY in this shell. Every agent will use its "
                           "deterministic rules. Export the key (see README) and restart for the AI agents.")
    else:
        LIVE.event("ai", f"AI {ai['mode'].upper()}: {ai['provider']} {ai['model']} (tool agents: {ai['agent_model']})")
    LIVE.set(provenance={"measurements": "docker_sandbox", "project": cfg().get("project"), "ai": ai,
                         "started_at": time.time()})
    LIVE.set(phase="running", run_status="running", run_dir=d, agent_active=None, approval_request=None, gate_sync=GATE_SYNC,
             approval_result=None, cleanup=None, report_path=None)
    return d


def start_oracle(eng):
    """Truth Oracle (gray-failure detector, core/truth.py). Best-effort: a failure here never stops a run."""
    try:
        from core.truth import TruthOracle
        oracle = TruthOracle(cfg(), eng.prober)
        oracle.start()
        eng.oracle = oracle
        return oracle
    except Exception as exc:  # noqa: BLE001
        LIVE.event("warn", f"[Truth] oracle unavailable ({type(exc).__name__}: {exc})")
        return None


def stop_oracle():
    oracle = RT.get("oracle")
    if oracle is not None:
        try:
            oracle.stop()
        except Exception:  # noqa: BLE001
            pass
        RT["oracle"] = None


def finish():
    """Always called, even on Ctrl+C or a crash: undo any active fault and stop traffic, then publish the TRUE end state."""
    stopped = os.path.exists(STOP_FILE)
    eng = RT.get("engine")
    if eng:
        eng._restore_all()
    if stopped:
        panic(cfg())
    stop_oracle()
    if eng:
        eng.prober.stop()
    LIVE.set(phase="stopped" if stopped else "ran", run_status="stopped" if stopped else "completed", agent_active=None,
             faulted=[], approval_request=None, cleanup={"done": True, "stopped": stopped, "at": time.time()})
