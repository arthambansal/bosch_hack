"""ChaosPilot AGENT: an autonomous observe -> reason -> act loop.

After EVERY experiment the LLM sees what just happened and decides the next experiment itself
(or finishes). It writes a falsifiable PREDICTION before each run; the engine then checks the
prediction against reality, so the demo can show "the agent predicted X, reality was Y".

Safety (the AI never gets raw power):
  * it can only pick candidate ids that planner.candidates() generated from OUR dependency map
  * every run still goes through Fault's sandbox check, the Guard kill switch and the STOP file
  * hard budget: max_experiments steps. No LLM key / no internet -> deterministic fallback plan
"""
import json

from .common import LIVE
from .llm import ask_json
from .planner import _experiment, candidates, heuristic_plan

SYSTEM = """You are an autonomous Site Reliability Engineer agent running chaos experiments in a sandbox.
Each turn you see the dependency map, the normal baseline, the candidate experiments, and the results of
experiments already run. Decide the NEXT experiment, or finish.
Rules:
- Use ONLY candidate ids from the list. Never repeat an experiment already run.
- Learn from results: if something surprising happened (data loss, slow recovery, failure spreading to a service
  predicted to be safe), dig deeper there. If a service held up, move on to a different weak point.
- A step list has 1 step, or 2 for a combined failure (second step delayed 3-15 s).
- Before running, state a falsifiable prediction. Be CALIBRATED: use the results so far. If an earlier experiment left a
  service crashed (stuck_services) and a similar fault is coming, predict recovers=false; if a fault was tolerated,
  predict no effect. Do not repeat an optimistic prediction that reality already contradicted.
- steps[].delay_s is the wait BEFORE a step starts, not the size of the fault.
- You may finish only after at least 3 experiments have run AND at least 3 different fault types (kill, pause,
  partition, latency, spike) have been used; until then only candidates with a NEW fault type are offered.
Reply with JSON only."""

USER = """Dependency map:
{graph}

Baseline: {baseline}

Candidates (id, risk, probes it should break):
{cands}

Already run (results so far): {history}

Findings from the other agents (recon threat model, root-cause investigations, safety reviewer feedback, user goal).
Use them: test the recon hypotheses, dig into investigated root causes, and if a user goal is given design the experiment to answer it:
{extra}

Reply:
{{"action": "run" | "finish",
  "steps": [{{"candidate": "kill:redis", "delay_s": 0}}],
  "name": "short title",
  "reason": "why THIS experiment NOW, citing what earlier results taught you",
  "hypothesis": "what a resilient system should do",
  "prediction": {{"probes_affected": ["vote_write"], "data_loss": false, "recovers": true}}}}"""


TYPES_REQUIRED = 3          # brief: "at least 3 failure types". Enforced in code, the AI cannot talk its way out of it.


def types_run(results):
    return {s["type"] for r in results for s in (r.get("steps") or [])}


