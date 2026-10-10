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
from core.knowledge import DEFAULT_PATH, KnowledgeStore, load_observation
from core.signatures import extract_features
from core.analysis_tools import reasoning_context
import sqlite3
import json
from core.tools import make_tools

from ..runtime import cfg

INVESTIGATION_SCHEMA = {"root_cause": "one or two sentences", "evidence": ["quote or number from a tool"],
                        "affected_services": ["service"], "confidence": "high|medium|low",
                        "suggested_fix": "empty string when no evidence-backed recommendation is justified"}


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


def matched_known_causes(cfg, graph, res):
    """Retrieve at most three confirmed cases; similarities are not probabilities.

    Missing measurements stay unknown. Existing memory is optional and no
    synthetic or unconfirmed cases are added to it by this lookup.
    """
    observation = res.get("observation") or load_observation(res.get("id")) or {}
    if observation.get("experiment") != res.get("id"):
        observation = {}
    # Engine measurements take precedence over optional Observer snapshots.
    measured = dict(observation)
    rates = dict(observation.get("probe_error_rate") or {})
    rates.update({name: data["error_rate"] for name, data in (res.get("probes") or {}).items()
                  if data.get("error_rate") is not None})
    measured["probe_error_rate"] = rates
    if "recovery_s" in res:
        measured["mttr_s"] = res["recovery_s"]
    features = extract_features(measured)
    services = (graph or {}).get("services") or cfg.get("services") or {}
    for service in res.get("stuck_services") or []:
        if (services.get(service) or {}).get("role") != "consumer":
            continue
        code = ((res.get("stuck_details") or {}).get(service) or {}).get("exit_code")
        if str(code).isdigit() and int(code) != 0:
            features["consumer_exit"] = 1
    logs = " ".join(str(line) for detail in (res.get("stuck_details") or {}).values()
                    for line in detail.get("last_logs") or []).lower()
    if any(marker in logs for marker in ("name or service not known", "enotfound", "getaddrinfo", "dns lookup")):
        features["new_dns_error"] = 1
    templates = dict(observation.get("new_log_templates") or {})
    for service, detail in (res.get("stuck_details") or {}).items():
        previous = templates.get(service) or []
        templates[service] = list(previous) + list(detail.get("last_logs") or [])
    measured["new_log_templates"] = templates
    if not DEFAULT_PATH.exists():
        return []
    try:
        with KnowledgeStore() as store:
            matches = store.retrieve_cases(features, measured, exclude_experiment=res.get("id"), limit=3)
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        LIVE.event("warn", "[Diagnostician] signature memory unavailable; continuing with measured evidence")
        return []
    return matches


