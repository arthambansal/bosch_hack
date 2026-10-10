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
    return {"final": final, "tool_calls": 0, "trace": [], "known_evidence": [], "source": "memory",
            "signature_id": signature["id"], "seen_in_run": signature.get("from")}


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
        make_tools(cfg, graph), INVESTIGATION_SCHEMA, max_steps=4, offline=offline, prefetch=True, time_budget_s=45,
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
    steps = res.get("steps") or []
    targets = [s.get("target") for s in steps if s.get("target")]
    probes = res.get("probes") or {}
    hit = sorted(((n, p.get("error_rate") or 0) for n, p in probes.items()), key=lambda x: -x[1])
    worst = [f"{n} {r:.0%} errors" for n, r in hit if r > 0][:2]
    action = " then ".join(f"{s.get('type')} {s.get('target')}" for s in steps) or "the injected fault"
    users = sorted({u for t in targets for u in ((graph or {}).get("services", {}).get(t, {}).get("used_by") or [])})
    cause = (f"The injected {action} made {', '.join(worst) or 'the probes degrade'}"
             + (f"; the kill switch restored it after {res.get('fault_window_s')} s" if res.get("status") == "aborted" else "")
             + (f". {', '.join(targets)} has a single instance on the request path"
                + (f" used by {', '.join(users)}" if users else "") + ", so there is no failover" if targets else "")
             + f". Recovery after restoration took {res.get('recovery_s')} s. Deeper mechanism not established without AI analysis.")
    ev = [f"{n}: error rate {p.get('error_rate')}, p95 {p.get('p95_ms')} ms, n={p.get('n')}" for n, p in probes.items()]
    if res.get("abort_reason"):
        ev.append(str(res["abort_reason"]))
    known = (graph or {}).get("services")
    return {"root_cause": cause, "evidence": ev, "affected_services": [t for t in targets if not known or t in known],
            "confidence": "low", "suggested_fix": ""}


def _publish_memory(exp_id, out, final):
    """Dashboard 'Failure memory' panel: how many confirmed signatures exist, and whether this diagnosis came from one."""
    try:
        count = 0
        if DEFAULT_PATH.exists():
            with KnowledgeStore() as store:
                count = len(store.signatures())
        hit = None
        if out.get("source") == "memory":
            hit = {"experiment": exp_id, "signature_id": out.get("signature_id"), "similarity": out.get("similarity"),
                   "seen_in_run": out.get("seen_in_run"), "root_cause": str(final.get("root_cause", ""))[:300],
                   "saved_s": None}
        LIVE.set(memory={"last_hit": hit, "signatures": count})
    except Exception:  # noqa: BLE001 - display only
        pass


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
    final = dict(final or rule_based(res, state.get("graph") or {}))
    # Phase 1 evidence always travels with the diagnosis, then whatever the agent or rules cited
    final["evidence"] = list(dict.fromkeys(list(symptoms.get("evidence") or [])
                            + [str(e) for e in final.get("evidence") or []]
                            + (out.get("known_evidence") or [])))
    final["affected_services"] = sorted(set(final.get("affected_services") or []) | set(symptoms.get("affected_services") or []))
    final["fault_detected"] = detected
    final["by"] = by
    LIVE.event("ai", f"[Diagnostician] {res['id']} root cause ({by}): {final.get('root_cause')}")
    inv[res["id"]] = final
    _publish_memory(res["id"], out, final)
    return {"investigations": inv}


