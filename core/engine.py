"""Experiment runner + safety guard (kill switch).

For each experiment:
  settle -> warm-up -> INJECT (steps can be delayed = combined failure) -> observe while the
  Guard watches every 0.5 s -> RESTORE (automatic on threshold breach) -> measure recovery
  -> count delivered votes to detect silent data loss.
"""
import os
import time

from .common import BASELINE_FILE, LATEST_FILE, LIVE, PLAN_FILE, RUNS_DIR, STOP_FILE, docker, load_json, save_json
from .faults import Fault, SafetyError, panic
from .fmea import build_fmea
from .probes import Prober, backlog, settled_count, summarize
from .knowledge import KnowledgeStore
from .observer import summary as observer_summary

def account_delivery(sent, delivered, q0, q1):
    """accepted votes = stored + still queued + lost  ->  (lost, backlog_growth). Unknown queue sizes count as 0 growth."""
    if delivered is None:
        return None, 0
    growth = (q1 - q0) if None not in (q0, q1) else 0
    return max(0, sent - delivered - growth), max(0, growth)


class Guard:
    """Trips when thresholds are breached for `breach_ticks` consecutive checks.

    Three rules:
      error rate  - a probe's recent error rate >= max_error_rate
      latency     - a probe's recent p95 > max_p95_ms
      blast radius- a probe that the dependency map said should be SAFE starts failing
                    (the failure spread further than predicted -> stop immediately)
    """

    def __init__(self, cfg, prober, predicted):
        self.s, self.prober, self.predicted = cfg["safety"], prober, set(predicted)
        self.names = [p["name"] for p in cfg["probes"]]
        self.ticks = 0

    def check(self, since):
        reasons, snap = [], {}
        for name in self.names:
            res = self.prober.since(name, since)[-self.s["window"]:]
            if len(res) < 2:
                continue
            st = summarize(res)
            snap[name] = st
            if st["error_rate"] >= self.s["max_error_rate"]:
                if name in self.predicted:
                    reasons.append(f"{name} error rate {st['error_rate']:.0%} >= {self.s['max_error_rate']:.0%}")
                else:
                    reasons.append(f"BLAST RADIUS: {name} is failing but was predicted to be unaffected")
            elif st["p95_ms"] > self.s["max_p95_ms"]:
                reasons.append(f"{name} p95 {st['p95_ms']:.0f}ms > {self.s['max_p95_ms']}ms")
        self.ticks = self.ticks + 1 if reasons else 0
        return self.ticks >= self.s["breach_ticks"], reasons, snap


GRAY_MIN_S = 5          # monitoring green + correctness broken for this long = gray failure


