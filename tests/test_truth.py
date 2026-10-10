
"""Offline tests for the Truth Oracle."""

import unittest
from unittest.mock import patch

from core.truth import TruthOracle
from core.contract_v5 import validate_truth


class TruthOracleTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "safety": {"max_error_rate": 0.5},
            "services": {
                "worker": {"container": "chaos-worker"}
            },
        }

    def test_initial_snapshot_matches_contract(self):
        oracle = TruthOracle(self.cfg)
        self.assertEqual(validate_truth(oracle.snapshot()), [])
        self.assertEqual(oracle.snapshot()["status"], "unknown")

    def test_canary_counts_include_sent_votes(self):
        oracle = TruthOracle(self.cfg)
        now = 100.0
        oracle._canaries = [
            {"sent_at": 90.0, "result": {
                "accepted": True, "delivered": True, "canary_lag_s": 0.4
            }, "completed_at": 91.0},
            {"sent_at": 90.0, "result": {
                "accepted": True, "delivered": False
            }, "completed_at": 95.0},
            {"sent_at": 99.0, "result": None, "completed_at": None},
        ]

        counts, recent_lost = oracle._canary_counts(now)

        self.assertEqual(counts["sent"], 3)
        self.assertEqual(counts["stored"], 1)
        self.assertEqual(counts["pending"], 1)
        self.assertEqual(counts["suspected_lost"], 1)
        self.assertTrue(recent_lost)

    def test_failed_request_is_not_counted_as_lost(self):
        oracle = TruthOracle(self.cfg)
        oracle._canaries = [{
            "sent_at": 90.0,
            "result": {"accepted": False, "delivered": None},
            "completed_at": 91.0,
        }]

        counts, recent_lost = oracle._canary_counts(100.0)

        self.assertEqual(counts["sent"], 1)
        self.assertEqual(counts["suspected_lost"], 0)
        self.assertFalse(recent_lost)

    def test_snapshot_falls_back_if_checks_fail(self):
        oracle = TruthOracle(self.cfg)
        with patch.object(oracle, "_worker_invariant", side_effect=RuntimeError):
            snapshot = oracle._build_snapshot()

        self.assertEqual(validate_truth(snapshot), [])

    def test_window_has_required_keys(self):
        oracle = TruthOracle(self.cfg)
        window = oracle.window(0, 100)

        self.assertTrue({
            "sent", "stored", "suspected_lost", "diverged"
        }.issubset(window.keys()))


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TruthOracleTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("ALL CHECKS PASSED")
