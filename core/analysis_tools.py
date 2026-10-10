"""Deterministic Day-1 evidence analysis; no Docker or model calls."""


def reasoning_context(result, graph, observation=None, symptoms=None):
    """Keep facts, experimental intent and unknowns separate for causal reasoning.

    This is internal prompt context, not a new inter-agent or stored schema.
    A missing sample count or delivery counter stays unknown.
    """
    observation = observation or {}
    if observation.get("experiment") != result.get("id"):
        observation = {}
    probes = {name: {key: values.get(key) for key in
                    ("n", "ok", "error_rate", "p95_ms", "time_to_first_error_s")}
              for name, values in (result.get("probes") or {}).items()}
    delivery = result.get("delivery") or {}
    unknowns = []
    for name, values in probes.items():
        if values["n"] is None:
            unknowns.append(f"{name}: sample count unavailable; error rate is not proof of an application-wide spike")
    if delivery.get("sent") is None or delivery.get("delivered") is None:
        unknowns.append("End-to-end accepted/delivered counts are unavailable")
    details = result.get("stuck_details") or {}
    if not any(d.get("last_logs") for d in details.values()) and not observation.get("new_log_templates"):
        unknowns.append("No historical mechanism logs supplied; live tool logs may be from a different time")
    before = (symptoms or {}).get("preexisting_stopped_services")
    if before is None:
        unknowns.append("Pre-experiment service states are unavailable unless explicitly supplied in symptom evidence")
    stopped = result.get("stuck_services") or []
    return {
        "injected_action": result.get("faults_injected") or
            [f"{s['type']} -> {s['target']}" for s in result.get("steps", [])],
        "measured_effects": {"probes": probes, "delivery": delivery,
                             "stopped_services": stopped, "stop_details": details,
                             "recovery_s": result.get("recovery_s"),
                             "queue_depth": observation.get("queue_depth"),
                             "events": observation.get("events") or [],
                             "new_log_templates": observation.get("new_log_templates") or {}},
        "preexisting_conditions": {"stopped_services": before,
                                   "supplied_symptom_evidence": (symptoms or {}).get("evidence") or []},
        "timing": {"fault_window_s": result.get("fault_window_s"),
                   "observer_start": observation.get("t_start"), "observer_end": observation.get("t_end"),
                   "tool_readings": "post-experiment snapshots; do not substitute them for fault-window measurements"},
        "topology": localize(graph, stopped),
        "unknowns": unknowns,
        "safety_action": {"status": result.get("status"), "abort_reason": result.get("abort_reason")},
    }


def dependency_map(graph):
    services = (graph or {}).get("services") or {}
    deps = {name: set(s.get("depends_on") or []) for name, s in services.items()}
    for edge in (graph or {}).get("edges") or []:
        deps.setdefault(edge["from"], set()).add(edge["to"])
    return deps


def localize(graph, anomalous_services):
    """Find deepest observed anomalies, while marking dependency health unknown.

    Absence from the symptom set does not prove a dependency is healthy.
    Cycles are bounded with a visited set; ties stay deterministic.
    """
    deps = dependency_map(graph)
    anomalous = set(anomalous_services)

    def descendants(service):
        seen, pending = set(), list(deps.get(service, ()))
        while pending:
            name = pending.pop()
            if name not in seen:
                seen.add(name)
                pending.extend(deps.get(name, ()))
        return seen - {service}

    deepest = sorted(s for s in anomalous if not descendants(s) & anomalous)
    return {"candidates": deepest or sorted(anomalous),
            "dependencies": {s: sorted(deps.get(s, ())) for s in sorted(anomalous)},
            "dependency_health": "unknown unless separately measured"}


def compare_to_baseline(result, baseline):
    comparisons = {}
    for name, current in (result.get("probes") or {}).items():
        healthy = (baseline.get("probes") or {}).get(name) or {}
        row = {}
        for metric in ("error_rate", "p95_ms"):
            now, before = current.get(metric), healthy.get(metric)
            if isinstance(now, (int, float)) and isinstance(before, (int, float)):
                row[metric] = {"baseline": before, "observed": now, "delta": now - before}
        if row:
            comparisons[name] = row
    return comparisons


def evidence_context(result, graph, baseline=None, observation=None):
    """Keep injection metadata distinct from measured effects and log mechanism."""
    stuck = sorted(set(result.get("stuck_services") or []))
    evidence = []
    for service in stuck:
        detail = (result.get("stuck_details") or {}).get(service) or {}
        evidence.append(f"{service}: still stopped at post-experiment inspection")
        if detail.get("exit_code") is not None:
            evidence.append(f"{service}: exit code {detail['exit_code']}")
        evidence.extend(f"{service} log: {str(line)[:200]}"
                        for line in (detail.get("last_logs") or [])[-5:])
    for probe, values in sorted((result.get("probes") or {}).items()):
        if values.get("error_rate") is not None:
            evidence.append(f"probe {probe}: error_rate={values['error_rate']}")
    delivery = result.get("delivery") or {}
    if "lost" in delivery:
        evidence.append(f"delivery audit: undelivered at measurement cutoff={delivery['lost']}")
    if "recovery_s" in result:
        evidence.append(f"measured recovery_s={result['recovery_s']}")
    if result.get("abort_reason"):
        evidence.append(f"guard: {result['abort_reason']}")
    if observation and observation.get("experiment") == result.get("id"):
        for event in sorted(observation.get("events") or [], key=lambda e: e.get("t", 0)):
            evidence.append(f"observer event: {event.get('service')} {event.get('event')} "
                            f"at t={event.get('t')}; exit_code={event.get('exit_code')}")
        for service, templates in (observation.get("new_log_templates") or {}).items():
            evidence.extend(f"observer {service} template: {line}" for line in templates)
        evidence.append(f"observer delivery: {observation.get('delivery')}")
        evidence.append(f"observer queue_depth: {observation.get('queue_depth')}")
    return {"measured_evidence": evidence, "topology": localize(graph, stuck),
            "baseline_comparison": compare_to_baseline(result, baseline or {}),
            "injected_steps": result.get("steps") or [],
            "limitations": ["Post-experiment logs may include earlier messages; timing is unconfirmed.",
                            "Undelivered at cutoff does not establish permanent loss.",
                            "A dependency without a reported anomaly is not proven healthy."]}
