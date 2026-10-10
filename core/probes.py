"""Traffic + monitoring.

A Prober runs one background thread per probe (config.json -> probes). Each thread sends a request
every 0.5s and records (start_time, ok, latency_ms, status). This is both our "steady load" and our
monitoring signal. Votes that were accepted are counted so we can later check none were lost.
"""
import random
import threading
import time

import requests

from .common import docker, percentile


def summarize(results):
    """results: list of (t, ok, latency_ms, status) -> dict of stats."""
    if not results:
        return {"n": 0, "ok": 0, "error_rate": 0.0, "p50_ms": 0.0, "p95_ms": 0.0}
    lats = [r[2] for r in results]
    ok = sum(1 for r in results if r[1])
    return {"n": len(results), "ok": ok, "error_rate": round(1 - ok / len(results), 3),
            "p50_ms": round(percentile(lats, 50), 1), "p95_ms": round(percentile(lats, 95), 1)}


class Prober:
    def __init__(self, cfg):
        s = cfg["safety"]
        self.probes = cfg["probes"]
        self.interval, self.timeout = s["probe_interval_s"], s["probe_timeout_s"]
        self.results = {p["name"]: [] for p in self.probes}
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.hold = threading.Event()      # set = pause traffic (used while counting delivered votes)
        self.votes_ok = 0
        self.threads = []

    def hit(self, p):
        t = time.time()
        try:
            if p.get("method", "GET") == "POST":
                r = requests.post(p["url"], data=({"vote": random.choice("ab")} if (p.get("data") or {}).get("vote") else p.get("data")), timeout=self.timeout)
            else:
                r = requests.get(p["url"], timeout=self.timeout)
            lat = (time.time() - t) * 1000
            return t, r.status_code < 500, lat, r.status_code
        except requests.RequestException as e:
            return t, False, (time.time() - t) * 1000, type(e).__name__

    def record(self, p, result):
        with self.lock:
            self.results[p["name"]].append(result)
            if len(self.results[p["name"]]) > 5000:
                self.results[p["name"]] = self.results[p["name"]][-4000:]
            if result[1] and p.get("counts_votes"):
                self.votes_ok += 1

    def _loop(self, p):
        while not self.stop_evt.is_set():
            if self.hold.is_set():
                time.sleep(0.1)
                continue
            result = self.hit(p)
            self.record(p, result)
            time.sleep(max(0, self.interval - (time.time() - result[0])))

    def start(self):
        if self.threads:
            return
        for p in self.probes:
            t = threading.Thread(target=self._loop, args=(p,), daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_evt.set()

    def since(self, name, t0, t1=None):
        with self.lock:
            return [r for r in self.results[name] if r[0] >= t0 and (t1 is None or r[0] <= t1)]

    def snapshot(self, seconds=60):
        """Recent data for the dashboard chart."""
        now, out = time.time(), {}
        for p in self.probes:
            recent = self.since(p["name"], now - seconds)
            out[p["name"]] = {"series": [[round(r[0] - now, 2), round(r[2]), r[1]] for r in recent],
                              **summarize(recent[-8:])}
        return out


class Spike:
    """Traffic-spike fault: N threads hammering the entry probe as fast as they can."""

    def __init__(self, prober, probe, threads):
        self.prober, self.probe, self.n = prober, probe, threads
        self.stop_evt = threading.Event()
        self.threads = []

    def _loop(self):
        while not self.stop_evt.is_set():
            r = self.prober.hit(self.probe)
            if r[1] and self.probe.get("counts_votes"):
                with self.prober.lock:
                    self.prober.votes_ok += 1

    def start(self):
        for _ in range(self.n):
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stop_evt.set()
        for t in self.threads:
            t.join(timeout=4)


def delivery_count(cfg):
    """How many votes made it all the way to Postgres? None if the DB can't be read."""
    dc = cfg.get("delivery_check")
    if not dc:
        return None
    ok, out = docker("exec", dc["container"], *dc["cmd"], timeout=8)
    if "does not exist" in out:
        return 0          # table not created yet = nothing delivered yet
    if not ok:
        return None
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def backlog(cfg):
    """Items still waiting in the queue (redis list). None if it can't be read."""
    bc = cfg.get("backlog_check")
    if not bc:
        return 0
    ok, out = docker("exec", bc["container"], *bc["cmd"], timeout=8)
    try:
        return int(out.strip().splitlines()[-1]) if ok else None
    except (ValueError, IndexError):
        return None


def settled_count(cfg, timeout=40):
    """Wait until the queue is empty AND the delivered count stops changing, then return the count.
    (Without the queue check a slowly-restarting worker would look like lost data.)"""
    deadline, last, same = time.time() + timeout, None, 0
    while time.time() < deadline:
        c, q = delivery_count(cfg), backlog(cfg)
        same = same + 1 if (c is not None and c == last and q == 0) else 0
        if same >= 2:
            return c
        last = c
        time.sleep(1)
    return last
