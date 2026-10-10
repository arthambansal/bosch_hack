"""Local dashboard state/control bridge. Approvals are recorded through the orchestrator's shared gate lock
(agentic.gate.submit_decision: validate + write under runs/gate.lock). Only that one pure function is imported,
never the orchestrator's LIVE singleton (a different process).
"""
import ipaddress
import json
import math
import os
import sys
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")                      # `npm run build` output; served on :8000 when it exists
_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
                ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json; charset=utf-8",
                ".woff2": "font/woff2", ".map": "application/json; charset=utf-8"}
ROOT = os.path.dirname(os.path.realpath(HERE))        # resolved once: a project folder reached through a symlink must not make every path check fail
STATE = os.path.join(ROOT, "runs", "live_state.json")
APPROVAL = os.path.join(ROOT, "runs", "approval.json")
STOP = os.path.join(ROOT, "STOP")
CONSUMER_PID = os.path.join(ROOT, "runs", "mystery_consumer.pid")
CONSUMER_LOG = os.path.join(ROOT, "runs", "mystery_consumer.log")
MAX_BODY = 4096
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

sys.path.insert(0, ROOT)
from agentic.gate import submit_decision  # noqa: E402  (pure file+lock logic, safe to import in this process)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def approval_error(payload, snapshot, now=None):
    """Read-only validation. It cannot atomically claim an orchestrator gate."""
    now = time.time() if now is None else now
    gate = snapshot.get("approval_request")
    if not isinstance(gate, dict) or not gate.get("gate_id"):
        return "no_pending"
    if snapshot.get("run_status") != "running" or snapshot.get("agent_active") != "human" or os.path.exists(STOP):
        return "no_pending"
    if payload.get("gate_id") != gate["gate_id"]:
        return "stale"
    expiry = gate.get("expires_at")
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or not math.isfinite(expiry) or now >= expiry:
        return "expired"
    result = snapshot.get("approval_result")
    if isinstance(result, dict) and result.get("gate_id") == gate["gate_id"]:
        return "no_pending"
    # Reject a decision already placed by another client; never overwrite it.
    try:
        with open(APPROVAL, encoding="utf-8") as stream:
            decision = json.load(stream)
        if isinstance(decision, dict) and decision.get("gate_id") == gate["gate_id"]:
            return "no_pending"
    except (OSError, ValueError):
        pass
    return None


def runs_root():
    return Path(ROOT) / "runs"


def run_started_at(name):
    # Runtime's name is authoritative local calendar time, not UTC or file mtime.
    if not isinstance(name, str) or not re.fullmatch(r"auto_\d{8}_\d{6}", name):
        raise ValueError("invalid run")
    try:
        return datetime.strptime(name[5:], "%Y%m%d_%H%M%S").isoformat()
    except ValueError:
        raise ValueError("invalid run") from None


def safe_run(name):
    run_started_at(name)
    root = runs_root()
    path = root / name
    if root.is_symlink() or root.resolve() != root.absolute() or path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("invalid run")
    return path


def safe_artifact(folder, filename):
    path = folder / filename
    if path.is_symlink() or path.resolve() != path.absolute():
        raise ValueError("invalid artifact")
    return path


def run_summaries():
    root = runs_root()
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError("invalid runs directory")
    if not root.exists():
        return []
    summaries = []
    for entry in root.iterdir():
        try:
            folder = safe_run(entry.name)
            if not folder.is_dir():
                continue
            try:
                has_report = safe_artifact(folder, "report.md").is_file()
            except ValueError:
                has_report = False
            summaries.append({"name": entry.name, "started_at": run_started_at(entry.name), "has_report": has_report})
        except ValueError:
            continue
    return sorted(summaries, key=lambda row: row["started_at"], reverse=True)