# ---------------------------------------------------------------- Day 2 interfaces (Dipen) — DAY2_CONTRACT.md 4.2, 4.3, 5
_BLIND_TIMINGS = {}
def diagnose_blind(res, cfg, graph, offline=False):
    """Name the hidden fault and target from evidence only. `res` is redacted (no name/steps/faults_injected/...)."""
    import time
    from core.analysis_tools import blind_candidates
    from core.contract_v5 import validate_guess
    t0 = time.perf_counter()
    incident = res.get("id")
    # Whitelist rather than copying the result: injection fields are never read.
    safe = {key: res.get(key) for key in ("probes", "delivery", "stuck_services", "stuck_details", "recovery_s")}
    safe["id"] = "blind-incident"
    original = res.get("observation") or load_observation(incident) or {}
    if original.get("experiment") != incident:
        original = {}
    observation = {key: original.get(key) for key in ("probe_error_rate", "queue_depth", "mttr_s",
        "events", "new_log_templates", "delivery", "mttd_s", "t_start", "t_end") if key in original}
    observation["experiment"] = safe["id"]
    safe["observation"] = observation
    window = res.get("fault_window_evidence") or {}
    # Explicit whitelist prevents injection metadata from entering the prompt.
    window_states = {name: {key: state.get(key) for key in ("status", "running", "paused", "exit_code")}
                     for name, state in (window.get("container_states") or {}).items()
                     if name in cfg.get("services", {}) and isinstance(state, dict)}
    fault_window = {key: window.get(key) for key in ("t_start", "t_end", "captured_at")}
    fault_window.update(container_states=window_states, events=observation.get("events") or [],
                        probes=safe.get("probes") or {})
    measured = dict(observation)
    rates = dict(observation.get("probe_error_rate") or {})
    rates.update({name: values["error_rate"] for name, values in (safe.get("probes") or {}).items()
                  if values.get("error_rate") is not None})
    measured["probe_error_rate"] = rates
    features = extract_features(measured)
    tools = make_tools(cfg, graph)
    try:
        states = json.loads(tools["list_containers"].run({}))
        if not isinstance(states, dict):
            states = {}
    except (KeyError, ValueError, TypeError):
        states = {}
    candidates = blind_candidates(safe, observation, window_states or states, cfg, graph)
    if not candidates:
        LIVE.set(memory={"last_hit": None, "signatures": 0})
        return None  # no configured service: cannot manufacture a valid target
    memory = None
    signature_count = 0
    try:
        if DEFAULT_PATH.exists():
            with KnowledgeStore() as store:
                signatures = store.signatures()
                signature_count = len(signatures)
                matches = store.similar_signatures(features, limit=max(1, len(signatures)))
                viable = []
                for match in matches:
                    signature = match["signature"]
                    if signature["from"] == incident or match["similarity"] < 0.8:
                        continue
                    source = store.get_observation(signature["from"])
                    if not source:
                        continue
                    shared = features.keys() & signature["features"].keys()
                    if len(shared) < 3 or any(features[k] != signature["features"][k] for k in shared):
                        continue
                    experiment = store.get_experiment(signature["from"])
                    steps = ((experiment or {}).get("spec") or {}).get("steps") or []
                    target = steps[0].get("target") if len(steps) == 1 else None
                    if target is None:
                        roles = [name for name, service in cfg.get("services", {}).items()
                                 if service.get("role") == signature["fault"]["target_role"]]
                        target = roles[0] if len(roles) == 1 else None
                    if target not in cfg.get("services", {}) or signature["fault"]["type"] not in (
                            "kill", "pause", "partition", "latency", "spike"):
                        continue
                    viable.append((match, target, experiment, store.diagnosis_duration(signature["id"])))
                identities = {(m["signature"]["fault"]["type"], target) for m, target, _, _ in viable}
                if len(identities) == 1:
                    best = viable[0]
                    pair = (best[0]["signature"]["fault"]["type"], best[1])
                    # Do not override strong contradictory current evidence.
                    if candidates[0]["confidence"] < 0.6 or pair == (candidates[0]["fault"], candidates[0]["target"]):
                        memory = best
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        LIVE.event("warn", "[Diagnostician] blind memory unavailable; using measured evidence")
    source = "rules"
    guess = {key: candidates[0][key] for key in ("fault", "target", "confidence")}
    guess.update(top3=[{key: c[key] for key in ("fault", "target", "confidence")} for c in candidates],
        root_cause="Evidence-ranked hypothesis; these weights are not calibrated probabilities. "
                   "The precise mechanism needs confirmation.",
        evidence=list(dict.fromkeys(fact for c in candidates for fact in c["evidence"]))[:8], memory_hit=False)
    if memory:
        match, target, experiment, previous_seconds = memory
        signature = match["signature"]
        pair = {"fault": signature["fault"]["type"], "target": target, "confidence": match["similarity"]}
        guess = {**pair, "top3": [pair], "root_cause": "Historical match: " + signature["root_cause"][:300],
                 "evidence": [f"Past signature {signature['id']}; similarity={match['similarity']}; "
                              f"compared features={','.join(match['compared_features'])}; not current confirmation"],
                 "memory_hit": True}
        source = "memory"
    if not offline:
        schema = {"fault": "kill|pause|partition|latency|spike", "target": "configured service",
                  "confidence": "number 0..1", "top3": [{"fault": "type", "target": "service", "confidence": 0.3}],
                  "root_cause": "evidence-backed hypothesis with limitations", "evidence": ["quoted measurement"]}
        context = reasoning_context(safe, graph, observation)
        context.pop("injected_action", None)
        context["container_state"] = states
        context["fault_window"] = fault_window
        context["candidates"] = candidates
        context["configured_services"] = sorted(cfg.get("services", {}))
        agent = ReActAgent("BlindDiagnostician", "an SRE diagnosing an unknown fault from measurements only. "
            "You do not know the injection. Rank fault/target pairs, cite actual evidence, and state uncertainty. "
            "Prioritize fault_window measured states and events over current container_state and live logs. "
            "Paused=true supports pause; an exited state supports a crash. Probe latency locates a dependency path, "
            "not necessarily the slow component. Healthy logs do not rule out dependency latency. "
            "Post-restoration state does not prove fault-window health. Never read files or injection metadata.",
            tools, schema, max_steps=4, offline=False, starters=[("list_containers", {})], prefetch=True,
            time_budget_s=45)
        try:
            answer, trace = agent.run("Identify the fault and target from this blind evidence packet.", context)
            checked = _validated_blind_guess(answer, cfg)
            if checked:
                guess, source = checked, "ai"
                memory = None
        except Exception as exc:
            LIVE.event("warn", f"[Diagnostician] blind AI unavailable ({type(exc).__name__}); using evidence ranking")
    seconds = time.perf_counter() - t0
    guess["seconds"] = round(seconds, 6)
    if memory:
        match, target, experiment, previous_seconds = memory
        LIVE.set(memory={"signatures": signature_count, "last_hit": {"experiment": incident,
            "signature_id": match["signature"]["id"], "similarity": match["similarity"],
            "seen_in_run": (experiment or {}).get("run_id"), "root_cause": guess["root_cause"],
            "saved_s": previous_seconds - seconds if previous_seconds is not None else None}})
    else:
        LIVE.set(memory={"last_hit": None, "signatures": signature_count})
    if len(_BLIND_TIMINGS) >= 100:
        _BLIND_TIMINGS.pop(next(iter(_BLIND_TIMINGS)))
    _BLIND_TIMINGS[incident] = {"seconds": seconds, "source": source}
    return guess if not validate_guess(guess, cfg.get("services") or {}) else None


