"""Fault injection. Every fault knows how to undo itself.

Safety: a fault can only target a container that (1) is listed in config.json AND (2) carries the
Docker Compose label of OUR sandbox project. Anything else is refused - even if an AI asks for it.
"""
from .common import LIVE, docker
from .probes import Spike

FAULT_TYPES = {
    "kill":      "crash the container (SIGKILL)",
    "pause":     "freeze the container (process hangs, sockets stay open)",
    "partition": "cut the container off the network",
    "latency":   "add network delay to every packet it sends",
    "spike":     "sudden traffic spike on the entry point",
}


class SafetyError(Exception):
    pass


class Fault:
    def __init__(self, ftype, target, cfg, prober=None, params=None):
        if ftype not in FAULT_TYPES:
            raise SafetyError(f"unknown fault type '{ftype}'")
        if target not in cfg["services"]:
            raise SafetyError(f"'{target}' is not a service in config.json")
        self.type, self.target, self.cfg, self.prober = ftype, target, cfg, prober
        self.container = cfg["services"][target]["container"]
        self.params = {**cfg.get("fault_params", {}).get(ftype, {}), **(params or {})}
        self.spike = None
        self.hidden = False      # mystery mode: never print which fault this is until the reveal
        self._check_sandbox()

    def _check_sandbox(self):
        ok, project = docker("inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', self.container)
        if not ok or project.strip() != self.cfg["project"]:
            raise SafetyError(f"{self.container} is not part of sandbox project '{self.cfg['project']}' - refusing")

    def describe(self):
        if self.hidden:
            return "[hidden fault]"
        extra = f" {self.params.get('delay_ms')}ms" if self.type == "latency" else ""
        extra = f" x{self.params.get('threads')} threads" if self.type == "spike" else extra
        return f"{self.type.upper()}{extra} -> {self.target}"

    def _netem(self, *tc_args):
        img = self.cfg.get("fault_params", {}).get("netem_image", "nicolaka/netshoot")
        if not docker("image", "inspect", img)[0]:
            return False, f"image {img} not pulled - run: docker pull {img}"
        # A throwaway helper container joins the target's network namespace and runs `tc`.
        return docker("run", "--rm", "--net", f"container:{self.container}", "--cap-add", "NET_ADMIN",
                      img, "tc", "qdisc", *tc_args, timeout=40)

    def apply(self):
        net = self.cfg["network"]
        if self.type == "kill":
            ok, out = docker("kill", self.container)
        elif self.type == "pause":
            ok, out = docker("pause", self.container)
        elif self.type == "partition":
            ok, out = docker("network", "disconnect", net, self.container)
        elif self.type == "latency":
            ok, out = self._netem("add", "dev", "eth0", "root", "netem", "delay", f"{self.params.get('delay_ms', 400)}ms")
        else:  # spike
            probe = next(p for p in self.cfg["probes"] if p["entry"] == self.target)
            self.spike = Spike(self.prober, probe, int(self.params.get("threads", 30)))
            self.spike.start()
            ok, out = True, "spike started"
        LIVE.event("inject" if ok else "warn", f"INJECT {self.describe()} {'OK' if ok else 'FAILED: ' + out}")
        return ok, out

    def undo(self):
        net = self.cfg["network"]
        if self.type == "kill":
            ok, out = docker("start", self.container)
        elif self.type == "pause":
            ok, out = docker("unpause", self.container)
        elif self.type == "partition":
            # --alias restores the service's DNS name, otherwise other services can't find it again
            ok, out = docker("network", "connect", "--alias", self.target, net, self.container)
        elif self.type == "latency":
            ok, out = self._netem("del", "dev", "eth0", "root")
        else:
            self.spike.stop()
            ok, out = True, "spike stopped"
        LIVE.event("restore" if ok else "warn", f"RESTORE {self.describe()} {'OK' if ok else 'FAILED: ' + out}")
        return ok, out


def panic(cfg):
    """Big red button: undo every possible fault on every sandbox container. Safe to run any time."""
    LIVE.event("guard", "PANIC: restoring every sandbox container")
    for name, s in cfg["services"].items():
        c = s["container"]
        docker("unpause", c)
        docker("start", c)
        docker("network", "connect", "--alias", name, cfg["network"], c)   # errors if already connected - fine
        try:
            Fault("latency", name, cfg)._netem("del", "dev", "eth0", "root")
        except Exception:
            pass
    LIVE.set(faulted=[])
    LIVE.event("restore", "PANIC restore finished - check `docker ps`")
