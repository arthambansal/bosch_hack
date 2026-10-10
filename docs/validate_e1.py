"""Single approved E1 validation; avoids Windows terminal select() bug.

Run ONLY after a human approves this exact Redis kill. No planner, combined
faults or configuration fixes. Uses production policy, executor and reporter.
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from agentic import runtime
from agentic.nodes.cartographer import cartographer_node
from agentic.nodes.governor import governor_node
from agentic.nodes.execute import execute_node, evaluate_node
from agentic.nodes.reporter import reporter_node
from core.common import BASELINE_FILE, DEPS_FILE, load_config, load_json, save_json
from core.planner import candidates, _experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--human-approved-e1", action="store_true")
    args = parser.parse_args()
    if not args.human_approved_e1:
        parser.error("explicit human approval required for the single Redis kill")
    cfg, graph = load_config(), load_json(DEPS_FILE)
    if not graph:
        parser.error("collect a real dependency map first")
    runtime.RT["cfg"] = cfg
    candidate = next(c for c in candidates(cfg, graph) if c["id"] == "kill:redis")
    proposal = _experiment(1, [candidate], [0], "Human-approved W1 source-hypothesis validation",
                           "DNS failure in GetIp can make Main exit 1; test whether Redis kill triggers this mechanism.", cfg, graph)
    assert proposal["steps"] == [{"type": "kill", "target": "redis", "delay_s": 0}]
    state = {"graph": graph, "baseline": load_json(BASELINE_FILE, {}), "offline": True,
             "results": [], "investigations": {}, "proposal": proposal, "skip_heal": True}
    state.update(governor_node(state))
    if not state["review"]["approved"]:
        raise SystemExit("Governor rejected E1")
    # Explicit approval was obtained outside the terminal; preserve that evidence.
    state["review"]["human"] = "approved"
    directory = runtime.start(graph)
    save_json(os.path.join(directory, "approval_evidence.json"), {"scope": proposal["steps"],
              "human_answer": "Approve E1 validation", "channel": "Codex user response", "fixes": "none"})
    save_json(os.path.join(directory, "baseline.json"), state["baseline"])
    try:
        state.update(cartographer_node(state))
        state.update(execute_node(state))
        state.update(evaluate_node(state))
        state["done_reason"] = "Single human-approved E1 validation; no fixes or further experiments"
        state.update(reporter_node(state))
        save_json(os.path.join(directory, "final_state.json"), state)
        print("REAL E1 REPORT: " + state["report"]["path_md"])
    finally:
        runtime.finish()


if __name__ == "__main__":
    main()