class Engine:
    def __init__(self, cfg, graph):
        self.cfg, self.graph = cfg, graph
        self.prober = Prober(cfg)
        self.active = []          # faults currently applied (so Ctrl+C can always undo them)
        self.oracle = None        # Truth Oracle (core/truth.py), set by agentic/runtime.py or core/mystery.py
        LIVE.set(graph=graph, thresholds=cfg["safety"])

    def publish(self, **extra):
        if self.oracle is not None:
            try:
                truth = self.oracle.snapshot()
                extra.setdefault("truth", truth)
                status = truth.get("status")
                # Announce a gray failure only when it lasts: a fault that is about to break the probes is not "gray".
                since = truth.get("diverged_at")
                lasting = status == "diverged" and since is not None and time.time() - since >= GRAY_MIN_S
                if lasting and not getattr(self, "_gray_announced", False):
                    self._gray_announced = True
                    bad = [i["name"] for i in truth.get("invariants", []) if i.get("ok") is False]
                    LIVE.event("warn", f"[Truth] GRAY FAILURE: health probes have looked fine for {GRAY_MIN_S}s+ but "
                                       f"{', '.join(bad) or 'an invariant'} is failing (users are affected silently)")
                    from .notify import notify
                    notify("gray_failure", "Gray failure detected",
                           f"Monitoring is green but {', '.join(bad) or 'an invariant'} is failing.",
                           {"failing invariants": ", ".join(bad) or "unknown"})
                if status != "diverged":
                    self._gray_announced = False
                self._truth_status = status
            except Exception:  # noqa: BLE001 - the oracle must never break the run
                pass
        LIVE.set(probes=self.prober.snapshot(), **extra)

    def _sleep_publishing(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.publish()
            time.sleep(0.5)

    def _quiesce(self):
        """Pause traffic, let in-flight requests finish, return (votes_accepted, votes_delivered, votes_still_queued)."""
        self.prober.hold.set()
        time.sleep(self.cfg["safety"]["probe_timeout_s"] + 0.3)
        sent = self.prober.votes_ok
        delivered = settled_count(self.cfg)
        return sent, delivered, backlog(self.cfg)

    # ------------------------------------------------------------------ baseline
    def baseline(self, seconds=30):
        LIVE.set(phase="baseline")
        LIVE.event("info", f"Capturing baseline: {seconds}s of steady traffic ...")
        self.prober.start()
        sent0, c0, _q0 = self._quiesce()
        self.prober.hold.clear()
        t0 = time.time()
        self._sleep_publishing(seconds)
        sent1, c1, _q1 = self._quiesce()
        self.prober.hold.clear()
        probes = {p["name"]: summarize(self.prober.since(p["name"], t0)) for p in self.cfg["probes"]}
        sent = sent1 - sent0
        delivered = (c1 - c0) if None not in (c0, c1) else None
        base = {"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": seconds, "probes": probes,
                "delivery": {"sent": sent, "delivered": delivered}}
        save_json(BASELINE_FILE, base)
        for name, st in probes.items():
            LIVE.event("ok", f"  {name:12} requests={st['n']} errors={st['error_rate']:.0%} "
                             f"p50={st['p50_ms']}ms p95={st['p95_ms']}ms")
        LIVE.event("ok", f"  delivery: {sent} votes accepted, {delivered} reached the database")
        LIVE.set(phase="idle", baseline=base)
        return base

    # ------------------------------------------------------------------ one experiment
    def run_experiment(self, exp):
        cfg, d = self.cfg, self.cfg["experiment_defaults"]
        s = cfg["safety"]
        # Observation IDs are reused across runs; never retrieve an older run's evidence.
        try:
            with KnowledgeStore() as store:
                store.clear_observation(exp["id"])
        except Exception as exc:
            LIVE.event("warn", f"Observer memory unavailable ({type(exc).__name__})")
        hidden = bool(exp.get("hidden"))                       # mystery mode: the dashboard and log must not reveal the fault
        LIVE.event("info", f"=== {exp['id']}: {'Mystery fault' if hidden else exp['name']} ===")
        if not hidden:
            LIVE.event("ai", f"Why: {exp['reason']}")
        LIVE.set(experiment=({"id": exp["id"], "name": "Mystery fault", "steps": [], "reason": "hidden",
                              "predicted_probes": []} if hidden else exp),
                 guard={"ticks": 0, "reasons": [], "tripped": False})

        try:
            faults = [Fault(st["type"], st["target"], cfg, self.prober, st.get("params")) for st in exp["steps"]]
        except SafetyError as e:
            LIVE.event("guard", f"REFUSED by safety check: {e}")
            return {"id": exp["id"], "name": exp["name"], "status": "refused", "error": str(e)}
        for f in faults:
            f.hidden = hidden

        down = self._stopped()
        if down:
            LIVE.event("warn", f"PRE-FLIGHT: {down} were not running, starting them so the experiment is clean")
            self._start_services(down)
        sent0, c0, q0 = self._quiesce()
        self.prober.hold.clear()
        self._sleep_publishing(d["warmup_s"])

        guard = Guard(cfg, self.prober, exp["predicted_probes"])
        pending = sorted(zip(exp["steps"], faults), key=lambda x: x[0].get("delay_s", 0))
        t_inject, aborted, guard_log = time.time(), None, []
        queue_start = backlog(cfg)
        while True:
            elapsed = time.time() - t_inject
            while pending and pending[0][0].get("delay_s", 0) <= elapsed:
                if os.path.exists(STOP_FILE):                 # STOP pressed: never start another injection
                    aborted = "manual kill switch (STOP file) before injection"
                    LIVE.event("guard", aborted)
                    break
                _, f = pending.pop(0)
                ok, out = f.apply()
                if not ok:
                    aborted = f"injection failed: {out}"
                    break
                self.active.append(f)
                LIVE.set(faulted=[({"target": "hidden", "type": "hidden"} if hidden else {"target": x.target, "type": x.type})
                                  for x in self.active])
            if aborted:
                break
            tripped, reasons, snap = guard.check(since=t_inject)
            if reasons:
                guard_log.append({"t": round(elapsed, 1), "reasons": reasons})
                LIVE.event("guard", f"guard {guard.ticks}/{s['breach_ticks']}: {'; '.join(reasons)}")
            self.publish(guard={"ticks": guard.ticks, "reasons": reasons, "tripped": tripped, "snap": snap,
                                "elapsed": round(elapsed, 1)})
            if tripped:
                aborted = "KILL SWITCH: " + "; ".join(reasons)
                LIVE.event("guard", "!" * 20 + f" {aborted} " + "!" * 20)
                break
            if os.path.exists(STOP_FILE):
                aborted = "manual kill switch (STOP file)"
                LIVE.event("guard", aborted)
                break
            if elapsed >= s["max_experiment_s"]:
                aborted = "hard time limit reached"
                break
            if elapsed >= d["duration_s"] and not pending:
                break
            time.sleep(s["probe_interval_s"])

        # Read measured state while the fault is still present; never expose fault metadata.
        from .tools import capture_container_states
        captured_at = time.time()
        try:
            fault_states = capture_container_states(cfg)
        except Exception:
            fault_states = {}
        if not fault_states:
            LIVE.event("warn", "Fault-window container state unavailable; retaining probe and event evidence")
        t_restore = time.time()
        self._restore_all()

        # Recovery: every probe must return 3 healthy results in a row after the restore.
        recovery_s = None
        while time.time() - t_restore < d["recovery_timeout_s"]:
            healthy_since = self._healthy_since(t_restore)
            if healthy_since is not None:
                recovery_s = round(healthy_since - t_restore, 1)
                break
            self.publish()
            time.sleep(0.5)
        LIVE.event("ok" if recovery_s is not None else "warn",
                   f"Recovered in {recovery_s}s" if recovery_s is not None else "NOT recovered within timeout")

        time.sleep(4)   # give crashed containers time to show as crashed
        stuck = self._stopped()
        stuck_details = {}
        for n in stuck:
            c = self.cfg["services"][n]["container"]
            _, code = docker("inspect", "-f", "{{.State.ExitCode}}", c)
            _, logs = docker("logs", "--tail", "12", c, timeout=10)
            stuck_details[n] = {"exit_code": code.strip(), "last_logs": [x[:200] for x in logs.splitlines()[-12:]]}
        if stuck:
            LIVE.event("guard", f"CASCADE FAILURE: {'a service' if hidden else stuck} crashed and did NOT come back on their own "
                                f"(probes look healthy, but the pipeline is silently broken)")
            self._start_services(stuck)   # manual rescue so the next experiment starts clean
        sent1, c1, q1 = self._quiesce()
        self.prober.hold.clear()
        sent = sent1 - sent0
        delivered = (c1 - c0) if None not in (c0, c1) else None
        # Votes still waiting in the queue are a BACKLOG, not a loss: votes accepted = stored + still queued + lost.
        # This also stops a backlog left over from the previous experiment from being counted as "extra delivered".
        lost, backlog_growth = account_delivery(sent, delivered, q0, q1)
        if lost:
            LIVE.event("guard", f"DATA LOSS: {sent} votes accepted, only {delivered} reached the database ({lost} lost)")
        elif lost == 0:
            if backlog_growth > 0:
                LIVE.event("guard", f"BACKLOG: {sent} votes accepted, {delivered} stored, {backlog_growth} still waiting in the queue "
                                    "at the cutoff (the worker drains slowly). Not counted as lost, but users wait for them.")
            else:
                drained = max(0, delivered - sent) if q0 else 0
                extra = (f" ({drained} vote(s) queued before this experiment were stored during it)" if drained else
                         f" ({delivered - sent} vote(s) the client saw as failed/timed out were still stored: "
                         "the user got an error for a vote that counted)" if delivered > sent else "")
                LIVE.event("ok", f"No data loss: {sent} accepted, {delivered} delivered{extra}")

        window = {}
        for p in cfg["probes"]:
            res = self.prober.since(p["name"], t_inject, t_restore)
            st = summarize(res)
            first_fail = next((r[0] for r in res if not r[1]), None)
            st["time_to_first_error_s"] = round(first_fail - t_inject, 1) if first_fail else None
            window[p["name"]] = st

        pred, check = exp.get("prediction"), None
        if pred:   # did the agent's falsifiable prediction match reality?
            hit = {n for n, st in window.items() if st["error_rate"] >= 0.5}
            check = {"probes": hit == set(pred.get("probes_affected") or []),
                     # "recovers" means the whole system, so a crashed service that stayed down counts as NOT recovered
                     "recovers": (recovery_s is not None and not stuck) == bool(pred.get("recovers", True)),
                     "data_loss": None if lost is None else (lost > 0) == bool(pred.get("data_loss", False))}
            parts = {"probes": f"broken probes {sorted(hit) or 'none'} (predicted {sorted(pred.get('probes_affected') or []) or 'none'})",
                     "recovers": f"system {'recovered' if recovery_s is not None and not stuck else 'did NOT fully recover'}"
                                 f" (predicted {'recovers' if pred.get('recovers', True) else 'no recovery'})",
                     "data_loss": f"{'data lost' if lost else 'no data lost' if lost == 0 else 'loss unknown'}"
                                  f" (predicted {'loss' if pred.get('data_loss') else 'no loss'})"}
            right = [k for k, v in check.items() if v is True]
            wrong = [k for k, v in check.items() if v is False]
            LIVE.event("ai", f"PREDICTION {'CORRECT' if not wrong else f'{len(right)}/{len(right) + len(wrong)} right'}: "
                       + "; ".join(("OK " if check[k] else "MISS ") + parts[k] for k in check if check[k] is not None))
        observation_end = time.time()
        queue_end = backlog(cfg)

        first_guard_time = (
                guard_log[0]["t"]
                if guard_log
                else None
            )
        observation = observer_summary(
            t_start=t_inject,
            t_end=t_restore,
            cfg={**cfg, "experiment": exp["id"]},
            prober=self.prober,
            queue_start=queue_start,
            queue_end=queue_end,
            accepted_count=sent,
            delivered_count=delivered,
            kill_switch=aborted if aborted and (
                "KILL SWITCH" in aborted
                or "kill switch" in aborted.lower()
            ) else None,
            stuck_services=stuck,
            mttd_s=first_guard_time,
            mttr_s=recovery_s)
        result = {"id": exp["id"], "name": exp["name"], "steps": exp["steps"], "reason": exp["reason"],
                "hypothesis": exp.get("hypothesis"), "predicted_probes": exp["predicted_probes"],
                "status": "aborted" if aborted else "completed", "abort_reason": aborted,
                "fault_window_s": round(t_restore - t_inject, 1), "probes": window,
                "recovery_s": recovery_s, "guard_log": guard_log[-10:],
                "delivery": {"sent": sent, "delivered": delivered, "lost": lost, "queued": q1, "backlog_growth": backlog_growth},
                "faults_injected": [f.describe() for f in faults],
                "prediction": pred, "prediction_check": check,
                "stuck_services": stuck, "stuck_details": stuck_details,"observation": observation}
        self._save_observation(observation)
        result["fault_window_evidence"] = {"t_start": t_inject, "t_end": t_restore,
            "captured_at": captured_at, "container_states": fault_states}
        self._after_result(result, t_inject, t_restore, hidden)
        return result

    def _after_result(self, result, t_inject, t_end, hidden):
        """Day 2 extras for the dashboard and Discord. Every step is best-effort: it can never change the result."""
        try:
            if self.oracle is not None:
                result["truth"] = self.oracle.window(t_inject, t_end)
            from .report_extras import impact_of
            LIVE.set(impact=impact_of(result))
            reason = result.get("abort_reason") or ""
            if "KILL SWITCH" in reason:
                from .notify import notify
                notify("kill_switch", "Kill switch fired" if hidden else f"Kill switch fired in {result['id']}", reason[:300],
                       {"experiment": result["id"], "fault window": f"{result['fault_window_s']} s"})
        except Exception as exc:  # noqa: BLE001
            LIVE.event("warn", f"[extras] skipped ({type(exc).__name__}: {exc})")

    def _save_observation(self, observation):
        """Hand the Observer's summary to the Knowledge Store (the Diagnostician and Executor read it from there)."""
        try:
            with KnowledgeStore() as store:
                store.save_observation(observation)
            LIVE.event("info", f"[Observer] {observation['experiment']} summary saved for diagnosis")
        except Exception as exc:  # noqa: BLE001 - measuring/storing must never change fault restoration or the result contract
            LIVE.event("warn", f"[Observer] summary not saved ({type(exc).__name__}); engine evidence retained")

    def _stopped(self):
        """Services whose container is NOT running right now (crashed, killed or exited)."""
        down = []
        for name, svc in self.cfg["services"].items():
            ok, out = docker("inspect", "-f", "{{.State.Running}}", svc["container"])
            if ok and out.strip() != "true":
                down.append(name)
        return down

    def _start_services(self, names):
        for n in names:
            docker("start", self.cfg["services"][n]["container"])
        time.sleep(4)

    def _healthy_since(self, t_restore):
        """If every probe's last 3 results (after t_restore) are OK, return when that streak began."""
        starts = []
        for p in self.cfg["probes"]:
            res = self.prober.since(p["name"], t_restore)
            if len(res) < 3 or not all(r[1] for r in res[-3:]):
                return None
            starts.append(res[-3][0])
        return max(starts)

    def _restore_all(self):
        for f in reversed(self.active):      # undo in reverse order (LIFO)
            f.undo()
            time.sleep(1)
        self.active = []
        LIVE.set(faulted=[])

    # ------------------------------------------------------------------ agent loop
    def run_agent(self, chooser, max_steps=6):
        """Adaptive loop: chooser(results_so_far) returns the next experiment dict, or None to finish."""
        run_dir = os.path.join(RUNS_DIR, "run_" + time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        LIVE.log_path = os.path.join(run_dir, "events.log")
        with open(LATEST_FILE, "w") as f:
            f.write(run_dir)
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
        LIVE.set(phase="running", queue=[], score=None, findings=None, run_dir=run_dir)
        self.prober.start()
        self._sleep_publishing(3)
        results, executed, queue = [], [], []
        try:
            for _ in range(max_steps):
                if os.path.exists(STOP_FILE):
                    LIVE.event("guard", "STOP file present - agent halted")
                    break
                LIVE.event("ai", "AGENT is reasoning about what to break next ...")
                exp = chooser(results)
                if not exp:
                    break
                executed.append(exp)
                queue.append({"id": exp["id"], "name": exp["name"], "reason": exp["reason"],
                              "status": "running", "score": None})
                LIVE.set(queue=queue)
                res = self.run_experiment(exp)
                results.append(res)
                queue[-1]["status"] = res["status"]
                LIVE.set(queue=queue, fmea=build_fmea(results, load_json(BASELINE_FILE, {})))
                plan = {"source": "agent", "experiments": executed}
                save_json(os.path.join(run_dir, "results.json"), results)
                save_json(os.path.join(run_dir, "plan.json"), plan)
                save_json(PLAN_FILE, plan)               # so `heal` can re-run these exact experiments
                save_json(os.path.join(run_dir, "baseline.json"), load_json(BASELINE_FILE, {}))
                self._sleep_publishing(self.cfg["experiment_defaults"]["cooldown_s"])
        except KeyboardInterrupt:
            LIVE.event("guard", "Ctrl+C - restoring everything before exit")
        finally:
            self._restore_all()
            if os.path.exists(STOP_FILE):
                panic(self.cfg)
            self.prober.stop()
        LIVE.set(phase="ran", experiment=None)
        LIVE.event("ok", f"Agent run saved to {run_dir}")
        return run_dir, results

    # ------------------------------------------------------------------ whole plan
    def run(self, plan, only=None):
        run_dir = os.path.join(RUNS_DIR, "run_" + time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        LIVE.log_path = os.path.join(run_dir, "events.log")
        with open(LATEST_FILE, "w") as f:
            f.write(run_dir)
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)

        exps = [e for e in plan["experiments"] if not only or e["id"] in only]
        queue = [{"id": e["id"], "name": e["name"], "reason": e["reason"], "status": "planned", "score": None}
                 for e in exps]
        LIVE.set(phase="running", queue=queue, score=None, findings=None, run_dir=run_dir)
        self.prober.start()
        self._sleep_publishing(3)

        results = []
        save_json(os.path.join(run_dir, "plan.json"), plan)
        save_json(os.path.join(run_dir, "baseline.json"), load_json(BASELINE_FILE, {}))
        try:
            for i, exp in enumerate(exps):
                if os.path.exists(STOP_FILE):
                    LIVE.event("guard", "STOP file present - skipping remaining experiments")
                    break
                queue[i]["status"] = "running"
                LIVE.set(queue=queue)
                res = self.run_experiment(exp)
                results.append(res)
                queue[i]["status"] = res["status"]
                LIVE.set(queue=queue)
                save_json(os.path.join(run_dir, "results.json"), results)   # saved after every experiment
                LIVE.set(fmea=build_fmea(results, load_json(BASELINE_FILE, {})))
                self._sleep_publishing(self.cfg["experiment_defaults"]["cooldown_s"])
        except KeyboardInterrupt:
            LIVE.event("guard", "Ctrl+C - restoring everything before exit")
        finally:
            self._restore_all()
            if os.path.exists(STOP_FILE):
                panic(self.cfg)
            self.prober.stop()
        LIVE.set(phase="ran", experiment=None)
        LIVE.event("ok", f"Run saved to {run_dir}")
        return run_dir, results