def mystery_consumer_alive():
    """Is `chaospilot.py mystery --wait` already running (from a terminal or from this button)?"""
    try:
        pid = int(Path(CONSUMER_PID).read_text().strip())
        os.kill(pid, 0)
        command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3).stdout
        return "chaospilot" in command and "mystery" in command          # a reused pid of some other program does not count
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def start_mystery_consumer():
    """Dashboard button: start the fixed command `chaospilot.py mystery --wait --up` (nothing from the browser is used in it)."""
    if mystery_consumer_alive():
        return 200, {"already_running": True}
    if os.path.exists(STOP):
        return 409, {"error": "stop_file_present"}
    try:
        os.makedirs(os.path.dirname(CONSUMER_PID), exist_ok=True)
        with open(CONSUMER_LOG, "ab") as log:
            process = subprocess.Popen([sys.executable, os.path.join(ROOT, "chaospilot.py"), "mystery", "--wait", "--up"],
                                       cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        Path(CONSUMER_PID).write_text(str(process.pid))
    except OSError:
        return 500, {"error": "mystery_start_failed"}
    return 202, {"started": True}


def mystery_submission(payload):
    """Serialize dashboard writers across processes; the consumer owns removal.

    No stale lock takeover: a crashed writer requires operator inspection.
    The consumer has no shared lifecycle lock, so this cannot claim a trial token.
    """
    root = runs_root()
    request = root / "mystery_request.json"
    lock = root / "dashboard_mystery.lock"
    acquired = False
    temporary = None
    try:
        root.mkdir(exist_ok=True)
        if root.is_symlink() or root.resolve() != root.absolute():
            return 500, {"error": "mystery_write_failed"}
        deadline = time.monotonic() + 5
        while not acquired:
            try:
                lock.mkdir()
                acquired = True
            except FileExistsError:
                if time.monotonic() >= deadline:
                    return 503, {"error": "mystery_busy"}
                time.sleep(0.02)
        snapshot = load_state()
        mystery = snapshot.get("mystery")
        if not isinstance(mystery, dict) or mystery.get("state") != "idle" or os.path.exists(STOP) or snapshot.get("run_status") in {"stopping", "stopped"}:
            return 409, {"error": "not_idle"}
        if os.path.lexists(request):
            return 409, {"error": "already_requested"}
        choice = payload.get("choice_id")
        menu = mystery.get("menu")
        valid = {item.get("id") for item in menu if isinstance(item, dict) and isinstance(item.get("id"), str)} if isinstance(menu, list) else set()
        if not isinstance(choice, str) or (choice != "random" and choice not in valid):
            return 400, {"error": "unknown_choice"}
        descriptor, temporary = tempfile.mkstemp(prefix=".mystery_request-", suffix=".tmp", dir=root)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"choice_id": choice, "by": "dashboard", "submitted_at": time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, request)
        temporary = None
        return 202, {"accepted": True}
    except OSError:
        return 500, {"error": "mystery_write_failed"}
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
        if acquired:
            try:
                lock.rmdir()
            except OSError:
                pass


