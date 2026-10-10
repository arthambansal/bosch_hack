
"""Truth Oracle: detects gray failures by checking accepted canary votes."""

import copy
import threading
import time

from .common import LIVE, docker
from .observer import trace_canary
from .probes import backlog
from .contract_v5 import validate_truth


MONITOR_WINDOW_S = 15     # "monitoring" = what a health dashboard would show right now


class TruthOracle:
    def __init__(self, cfg, prober=None, interval_s=2.0, grace_s=10.0):
        self.cfg = cfg
        self.prober = prober
        self.interval_s = max(0.1, float(interval_s))
        self.grace_s = max(0.1, float(grace_s))

        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._thread = None
        self._canaries = []
        self._snapshots = []
        self._last_lag_s = None
        self._last_backlog = None
        self._backlog_growth_streak = 0
        self._diverged_at = None

        self._last_good = {
            "status": "unknown",
            "monitoring": "unknown",
            "canaries": {
                "sent": 0,
                "stored": 0,
                "pending": 0,
                "suspected_lost": 0,
                "last_lag_s": None,
                "grace_s": self.grace_s,
            },
            "invariants": [
                {"name": "every_vote_counted", "ok": None,
                 "detail": "Not available: no canary results yet"},
                {"name": "worker_running", "ok": None,
                 "detail": "Not available: worker not checked yet"},
                {"name": "queue_drains", "ok": None,
                 "detail": "Not available: queue not checked yet"},
            ],
            "diverged_at": None,
            "updated_at": time.time(),
        }

    def _warn(self, message):
        try:
            LIVE.event("warn", f"[TruthOracle] {message}")
        except Exception:
            pass

    def start(self) -> None:
        """Start background monitoring. Safe to call more than once."""
        try:
            with self._lock:
                if self._thread is not None and self._thread.is_alive():
                    return
                self._stop_evt.clear()
                self._thread = threading.Thread(
                    target=self._loop,
                    name="truth-oracle",
                    daemon=True,
                )
                self._thread.start()
        except Exception as exc:
            self._warn(f"could not start monitoring: {type(exc).__name__}")

    def stop(self) -> None:
        """Stop monitoring and wait briefly for the monitor thread."""
        try:
            self._stop_evt.set()
            with self._lock:
                thread = self._thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=3.0)
        except Exception as exc:
            self._warn(f"could not stop cleanly: {type(exc).__name__}")

    def _launch_canary(self):
        """Register a canary and run its blocking check in a separate thread."""
        try:
            record = {
                "sent_at": time.time(),
                "result": None,
                "completed_at": None,
            }
            with self._lock:
                self._canaries.append(record)

            def check():
                try:
                    result = trace_canary(self.cfg, timeout_s=self.grace_s)
                    if not isinstance(result, dict):
                        raise ValueError("canary returned an invalid result")
                except Exception as exc:
                    self._warn(f"canary check failed: {type(exc).__name__}")
                    result = {
                        "accepted": False,
                        "delivered": None,
                        "canary_lag_s": None,
                        "status": "not_available",
                    }

                with self._lock:
                    record["result"] = result
                    record["completed_at"] = time.time()
                    if result.get("delivered") is True:
                        lag = result.get("canary_lag_s")
                        if isinstance(lag, (int, float)) and not isinstance(lag, bool):
                            self._last_lag_s = float(lag)

            threading.Thread(
                target=check,
                name="truth-canary",
                daemon=True,
            ).start()
        except Exception as exc:
            self._warn(f"could not launch canary: {type(exc).__name__}")

    def _canary_counts(self, now):
        with self._lock:
            records = list(self._canaries)
            last_lag = self._last_lag_s

        sent = len(records)
        stored = pending = suspected_lost = 0
        recent_lost = False
        recent_lost = False

        for record in records:
            sent_at = record["sent_at"]
            result = record["result"]

            if result is None:
                # The request may still be in progress. Do not call it lost.
                if now - sent_at < self.grace_s:
                    pending += 1
                continue

            if result.get("accepted") is not True:
                # Failed/rejected requests are not lost accepted votes.
                continue

            if result.get("delivered") is True:
                stored += 1
                continue

            age = now - sent_at
            if age < self.grace_s:
                pending += 1
            else:
                suspected_lost += 1
                if now - sent_at <= 60.0:
                    recent_lost = True

        return {
            "sent": sent,
            "stored": stored,
            "pending": pending,
            "suspected_lost": suspected_lost,
            "last_lag_s": last_lag,
            "grace_s": self.grace_s,
        }, recent_lost

    def _monitoring_status(self):
        if self.prober is None:
            return "unknown"

        try:
            data = self.prober.snapshot(seconds=MONITOR_WINDOW_S)
            if not isinstance(data, dict) or not data:
                return "unknown"

            threshold = float(self.cfg["safety"]["max_error_rate"])
            found_samples = False

            for probe in data.values():
                if not isinstance(probe, dict):
                    return "unknown"
                n = probe.get("n", 0)
                rate = probe.get("error_rate")
                if not isinstance(n, (int, float)) or n <= 0:
                    return "unknown"
                if not isinstance(rate, (int, float)) or isinstance(rate, bool):
                    return "unknown"
                found_samples = True
                if rate >= threshold:
                    return "degraded"

            return "healthy" if found_samples else "unknown"
        except Exception as exc:
            self._warn(f"probe check failed: {type(exc).__name__}")
            return "unknown"

    def _worker_invariant(self):
        try:
            worker = self.cfg.get("services", {}).get("worker", {})
            container = worker.get("container")
            if not container:
                return None, "Not available: worker container is not configured"

            ok, output = docker(
                "inspect", "-f",
                "{{.State.Running}} {{.State.ExitCode}}",
                container,
                timeout=5,
            )
            if not ok:
                return None, f"Not available: could not inspect {container}"

            parts = output.strip().split()
            if len(parts) != 2:
                return None, f"Not available: unexpected Docker response for {container}"

            running = parts[0].lower() == "true"
            exit_code = parts[1]

            if running:
                return True, f"{container} is running"
            return False, f"{container} exited (code {exit_code})"
        except Exception as exc:
            self._warn(f"worker check failed: {type(exc).__name__}")
            return None, "Not available: worker status check failed"

    def _queue_invariant(self):
        try:
            current = backlog(self.cfg)
            if current is None:
                self._last_backlog = None
                self._backlog_growth_streak = 0
                return None, "Not available: Redis queue length could not be read"

            if self._last_backlog is not None and current > self._last_backlog:
                self._backlog_growth_streak += 1
            else:
                self._backlog_growth_streak = 0

            self._last_backlog = current

            if self._backlog_growth_streak >= 3:
                return False, f"Redis queue grew for 3 consecutive samples (length {current})"

            return True, f"Redis queue length {current}"
        except Exception as exc:
            self._warn(f"queue check failed: {type(exc).__name__}")
            self._last_backlog = None
            self._backlog_growth_streak = 0
            return None, "Not available: queue status check failed"

    def _build_snapshot(self):
        now = time.time()
        canaries, recent_lost = self._canary_counts(now)

        with self._lock:
            has_canary_result = any(r["result"] is not None for r in self._canaries)

        every_vote_ok = (
            (not recent_lost, "No suspected-lost canaries in the last 60 seconds" if not recent_lost else
             f"Canary votes accepted but not stored within {self.grace_s:g}s in the last 60 seconds "
             f"({canaries['suspected_lost']} suspected lost so far)")
            if has_canary_result
            else (None, "Not available: no canary results yet")
        )

        
        try:
            worker_ok, worker_detail = self._worker_invariant()
        except Exception as exc:
            self._warn(f"worker invariant unavailable: {type(exc).__name__}")
            worker_ok, worker_detail = None, "Not available: worker check failed"

        try:
            queue_ok, queue_detail = self._queue_invariant()
        except Exception as exc:
            self._warn(f"queue invariant unavailable: {type(exc).__name__}")
            queue_ok, queue_detail = None, "Not available: queue check failed"

        try:
            monitoring = self._monitoring_status()
        except Exception as exc:
            self._warn(f"monitoring unavailable: {type(exc).__name__}")
            monitoring = "unknown"


        invariants = [
            {"name": "every_vote_counted", "ok": every_vote_ok[0],
             "detail": every_vote_ok[1]},
            {"name": "worker_running", "ok": worker_ok, "detail": worker_detail},
            {"name": "queue_drains", "ok": queue_ok, "detail": queue_detail},
        ]

        if not has_canary_result:
            status = "unknown"
        elif monitoring == "degraded":
            status = "down"
        elif monitoring == "healthy" and any(i["ok"] is False for i in invariants):
            status = "diverged"
        elif monitoring == "healthy":
            status = "ok"
        else:
            status = "unknown"

        with self._lock:
            if status == "diverged":
                if self._diverged_at is None:
                    self._diverged_at = now
            else:
                self._diverged_at = None

            snapshot = {
                "status": status,
                "monitoring": monitoring,
                "canaries": canaries,
                "invariants": invariants,
                "diverged_at": self._diverged_at,
                "updated_at": now,
            }

            errors = validate_truth(snapshot)
            if errors:
                self._warn(f"snapshot failed contract validation: {errors[0]}")
                return copy.deepcopy(self._last_good)

            self._last_good = copy.deepcopy(snapshot)
            self._snapshots.append(copy.deepcopy(snapshot))
            self._snapshots = self._snapshots[-2000:]
            return copy.deepcopy(snapshot)

    def _loop(self):
        next_canary = 0.0
        while not self._stop_evt.is_set():
            try:
                now = time.monotonic()
                if now >= next_canary:
                    self._launch_canary()
                    next_canary = now + self.interval_s

                self._build_snapshot()
            except Exception as exc:
                self._warn(f"monitor tick failed: {type(exc).__name__}")

            self._stop_evt.wait(min(self.interval_s, 0.5))

    def snapshot(self) -> dict:
        """Return the latest contract-valid snapshot."""
        try:
            with self._lock:
                return copy.deepcopy(self._last_good)
        except Exception as exc:
            self._warn(f"snapshot unavailable: {type(exc).__name__}")
            return {
                "status": "unknown",
                "monitoring": "unknown",
                "canaries": {
                    "sent": 0, "stored": 0, "pending": 0,
                    "suspected_lost": 0, "last_lag_s": None,
                    "grace_s": self.grace_s,
                },
                "invariants": [],
                "diverged_at": None,
                "updated_at": time.time(),
            }

    def window(self, t_start, t_end) -> dict:
        """Summarize canaries and divergence during an experiment time window."""
        try:
            with self._lock:
                records = list(self._canaries)
                snapshots = list(self._snapshots)

            selected = [
                r for r in records
                if t_start <= r["sent_at"] <= t_end
            ]
            stored = sum(
                1 for r in selected
                if isinstance(r["result"], dict)
                and r["result"].get("accepted") is True
                and r["result"].get("delivered") is True
            )
            lost = sum(
                1 for r in selected
                if isinstance(r["result"], dict)
                and r["result"].get("accepted") is True
                and r["result"].get("delivered") is not True
                and time.time() - r["sent_at"] >= self.grace_s
            )
            diverged = any(
                t_start <= s["updated_at"] <= t_end
                and s["status"] == "diverged"
                for s in snapshots
            )

            return {
                "sent": len(selected),
                "stored": stored,
                "suspected_lost": lost,
                "diverged": diverged,
            }
        except Exception as exc:
            self._warn(f"experiment window unavailable: {type(exc).__name__}")
            return {
                "sent": None, "stored": None,
                "suspected_lost": None, "diverged": None,
            }
