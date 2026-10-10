"""Process-level objects that must NOT live in graph state (they are not JSON): config, engine, run folder."""
import os
import time

from core.common import LATEST_FILE, LIVE, RUNS_DIR, STOP_FILE, load_config
from core.engine import Engine
from core.faults import panic
from agentic.gate import GATE_SYNC

RT = {"cfg": None, "engine": None, "run_dir": None}


def cfg():
    if RT["cfg"] is None:
        RT["cfg"] = load_config()
    return RT["cfg"]


def run_dir():
    return RT["run_dir"]


def engine():
    return RT["engine"]


def start(graph):
    """Create the run folder and start background traffic. Call once before the graph runs."""
    d = os.path.join(RUNS_DIR, "auto_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    LIVE.log_path = os.path.join(d, "events.log")
    with open(LATEST_FILE, "w") as f:
        f.write(d)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    eng = Engine(cfg(), graph)
    eng.prober.start()
    RT.update(engine=eng, run_dir=d)
    LIVE.set(phase="running", run_status="running", run_dir=d, agent_active=None, approval_request=None, gate_sync=GATE_SYNC,
             approval_result=None, cleanup=None, report_path=None)
    return d


def finish():
    """Always called, even on Ctrl+C or a crash: undo any active fault and stop traffic, then publish the TRUE end state."""
    stopped = os.path.exists(STOP_FILE)
    eng = RT.get("engine")
    if eng:
        eng._restore_all()
    if stopped:
        panic(cfg())
    if eng:
        eng.prober.stop()
    LIVE.set(phase="stopped" if stopped else "ran", run_status="stopped" if stopped else "completed", agent_active=None,
             experiment=None, faulted=[], approval_request=None, cleanup={"done": True, "stopped": stopped, "at": time.time()})
