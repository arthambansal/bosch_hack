"""Synthetic-only retrieval checks; never write to the real Knowledge Store."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.knowledge import KnowledgeStore
from core.signatures import build_signature
from agentic.nodes import diagnostician


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        self.store = KnowledgeStore(self.path)
        self.observation = {"experiment": "SYNTHETIC-E1",
            "probe_error_rate": {"vote_write": 1.0},
            "new_log_templates": {"worker": ["DNS lookup failed for redis at 10.0.0.1 retry 3"]}}
        self.signature = build_signature(self.observation, signature_id="SYNTHETIC-S1",
            fault={"type": "partition", "target_role": "queue"},
            root_cause="SYNTHETIC ONLY: worker could not resolve its queue dependency", confirmed=True)
        self.store.save_observation(self.observation)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def confirm(self):
        self.store.confirm_case(self.signature, manual_confirmation=True)

    def test_registration_requires_review_and_recorded_source(self):
        with self.assertRaises(ValueError):
            self.store.confirm_case(self.signature)
        wrong = dict(self.signature, **{"from": "MISSING"})
        with self.assertRaises(ValueError):
            self.store.confirm_case(wrong, manual_confirmation=True)
        self.confirm()
        self.confirm()  # idempotent, no duplicate
        with self.assertRaises(ValueError):
            self.store.confirm_case(dict(self.signature, root_cause="different cause"), manual_confirmation=True)
        self.assertEqual(self.store.signatures(), [self.signature])
        self.assertEqual(self.store.get_observation("SYNTHETIC-E1"), self.observation)

    def test_confirmed_symptom_retrieval_and_unknowns(self):
        self.confirm()
        matches = self.store.retrieve_cases({"entry_errors": 1})
        self.assertEqual(matches[0]["from"], "SYNTHETIC-E1")
        self.assertEqual(matches[0]["compared_features"], ["entry_errors"])
        self.assertIsNone(matches[0]["evidence"]["delivery"])
        self.assertIn("do not confirm", matches[0]["limitation"])
        self.assertEqual(self.store.retrieve_cases({"entry_errors": 0}), [])
        self.assertEqual(self.store.retrieve_cases({}), [])
        self.assertEqual(self.store.retrieve_cases({"entry_errors": 1}, exclude_experiment="SYNTHETIC-E1"), [])

    def test_log_only_match_retains_historical_service_and_source(self):
        self.confirm()
        current = {"new_log_templates": {"another_worker": ["DNS lookup failed for redis at 10.2.3.4 retry 99"]}}
        matches = self.store.retrieve_cases({}, current)
        self.assertEqual(matches[0]["similarity"], 0.0)
        self.assertEqual(matches[0]["matched_log_count"], 1)
        self.assertEqual(matches[0]["evidence"]["matching_logs"][0]["service"], "worker")
        self.assertEqual(self.store.retrieve_cases({}, {"new_log_templates": {"worker": ["database permission denied"]}}), [])

    def test_unconfirmed_and_orphan_cases_are_not_retrieved(self):
        self.store.save_signature(dict(self.signature, confirmed=False))
        self.assertEqual(self.store.retrieve_cases({"entry_errors": 1}, self.observation), [])
        self.store.save_signature(dict(self.signature, **{"from": "MISSING"}))
        self.assertEqual(self.store.retrieve_cases({"entry_errors": 1}, self.observation), [])

    def test_ordinary_traffic_logs_are_not_error_matches(self):
        ordinary = dict(self.observation, experiment="SYNTHETIC-TRAFFIC",
            new_log_templates={"vote": ["INFO Received vote for a", "POST / HTTP/<NUM> <NUM>"]})
        self.store.save_observation(ordinary)
        signature = dict(self.signature, id="SYNTHETIC-TRAFFIC", **{"from": "SYNTHETIC-TRAFFIC"})
        self.store.confirm_case(signature, manual_confirmation=True)
        self.assertEqual(self.store.retrieve_cases({}, ordinary), [])

    def test_bounded_ordered_retrieval(self):
        self.confirm()
        for number in range(2, 6):
            self.store.confirm_case(dict(self.signature, id=f"SYNTHETIC-S{number}"), manual_confirmation=True)
        self.assertEqual([m["signature"] for m in self.store.retrieve_cases({"entry_errors": 1})],
                         ["SYNTHETIC-S1", "SYNTHETIC-S2", "SYNTHETIC-S3"])
        with self.assertRaises(ValueError):
            self.store.retrieve_cases({}, limit=4)

    def test_diagnostician_receives_retrieved_evidence_without_model_call(self):
        self.confirm()
        current = {"id": "SYNTHETIC-E2", "probes": {}, "observation":
            {"experiment": "SYNTHETIC-E2", "new_log_templates":
                {"worker": ["DNS lookup failed for redis at 10.8.0.3 retry 8"]}}}
        before = copy.deepcopy(current)
        with patch.object(diagnostician, "DEFAULT_PATH", self.path), patch.object(
                diagnostician, "KnowledgeStore", side_effect=lambda: KnowledgeStore(self.path)):
            matches = diagnostician.matched_known_causes({}, {"services": {}}, current)
        self.assertEqual(matches[0]["signature"], "SYNTHETIC-S1")
        self.assertEqual(current, before)
        self.assertLess(len(json.dumps(matches)), 1800)


if __name__ == "__main__":
    print("SYNTHETIC ONLY: isolated structured RAG tests")
    unittest.main()
