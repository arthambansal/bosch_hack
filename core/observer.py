
"""ChaosPilot Observer.

Collects read-only evidence about the sandbox:
- Docker container events
- Container health and exit status
- New log patterns
- Probe and delivery measurements

This module never injects faults or changes containers.
"""
import uuid
import requests

from .common import docker
import re
import subprocess
import time
from collections import Counter


# Replace changing values so similar log messages share one template.
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def normalize_log(line):
    """Turn a log line into a reusable template."""
    line = _IP.sub("<IP>", line)
    line = _HEX.sub("<HEX>", line)
    line = _NUMBER.sub("<NUM>", line)
    return " ".join(line.split())


def mine_log_templates(lines):
    """Count how often each normalized log template occurs."""
    return dict(Counter(normalize_log(line) for line in lines if line.strip()))


def detect_anomalies(metrics, healthy=None):
    """Apply simple, explainable anomaly rules to measured metrics."""
    healthy = healthy or {}
    anomalies = []

    for probe, current in metrics.get("probe_error_rate", {}).items():
        baseline = healthy.get("probe_error_rate", {}).get(probe, {})
        baseline_rate = baseline.get("mean", 0.0)
        baseline_std = baseline.get("std", 0.0)

        if current > 0.05:
            anomalies.append({
                "type": "probe_error_rate",
                "service": probe,
                "value": current,
                "reason": "Probe error rate exceeds 5%",
            })
        elif baseline_std > 0 and current > baseline_rate + 3 * baseline_std:
            anomalies.append({
                "type": "probe_error_rate",
                "service": probe,
                "value": current,
                "reason": "Probe error rate is over 3 standard deviations above baseline",
            })

    queue = metrics.get("queue_depth")
    if isinstance(queue, dict):
        start = queue.get("start", 0)
        end = queue.get("end", 0)
        if start is not None and end is not None and end > start:
            anomalies.append({
                "type": "queue_growth",
                "service": "redis",
                "value": end - start,
                "reason": "Queue depth increased during observation",
            })

    for event in metrics.get("events", []):
        if event.get("event") == "die" and event.get("exit_code", 0) != 0:
            anomalies.append({
                "type": "container_exit",
                "service": event.get("service", "unknown"),
                "value": event.get("exit_code"),
                "reason": "Container exited with a non-zero code",
            })

    return anomalies