class Handler(BaseHTTPRequestHandler):
    def json_reply(self, status, body):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(encoded)

    def local_mutation(self):
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
            host = urlsplit("http://" + self.headers.get("Host", ""))
            if host.hostname not in LOCAL_HOSTS or host.port != self.server.server_port or host.username or host.password or host.path or host.query or host.fragment:
                return False
            origin = urlsplit(self.headers.get("Origin", ""))
            allowed_ports = {5173, 4173, self.server.server_port}
            if origin.scheme != "http" or origin.hostname not in LOCAL_HOSTS or origin.port not in allowed_ports or origin.username or origin.password or origin.path or origin.query or origin.fragment:
                return False
            return self.headers.get("Sec-Fetch-Site") not in {"cross-site"}
        except ValueError:
            return False

    def local_history(self):
        # Same-origin GET fetches may omit Origin. When present, validate it
        # through the existing mutation policy; always validate peer and Host.
        if self.headers.get("Origin") is not None:
            return self.local_mutation()
        try:
            host = urlsplit("http://" + self.headers.get("Host", ""))
            return (ipaddress.ip_address(self.client_address[0]).is_loopback
                    and host.hostname in LOCAL_HOSTS and host.port == self.server.server_port
                    and not any((host.username, host.password, host.path, host.query, host.fragment))
                    and self.headers.get("Sec-Fetch-Site") != "cross-site")
        except ValueError:
            return False

    def read_payload(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.json_reply(400, {"error": "invalid_body"})
            return None
        if self.headers.get("Transfer-Encoding") or size < 0 or size > MAX_BODY:
            self.json_reply(413, {"error": "invalid_body"})
            return None
        if size and self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.json_reply(415, {"error": "json_required"})
            return None
        try:
            self.connection.settimeout(5)
            payload = json.loads(self.rfile.read(size)) if size else {}
            if not isinstance(payload, dict):
                raise ValueError("object required")
            return payload
        except (ValueError, UnicodeError):
            self.json_reply(400, {"error": "invalid_body"})
            return None
        except TimeoutError:
            self.json_reply(408, {"error": "body_timeout"})
            return None

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in {"/approve", "/stop", "/mystery", "/mystery/start"}:
            self.json_reply(404, {"error": "not_found"})
            return
        if not self.local_mutation():
            self.json_reply(403, {"error": "local_origin_required"})
            return
        payload = self.read_payload()
        if payload is None:
            return
        if path == "/mystery/start":
            if payload:
                self.json_reply(400, {"error": "empty_body_required"})
                return
            status, body = start_mystery_consumer()
            self.json_reply(status, body)
            return
        if path == "/mystery":
            status, body = mystery_submission(payload)
            self.json_reply(status, body)
            return
        if path == "/approve":
            if type(payload.get("approved")) is not bool:
                self.json_reply(400, {"error": "boolean_required"})
                return
            error = approval_error(payload, load_state())
            if error:
                self.json_reply(409, {"error": error})
                return
            # Validate again and write under the SAME lock the orchestrator uses to open, consume and close the gate.
            status, body = submit_decision(payload["gate_id"], payload["approved"], by="dashboard", live_file=STATE,
                                           approval_file=APPROVAL, lock_dir=os.path.join(os.path.dirname(APPROVAL), "gate.lock"))
            self.json_reply(status, body)
            return
        if payload:
            self.json_reply(400, {"error": "empty_stop_body_required"})
            return
        try:
            # Exclusive creation preserves any existing STOP file byte-for-byte.
            descriptor = os.open(STOP, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        except FileExistsError:
            pass
        except OSError:
            self.json_reply(500, {"error": "stop_write_failed"})
            return
        self.json_reply(202, {"stop_requested": True})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/state":
            self.json_reply(200, load_state())
            return
        if path == "/runs" or path.startswith("/runs/"):
            if not self.local_history():
                self.json_reply(403, {"error": "local_origin_required"})
                return
            try:
                if path == "/runs":
                    self.json_reply(200, run_summaries())
                    return
                # Decode before splitting; encoded slash/backslash/dots cannot
                # bypass name validation. A second encoded layer fails regex.
                parts = unquote(path).split("/")
                if len(parts) != 4 or parts[3] not in {"report", "events"}:
                    raise ValueError("invalid run path")
                folder = safe_run(parts[2])
                artifact = safe_artifact(folder, "report.md" if parts[3] == "report" else "events.log")
                text = artifact.read_text(encoding="utf-8")
                if parts[3] == "events":
                    self.json_reply(200, {"lines": text.splitlines()})
                else:
                    body = text.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
            except ValueError:
                self.json_reply(400, {"error": "invalid_run"})
            except FileNotFoundError:
                self.json_reply(404, {"error": "not_found"})
            except (OSError, UnicodeError):
                self.json_reply(500, {"error": "run_read_failed"})
            return
        if path.startswith("/assets/") and os.path.isfile(os.path.join(DIST, "index.html")):
            self.static_asset(path[len("/assets/"):])
            return
        if path != "/":
            self.json_reply(404, {"error": "not_found"})
            return
        built = os.path.join(DIST, "index.html")
        try:
            with open(built if os.path.isfile(built) else os.path.join(HERE, "index.html"), "rb") as stream:
                body = stream.read()
        except OSError:
            self.json_reply(404, {"error": "frontend_missing"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def static_asset(self, name):
        """Serve one built file from dashboard/dist/assets. Plain names only: no slashes, no dots-first, no traversal."""
        ext = os.path.splitext(name)[1].lower()
        if not _ASSET_NAME.match(name) or ".." in name or ext not in _ASSET_TYPES:
            self.json_reply(404, {"error": "not_found"})
            return
        folder = os.path.realpath(os.path.join(DIST, "assets"))
        target = os.path.realpath(os.path.join(folder, name))
        if os.path.dirname(target) != folder:
            self.json_reply(404, {"error": "not_found"})
            return
        try:
            with open(target, "rb") as stream:
                body = stream.read()
        except OSError:
            self.json_reply(404, {"error": "not_found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", _ASSET_TYPES[ext])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Dashboard: http://127.0.0.1:8000" + (" (built React app)" if os.path.isfile(os.path.join(DIST, "index.html")) else " - run `cd dashboard && npm ci && npm run build` first for the full UI") + "  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
