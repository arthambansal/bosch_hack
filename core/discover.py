"""Automatic dependency mapping.

Three evidence sources, merged into dependencies.json:
  1. declared  - the `depends_on` that Docker Compose stores as a container label
  2. observed  - LIVE TCP connections read from /proc/net/tcp inside each container
                 (if container A has an open connection to B's listening port, A depends on B)
  3. manual    - corrections from config.json (the brief allows manual corrections)
"""
import json
import time

from .common import DEPS_FILE, LIVE, dependents_closure, docker, save_json

LISTEN, ESTABLISHED = "0A", "01"   # socket states as written in /proc/net/tcp


def hex_to_ip(h):
    """/proc/net/tcp stores IPv4 as little-endian hex: '0100007F' -> '127.0.0.1'."""
    return ".".join(str(int(h[i:i + 2], 16)) for i in (6, 4, 2, 0))


def parse_proc_net_tcp(text):
    """Return a list of (local_ip, local_port, remote_ip, remote_port, state)."""
    conns = []
    for line in text.splitlines()[1:]:          # first line is the header
        parts = line.split()
        if len(parts) < 4 or ":" not in parts[1]:
            continue
        lip, lport = parts[1].split(":")
        rip, rport = parts[2].split(":")
        conns.append((hex_to_ip(lip), int(lport, 16), hex_to_ip(rip), int(rport, 16), parts[3]))
    return conns


def inspect(container):
    ok, out = docker("inspect", container)
    if not ok:
        return None
    try:
        return json.loads(out)[0]
    except (json.JSONDecodeError, IndexError):
        return None


def discover(cfg, samples=6):
    services, net = cfg["services"], cfg["network"]
    LIVE.event("info", "Mapping services: reading container metadata ...")

    ip_to_svc, info = {}, {}
    for name, s in services.items():
        data = inspect(s["container"])
        if not data:
            LIVE.event("warn", f"  {s['container']} not found - is the sandbox running?")
            continue
        labels = data["Config"].get("Labels") or {}
        ip = (data["NetworkSettings"].get("Networks") or {}).get(net, {}).get("IPAddress")
        if ip:
            ip_to_svc[ip] = name
        declared = [d.split(":")[0] for d in labels.get("com.docker.compose.depends_on", "").split(",") if d]
        info[name] = {"running": data["State"]["Running"], "image": data["Config"]["Image"], "declared": declared}

    # Sample live sockets a few times (short-lived connections come and go).
    LIVE.event("info", f"Sniffing live TCP connections ({samples} samples) ...")
    listen = {n: set() for n in services}
    established = []
    for _ in range(samples):
        for name in info:
            ok, out = docker("exec", services[name]["container"], "cat", "/proc/net/tcp", timeout=5)
            if not ok:
                continue
            for lip, lport, rip, rport, state in parse_proc_net_tcp(out):
                if state == LISTEN:
                    listen[name].add(lport)
                elif state == ESTABLISHED and ip_to_svc.get(rip) not in (None, name):
                    established.append((name, lport, ip_to_svc[rip]))
        time.sleep(0.5)

    observed = set()
    for name, lport, other in established:
        # If our side of the socket is one of our listening ports, `other` called us.
        observed.add((other, name) if lport in listen[name] else (name, other))

    edges = {}
    for name, i in info.items():
        for d in i["declared"]:
            edges.setdefault((name, d), set()).add("declared")
    for e in observed:
        edges.setdefault(e, set()).add("observed")
    for a, b in cfg.get("manual_edges", []):
        edges.setdefault((a, b), set()).add("manual")

    graph = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "app": cfg.get("app_name"),
             "repo": cfg.get("app_repo"), "network": net, "services": {}, "edges": [], "data_flows": []}
    for name, s in services.items():
        graph["services"][name] = {
            "container": s["container"], "role": s.get("role", "service"), "stateful": s.get("stateful", False),
            "running": info.get(name, {}).get("running", False), "image": info.get(name, {}).get("image"),
            "listen_ports": sorted(listen[name]),
            "depends_on": sorted({b for (a, b) in edges if a == name}),
            "used_by": sorted({a for (a, b) in edges if b == name}),
        }
    graph["edges"] = [{"from": a, "to": b, "evidence": sorted(ev)} for (a, b), ev in sorted(edges.items())]

    # Level = distance from the user-facing roots; used to lay out the dashboard graph.
    levels = {n: 0 for n in services}
    for _ in range(len(services)):
        for a, b in edges:
            levels[b] = max(levels[b], levels[a] + 1)
    for name, svc in graph["services"].items():
        svc["level"] = levels[name]
        svc["blast_radius"] = sorted(dependents_closure(graph, name))

    # Data flows: every path from a root (nothing depends on it) down to a sink.
    def walk(node, path):
        deps = graph["services"][node]["depends_on"]
        if not deps:
            graph["data_flows"].append(" -> ".join(path))
        for d in deps:
            if d not in path:
                walk(d, path + [d])
    for name, svc in graph["services"].items():
        if not svc["used_by"]:
            walk(name, [name])

    save_json(DEPS_FILE, graph)
    LIVE.set(graph=graph)
    for e in graph["edges"]:
        LIVE.event("ok", f"  {e['from']:>7} -> {e['to']:<7} evidence: {', '.join(e['evidence'])}")
    for flow in graph["data_flows"]:
        LIVE.event("info", f"  flow: {flow}")
    return graph
