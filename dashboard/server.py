"""Local dashboard state/control bridge. Approval acceptance fails closed until
Artham supplies a shared cross-process gate submission/closure primitive.
No orchestrator module is imported: its LIVE singleton would be a different process.
"""
import ipaddress
import json
import math
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, "runs", "live_state.json")
APPROVAL = os.path.join(ROOT, "runs", "approval.json")
STOP = os.path.join(ROOT, "STOP")
MAX_BODY = 4096
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


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
        if path not in {"/approve", "/stop"}:
            self.json_reply(404, {"error": "not_found"})
            return
        if not self.local_mutation():
            self.json_reply(403, {"error": "local_origin_required"})
            return
        payload = self.read_payload()
        if payload is None:
            return
        if path == "/approve":
            if type(payload.get("approved")) is not bool:
                self.json_reply(400, {"error": "boolean_required"})
                return
            error = approval_error(payload, load_state())
            if error:
                self.json_reply(409, {"error": error})
                return
            # No dashboard-only lock can coordinate gate.py's consumption,
            # timeout, terminal decision, and close operations. DO NOT WRITE.
            self.json_reply(503, {"error": "gate_sync_unavailable"})
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
        if path != "/":
            self.json_reply(404, {"error": "not_found"})
            return
        try:
            with open(os.path.join(HERE, "index.html"), "rb") as stream:
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

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Dashboard backend: http://127.0.0.1:8000 (React uses Vite; Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
