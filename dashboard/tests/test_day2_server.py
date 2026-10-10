"""Day 2 API tests use only temporary files and loopback sockets."""
import concurrent.futures
import http.client
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_server as controls
server = controls.server

class Day2ServerTests(unittest.TestCase):
    setUp = controls.ControlServerTests.setUp
    tearDown = controls.ControlServerTests.tearDown
    save_state = controls.ControlServerTests.save_state
    request = controls.ControlServerTests.request

    def idle(self):
        self.snapshot["mystery"] = {"state": "idle", "menu": [{"id": "M-kill-redis"}]}
        self.save_state()

    def get(self, path, origin=None, host=None):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if host is not None:
            headers["Host"] = host
        connection = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        result = response.status, response.getheader("Content-Type"), response.read().decode("utf-8")
        connection.close()
        return result

    def test_mystery_atomic_publication_and_valid_choices(self):
        self.idle()
        request = self.root / "runs/mystery_request.json"
        real_replace = os.replace
        def inspect(source, destination):
            self.assertFalse(request.exists())
            data = json.loads(Path(source).read_text(encoding="utf-8"))
            self.assertEqual(data["by"], "dashboard")
            self.assertIsInstance(data["submitted_at"], float)
            real_replace(source, destination)
        for choice in ("random", "M-kill-redis"):
            request.unlink(missing_ok=True)
            with patch.object(server.os, "replace", side_effect=inspect) as replace:
                self.assertEqual(self.request("/mystery", {"choice_id": choice}), (202, {"accepted": True}))
                replace.assert_called_once()
            self.assertEqual(json.loads(request.read_text())["choice_id"], choice)
            self.assertEqual(list((self.root / "runs").glob("*.tmp")), [])
            self.assertFalse((self.root / "runs/dashboard_mystery.lock").exists())

    def test_mystery_rejections_and_duplicate_preservation(self):
        self.assertEqual(self.request("/mystery", {"choice_id": "random"}), (409, {"error": "not_idle"}))
        self.idle()
        for choice in ("missing", None, [], 1):
            self.assertEqual(self.request("/mystery", {"choice_id": choice}), (400, {"error": "unknown_choice"}))
        self.assertEqual(self.request("/mystery", {"choice_id": "random"})[0], 202)
        target = self.root / "runs/mystery_request.json"
        original = target.read_bytes()
        self.assertEqual(self.request("/mystery", {"choice_id": "M-kill-redis"}), (409, {"error": "already_requested"}))
        self.assertEqual(target.read_bytes(), original)

    def test_concurrent_dashboard_writers_accept_only_one_request(self):
        self.idle()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: server.mystery_submission({"choice_id": "random"}), range(8)))
        self.assertEqual([status for status, _ in results].count(202), 1)
        self.assertEqual([status for status, _ in results].count(409), 7)

    def test_atomic_write_failure_cleans_temp_and_lock(self):
        self.idle()
        with patch.object(server.os, "replace", side_effect=OSError("test")):
            self.assertEqual(self.request("/mystery", {"choice_id": "random"})[0], 500)
        self.assertFalse((self.root / "runs/mystery_request.json").exists())
        self.assertEqual(list((self.root / "runs").glob("*.tmp")), [])
        self.assertFalse((self.root / "runs/dashboard_mystery.lock").exists())

    def test_mystery_preserves_security_and_stop(self):
        self.idle()
        for origin in (None, "https://example.com", "http://localhost:9999"):
            self.assertEqual(self.request("/mystery", origin=origin)[0], 403)
        self.assertEqual(self.request("/mystery", host="example.com:8000")[0], 403)
        fake = SimpleNamespace(client_address=("192.0.2.1", 42), headers={"Host": f"localhost:{self.http.server_port}", "Origin": "http://localhost:5173"}, server=self.http)
        self.assertFalse(server.Handler.local_mutation(fake))
        fake.headers.pop("Origin")
        self.assertFalse(server.Handler.local_history(fake))
        self.assertEqual(self.request("/stop")[0], 202)
        self.assertEqual(self.request("/mystery", {"choice_id": "random"}), (409, {"error": "not_idle"}))

    def test_runs_list_uses_name_timestamp_not_file_mtime(self):
        for name in ("auto_20261010_120000", "auto_20261011_010203", "auto_bad", "auto_20261310_120000", "manual"):
            (self.root / "runs" / name).mkdir()
        (self.root / "runs/auto_20261010_120000/report.md").write_text("# actual report")
        status, _, body = self.get("/runs")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [{"name": "auto_20261011_010203", "started_at": "2026-10-11T01:02:03", "has_report": False}, {"name": "auto_20261010_120000", "started_at": "2026-10-10T12:00:00", "has_report": True}])

    def test_actual_report_and_events_and_absent_files(self):
        folder = self.root / "runs/auto_20261010_120000"
        folder.mkdir()
        for kind in ("report", "events"):
            self.assertEqual(self.get(f"/runs/{folder.name}/{kind}")[0], 404)
        report = "# Actual report\n\nMeasured evidence.\n"
        (folder / "report.md").write_text(report, encoding="utf-8")
        (folder / "events.log").write_text("exact first\nexact second\n", encoding="utf-8")
        status, content_type, body = self.get(f"/runs/{folder.name}/report")
        self.assertEqual((status, body), (200, report))
        self.assertIn("text/markdown", content_type)
        self.assertEqual(json.loads(self.get(f"/runs/{folder.name}/events")[2]), {"lines": ["exact first", "exact second"]})

    def test_traversal_and_foreign_read_security(self):
        for name in ("..", "%2e%2e", "auto_20261010_120000%2f..", "auto_20261010_120000%5c..", "auto_20261010_120000\\..", "%252e%252e", "auto_20261010_120000/../outside"):
            self.assertEqual(self.get(f"/runs/{name}/report")[0], 400, name)
        self.assertEqual(self.get("/runs", origin="https://evil.example")[0], 403)
        self.assertEqual(self.get("/runs", host="evil.example:8000")[0], 403)

    def test_symlink_directory_and_artifacts_cannot_escape(self):
        folder = self.root / "runs/auto_20261010_120000"
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "report.md").write_text("secret")
        try:
            folder.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"OS does not allow symlink creation: {error}")
        self.assertEqual(self.get(f"/runs/{folder.name}/report")[0], 400)
        self.assertEqual(json.loads(self.get("/runs")[2]), [])
        folder.unlink()
        folder.mkdir()
        (folder / "report.md").symlink_to(outside / "report.md")
        (folder / "events.log").symlink_to(outside / "report.md")
        for kind in ("report", "events"):
            self.assertEqual(self.get(f"/runs/{folder.name}/{kind}")[0], 400)

    def test_link_validation_fails_closed_without_symlink_privilege(self):
        folder = self.root / "runs/auto_20261010_120000"
        folder.mkdir()
        with patch.object(server.Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                server.safe_run(folder.name)
            with self.assertRaises(ValueError):
                server.safe_artifact(folder, "report.md")

    def test_existing_body_limits_and_json_validation_apply_to_mystery(self):
        import io
        for headers, content, expected in (
            ({"Content-Length": "4097", "Content-Type": "application/json"}, b"", 413),
            ({"Content-Length": "2", "Content-Type": "text/plain"}, b"{}", 415),
            ({"Content-Length": "2", "Content-Type": "application/json"}, b"[]", 400),
            ({"Content-Length": "1", "Content-Type": "application/json"}, b"{", 400),
            ({"Content-Length": "-1"}, b"", 413),
        ):
            replies = []
            fake = SimpleNamespace(headers=headers, rfile=io.BytesIO(content), connection=SimpleNamespace(settimeout=lambda _: None), json_reply=lambda status, body: replies.append(status))
            self.assertIsNone(server.Handler.read_payload(fake))
            self.assertEqual(replies, [expected])

    def test_separate_dashboard_processes_do_not_overwrite_pending_request(self):
        import subprocess
        import sys
        self.idle()
        script = """import importlib.util,json,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('bridge',sys.argv[1])
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
bridge.ROOT=sys.argv[2];bridge.STATE=str(Path(sys.argv[2])/'runs/live_state.json');bridge.STOP=str(Path(sys.argv[2])/'STOP')
print(json.dumps(bridge.mystery_submission({'choice_id':'random'})))
"""
        processes = [subprocess.Popen([sys.executable, "-B", "-c", script, server.__file__, str(self.root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
        codes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            codes.append(json.loads(stdout)[0])
        self.assertEqual(sorted(codes), [202, 409, 409])
