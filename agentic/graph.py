"""The multi-agent graph (LangGraph). Owner: Artham.

cartographer -> experimenter -> governor -> [human gate] -> execute -> evaluate -> (diagnostician) -> experimenter ... loop
experimenter done -> remediator -> verify -> (remediator again if not improved) -> reporter -> END

LangGraph gives us: explicit routing (the AI decides INSIDE nodes, the graph decides WHAT CAN HAPPEN NEXT),
interrupt() for human approval, a checkpointer (pause/resume), streaming of every node for the dashboard,
and an auto-generated diagram of the graph (python chaospilot.py graph).
"""
import select
import sys
import time

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from core.common import BASELINE_FILE, DEPS_FILE, LIVE, RUNS_DIR, load_json

from . import runtime
from .nodes.execute import evaluate_node, execute_node, needs_investigation, verify_node
from .nodes.diagnostician import diagnostician_node
from .nodes.cartographer import cartographer_node
from .nodes.remediator import remediator_node
from .nodes.reporter import reporter_node
from .nodes.governor import approval_node, governor_node
from .nodes.experimenter import experimenter_node
from .state import ChaosState

MAX_REJECTIONS = 3


def guarded(name, fn, fallback):
    """A teammate's node may crash while being upgraded. Never let that kill the run: log it, use a safe fallback."""
    def wrapper(state):
        try:
            return fn(state)
        except Exception as e:  # noqa: BLE001 - deliberate: the demo must survive
            LIVE.event("warn", f"[{name}] crashed ({type(e).__name__}: {e}); using safe fallback")
            return fallback(state)
    return wrapper


FALLBACKS = {
    "cartographer": lambda s: {"threat_model": {"single_points_of_failure": [], "risks": [], "hypotheses_to_test": [],
                                         "source": "error"}},
    "experimenter": lambda s: {"proposal": None, "done_reason": "experimenter error"},
    "governor": lambda s: {"review": {"approved": False, "reasons": ["safety node error: denied by default"]},
                         "rejections": s.get("rejections", 0) + 1},
    "diagnostician": lambda s: {},
    "remediator": lambda s: {"pending_fix": False},
    "reporter": lambda s: {},
}


def after_governor(s):
    if s["review"]["approved"]:
        return "approval"
    return "remediator" if s.get("rejections", 0) >= MAX_REJECTIONS else "experimenter"


def build(checkpointer=None):
    g = StateGraph(ChaosState)
    for name, fn in [("cartographer", cartographer_node), ("experimenter", experimenter_node), ("governor", governor_node),
                     ("approval", approval_node), ("execute", execute_node), ("evaluate", evaluate_node),
                     ("diagnostician", diagnostician_node), ("remediator", remediator_node),
                     ("verify", verify_node), ("reporter", reporter_node)]:
        g.add_node(name, guarded(name, fn, FALLBACKS[name]) if name in FALLBACKS else fn)
    g.add_edge(START, "cartographer")
    g.add_edge("cartographer", "experimenter")
    g.add_conditional_edges("experimenter", lambda s: "governor" if s.get("proposal") else "remediator",
                            ["governor", "remediator"])
    g.add_conditional_edges("governor", after_governor, ["approval", "experimenter", "remediator"])
    g.add_conditional_edges("approval", lambda s: "execute" if s["review"]["approved"] else "experimenter",
                            ["execute", "experimenter"])
    g.add_edge("execute", "evaluate")
    g.add_conditional_edges("evaluate", needs_investigation, ["diagnostician", "experimenter"])
    g.add_edge("diagnostician", "experimenter")
    g.add_conditional_edges("remediator", lambda s: "verify" if s.get("pending_fix") else "reporter",
                            ["verify", "reporter"])
    g.add_conditional_edges("verify", lambda s: "reporter" if (s["verification"]["improved"] or
                                                              s.get("fix_attempts", 0) >= 2) else "remediator",
                            ["remediator", "reporter"])
    g.add_edge("reporter", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())


def ask_human(req, timeout_s=180):
    """Terminal y/n, or the dashboard writes runs/approval.json {"answer": "yes"}. No answer = deny (safe default)."""
    import json
    import os
    path = os.path.join(RUNS_DIR, "approval.json")
    if os.path.exists(path):
        os.remove(path)
    print(f"\n>>> HUMAN APPROVAL NEEDED: {req['question']}\n    why: {req.get('reason')}\n    type y or n: ", end="", flush=True)
    end = time.time() + timeout_s
    while time.time() < end:
        if os.path.exists(path):
            try:
                return json.load(open(path)).get("answer", "no")
            except (OSError, ValueError):
                pass
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if ready:
            return sys.stdin.readline().strip()
    print("(no answer, denied)")
    return "no"


def run(goal="", require_approval=False, offline=False, heal=True):
    deps, base = load_json(DEPS_FILE), load_json(BASELINE_FILE, {})
    if not deps:
        sys.exit("Missing dependencies.json. Run: python chaospilot.py map")
    app = build()
    conf = {"configurable": {"thread_id": "chaos-" + time.strftime("%H%M%S")}, "recursion_limit": 200}
    state_in = {"goal": goal, "graph": deps, "baseline": base, "offline": offline, "require_approval": require_approval,
                "skip_heal": not heal, "results": [], "investigations": {}, "fmea": [], "fixes": [],
                "rejections": 0, "rejected_sigs": [], "fix_attempts": 0}
    runtime.start(deps)
    LIVE.event("info", f"AUTOPILOT start. Goal: {goal or 'find the weakest points'}")
    try:
        inp = state_in
        while True:
            pending = None
            for chunk in app.stream(inp, conf, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    pending = chunk["__interrupt__"][0].value
                else:
                    LIVE.event("info", f"[graph] {next(iter(chunk))} done")
            if pending is None:
                break
            inp = Command(resume=ask_human(pending))
    except KeyboardInterrupt:
        LIVE.event("guard", "Ctrl+C - restoring everything before exit")
    finally:
        runtime.finish()
    return app.get_state(conf).values


def mermaid():
    return build().get_graph().draw_mermaid()