def memory_diagnosis(configuration, graph, res):
    """Reuse a specific, unambiguous known cause and verified recommendation.

    Conservative initial gate: same injected fault/role, three known features,
    no conflicting measurements, same-service error pattern and one solution.
    Retrieval similarity alone never bypasses reasoning or authorizes a fix.
    """
    from core.signatures import extract_features, error_templates, jaccard
    steps = res.get("steps") or []
    if len(steps) != 1 or not DEFAULT_PATH.exists():
        return None
    step = steps[0]
    target = step.get("target")
    service = (graph.get("services") or {}).get(target)
    if not service or not service.get("role"):
        return None
    observation = res.get("observation") or load_observation(res.get("id")) or {}
    if observation.get("experiment") != res.get("id"):
        return None
    current = dict(observation)
    rates = dict(observation.get("probe_error_rate") or {})
    rates.update({name: data["error_rate"] for name, data in (res.get("probes") or {}).items()
                  if data.get("error_rate") is not None})
    current["probe_error_rate"] = rates
    features = extract_features(current)
    logs = error_templates(current)
    if not logs or not any(value == 1 for key, value in features.items() if key != "recovers"):
        return None
    try:
        with KnowledgeStore() as store:
            candidates = []
            # Scan all candidates: a top-k truncation must not hide ambiguity.
            for signature in store.signatures():
                if signature["from"] == res.get("id") or signature["fault"] != {
                        "type": step.get("type"), "target_role": service["role"]}:
                    continue
                source = store.get_observation(signature["from"])
                if not source or source.get("experiment") != signature["from"]:
                    continue
                shared = features.keys() & signature["features"].keys()
                matching_logs = logs.keys() & error_templates(source).keys()
                # Even weak competing cases block the shortcut.
                if jaccard(features, signature["features"]) >= 0.6 or matching_logs:
                    candidates.append((signature, shared, matching_logs))
            if not candidates or len({s["root_cause"].strip() for s, _, _ in candidates}) != 1:
                return None
            eligible = [(s, shared, lines) for s, shared, lines in candidates if len(shared) >= 3
                        and lines and all(features[k] == s["features"][k] for k in shared)]
            if not eligible:
                return None
            solutions = {}
            for signature, shared, lines in eligible:
                for solution in store.verified_solutions(signature):
                    solutions[solution["fix"]["id"]] = (signature, lines, solution)
            if len(solutions) != 1:
                return None
            signature, lines, solution = next(iter(solutions.values()))
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        LIVE.event("warn", "[Diagnostician] verified memory unavailable; continuing with reasoning")
        return None
    fix = solution["fix"]
    affected = sorted({target} | {name for name, _ in lines if name in graph.get("services", {})})
    final = {"root_cause": f"Known-case match: {signature['root_cause'][:300]} "
                           "This is a historical explanation matching current evidence, not independent confirmation.",
             "evidence": [f"Memory signature {signature['id']} from {signature['from']}",
                          f"Current measured features: {json.dumps(features, sort_keys=True)}"] +
                         [f"Current {name} error template: {logs[(name, pattern)][:240]}" for name, pattern in sorted(lines)[:2]] +
                         [f"Previously verified fix {fix['id']}: {solution['verification']['runs']} runs; decision keep"],
             "affected_services": affected, "confidence": "low",
             "suggested_fix": f"Previously verified recommendation {fix['id']}: {str(fix['why'])[:240]}. "
                              f"Proposed change: {json.dumps(fix['change'], ensure_ascii=False)[:400]}. "
                              "Review applicability and pass existing safety/approval controls before applying."}
    LIVE.event("info", f"[Diagnostician] memory matched {signature['id']}; verified fix {fix['id']}; skipped LLM")
    return {"final": final, "tool_calls": 0, "trace": [], "known_evidence": [], "source": "memory"}


def investigate(cfg, graph, res, offline=False, symptoms=None):
    remembered = memory_diagnosis(cfg, graph, res)
    if remembered:
        return remembered
    observation = res.get("observation") or load_observation(res.get("id"))
    facts = reasoning_context(res, graph, observation, symptoms)
    facts["note"] = ("Injected action is experimental intent, not proof of downstream impact. "
                     "KILL SWITCH is our restoration control, not the application root cause. "
                     "Undelivered at the measurement cutoff does not prove permanent loss. "
                     "Null measurements are unknown, not healthy. No confirming intervention evidence "
                     "or independently verified agreement among diagnostic methods is supplied.")
    matches = matched_known_causes(cfg, graph, res)
    facts["matched_known_causes"] = matches
    facts["signature_note"] = ("These are confirmed PAST cases, not proof of this incident's cause. "
                               "Similarity is not confidence; few compared features mean limited support. "
                               "Retrieval uses symptom similarity >= 0.6 or an exact normalized log pattern. "
                               "No matches means no qualifying recorded case, not that the system is healthy. "
                               "Confirm or reject a retrieved cause using current logs and state.")
    agent = ReActAgent(
        "Diagnostician",
        "an SRE doing root-cause analysis right after a chaos experiment. Use read-only tools (logs, container "
        "state, queue depth, database count, config) to explain WHY the system behaved the way it did. "
        "Separate the intentional injection trigger, observed failure mechanism, and unproven deeper weakness. "
        "Do not blame pre-existing stopped services on this experiment. Include relevant limitations in root_cause. "
        "A failed Redis PING is not evidence of failed HTTP requests, vote loss, or a traffic-wide error spike. "
        "Sample counts matter; never invent them. Historical records and current snapshots have different times. "
        "A tool saying logs are unavailable supplies no mechanism evidence. "
        "Exit code 137 alone does not distinguish an intentional kill from other SIGKILL mechanisms. "
        "Use low confidence until independent methods and intervention are verified, not just because the fault is known. "
        "Keep suggested_fix empty if the evidence does not support a specific remedy. Docker healthchecks alone "
        "do not restart containers; restart is recovery, not proof of a root-cause fix.",
        make_tools(cfg, graph), INVESTIGATION_SCHEMA, max_steps=5, offline=offline,
        starters=[("list_containers", {})] + [("container_logs", {"service": n, "lines": 20}) for n in
                                              (res.get("stuck_services") or [st["target"] for st in res.get("steps", [])])[:3]])
    final, trace = agent.run(f"Explain the root cause of what happened in experiment {res.get('id')}.", facts)
    final = guarded_diagnosis(final, graph)
    known_evidence = [f"Past signature {m['signature']} (from {m['from']}), similarity={m['similarity']}, "
                      f"compared={','.join(m['compared_features'])}, matched_logs={m['matched_log_count']}: {m['known_cause']} "
                      "[historical cause; not confirmed for this incident]" for m in matches]
    real_calls = sum(bool(t.get("tool")) and not str(t.get("observation", "")).startswith(
        ("REJECTED:", "unknown tool", "SKIPPED:")) for t in trace)
    return {"final": final, "tool_calls": real_calls, "trace": trace, "known_evidence": known_evidence}


