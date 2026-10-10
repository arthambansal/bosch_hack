"""TRUTH ORACLE (gray-failure detector). Owner: Pratham. Contract: docs/day2/DAY2_CONTRACT.md 4.1 and 5.

STUB: safe defaults so the system runs before it is implemented. Replace the bodies, keep the signatures.
"""
import time


class TruthOracle:
    def __init__(self, cfg, prober=None, interval_s=2.0, grace_s=10.0):
        self.cfg, self.prober, self.interval_s, self.grace_s = cfg, prober, interval_s, grace_s

    def start(self):
        """Start the background canary loop. Must never raise."""

    def stop(self):
        """Stop the loop and wait at most a few seconds."""

    def snapshot(self):
        return {"status": "unknown", "monitoring": "unknown",
                "canaries": {"sent": 0, "stored": 0, "pending": 0, "suspected_lost": 0, "last_lag_s": None,
                             "grace_s": self.grace_s},
                "invariants": [], "diverged_at": None, "updated_at": time.time()}

    def window(self, t_start, t_end):
        return {"sent": None, "stored": None, "suspected_lost": None, "diverged": None}
