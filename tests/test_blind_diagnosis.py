"""SYNTHETIC ONLY. Blind interfaces tested without Docker, network or credentials."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentic.nodes import diagnostician as D
from core.agentkit import Tool
from core.contract_v5 import validate_guess, validate_memory
from core.knowledge import KnowledgeStore


class FakeLive:
    def __init__(self):
        self.state = {"run_dir": "SYNTHETIC-RUN"}

    def set(self, **values):
        self.state.update(values)

    def event(self, *args):
        pass


class Redacted(dict):
    def get(self, key, default=None):
        if key in {"name", "steps", "reason", "faults_injected", "hypothesis", "prediction", "predicted_probes"}:
            raise AssertionError(f"Read forbidden injection field {key}")
        return super().get(key, default)


class BlindTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        self.live = FakeLive()
        self.configuration = {"services": {"redis": {"role": "queue"}, "db": {"role": "database"},
            "worker": {"role": "consumer"}, "vote": {"role": "entrypoint"}, "result": {"role": "entrypoint"}},
            "probes": [{"name": "vote_write", "entry": "vote"}, {"name": "result_page", "entry": "result"}]}
        self.graph = {"services": self.configuration["services"], "edges": [
            {"from": "vote", "to": "redis"}, {"from": "worker", "to": "redis"},
            {"from": "worker", "to": "db"}, {"from": "result", "to": "db"}]}
        self.states = {}
        self.tools = {"list_containers": Tool("list_containers", "recorded synthetic states", [], lambda: self.states)}
        self.patches = [patch.object(D, "DEFAULT_PATH", self.path),
            patch.object(D, "KnowledgeStore", side_effect=lambda *args: KnowledgeStore(self.path)),
            patch.object(D, "load_observation", return_value=None), patch.object(D, "LIVE", self.live),
            patch.object(D, "cfg", return_value=self.configuration),
            patch.object(D, "make_tools", return_value=self.tools)]
        for item in self.patches:
            item.start()
        D._BLIND_TIMINGS.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        D._BLIND_TIMINGS.clear()
        self.temp.cleanup()

    def result(self, incident="M1"):
        observation = {"experiment": incident, "probe_error_rate": {"vote_write": 1, "result_page": 0},
            "queue_depth": {"start": 0, "end": 8}, "mttr_s": None,
            "new_log_templates": {}, "events": []}
        return Redacted(id=incident, observation=observation,
            probes={"vote_write": {"n": 10, "error_rate": 1, "p95_ms": 80}}, stuck_services=[])

    def check(self, guess):
        self.assertEqual(validate_guess(guess, self.configuration["services"]), [])
        self.assertGreaterEqual(guess["seconds"], 0)
        self.assertEqual(validate_memory(self.live.state["memory"]), [])
        for candidate in guess["top3"]:
            self.assertIn(candidate["target"], self.configuration["services"])
            self.assertIn(candidate["fault"], {"kill", "pause", "partition", "latency", "spike"})

    def test_menu_faults_from_measured_states_and_events(self):
        for fault, target in [("kill", "redis"), ("kill", "db"), ("kill", "worker"), ("kill", "result"),
                              ("pause", "redis"), ("pause", "db"), ("partition", "worker"), ("latency", "redis")]:
            with self.subTest(fault=fault, target=target):
                result = self.result()
                self.states = {}
                if fault == "kill":
                    result["observation"]["events"] = [{"service": target, "event": "die", "exit_code": 137, "t": 1}]
                elif fault == "pause":
                    self.states = {target: {"status": "paused"}}
                elif fault == "partition":
                    self.states = {target: {"status": "running", "network_connected": False}}
                else:
                    result["probes"] = {"vote_write": {"n": 10, "error_rate": 0, "p95_ms": 800}}
                before = copy.deepcopy(dict(result))
                guess = D.diagnose_blind(result, self.configuration, self.graph, offline=True)
                self.check(guess)
                self.assertIn((fault, target), [(c["fault"], c["target"]) for c in guess["top3"]])
                self.assertEqual(dict(result), before)
                self.assertAlmostEqual(sum(c["confidence"] for c in guess["top3"]), 1)

    def test_memory_and_measured_savings_with_no_ai(self):
        old = self.result("M-old")
        D._BLIND_TIMINGS["M-old"] = {"seconds": 4.0, "source": "ai"}
        D.remember_confirmed(old, {"fault": "kill", "target": "redis"}, "SYNTHETIC Redis interruption")
        with patch.object(D, "ReActAgent") as agent, patch("time.perf_counter", side_effect=[20.0, 22.0]):
            guess = D.diagnose_blind(self.result("M-new"), self.configuration, self.graph)
        agent.assert_not_called()
        self.check(guess)
        self.assertTrue(guess["memory_hit"])
        self.assertEqual((guess["fault"], guess["target"]), ("kill", "redis"))
        self.assertEqual(self.live.state["memory"]["last_hit"]["saved_s"], 2.0)

    def test_self_match_excluded_and_ambiguous_memory_not_used(self):
        old = self.result("M-old")
        D.remember_confirmed(old, {"type": "kill", "target": "redis"}, "SYNTHETIC known interruption")
        self.assertFalse(D.diagnose_blind(old, self.configuration, self.graph, True)["memory_hit"])
        D.remember_confirmed(self.result("M-other"), {"fault": "pause", "target": "redis"}, "SYNTHETIC pause")
        guess = D.diagnose_blind(self.result("M-new"), self.configuration, self.graph, True)
        self.assertFalse(guess["memory_hit"])
        self.assertIsNone(self.live.state["memory"]["last_hit"])

    def test_reveal_is_idempotent_and_preserves_formats(self):
        old = self.result("M-old")
        D.remember_confirmed(old, {"fault": "kill", "target": "redis"}, "SYNTHETIC interruption")
        D.remember_confirmed(self.result("M-repeated"), {"fault": "kill", "target": "redis"}, "SYNTHETIC same symptoms, different wording")
        with KnowledgeStore(self.path) as store:
            signatures = store.signatures()
            self.assertEqual(len(signatures), 1)
            self.assertEqual(set(signatures[0]), {"id", "from", "fault", "features", "root_cause", "confirmed"})
            self.assertEqual(signatures[0]["from"], "M-old")
            self.assertEqual(store.get_observation("M-old"), old["observation"])
            self.assertIsNone(store.diagnosis_duration(signatures[0]["id"]))

    def test_invalid_ai_falls_back_and_context_has_no_injection(self):
        result = self.result()
        with patch.object(D, "ReActAgent") as agent:
            agent.return_value.run.return_value = ({"fault": "made_up", "target": "production"}, [])
            guess = D.diagnose_blind(result, self.configuration, self.graph)
            context = agent.return_value.run.call_args.args[1]
        self.check(guess)
        self.assertNotIn("injected_action", context)
        self.assertNotIn("M1", json.dumps(context))
        self.assertFalse(guess["memory_hit"])

    def test_valid_ai_and_invalid_ranked_pairs(self):
        answer = {"fault": "partition", "target": "redis", "confidence": 0.5,
            "top3": [{"fault": "partition", "target": "redis", "confidence": 0.5},
                     {"fault": "pause", "target": "redis", "confidence": 0.5}],
            "root_cause": "SYNTHETIC: dependency connectivity failure is plausible, but needs confirmation",
            "evidence": ["vote_write error_rate=1"]}
        with patch.object(D, "ReActAgent") as agent:
            agent.return_value.run.return_value = (answer, [])
            guess = D.diagnose_blind(self.result(), self.configuration, self.graph)
        self.check(guess)
        self.assertEqual(guess["fault"], "partition")
        invalid = copy.deepcopy(answer)
        invalid["top3"][1]["target"] = "production"
        self.assertIsNone(D._validated_blind_guess(invalid, self.configuration))

    def test_missing_measurements_and_failed_reveal_do_not_invent_evidence(self):
        guess = D.diagnose_blind(Redacted(id="M-empty"), self.configuration, self.graph, True)
        self.check(guess)
        self.assertEqual(guess["evidence"], [])
        self.assertLess(guess["confidence"], 0.6)
        D.remember_confirmed({"id": "M-empty"}, {"fault": "kill", "target": "redis"}, "unsupported")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    print("SYNTHETIC ONLY: blind diagnosis interface checks")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlindTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL CHECKS PASSED")
