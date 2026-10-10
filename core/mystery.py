"""MYSTERY MODE: a hidden fault the agents must diagnose blind. Owner: Artham. Contract: docs/day2/DAY2_CONTRACT.md 4.2, 5, 6.

How a trial works:
  1. A fault is picked from a SAFE menu (a judge on the dashboard, a terminal line, or random).
  2. It runs through the normal Engine: same sandbox check, same Guard kill switch, same STOP file, same recovery checks.
     The experiment is marked hidden, so no log line or dashboard field names the fault or the target.
  3. The Diagnostician receives a REDACTED result (no name, steps, faults_injected, reason, hypothesis, prediction) and must
     name the fault and the target from evidence alone: agentic.nodes.diagnostician.diagnose_blind().
  4. We reveal the truth, score the guess (top-1, top-3, target-only) and append one line to runs/mystery_trials.jsonl.

live_state.mystery is published at every step (shape in the contract). `answer` and `correct` stay null until the reveal.
"""
import json
import os
import random
import threading
import time
from contextlib import contextmanager

from .common import LIVE, RUNS_DIR, STOP_FILE, docker
from .planner import _experiment, candidates

REQUEST_FILE = os.path.join(RUNS_DIR, "mystery_request.json")
TRIALS_FILE = os.path.join(RUNS_DIR, "mystery_trials.jsonl")
REVEAL_PAUSE_S = 2.0
READ_PAUSE_S = 8.0          # wait mode: time for the room to read the reveal before the next pick

# (fault, service, label shown to the judge). Only entries whose service exists in config.json are offered.
MENU_SPEC = [
    ("kill", "redis", "Crash the queue (Redis)"),
    ("kill", "db", "Crash the database (Postgres)"),
    ("kill", "worker", "Crash the worker"),
    ("kill", "result", "Crash the result page"),
    ("pause", "redis", "Freeze the queue (Redis)"),
    ("pause", "db", "Freeze the database (Postgres)"),
    ("partition", "worker", "Cut the worker off the network"),
    ("latency", "redis", "Slow the queue down (400 ms)"),
]

# Fields that would give the answer away. The Diagnostician never sees them.
HIDE_KEYS = {"name", "steps", "faults_injected", "reason", "hypothesis", "prediction", "prediction_check",
             "predicted_probes", "risk_score", "hidden"}


# ------------------------------------------------------------------------------------------------ menu and scoring
def menu(cfg):
    return [{"id": f"M-{f}-{t}", "label": label, "fault": f, "target": t}
            for f, t, label in MENU_SPEC if t in cfg["services"]]


def redact(result, target=None):
    """What the Diagnostician is allowed to see: measurements and evidence, never the injected fault."""
    red = {k: v for k, v in result.items() if k not in HIDE_KEYS}
    red["name"] = "Mystery fault"
    if target and isinstance(red.get("abort_reason"), str):
        red["abort_reason"] = red["abort_reason"].replace(target, "[service]")
    return red


def score(guess, answer):
    """top1: fault and target both right. top3: any of the guesses both right. target: the service alone."""
    if not guess:
        return {"top1": False, "top3": False, "target": False}

    def same(g):
        return bool(g) and g.get("fault") == answer["fault"] and g.get("target") == answer["target"]
    top1 = same(guess)
    return {"top1": top1, "top3": top1 or any(same(g) for g in guess.get("top3") or []),
            "target": guess.get("target") == answer["target"]}