def guarded_diagnosis(final, graph):
    """Validate shape and cap confidence independently of the model's assertion.

    This pipeline does not yet produce machine-verified method agreement or
    intervention confirmation, so confidence is conservatively capped at low.
    Adding more logs or retrieving a signature does not lift that cap by itself.
    """
    if not isinstance(final, dict):
        return None
    cause, evidence, affected = final.get("root_cause"), final.get("evidence"), final.get("affected_services")
    if not isinstance(cause, str) or len(cause.strip()) < 25 or cause.upper().startswith("KILL SWITCH"):
        return None
    if not isinstance(evidence, list) or not evidence or not all(isinstance(e, str) and e.strip() for e in evidence):
        return None
    if not isinstance(affected, list) or not all(isinstance(s, str) and s in graph.get("services", {}) for s in affected):
        return None
    if final.get("confidence") not in ("low", "medium", "high") or not isinstance(final.get("suggested_fix", ""), str):
        return None
    return {"root_cause": cause, "evidence": evidence, "affected_services": affected,
            "confidence": "low", "suggested_fix": final.get("suggested_fix", "")}


def rule_based(res, graph=None):
    stuck, details = res.get("stuck_services") or [], res.get("stuck_details") or {}
    lost = (res.get("delivery") or {}).get("lost") or 0
    if stuck:
        ev = [f"{s} exit code {details.get(s, {}).get('exit_code', '?')}" for s in stuck]
        ev += [line for s in stuck for line in details.get(s, {}).get("last_logs", [])[-2:]]
        return {"root_cause": f"{', '.join(stuck)} remained stopped at inspection. "
                              "The crash mechanism, onset and restart-policy contribution are not established.",
                "evidence": ev, "affected_services": stuck, "confidence": "low", "suggested_fix": ""}
    if lost:
        return {"root_cause": f"{lost} votes were undelivered at the measurement cutoff; "
                              "the cause and permanent loss are not established.",
                "evidence": [f"delivery audit: {res['delivery']}"], "affected_services": [],
                "confidence": "low", "suggested_fix": ""}
    return {"root_cause": res.get("abort_reason") or "behaviour differed from the prediction",
            "evidence": [str(res.get("prediction_check"))], "affected_services": [],
            "confidence": "low", "suggested_fix": ""}


def diagnostician_node(state):
    LIVE.set(agent_active="diagnostician")
    inv = dict(state.get("investigations") or {})
    if not state.get("results"):
        return {"investigations": inv}
    res = state["results"][-1]
    symptoms, detected = detect_fault(res, cfg(), state.get("baseline"), load_observation(res.get("id")))      # Phase 1
    try:
        out = investigate(cfg(), state.get("graph") or {}, res, offline=state.get("offline", False), symptoms=symptoms)
    except Exception as exc:
        LIVE.event("warn", f"[Diagnostician] reasoning unavailable ({type(exc).__name__}); using measured fallback")
        out = {}
    final = guarded_diagnosis(out.get("final"), state.get("graph") or {})
    cause = str((final or {}).get("root_cause", "")).strip()
    if not final or len(cause) < 25 or cause.upper().startswith("KILL SWITCH"):    # empty, or just a copied log line
        final = None
    by = "agent" if final and out.get("source") != "memory" else "rules"
    final = dict(final or rule_based(res))
    # Phase 1 evidence always travels with the diagnosis, then whatever the agent or rules cited
    final["evidence"] = list(dict.fromkeys(list(symptoms.get("evidence") or [])
                            + [str(e) for e in final.get("evidence") or []]
                            + (out.get("known_evidence") or [])))
    final["affected_services"] = sorted(set(final.get("affected_services") or []) | set(symptoms.get("affected_services") or []))
    final["fault_detected"] = detected
    final["by"] = by
    LIVE.event("ai", f"[Diagnostician] {res['id']} root cause: {final.get('root_cause')}")
    inv[res["id"]] = final
    return {"investigations": inv}
