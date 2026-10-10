"""Replay an actual Redis recording with live LLM reasoning; no Docker actions."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import agentkit
from core.agentkit import Tool
from agentic.nodes import diagnostician as diagnosis
from agentic.runtime import cfg


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is missing in this terminal. No inference was run.")
    recorded = json.loads((ROOT / "runs/actual_redis_checks_572e3269bc/kill.json").read_text(encoding="utf-8-sig"))
    graph = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8-sig"))
    result = dict(recorded["result"], observation=recorded["observation"])
    symptoms = dict(recorded["detection"], preexisting_stopped_services=recorded["preexisting_stopped"])
    tools = {
        "list_containers": Tool("list_containers", "Historical container state during the recorded experiment, not live state", {},
            lambda: {"redis": recorded["redis_state_during"],
                     "worker": {"status": "stopped before experiment"},
                     "other_services": "Historical state not supplied"}),
        "container_logs": Tool("container_logs", "Historical logs availability", {"service": "service", "lines": "count"},
            lambda service, lines=20: "Container logs were not recorded for this test."),
    }
    sources = []
    original = agentkit.ask_json

    def tracked(*args, **kwargs):
        answer, source = original(*args, **kwargs)
        sources.append(source)
        return answer, source

    with patch.object(diagnosis, "make_tools", return_value=tools), patch.object(agentkit, "ask_json", side_effect=tracked):
        output = diagnosis.investigate(cfg(), graph, result, offline=False, symptoms=symptoms)
    artifact = {"provenance": "Live LLM replay of actual recorded Redis kill evidence; no new fault or delivery test",
                "llm_sources": sources, "output": output}
    target = ROOT / "runs/diagnostician_redis_replay.json"
    target.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print("ACTUAL RECORDED DATA - LIVE LLM REPLAY")
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    print("Saved:", target)
    if not output["final"] or not sources or any(source in ("none", "cache") for source in sources):
        raise SystemExit("Incomplete live reasoning test; inspect sources and trace above.")


if __name__ == "__main__":
    main()
