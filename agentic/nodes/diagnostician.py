"""DIAGNOSTICIAN AGENT. Owner: Dipen. See blueprint 6.3 and 11.

Two phases, both feed state["investigations"][experiment_id]:
  Phase 1  detect_fault()  (Dipen, deterministic code): lists the SYMPTOMS with exact evidence - probe errors, stuck services,
           lost votes, no recovery, Observer events (container died, exit code). No AI, cannot be argued with.
  Phase 2  investigate()   (ReAct agent with READ-ONLY tools: logs, container state, queue depth, DB count, config):
           explains WHY it happened, starting from the Phase 1 evidence. Rule-based fallback if the AI is unavailable
           or its answer is empty / just a copied log line.
Output: {root_cause, evidence[], affected_services[], confidence, suggested_fix, by, fault_detected}
Upgrade (Dipen): compare with baseline, timeline tool, match against the Knowledge Store signatures (core/signatures.py),
state confidence honestly and say what evidence would change the diagnosis.
"""
from core.agentkit import ReActAgent
from core.common import LIVE
from core.knowledge import load_observation
from core.tools import make_tools

from ..runtime import cfg

INVESTIGATION_SCHEMA = {"root_cause": "one or two sentences", "evidence": ["quote or number from a tool"],
                        "affected_services": ["service"], "confidence": "high|medium|low",
                        "suggested_fix": "one concrete change"}


def detect_fault(res, configuration=None, baseline=None, observation=None):
    evidence, affected = [], set()
    configuration, baseline = configuration or {}, baseline or {}
    entries = {p['name']: p.get('entry') for p in configuration.get('probes', [])}
    for service in res.get('stuck_services') or []:
        affected.add(service)
        detail = (res.get('stuck_details') or {}).get(service) or {}
        evidence.append(f"{service} was stopped at inspection; exit_code={detail.get('exit_code', 'unknown')}")
    for probe, measured in (res.get('probes') or {}).items():
        rate = measured.get('error_rate')
        if isinstance(rate, (int, float)) and rate > 0:
            evidence.append(f"{probe}: error_rate={rate:.1%}")
            if entries.get(probe):
                affected.add(entries[probe])
        before = ((baseline.get('probes') or {}).get(probe) or {}).get('p95_ms')
        latency = measured.get('p95_ms')
        if isinstance(before, (int, float)) and before > 0 and isinstance(latency, (int, float)) and latency > 2 * before:
            evidence.append(f"{probe}: p95={latency}ms exceeds twice baseline={before}ms")
            if entries.get(probe):
                affected.add(entries[probe])
    lost = (res.get('delivery') or {}).get('lost')
    if isinstance(lost, (int, float)) and lost > 0:
        evidence.append(f"{lost} accepted votes undelivered at measurement cutoff")
    if 'recovery_s' in res and res['recovery_s'] is None:
        evidence.append('Recovery not observed within measurement window')
    if observation and observation.get('experiment') == res.get('id'):
        for event in observation.get('events') or []:
            if event.get('event') == 'die':
                evidence.append(f"Observer: {event.get('service')} exited at t={event.get('t')}; exit_code={event.get('exit_code')}")
                if event.get('service'):
                    affected.add(event['service'])
    if res.get('status') == 'aborted':
        evidence.append(f"Experiment stopped: {res.get('abort_reason') or 'reason unavailable'}")
    detected = bool(evidence)
    if not detected:
        evidence.append('No fault confirmed by available measurements; full health is not established')
    return ({'root_cause': 'Phase 2', 'evidence': evidence,
             'affected_services': sorted(affected), 'confidence': 'low',
             'suggested_fix': ''}, detected)