def load_trials(path=None):
    out = []
    try:
        with open(path or TRIALS_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def accuracy(trials):
    return {"trials": len(trials), "top1": sum(1 for t in trials if t["correct"]["top1"]),
            "top3": sum(1 for t in trials if t["correct"]["top3"]),
            "target": sum(1 for t in trials if t["correct"]["target"])}


# ------------------------------------------------------------------------------------------------ live state
class _State:
    """Keeps the contract shape in one place and publishes it to live_state.mystery."""

    def __init__(self, cfg, trial=0):
        self.data = {"state": "off", "trial": trial, "menu": menu(cfg), "chosen_by": None, "injected_at": None,
                     "detected_at": None, "diagnosed_at": None, "detected_by": None, "guess": None, "answer": None,
                     "correct": None, "accuracy": accuracy(load_trials())}

    def set(self, **kw):
        self.data.update(kw)
        LIVE.set(mystery=json.loads(json.dumps(self.data)))

    def fresh(self, trial, chosen_by, state="off"):
        self.set(state=state, trial=trial, chosen_by=chosen_by, injected_at=None, detected_at=None, diagnosed_at=None,
                 detected_by=None, guess=None, answer=None, correct=None, accuracy=accuracy(load_trials()))


class _Watcher(threading.Thread):
    """Notes when the fault goes in and when ChaosPilot first notices it (and what noticed it). Read-only."""

    def __init__(self, cfg, st):
        super().__init__(daemon=True)
        self.cfg, self.st, self.stop_evt = cfg, st, threading.Event()
        self.containers = [s["container"] for s in cfg["services"].values()]
        self._last_container_check = 0.0

    def run(self):
        while not self.stop_evt.wait(0.25):
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - observation only, never affects the experiment
                pass

    def _tick(self):
        d, state = self.st.data, LIVE.state
        if d["injected_at"] is None:
            if state.get("faulted"):
                self.st.set(state="injected", injected_at=time.time())
            return
        if d["detected_at"] is not None:
            return
        guard = state.get("guard") or {}
        truth = state.get("truth") or {}
        by = None
        if guard.get("tripped"):
            by = "kill switch"
        elif truth.get("status") in ("diverged", "down"):
            by = "truth oracle"
        elif any((p or {}).get("error_rate", 0) > 0 for p in (state.get("probes") or {}).values()
                 if isinstance(p, dict)):
            by = "probes"
        elif time.time() - self._last_container_check > 2.0:
            self._last_container_check = time.time()
            for c in self.containers:
                ok, out = docker("inspect", "-f", "{{.State.Status}}", c, timeout=4)
                if ok and out.strip() != "running":
                    by = "container state"
                    break
        if by:
            self.st.set(state="detected", detected_at=time.time(), detected_by=by)


# ------------------------------------------------------------------------------------------------ trial
@contextmanager
def _session(graph):
    """Reuse the running engine if there is one (autopilot), otherwise start prober + oracle and always clean up."""
    from agentic import runtime
    started = runtime.RT.get("engine") is None
    if started:
        runtime.start(graph)
    try:
        yield runtime.RT["engine"]
    finally:
        if started:
            runtime.finish()
            runtime.RT["engine"] = None


def _pick(items, choice_id):
    if choice_id in (None, "random"):
        return random.choice(items)
    for it in items:
        if it["id"] == choice_id:
            return it
    raise ValueError(f"unknown mystery choice '{choice_id}'")


def _run_one(eng, cfg, graph, item, trial, offline, chosen_by, st):
    from agentic.nodes import diagnostician

    answer = {"fault": item["fault"], "target": item["target"]}
    cand = next((c for c in candidates(cfg, graph) if c["type"] == item["fault"] and c["target"] == item["target"]), None)
    if cand is None:
        raise RuntimeError(f"{item['fault']} {item['target']} is not a valid experiment for this system")
    exp = _experiment(trial, [cand], [0], "hidden", "hidden", cfg, graph, name="Mystery fault")
    exp["id"] = f"M{trial}"
    exp["hidden"] = True
    exp["prediction"] = None

    st.fresh(trial, chosen_by)
    watcher = _Watcher(cfg, st)
    watcher.start()
    t0 = time.time()
    try:
        result = eng.run_experiment(exp)          # same Guard, sandbox check, STOP file and recovery checks as any experiment
    finally:
        watcher.stop_evt.set()
        watcher.join(timeout=2)
    if result.get("status") == "refused":
        st.set(state="off")
        raise RuntimeError(f"mystery fault refused by the safety check: {result.get('error')}")

    d = st.data
    if d["injected_at"] is None:
        d["injected_at"] = t0
    if d["detected_at"] is None and result.get("guard_log"):          # watcher missed it; the guard log is authoritative
        d["detected_at"], d["detected_by"] = d["injected_at"] + float(result["guard_log"][0]["t"]), "probes"

    t_diag = time.time()
    guess, error = None, None
    try:
        guess = diagnostician.diagnose_blind(redact(result, answer["target"]), cfg, graph, offline=offline)
    except Exception as exc:  # noqa: BLE001 - a diagnosis failure is a (wrong) trial, not a crash
        error = f"{type(exc).__name__}: {exc}"
        LIVE.event("warn", f"[Mystery] blind diagnosis failed: {error}")
    seconds_to_diagnose = round(time.time() - t_diag, 2)
    shown = None
    if guess:
        shown = {k: guess.get(k) for k in ("fault", "target", "confidence", "top3", "root_cause", "evidence", "memory_hit")}
        shown["top3"] = shown["top3"] or [{k: guess.get(k) for k in ("fault", "target", "confidence")}]
        shown["evidence"] = shown["evidence"] or []
        shown["memory_hit"] = bool(shown["memory_hit"])
    st.set(state="diagnosed", diagnosed_at=time.time(), guess=shown)
    LIVE.event("ai", "[Mystery] diagnosis ready, revealing the hidden fault ..." if guess else "[Mystery] no diagnosis")

    time.sleep(REVEAL_PAUSE_S)
    correct = score(guess, answer)
    line = {"trial": trial, "at": time.time(), "choice_id": item["id"], "chosen_by": chosen_by, "answer": answer,
            "guess": shown, "correct": correct,
            "seconds_to_detect": round(d["detected_at"] - d["injected_at"], 2) if d["detected_at"] else None,
            "seconds_to_diagnose": seconds_to_diagnose, "detected_by": d["detected_by"],
            "memory_hit": bool(shown and shown["memory_hit"]), "error": error}
    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(TRIALS_FILE, "a") as f:
        f.write(json.dumps(line) + "\n")
    st.set(state="revealed", answer=answer, correct=correct, accuracy=accuracy(load_trials()))
    g = shown or {}
    LIVE.event("ok" if correct["top1"] else "warn",
               f"[Mystery] REVEAL: it was {answer['fault']} -> {answer['target']}; guess {g.get('fault')} -> {g.get('target')} "
               f"({'correct' if correct['top1'] else 'in top-3' if correct['top3'] else 'wrong'})")
    try:
        if correct["top1"]:
            diagnostician.remember_confirmed(result, answer, g.get("root_cause") or "")
        from .notify import notify
        notify("mystery_reveal", "Mystery fault revealed",
               f"It was {answer['fault']} on {answer['target']}. ChaosPilot guessed {g.get('fault')} on {g.get('target')}.",
               {"correct (top-1)": str(correct["top1"]), "seconds to diagnose": str(seconds_to_diagnose)})
    except Exception as exc:  # noqa: BLE001
        LIVE.event("warn", f"[Mystery] post-trial extras skipped ({type(exc).__name__})")
    return line


def run_trial(choice_id, cfg, graph, offline=False, chosen_by="random"):
    """Run ONE hidden-fault trial and return its trial line (also appended to runs/mystery_trials.jsonl)."""
    items = menu(cfg)
    if not items:
        raise RuntimeError("no mystery faults available for this config")
    item = _pick(items, choice_id)
    with _session(graph) as eng:
        st = _State(cfg, len(load_trials()) + 1)          # after the session starts: starting a run clears old live evidence
        return _run_one(eng, cfg, graph, item, len(load_trials()) + 1, offline, chosen_by, st)


def run_trials(n, cfg, graph, offline=False, cooldown_s=None):
    """N trials in a row inside ONE session, cycling through the menu in random order. Returns the trial lines."""
    cooldown_s = cfg["experiment_defaults"].get("cooldown_s", 5) if cooldown_s is None else cooldown_s
    items = menu(cfg)
    if not items:
        raise RuntimeError("no mystery faults available for this config")
    order = []
    while len(order) < n:
        order += random.sample(items, len(items))
    lines = []
    with _session(graph) as eng:
        st = _State(cfg, len(load_trials()))
        for item in order[:n]:
            if os.path.exists(STOP_FILE):
                break
            lines.append(_run_one(eng, cfg, graph, item, len(load_trials()) + 1, offline, "random", st))
            time.sleep(cooldown_s)
    return lines


def format_table(lines):
    out = [f"{'#':>2}  {'hidden fault':<20} {'guess':<20} {'top1':<5} {'top3':<5} {'target':<6} {'detect s':>8} {'diagnose s':>10}"]
    for t in lines:
        a, g = t["answer"], t.get("guess") or {}
        guess = f"{g.get('fault')} {g.get('target')}" if g else "-"
        out.append(f"{t['trial']:>2}  {a['fault'] + ' ' + a['target']:<20} {guess:<20} "
                   f"{'yes' if t['correct']['top1'] else 'no':<5} {'yes' if t['correct']['top3'] else 'no':<5} "
                   f"{'yes' if t['correct']['target'] else 'no':<6} {str(t['seconds_to_detect']):>8} {t['seconds_to_diagnose']:>10}")
    acc = accuracy(lines)
    n = max(acc["trials"], 1)
    out.append(f"\ntop-1 {acc['top1']}/{acc['trials']} ({100 * acc['top1'] // n}%)   top-3 {acc['top3']}/{acc['trials']}   "
               f"target {acc['target']}/{acc['trials']}")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ judge mode
def _read_request(valid_ids, st=None):
    """Consume runs/mystery_request.json. Returns a valid choice id, or None. A bad or used file is always removed.

    The claim happens while holding the SAME lock directory the dashboard takes before it accepts a request, and the
    non-idle state is published (st.set) before that lock is released. So a second dashboard submission can never be
    accepted between "request claimed" and "state is no longer idle"."""
    lock = os.path.join(os.path.dirname(REQUEST_FILE), "dashboard_mystery.lock")      # same folder + name the dashboard locks
    claimed = REQUEST_FILE + ".claimed"
    held = False
    deadline = time.monotonic() + 2
    while not held:
        try:
            os.mkdir(lock)
            held = True
        except FileExistsError:
            if time.monotonic() >= deadline:
                return None                                   # the dashboard is mid-write; try again on the next poll
            time.sleep(0.02)
        except OSError:
            return None
    try:
        try:
            os.replace(REQUEST_FILE, claimed)                 # atomic: only one reader can ever claim a request
        except OSError:
            return None
        try:
            with open(claimed) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        try:
            os.remove(claimed)
        except OSError:
            pass
        choice = data.get("choice_id") if isinstance(data, dict) else None
        choice = choice if choice == "random" or choice in valid_ids else None
        if choice is not None and st is not None:
            st.set(state="injected")                          # not idle any more: the dashboard now answers 409
        return choice
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def wait_loop(cfg, graph, offline=False):
    """`python chaospilot.py mystery --wait`: keep the sandbox up and run a trial whenever a judge picks one."""
    from agentic.gate import _poll_terminal
    items = menu(cfg)
    valid = {m["id"] for m in items}
    try:
        os.remove(REQUEST_FILE)                                   # never act on a request left over from earlier
    except OSError:
        pass
    print("Mystery mode is waiting. Pick a fault on the dashboard, or type 'random' or one of: " + ", ".join(sorted(valid)))
    with _session(graph) as eng:
        st = _State(cfg, len(load_trials()))
        try:
            while not os.path.exists(STOP_FILE):
                st.fresh(len(load_trials()) + 1, None, state="idle")
                choice, by = None, None
                while choice is None and not os.path.exists(STOP_FILE):
                    choice, by = _read_request(valid, st), "judge"
                    if choice is None:
                        line = _poll_terminal()
                        if line and (line == "random" or line in valid):
                            choice, by = line, "terminal"
                    if choice is None:
                        time.sleep(0.3)
                if choice is None:
                    break
                if by != "judge":
                    st.set(state="injected")                          # a terminal pick is not claimed under the lock; block dashboard picks too
                try:
                    _run_one(eng, cfg, graph, _pick(items, choice), len(load_trials()) + 1, offline, by, st)
                except RuntimeError as exc:
                    LIVE.event("warn", f"[Mystery] trial skipped: {exc}")
                time.sleep(READ_PAUSE_S)                          # let the room read the reveal before the next one
        except KeyboardInterrupt:
            LIVE.event("guard", "Ctrl+C - leaving mystery mode, restoring everything")
        finally:
            st.set(state="off")
