"""Tejas-owned regression checks. Run with python docs/test_tejas.py."""
import json
import copy
import pathlib
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import core.code_tools as code
import core.report_extras as extras
import agentic.nodes.cartographer as cartographer
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


def check_hypothesis_validation():
    """Exercise new findings, hostile/malformed replies and fallback at the node boundary."""
    scratch = pathlib.Path(__file__).resolve().parents[1] / "runs"
    with tempfile.TemporaryDirectory(dir=scratch) as temp:
        root = pathlib.Path(temp) / "app"
        root.mkdir()
        source = root / "consumer.cs"
        source.write_text("void Consume() {\n  var item = queue.Pop();\n  database.Save(item);\n}\n", encoding="utf-8")
        (root / ".env").write_text("PRIVATE=value", encoding="utf-8")
        (root / "binary.cs").write_bytes(b"\0binary")
        graph = {"services": {"worker": {"used_by": [], "stateful": False},
                              "redis": {"used_by": ["worker"], "stateful": True},
                              "db": {"used_by": ["worker"], "stateful": True}}}
        finding = {"id": "H2", "statement": "If the consumer fails after Pop but before Save, a vote may be lost.",
                   "source": "code", "evidence": ["consumer.cs:1: void Consume() {",
                   "consumer.cs:2: var item = queue.Pop();", "consumer.cs:3: database.Save(item);"],
                   "affected": ["worker", "db"], "priority": "high", "status": "open"}
        with patch.object(code, "SOURCE_ROOT", root):
            assert cartographer.verified_hypotheses([finding], graph) == [finding]
            assert cartographer.valid_citation("consumer.cs:2:   var item = queue.Pop();")
            bad_citations = ["consumer.cs:2: invented();", "consumer.cs:99: database.Save(item);",
                "consumer.cs:3: var item = queue.Pop();", "missing.cs:2: var item = queue.Pop();",
                "consumer.cs:2: queue.Pop()", "consumer.cs:2: var item = queue.Pop(); explanation",
                "consumer.cs:0: code", "consumer.cs:-1: code", "consumer.cs:2-3: code",
                "../consumer.cs:2: var item = queue.Pop();", "..\\consumer.cs:2: var item = queue.Pop();",
                str(source) + ":2: var item = queue.Pop();", "/consumer.cs:2: var item = queue.Pop();",
                ".env:1: PRIVATE=value", "binary.cs:1: binary", "consumer.cs:2:   ",
                "consumer.cs:2: var item = queue.Pop();\nignored", None]
            for citation in bad_citations:
                assert not cartographer.valid_citation(citation), repr(citation)
            for key, value in [("status", "confirmed"), ("priority", []), ("statement", " "),
                               ("affected", ["unknown"]), ("affected", [3]), ("evidence", []),
                               ("source", "measurement"), ("id", {})]:
                bad = {**finding, key: value}
                assert cartographer.verified_hypotheses([bad], graph) == [], (key, value)
            assert cartographer.verified_hypotheses([{**finding, "new_contract_field": True}], graph) == []
            assert cartographer.verified_hypotheses([finding, finding], graph) == []
            assert cartographer.verified_hypotheses([finding] * 21, graph) == []
            bad = {**finding, "id": "H3", "evidence": ["consumer.cs:2: invented();"]}
            assert cartographer.verified_hypotheses([bad, finding, None], graph) == [finding]

            final = {"single_points_of_failure": ["redis"], "risks": [],
                     "hypotheses_to_test": ["unverified model text must not survive"],
                     "hypotheses": [finding, bad], "unexpected_key": "must not enter state"}
            original = copy.deepcopy(final)
            with patch.object(cartographer, "recon_agent", return_value={"final": final}), \
                 patch.object(cartographer, "cfg", return_value={}), \
                 patch.object(cartographer, "save_json") as save, \
                 patch.object(cartographer, "LIVE"):
                output = cartographer.cartographer_node({"graph": graph, "offline": True})
                assert set(output) == {"threat_model"}
                tm = output["threat_model"]
                assert set(tm) == set(cartographer.RECON_SCHEMA) | {"source"}
                assert tm["source"] == "agent" and len(tm["hypotheses_to_test"]) == 1
                assert finding["statement"] in tm["hypotheses_to_test"][0]
                assert "unverified model text" not in tm["hypotheses_to_test"][0]
                assert save.call_args.args[1] == [finding]
                assert final == original  # validation must not mutate a cached AI answer

            # A stale citation stops validating as soon as the source changes.
            source.write_text("changed\n", encoding="utf-8")
            assert cartographer.verified_hypotheses([finding], graph) == []
            for response in ({"final": final}, {"final": None}, {"final": "bad JSON shape"}):
                with patch.object(cartographer, "recon_agent", return_value=response), \
                     patch.object(cartographer, "cfg", return_value={}), \
                     patch.object(cartographer, "save_json"), patch.object(cartographer, "LIVE"):
                    tm = cartographer.cartographer_node({"graph": graph})["threat_model"]
                    assert tm["source"] == "rules"
                    assert tm["single_points_of_failure"] == ["redis", "db"]
                    assert len(tm["hypotheses_to_test"]) == 2  # source unavailable: dependency fallback
    # The actual W1 fallback still verifies with the same citation checker.
    hypotheses = source_hypotheses()
    assert cartographer.verified_hypotheses(hypotheses, graph) == hypotheses