def _validated_blind_guess(answer, configuration):
    """Validate every ranked pair, not just the permissive shared validator."""
    import math
    from core.contract_v5 import validate_guess
    LIVE.event("warn", "[Diagnostician] blind AI raw answer: " + json.dumps(answer, default=str)[:300])
    def reject(reason):
        LIVE.event("warn", "[Diagnostician] blind AI answer rejected: " + reason)
        return None
    if not isinstance(answer, dict):
        return reject("answer is not an object")
    guess = {key: answer.get(key) for key in ("fault", "target", "confidence", "top3", "root_cause", "evidence")}
    guess["memory_hit"] = False
    try:
        faults = {"kill", "pause", "partition", "latency", "spike"}
        services = configuration.get("services") or {}
        if guess["fault"] not in faults or guess["target"] not in services:
            return reject("unknown primary fault or unconfigured target")
        if not isinstance(guess["root_cause"], str) or len(guess["root_cause"].strip()) < 25:
            return reject("root_cause must contain at least 25 characters")
        if not isinstance(guess["evidence"], list) or not guess["evidence"] or not all(isinstance(fact, str) and fact.strip() for fact in guess["evidence"]):
            return reject("evidence must contain nonempty strings")
        if not isinstance(guess["top3"], list) or not guess["top3"]:
            return reject("top3 must be a nonempty list")
        unique = {}
        for item in guess["top3"]:
            pair = (item["fault"], item["target"])
            confidence = item["confidence"]
            if pair[0] not in faults or pair[1] not in services:
                return reject("unknown fault or unconfigured target in top3")
            if type(confidence) not in (int, float) or not math.isfinite(confidence):
                return reject("top3 confidence must be a finite number")
            weight = min(1.0, max(0.0, confidence))
            unique[pair] = max(unique.get(pair, 0), weight)
        ranked = sorted(unique.items(), key=lambda p: -p[1])[:3]
        total = sum(weight for _, weight in ranked)
        guess["top3"] = [{"fault": pair[0], "target": pair[1],
                          "confidence": weight / total if total else 1 / len(ranked)}
                         for pair, weight in ranked]
        guess.update(guess["top3"][0])
        errors = validate_guess(guess, services)
        if errors:
            return reject("contract validation: " + str(errors))
        return guess
    except (TypeError, KeyError, ValueError) as exc:
        return reject("malformed answer: " + str(exc))