def investigate(cfg, graph, res, offline=False, symptoms=None):
    facts = {k: res.get(k) for k in ("name", "status", "abort_reason", "recovery_s", "stuck_services",
                                     "stuck_details", "delivery", "prediction", "prediction_check")}
    # what was REALLY injected (e.g. "LATENCY 400ms -> redis"). The raw step field delay_s is only the wait before the
    # step starts, so it is NOT passed: a model once read delay_s=0 as "no latency was injected".
    facts["faults_injected"] = res.get("faults_injected") or [f"{s['type']} -> {s['target']}" for s in res.get("steps", [])]
    facts["note"] = ("Faults were injected for the fault window and then removed. If an injected fault shows no effect, "
                     "the system tolerated it; do not claim the fault was missing unless a tool shows that. 'KILL SWITCH' in the "
                     "logs is OUR safety system restoring services after the error rate got too high; it never causes "
                     "failures. delivery.lost is the number of lost votes: do not claim more than that.")
    facts["error_rate_by_probe"] = {k: v.get("error_rate") for k, v in (res.get("probes") or {}).items()}
    if symptoms:
        facts["detected_symptoms"] = symptoms.get("evidence")      # Phase 1 evidence (deterministic)
    agent = ReActAgent(
        "Diagnostician",
        "an SRE doing root-cause analysis right after a chaos experiment. Use read-only tools (logs, container "
        "state, queue depth, database count, config) to explain WHY the system behaved the way it did",
        make_tools(cfg, graph), INVESTIGATION_SCHEMA, max_steps=5, offline=offline,
        starters=[("list_containers", {})] + [("container_logs", {"service": n, "lines": 20}) for n in
                                              (res.get("stuck_services") or [st["target"] for st in res.get("steps", [])])[:3]])
    final, trace = agent.run(f"Explain the root cause of what happened in experiment {res.get('id')}.", facts)
    return {"final": final, "tool_calls": len(trace), "trace": trace}


def rule_based(res, graph=None):
    stuck, details = res.get("stuck_services") or [], res.get("stuck_details") or {}
    lost = (res.get("delivery") or {}).get("lost") or 0
    if stuck:
        ev = [f"{s} exit code {details.get(s, {}).get('exit_code', '?')}" for s in stuck]
        ev += [line for s in stuck for line in details.get(s, {}).get("last_logs", [])[-2:]]
        return {"root_cause": f"{', '.join(stuck)} crashed during the fault and has no restart policy, so it stayed down",
                "evidence": ev, "affected_services": stuck, "confidence": "medium",
                "suggested_fix": "restart: unless-stopped, plus reconnect-with-retry in the client"}
    if lost:
        return {"root_cause": f"{lost} accepted votes never reached the database; the queue does not persist data",
                "evidence": [f"delivery audit: {res['delivery']}"], "affected_services": [s["target"] for s in res["steps"]],
                "confidence": "medium", "suggested_fix": "enable Redis append-only persistence"}
    return {"root_cause": res.get("abort_reason") or "behaviour differed from the prediction",
            "evidence": [str(res.get("prediction_check"))], "affected_services": [s["target"] for s in res["steps"]],
            "confidence": "low", "suggested_fix": "investigate manually"}


def diagnostician_node(state):
    LIVE.set(agent_active="diagnostician")
    inv = dict(state.get("investigations") or {})
    if not state.get("results"):
        return {"investigations": inv}
    res = state["results"][-1]
    symptoms, detected = detect_fault(res, cfg(), state.get("baseline"), load_observation(res.get("id")))      # Phase 1
    out = investigate(cfg(), state.get("graph") or {}, res, offline=state.get("offline", False), symptoms=symptoms)  # Phase 2
    final = out.get("final")
    cause = str((final or {}).get("root_cause", "")).strip()
    if not final or len(cause) < 25 or cause.upper().startswith("KILL SWITCH"):    # empty, or just a copied log line
        final = None
    by = "agent" if final else "rules"
    final = dict(final or rule_based(res))
    # Phase 1 evidence always travels with the diagnosis, then whatever the agent or rules cited
    final["evidence"] = list(dict.fromkeys(list(symptoms.get("evidence") or []) + [str(e) for e in final.get("evidence") or []]))
    final["affected_services"] = sorted(set(final.get("affected_services") or []) | set(symptoms.get("affected_services") or []))
    final["fault_detected"] = detected
    final["by"] = by
    LIVE.event("ai", f"[Diagnostician] {res['id']} root cause: {final.get('root_cause')}")
    inv[res["id"]] = final
    return {"investigations": inv}
