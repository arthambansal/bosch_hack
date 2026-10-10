"""Dashboard HTTP tests. All files live in a temporary sandbox; no Docker calls."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import HTTPServer

spec = importlib.util.spec_from_file_location("dashboard_control_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class ControlServerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="chaospilot-dashboard-test-")
        self.root = Path(self.folder.name)
        (self.root / "runs").mkdir()
        self.paths = patch.multiple(server, ROOT=str(self.root), STATE=str(self.root / "runs/live_state.json"), APPROVAL=str(self.root / "runs/approval.json"), STOP=str(self.root / "STOP"))
        self.paths.start()
        self.snapshot = {"phase": "running", "run_status": "running", "agent_active": "human", "run_dir": str(self.root / "runs/run-test"),
                         "approval_request": {"gate_id": "current-gate", "id": "E6", "name": "Combined failure", "question": "Approve?", "reason": "Test", "steps": [], "created_at": time.time()-1, "expires_at": time.time()+60, "timeout_s": 61}}
        self.save_state()
        self.http = HTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.thread.join(timeout=3)
        self.http.server_close()
        self.paths.stop()
        self.folder.cleanup()

    def save_state(self):
        Path(server.STATE).write_text(json.dumps(self.snapshot), encoding="utf-8")

    def request(self, path, payload=None, origin="http://localhost:5173", host=None, method="POST"):
        headers = {"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"}
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        connection = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        connection.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=headers)
        response = connection.getresponse()
        status, result = response.status, json.loads(response.read())
        connection.close()
        return status, result

    def test_missing_pending_gate(self):
        self.snapshot["approval_request"] = None
        self.save_state()
        self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": True}), (409, {"error": "no_pending"}))
        self.assertFalse(Path(server.APPROVAL).exists())

    def test_stale_token(self):
        self.assertEqual(self.request("/approve", {"gate_id": "old-gate", "approved": True}), (409, {"error": "stale"}))
        self.assertFalse(Path(server.APPROVAL).exists())

    def test_expired_gate(self):
        self.snapshot["approval_request"]["expires_at"] = time.time()-1
        self.save_state()
        self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": False}), (409, {"error": "expired"}))
        self.assertFalse(Path(server.APPROVAL).exists())

    def test_valid_approval_and_denial_fail_closed_without_shared_sync(self):
        for approved in (True, False):
            with self.subTest(approved=approved):
                self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": approved}), (503, {"error": "gate_sync_unavailable"}))
                self.assertFalse(Path(server.APPROVAL).exists())

    def test_repeated_valid_submissions_never_write(self):
        for approved in (True, True, False):
            self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": approved})[0], 503)
        self.assertFalse(Path(server.APPROVAL).exists())

    def test_existing_decision_is_never_overwritten(self):
        original = json.dumps({"gate_id": "current-gate", "approved": False, "by": "discord", "submitted_at": time.time()})
        Path(server.APPROVAL).write_text(original, encoding="utf-8")
        self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": True}), (409, {"error": "no_pending"}))
        self.assertEqual(Path(server.APPROVAL).read_text(encoding="utf-8"), original)

    def test_boolean_is_required(self):
        self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": "true"})[0], 400)
        self.assertFalse(Path(server.APPROVAL).exists())

    def test_stop_is_idempotent_and_acknowledges_only_the_request(self):
        self.assertEqual(self.request("/stop"), (202, {"stop_requested": True}))
        original_stat = Path(server.STOP).stat()
        self.assertEqual(self.request("/stop"), (202, {"stop_requested": True}))
        self.assertEqual(Path(server.STOP).stat().st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(json.loads(Path(server.STATE).read_text())["run_status"], "running")

    def test_existing_stop_contents_are_preserved(self):
        Path(server.STOP).write_text("operator stop", encoding="utf-8")
        self.assertEqual(self.request("/stop"), (202, {"stop_requested": True}))
        self.assertEqual(Path(server.STOP).read_text(encoding="utf-8"), "operator stop")

    def test_stop_blocks_approvals(self):
        self.request("/stop")
        self.assertEqual(self.request("/approve", {"gate_id": "current-gate", "approved": True}), (409, {"error": "no_pending"}))

    def test_foreign_origin_and_host_cannot_mutate(self):
        self.assertEqual(self.request("/stop", origin="https://example.com")[0], 403)
        self.assertEqual(self.request("/stop", host="example.com:8000")[0], 403)
        self.assertEqual(self.request("/stop", origin=None)[0], 403)
        self.assertFalse(Path(server.STOP).exists())

    def test_state_is_not_augmented_or_mutated(self):
        self.assertEqual(self.request("/state", method="GET"), (200, self.snapshot))

    @unittest.skip("Approval acceptance requires an orchestrator-owned shared claim/closure helper; none exists in cab07d5")
    def test_valid_decision_is_atomically_accepted(self):
        pass


if __name__ == "__main__":
    unittest.main()