def remember_confirmed(res, fault, root_cause):
    """Remember a revealed fault; no claim that reveal proves a deeper mechanism."""
    import hashlib
    from core.signatures import build_signature
    try:
        configuration = cfg()
        target = fault.get("target")
        kind = fault.get("fault", fault.get("type"))
        role = (configuration.get("services") or {}).get(target, {}).get("role")
        if kind not in ("kill", "pause", "partition", "latency", "spike") or not role or not res.get("id"):
            raise ValueError("invalid revealed fault or source incident")
        observation = res.get("observation") or load_observation(res["id"])
        if not observation or observation.get("experiment") != res["id"]:
            raise ValueError("a matching measured observation is required")
        cause = f"Revealed {kind} on {target}. Diagnosis hypothesis (mechanism not independently confirmed): {str(root_cause)[:300]}"
        signature = build_signature(observation, signature_id="pending", fault={"type": kind, "target_role": role},
                                    root_cause=cause, confirmed=True)
        # Repeated model wording must not create duplicates of the same case.
        identity = {"fault": signature["fault"], "target": target, "features": signature["features"]}
        signature["id"] = "S-mystery-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
        with KnowledgeStore() as store:
            if any(s["id"] == signature["id"] for s in store.signatures()):
                return None
            # Keep original artifact fields. Reveal supplies the missing experiment label.
            spec = dict(res)
            spec["steps"] = [{"type": kind, "target": target}]
            run = LIVE.state.get("run_dir")
            with store.connection:
                existing = store.get_observation(res["id"])
                if existing and existing != observation:
                    raise ValueError("source observation ID already belongs to different evidence")
                store.save_observation(observation)
                store.save_experiment(spec, str(run or "unknown"))
                store.save_signature(signature)
                timing = _BLIND_TIMINGS.get(res["id"])
                if timing and timing["source"] == "ai":
                    store.record_diagnosis_duration(signature["id"], timing["seconds"])
            count = len(store.signatures())
        LIVE.set(memory={"last_hit": None, "signatures": count})
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        LIVE.event("warn", f"[Diagnostician] revealed case not stored ({type(exc).__name__})")
    return None