def check_hypothesis_logic():
    """Isolated validation tests with source-tool responses mocked (no Docker/API/files)."""
    graph = {"services": {"worker": {}, "redis": {}, "db": {}}}
    finding = {"id": "H2", "statement": "A crash between pop and write may lose an item.",
               "source": "code", "evidence": ["consumer.cs:2: var item = queue.Pop();"],
               "affected": ["worker", "db"], "priority": "high", "status": "open"}
    with patch.object(cartographer, "read_file", return_value="2:   var item = queue.Pop();") as read:
        assert cartographer.verified_hypotheses([finding], graph) == [finding]
        read.assert_called_once_with("consumer.cs", 2, 2)
        assert not cartographer.valid_citation("consumer.cs:2: queue.Pop()")
        assert not cartographer.valid_citation("consumer.cs:2: fabricated();")
        assert cartographer.verified_hypotheses([finding, finding], graph) == []
        assert cartographer.verified_hypotheses([{**finding, "affected": ["foreign"]}], graph) == []
        assert cartographer.verified_hypotheses([{**finding, "status": "confirmed"}], graph) == []
        assert not cartographer.valid_hypotheses([{**finding, "priority": []}])
        bad = {**finding, "id": "H3", "evidence": ["consumer.cs:2: fabricated();"]}
        assert cartographer.verified_hypotheses([bad, finding], graph) == [finding]
        for path in ("../consumer.cs", "..\\consumer.cs", "/consumer.cs", "C:\\consumer.cs"):
            read.reset_mock()
            assert not cartographer.valid_citation(f"{path}:2: var item = queue.Pop();")
            read.assert_not_called()
        final = {"single_points_of_failure": [], "risks": [], "hypotheses_to_test": ["unchecked"],
                 "hypotheses": [bad, finding], "extra": "not state"}
        original = copy.deepcopy(final)
        with patch.object(cartographer, "recon_agent", return_value={"final": final}), \
             patch.object(cartographer, "cfg", return_value={}), \
             patch.object(cartographer, "save_json") as save, patch.object(cartographer, "LIVE"):
            tm = cartographer.cartographer_node({"graph": graph})["threat_model"]
            assert tm["source"] == "agent" and finding["statement"] in tm["hypotheses_to_test"][0]
            assert len(tm["hypotheses_to_test"]) == 1 and "extra" not in tm
            assert save.call_args.args[1] == [finding] and original == final
    with patch.object(cartographer, "read_file", side_effect=FileNotFoundError):
        assert cartographer.verified_hypotheses([finding], graph) == []
    fallback = {"single_points_of_failure": [], "risks": [], "hypotheses_to_test": ["fallback"]}
    with patch.object(cartographer, "recon_agent", return_value={"final": final}), \
         patch.object(cartographer, "read_file", side_effect=PermissionError), \
         patch.object(cartographer, "rule_based", return_value=fallback) as rules, \
         patch.object(cartographer, "cfg", return_value={}), patch.object(cartographer, "LIVE"):
        tm = cartographer.cartographer_node({"graph": graph})["threat_model"]
        assert tm["source"] == "rules" and tm["hypotheses_to_test"] == ["fallback"]
        rules.assert_called_once_with(graph)


if __name__ == "__main__":
    check_hypothesis_logic()
    check_tools()
    check_reporting()
    check_hypothesis_validation()
    hypotheses = source_hypotheses()
    assert len(hypotheses) == 1 and valid_hypotheses(hypotheses)
    assert all(any(fn in e for e in hypotheses[0]["evidence"]) for fn in ("GetIp", "RedisConnectionException", "return 1"))
    assert hypotheses[0]["status"] == "open"
    print(json.dumps(hypotheses, indent=2))
    print("TEJAS CHECKS PASSED")
