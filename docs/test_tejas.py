"""Tejas-owned regression checks. Run with python docs/test_tejas.py."""
import json
import pathlib
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import core.code_tools as code
import core.report_extras as extras
from agentic.nodes.cartographer import source_hypotheses, valid_hypotheses


def check_tools():
    scratch = pathlib.Path(__file__).resolve().parents[1] / "runs"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        root = pathlib.Path(temp) / "app"
        root.mkdir()
        (root / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        outside = pathlib.Path(temp) / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        with patch.object(code, "SOURCE_ROOT", root):
            assert code.list_files() == ["a.txt"]
            assert code.read_file("a.txt", 2, 2) == "2: beta"
            assert code.grep("beta") == ["a.txt:2: beta"]
            for path in ("../secret.txt", str(outside)):
                try:
                    code.read_file(path)
                except ValueError:
                    pass
                else:
                    raise AssertionError("escaped source root")
            try:
                code.read_file("a.txt", 1, 100)
            except ValueError:
                pass
            else:
                raise AssertionError("unbounded read")


def check_reporting():
    results = [{"id": "E1", "status": "completed", "recovery_s": 0.5,
                "delivery": {"lost": 14}, "stuck_services": ["worker"],
                "steps": [{"target": "redis", "type": "kill"}],
                "probes": {"vote": {"time_to_first_error_s": 0}}},
               {"id": "E2", "observation": {"mttd_s": 0, "mttr_s": 2}}]
    rows = extras.timing_rows(results)
    assert rows[0]["mttd_s"] is None and rows[0]["mttr_s"] is None
    assert rows[0]["probe_first_error_s"] == 0
    assert rows[1]["mttd_s"] == 0 and rows[1]["mttr_s"] == 2
    assert "1/2" in "\n".join(extras.timing_markdown(results))
    assert "adverse outcome" in extras.heatmap_html(results, ["redis", "db"])
    assert "not tested" in extras.heatmap_html(results, ["redis", "db"])
    with patch.object(extras, "ask_json", return_value=({"fact_ids": [999]}, "mock")):
        summary = extras.executive_summary({"results": results}, 80, "B")
        assert "80/100" in summary and "14" in summary
    malicious = [{"id": "<script>", "status": "refused", "steps": [{"target": "redis", "type": "kill"}]}]
    assert "<script>" not in extras.heatmap_html(malicious, ["redis"])


if __name__ == "__main__":
    check_tools()
    check_reporting()
    hypotheses = source_hypotheses()
    assert len(hypotheses) == 1 and valid_hypotheses(hypotheses)
    assert all(any(fn in e for e in hypotheses[0]["evidence"]) for fn in ("GetIp", "RedisConnectionException", "return 1"))
    assert hypotheses[0]["status"] == "open"
    print(json.dumps(hypotheses, indent=2))
    print("TEJAS CHECKS PASSED")