class Agent:
    """Callable used by Engine.run_agent: agent(results_so_far) -> next experiment dict, or None to stop."""

    def __init__(self, cfg, graph, baseline, offline=False, extra=None):
        self.cfg, self.graph, self.baseline, self.offline = cfg, graph, baseline, offline
        self.extra = extra or {}
        self.cands = candidates(cfg, graph)
        self.by_id = {c["id"]: c for c in self.cands}
        self.fallback = heuristic_plan(cfg, graph, self.cands, cfg.get("max_experiments", 6))
        self.used, self.n = set(), 0

    def _history(self, results):
        return [{"id": r["id"], "experiment": r["name"], "status": r["status"], "recovery_s": r.get("recovery_s"),
                 "lost_votes": (r.get("delivery") or {}).get("lost"),
                 "services_left_crashed": r.get("stuck_services"),
                 "faults_injected": r.get("faults_injected"),
                 "error_rate": {k: v["error_rate"] for k, v in (r.get("probes") or {}).items()},
                 "prediction_check": r.get("prediction_check")} for r in results]

    def _needs_new_type(self, results):
        return len(types_run(results)) < TYPES_REQUIRED

    def _publish_ranking(self, results, chosen_id, reason):
        """Show the full risk-ranked list on the dashboard (brief: AI ranks and selects experiments with a reason)."""
        tried = {f"{s['type']}:{s['target']}" for r in results for s in (r.get("steps") or [])}
        covered = sorted(types_run(results))
        LIVE.set(plan_ranking={
            "turn": self.n, "chosen": chosen_id, "reason": reason, "types_covered": covered,
            "types_required": TYPES_REQUIRED,
            "candidates": [{"id": c["id"], "type": c["type"], "target": c["target"], "risk_score": c["risk_score"],
                            "predicted_probes": c["predicted_probes"], "tried": c["id"] in tried} for c in self.cands[:10]]})

    def _fallback(self, results=()):
        need_new = self._needs_new_type(results)
        seen_types = types_run(results)
        for e in self.fallback:
            sig = tuple(f"{s['type']}:{s['target']}" for s in e["steps"])
            if need_new and all(s["type"] in seen_types for s in e["steps"]):
                continue                                  # coverage rule: only experiments that add a new fault type
            if sig not in self.used:
                self.used.add(sig)
                LIVE.event("ai", f"AGENT step {self.n}: (rule-based fallback) {e['name']}")
                self._publish_ranking(results, "+".join(sig), e.get("reason", ""))
                return dict(e, id=f"E{self.n}", prediction=None)
        return None

    def __call__(self, results):
        self.n += 1
        compact = {n: {k: s[k] for k in ("role", "stateful", "depends_on", "used_by")}
                   for n, s in self.graph["services"].items()}
        need_new, seen_types = self._needs_new_type(results), types_run(results)
        shown = [c for c in self.cands if c["type"] not in seen_types] if need_new else self.cands
        self.allowed = {c["id"] for c in shown}
        user = USER.format(
            graph=json.dumps({"services": compact, "data_flows": self.graph["data_flows"]}),
            baseline=json.dumps((self.baseline or {}).get("probes", {})),
            cands="\n".join(f"- {c['id']} (risk {c['risk_score']}, breaks: {c['predicted_probes'] or 'none'})"
                            for c in shown),
            history=json.dumps(self._history(results)) if results else "nothing yet, this is the first experiment",
            extra=json.dumps(self.extra, default=str)[:3500])
        data, source = ask_json(f"agent_step{self.n}", SYSTEM, user, offline=self.offline, max_tokens=900)
        if not data:
            return self._fallback()
        if data.get("action") == "finish":
            if self.n > 3 and not need_new:
                LIVE.event("ai", f"AGENT decides to finish: {str(data.get('reason', ''))[:200]}")
                return None
            return self._fallback(results)               # not allowed to stop before 3 experiments / 3 fault types
        steps = [s for s in data.get("steps", [])[:2] if s.get("candidate") in self.by_id]
        sig = tuple(s["candidate"] for s in steps)
        adds_type = any(self.by_id[s["candidate"]]["type"] not in seen_types for s in steps)
        if not steps or sig in self.used or (need_new and not adds_type):
            if need_new and steps and not adds_type:
                LIVE.event("warn", f"[coverage] {'+'.join(sig)} adds no new fault type "
                                   f"({len(seen_types)}/{TYPES_REQUIRED} covered): using a rule-based pick")
            return self._fallback(results)               # invalid, repeated or breaks coverage -> never executed
        self.used.add(sig)
        delays = [max(0, min(15, int(s.get("delay_s", 0) or 0))) for s in steps]
        exp = _experiment(self.n, [self.by_id[s["candidate"]] for s in steps], delays,
                          str(data.get("reason", ""))[:400], str(data.get("hypothesis", ""))[:300],
                          self.cfg, self.graph, name=str(data.get("name", ""))[:80] or None)
        exp["id"] = f"E{self.n}"
        pred = data.get("prediction")
        exp["prediction"] = pred if isinstance(pred, dict) else None
        self._publish_ranking(results, "+".join(sig), exp["reason"])
        LIVE.event("ai", f"AGENT step {self.n} ({source}): {exp['name']}")
        LIVE.event("ai", f"  because: {exp['reason']}")
        if exp["prediction"]:
            LIVE.event("ai", f"  predicts: {json.dumps(exp['prediction'])}")
        return exp
