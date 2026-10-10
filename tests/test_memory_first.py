"""Synthetic-only checks for zero-inference reuse and guarded fallbacks."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.knowledge import KnowledgeStore
from core.signatures import build_signature
from agentic.nodes import diagnostician as D


class MemoryFirstTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        self.store = KnowledgeStore(self.path)
        self.obs = {"experiment": "SYNTHETIC-OLD", "probe_error_rate": {"vote_write": 1, "result_page": 0},
                    "queue_depth": {"start": 0, "end": 10}, "mttr_s": None,
                    "new_log_templates": {"worker": ["DNS lookup failed for redis"]}}
        self.sig = build_signature(self.obs, signature_id="SYNTHETIC-S1",
            fault={"type": "partition", "target_role": "queue"},
            root_cause="SYNTHETIC ONLY: worker failed to resolve its Redis dependency", confirmed=True)
        self.store.save_observation(self.obs)
        self.store.confirm_case(self.sig, manual_confirmation=True)
        self.diagnosis = {"incident": "SYNTHETIC-I1", "root_cause": self.sig["root_cause"],
            "symptoms": ["synthetic failed writes"], "differential": [], "evidence_for": ["synthetic DNS error"],
            "evidence_against": [], "confirmed_by": "SYNTHETIC confirming intervention", "confidence": "high",
            "would_change_mind": "different mechanism logs"}
        self.fix = {"id": "SYNTHETIC-F1", "for": self.diagnosis["incident"], "layer": "code",
            "change": {"service": "worker", "recommendation": "bounded DNS retry"},
            "why": "SYNTHETIC: recover dependency lookup", "expected": {"delivery_ratio": 0.9},
            "verification": {"rerun": [self.obs["experiment"]], "repeat": 3,
                             "must_improve": ["delivery_ratio"], "regression_guard": ["review latency"]},
            "code_patch": "suggestion only", "approval": "required"}
        self.report = {"fix": self.fix["id"], "runs": 3, "before": {"delivery_ratio": 0.2},
            "after": {"delivery_ratio": [0.9, 0.95, 1.0]},
            "regression": {"vote_p95_ms": {"before": 40, "after": 41}}, "decision": "keep"}
        self.current = {"id": "SYNTHETIC-NEW", "steps": [{"type": "partition", "target": "redis"}],
                        "observation": dict(self.obs, experiment="SYNTHETIC-NEW")}
        self.graph = {"services": {"redis": {"role": "queue"}, "worker": {"role": "consumer"}}}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def register(self, report=None, fix=None):
        self.store.register_solution(self.sig["id"], self.diagnosis, fix or self.fix,
                                     report or self.report, manual_confirmation=True)

    def memory(self, result=None):
        with patch.object(D, "DEFAULT_PATH", self.path), patch.object(D, "KnowledgeStore",
                side_effect=lambda: KnowledgeStore(self.path)):
            return D.memory_diagnosis({}, self.graph, result or self.current)

    def test_specific_verified_case_skips_all_inference(self):
        self.register()
        with patch.object(D, "DEFAULT_PATH", self.path), patch.object(D, "KnowledgeStore",
                side_effect=lambda: KnowledgeStore(self.path)), patch.object(D, "ReActAgent") as agent:
            output = D.investigate({}, self.graph, self.current)
        agent.assert_not_called()
        self.assertEqual(output["tool_calls"], 0)
        self.assertEqual(output["trace"], [])
        self.assertEqual(output["final"]["confidence"], "low")
        self.assertIn("SYNTHETIC-F1", output["final"]["suggested_fix"])

    def test_no_verified_fix_does_not_skip(self):
        self.assertIsNone(self.memory())
        with patch.object(D, "DEFAULT_PATH", self.path), patch.object(D, "KnowledgeStore",
                side_effect=lambda: KnowledgeStore(self.path)), patch.object(D, "ReActAgent") as agent, \
                patch.object(D, "make_tools", return_value={}):
            agent.return_value.run.return_value = (None, [])
            D.investigate({}, self.graph, self.current)
        agent.assert_called_once()

    def test_node_preserves_contract_and_identifies_rule_memory(self):
        self.register()
        current = dict(self.current, probes={"vote_write": {"error_rate": 1.0}})
        with patch.object(D, "DEFAULT_PATH", self.path), patch.object(D, "KnowledgeStore",
                side_effect=lambda: KnowledgeStore(self.path)), patch.object(D, "ReActAgent") as agent, \
                patch.object(D, "cfg", return_value={}), patch.object(D, "load_observation", return_value=current["observation"]):
            output = D.diagnostician_node({"results": [current], "graph": self.graph})
        agent.assert_not_called()
        finding = output["investigations"][current["id"]]
        self.assertEqual(finding["by"], "rules")
        self.assertTrue(finding["fault_detected"])
        self.assertEqual(set(finding), {"root_cause", "evidence", "affected_services", "confidence",
                                       "suggested_fix", "by", "fault_detected"})

    def test_ambiguous_cause_blocks_shortcut(self):
        self.register()
        other = dict(self.sig, id="SYNTHETIC-S2", root_cause="SYNTHETIC ONLY: different cause")
        self.store.confirm_case(other, manual_confirmation=True)
        self.assertIsNone(self.memory())

    def test_missing_logs_wrong_role_and_contradictions_do_not_skip(self):
        self.register()
        changed = copy.deepcopy(self.current)
        changed["observation"]["new_log_templates"] = {}
        self.assertIsNone(self.memory(changed))
        changed = copy.deepcopy(self.current)
        changed["observation"]["probe_error_rate"]["result_page"] = 1
        self.assertIsNone(self.memory(changed))
        changed = copy.deepcopy(self.current)
        changed["steps"][0]["type"] = "kill"
        self.assertIsNone(self.memory(changed))
        old = dict(self.current, id=self.obs["experiment"], observation=self.obs)
        self.assertIsNone(self.memory(old))

    def test_review_and_improvement_are_required(self):
        with self.assertRaises(ValueError):
            self.store.register_solution(self.sig["id"], self.diagnosis, self.fix, self.report)
        for changed in (dict(self.report, decision="revert"), dict(self.report, runs=1),
                        dict(self.report, after={"delivery_ratio": [0.1, 0.2, 0.3]}),
                        dict(self.report, regression={})):
            with self.assertRaises(ValueError):
                self.register(report=changed)

    def test_artifact_roundtrip_and_collision_preserves_records(self):
        self.register()
        self.assertEqual(self.store.verified_solutions(self.sig), [{"fix": self.fix, "verification": self.report}])
        changed = dict(self.fix, why="different")
        with self.assertRaises(ValueError):
            self.register(fix=changed)
        self.assertEqual(self.store.verified_solutions(self.sig)[0]["fix"], self.fix)
        packet = self.store.retrieve_cases(self.sig["features"], self.obs)
        self.assertEqual(packet[0]["verified_fixes"][0]["id"], self.fix["id"])

    def test_competing_verified_fixes_block_shortcut(self):
        self.register()
        second = dict(self.fix, id="SYNTHETIC-F2")
        self.store.register_solution(self.sig["id"], self.diagnosis, second,
            dict(self.report, fix=second["id"]), manual_confirmation=True)
        self.assertIsNone(self.memory())


if __name__ == "__main__":
    print("SYNTHETIC ONLY: memory-first diagnosis; no real fixes or containers changed")
    unittest.main()