def docker_events(t_start, t_end, project="chaos"):
    """Read Docker events in a time range; never issue Docker control commands."""
    since = str(max(0, int(t_start)))
    until = str(max(int(t_start), int(t_end)))

    try:
        result = subprocess.run(
            [
                "docker", "events",
                "--since", since,
                "--until", until,
                "--filter", f"label=com.docker.compose.project={project}",
                "--format", "{{json .}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    events = []
    for line in result.stdout.splitlines():
        try:
            import json
            event = json.loads(line)
        except ValueError:
            continue

        action = event.get("Action", event.get("status", ""))
        if action not in {"die", "start", "restart"}:
            continue

        attrs = event.get("Actor", {}).get("Attributes", {})
        events.append({
            "t": event.get("time", 0),
            "service": attrs.get("com.docker.compose.service", "unknown"),
            "event": action,
            "exit_code": int(attrs.get("exitCode", 0) or 0),
        })

    return events

def collect_log_templates(
    cfg, t_start, t_end=None, healthy_templates=None
):
    """Collect service logs for a time window and return unseen log templates."""
    import subprocess

    healthy_templates = healthy_templates or {}
    new_templates = {}

    for name, service in cfg.get("services", {}).items():
        container = service.get("container")
        if not container:
            continue

        try:
            result = subprocess.run(
                [
                    "docker", "logs",
                    "--since", str(max(0, int(t_start))),
                    "--until", str(max(int(t_start), int(t_end)))
                        if t_end is not None else "now",
                    container,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue

        lines = (result.stdout + "\n" + result.stderr).splitlines()
        observed = mine_log_templates(lines)
        known = set(healthy_templates.get(name, []))
        unseen = sorted(template for template in observed if template not in known)

        if unseen:
            new_templates[name] = unseen

    return new_templates


def summary(
    t_start,
    t_end,
    cfg=None,
    prober=None,
    healthy=None,
    canary_result=None,
    queue_start=None,
    queue_end=None,
    accepted_count=None,
    delivered_count=None,
    kill_switch=None,
    stuck_services=None,
    mttd_s=None,
    mttr_s=None,
    healthy_templates=None,
):
    """Return a best-effort observation summary for the requested time range.

    Missing evidence is represented as None or an empty list rather than
    inventing measurements. Pass cfg and prober when available.
    """
    cfg = cfg or {}
    metrics = {}
    events = docker_events(t_start, t_end, cfg.get("project", "chaos"))

    probe_errors = {}
    if prober is not None:
        for name in prober.results:
            results = prober.since(name, t_start, t_end)
            if results:
                probe_errors[name] = round(
                    sum(1 for row in results if not row[1]) / len(results), 3
                )

    metrics["probe_error_rate"] = probe_errors

    queue_check = cfg.get("backlog_check")

    if queue_check and queue_end is None:
        try:
            from .probes import backlog
            queue_end = backlog(cfg)
        except (ImportError, KeyError, OSError):
            queue_end = None

    metrics["queue_depth"] = {
        "start": queue_start,
        "end": queue_end,
    } if queue_check else None

    anomalies = detect_anomalies(metrics, healthy)
    accepted = (
        accepted_count
        if accepted_count is not None
        else (
            canary_result.get("accepted")
            if canary_result is not None
            else getattr(prober, "votes_ok", None)
        )
    )

    delivered = (
        delivered_count
        if delivered_count is not None
        else (
            canary_result.get("delivered")
            if canary_result is not None
            else None
        )
    )

    delivery = {
        "accepted": accepted,
        "delivered": delivered,
        "canary_lag_s": (
            canary_result.get("canary_lag_s")
            if canary_result is not None
            else None
        ),
    }

    new_log_templates = collect_log_templates(
        cfg,
        t_start,
        t_end=t_end,
        healthy_templates=healthy_templates,
    )

    return {
        "experiment": cfg.get("experiment", "unknown"),
        "t_start": t_start,
        "t_end": t_end,
        "mttd_s": mttd_s,
        "mttr_s": mttr_s,
        "probe_error_rate": probe_errors,
        "delivery": delivery,
        "queue_depth": metrics["queue_depth"],
        "events": events,
        "new_log_templates": new_log_templates,
        "anomalies": anomalies,
        "kill_switch": kill_switch,
        "stuck_services": stuck_services or [],
    }


def trace_canary(cfg=None, timeout_s=8.0):
    """Send one uniquely identified test vote and check PostgreSQL for it.

    A timeout means the row was not observed within the time limit.
    It does not prove permanent data loss.
    """
    from .common import load_config

    cfg = cfg or load_config()

    vote_probe = next(
        (p for p in cfg.get("probes", []) if p.get("name") == "vote_write"),
        None,
    )
    db_cfg = cfg.get("delivery_check", {})

    if not vote_probe or not db_cfg.get("container"):
        return {
            "accepted": False,
            "delivered": None,
            "canary_lag_s": None,
            "status": "configuration_missing",
        }

    # Only generated, restricted IDs are used in the SQL query.
    canary_id = "canary-" + uuid.uuid4().hex[:12]
    vote = "a"
    started = time.monotonic()

    try:
        response = requests.post(
            vote_probe["url"],
            data={"vote": vote},
            cookies={"voter_id": canary_id},
            timeout=2.5,
        )
        accepted = response.status_code < 400
        http_status = response.status_code
    except requests.RequestException as exc:
        return {
            "canary_id": canary_id,
            "accepted": False,
            "delivered": None,
            "canary_lag_s": None,
            "status": "request_failed",
            "error": type(exc).__name__,
        }

    if not accepted:
        return {
            "canary_id": canary_id,
            "accepted": False,
            "delivered": None,
            "canary_lag_s": None,
            "http_status": http_status,
            "status": "request_rejected",
        }

    deadline = time.monotonic() + timeout_s
    query = (
        "SELECT EXISTS "
        f"(SELECT 1 FROM votes WHERE id = '{canary_id}');"
    )

    while time.monotonic() < deadline:
        ok, output = docker(
            "exec",
            db_cfg["container"],
            "psql",
            "-U", "postgres",
            "-tAc", query,
            timeout=3,
        )

        if ok:
            answer = output.strip().lower()

            if answer == "t":
                return {
                    "canary_id": canary_id,
                    "accepted": True,
                    "delivered": True,
                    "canary_lag_s": round(
                        time.monotonic() - started, 3
                    ),
                    "http_status": http_status,
                    "status": "delivered",
                }

            if answer not in {"f", ""}:
                return {
                    "canary_id": canary_id,
                    "accepted": True,
                    "delivered": None,
                    "canary_lag_s": None,
                    "status": "database_query_error",
                }

        time.sleep(0.25)

    return {
        "canary_id": canary_id,
        "accepted": True,
        "delivered": False,
        "canary_lag_s": None,
        "http_status": http_status,
        "status": "not_seen_before_timeout",
    }
