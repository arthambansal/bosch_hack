"""Read-only investigation tools that agents may call. None of them can change anything.

Every tool validates its arguments against config.json, truncates output, and hides secret values
(environment variable VALUES are never returned, only their names).
"""
import json

from .agentkit import Tool
from .common import docker
from .probes import backlog, delivery_count


def make_tools(cfg, graph):
    services = cfg["services"]

    def container_of(service):
        if service not in services:
            raise ValueError(f"unknown service '{service}'. Valid services: {sorted(services)}")
        return services[service]["container"]

    def list_containers():
        out = {}
        fmt = "{{.State.Status}}|{{.State.ExitCode}}|{{.RestartCount}}|{{.HostConfig.RestartPolicy.Name}}|{{json .NetworkSettings.Networks}}"
        for name, svc in services.items():
            ok, txt = docker("inspect", "-f", fmt, svc["container"])
            if not ok:
                out[name] = {"status": "missing"}
                continue
            status, code, restarts, policy, networks = (txt.strip().split("|") + ["", "", "", "", ""])[:5]
            try:
                attached = json.loads(networks)
                connected = cfg["network"] in attached if isinstance(attached, dict) and cfg.get("network") else None
            except (ValueError, TypeError):
                connected = None
            out[name] = {"status": status, "exit_code": code, "restart_count": restarts,
                         "restart_policy": policy or "no", "network_connected": connected}
        return out

    def container_logs(service, lines=30):
        n = max(5, min(int(lines), 40))
        ok, txt = docker("logs", "--tail", str(n), container_of(service), timeout=10)
        return "\n".join(line[:200] for line in txt.splitlines()[-n:]) or "(no log output)"

    def service_config(service):
        ok, txt = docker("inspect", container_of(service))
        if not ok:
            return f"could not inspect {service}: {txt[:200]}"
        d = json.loads(txt)[0]
        return {"image": d["Config"].get("Image"), "command": d["Config"].get("Cmd"),
                "env_var_names": [e.split("=", 1)[0] for e in d["Config"].get("Env") or []],
                "restart_policy": (d["HostConfig"].get("RestartPolicy") or {}).get("Name") or "no",
                "volumes": [m.get("Destination") for m in d.get("Mounts") or []],
                "healthcheck": bool((d["Config"].get("Healthcheck") or {}).get("Test"))}

    def dependencies(service):
        container_of(service)
        s = graph["services"][service]
        return {k: s.get(k) for k in ("role", "stateful", "depends_on", "used_by", "blast_radius")}

    def queue_depth():
        q = backlog(cfg)
        return {"items_waiting_in_queue": q} if q is not None else "queue not readable"

    def db_row_count():
        c = delivery_count(cfg)
        return {"rows_in_database": c} if c is not None else "database not readable"

    tools = [
        Tool("list_containers", "status, exit code, restart count and restart policy of every service", [], list_containers),
        Tool("container_logs", "last N log lines of one service (max 40)", ["service", "lines"], container_logs),
        Tool("service_config", "image, command, env var NAMES, restart policy, volumes, healthcheck of one service",
             ["service"], service_config),
        Tool("dependencies", "who this service depends on and who depends on it", ["service"], dependencies),
        Tool("queue_depth", "how many items are waiting in the queue right now", [], queue_depth),
        Tool("db_row_count", "how many votes are stored in the database right now", [], db_row_count),
    ]
    return {t.name: t for t in tools}
