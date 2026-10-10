"""Deterministic Day-1 evidence analysis; no Docker or model calls."""


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
