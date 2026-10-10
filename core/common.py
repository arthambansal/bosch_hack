"""Shared helpers: file paths, config loading, docker calls, logging, live dashboard state."""
import json
import os
import subprocess
import threading
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS_DIR = os.path.join(ROOT, "runs")
LIVE_FILE = os.path.join(RUNS_DIR, "live_state.json")   # the dashboard reads this
DEPS_FILE = os.path.join(ROOT, "dependencies.json")
PLAN_FILE = os.path.join(ROOT, "plan.json")
BASELINE_FILE = os.path.join(ROOT, "baseline.json")
LATEST_FILE = os.path.join(RUNS_DIR, "latest.txt")      # path of the most recent run folder
STOP_FILE = os.path.join(ROOT, "STOP")                  # create this file = manual kill switch

os.makedirs(RUNS_DIR, exist_ok=True)

# ANSI colours so the terminal output is readable during the demo
COLORS = {"info": "\033[37m", "inject": "\033[91m", "guard": "\033[95m", "restore": "\033[92m",
          "ai": "\033[96m", "ok": "\033[92m", "warn": "\033[93m"}
RESET = "\033[0m"


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, data):
    """Write to a temp file then rename, so readers never see a half-written file."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = load_json(os.path.join(ROOT, "config.json"))
    if cfg is None:
        raise SystemExit("config.json is missing or not valid JSON")
    return cfg


def docker(*args, timeout=30):
    """Run `docker <args>`. Returns (ok, output). Never raises."""
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return False, "docker not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"


def percentile(values, pct):
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round(pct / 100 * (len(s) - 1))))
    return s[k]


def latest_run_dir():
    try:
        with open(LATEST_FILE, encoding="utf-8") as f:
            path = f.read().strip()
        return path if os.path.isdir(path) else None
    except OSError:
        return None


# ---------------------------------------------------------------- graph helpers
def deps_closure(graph, svc):
    """All services `svc` depends on, directly or indirectly."""
    seen, stack = set(), [svc]
    while stack:
        for d in graph["services"].get(stack.pop(), {}).get("depends_on", []):
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


def dependents_closure(graph, svc):
    """All services that depend on `svc`, directly or indirectly (its blast radius)."""
    seen, stack = set(), [svc]
    while stack:
        for d in graph["services"].get(stack.pop(), {}).get("used_by", []):
            if d not in seen:
                seen.add(d)
                stack.append(d)
    return seen


def probes_affected(cfg, graph, targets):
    """Which health probes should fail if `targets` break? Used to predict blast radius."""
    hit = []
    for p in cfg["probes"]:
        path = {p["entry"]} | deps_closure(graph, p["entry"])
        if path & set(targets):
            hit.append(p["name"])
    return hit


# ---------------------------------------------------------------- live state
class Live:
    """Thread-safe store of everything the dashboard shows. Flushed to LIVE_FILE on change."""

    def __init__(self):
        self.lock = threading.Lock()
        self.log_path = None
        self.state = {"phase": "idle", "events": [], "queue": [], "probes": {}, "faulted": [],
                      "guard": {}, "experiment": None, "score": None, "findings": None,
                      "graph": load_json(DEPS_FILE, {}), "thresholds": {}}

    def event(self, kind, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        rendered = COLORS.get(kind, "") + line + RESET
        try:
            print(rendered, flush=True)
        except UnicodeEncodeError:
            import sys
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            print(rendered.encode(encoding, errors="backslashreplace").decode(encoding), flush=True)
        with self.lock:
            self.state["events"] = (self.state["events"] + [{"t": time.time(), "kind": kind, "msg": line}])[-60:]
        if self.log_path:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{kind.upper():8} {line}\n")
        self.flush()

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)
        self.flush()

    # Everything NOT listed here is run evidence and is dropped when a new run starts (whitelist, so a key added later
    # is reset automatically instead of leaking into the next run).
    GLOBAL_KEYS = ("graph", "thresholds", "gate_sync")
    RUN_DEFAULTS = {"phase": "idle", "events": [], "queue": [], "probes": {}, "faulted": [], "guard": {},
                    "experiment": None, "score": None, "findings": None}

    def reset_run(self, baseline=None):
        """Forget the previous run's evidence. Only global catalogs (graph, thresholds, gate_sync) survive.
        `baseline` is the saved baseline.json this run will compare against (an input, re-published fresh)."""
        with self.lock:
            kept = {k: self.state[k] for k in self.GLOBAL_KEYS if k in self.state}
            self.state = {**json.loads(json.dumps(self.RUN_DEFAULTS)), **kept}
            if baseline is not None:
                self.state["baseline"] = baseline
        self.flush()

    def flush(self):
        with self.lock:
            snapshot = json.dumps(self.state)
        try:
            tmp = LIVE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(snapshot)
            os.replace(tmp, LIVE_FILE)
        except OSError:
            pass  # the dashboard is optional; never crash the experiment over it


LIVE = Live()
