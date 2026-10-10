"""Notification tests: every HTTP request is mocked; no real Discord messages."""
import concurrent.futures
import contextlib
import inspect
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import notify as module

WEBHOOK = "https://discord.invalid/api/webhooks/test/secret-token"


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": WEBHOOK}, clear=True),
                        patch.object(module, "_LOCK", threading.Lock()),
                        patch.object(module, "_last_attempt", None),
                        patch.object(module.time, "monotonic", return_value=100),
                        patch.object(module.requests, "post", return_value=Mock(status_code=204))]
        self.environment, self.lock, self.last, self.clock, self.post = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)

    def test_exact_public_signature(self):
        signature = inspect.signature(module.notify)
        self.assertEqual(list(signature.parameters), ["kind", "title", "text", "fields"])
        for name in ("kind", "title", "text"):
            self.assertIs(signature.parameters[name].annotation, str)
            self.assertIs(signature.parameters[name].default, inspect.Parameter.empty)
        self.assertEqual(signature.parameters["fields"].annotation, dict | None)
        self.assertIsNone(signature.parameters["fields"].default)
        self.assertIs(signature.return_annotation, bool)

    def test_missing_empty_and_whitespace_webhook_are_silent(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            for value in (None, "", "   "):
                if value is None:
                    os.environ.pop("DISCORD_WEBHOOK_URL", None)
                else:
                    os.environ["DISCORD_WEBHOOK_URL"] = value
                self.assertIs(module.notify("report", "Report", "Ready"), False)
        self.post.assert_not_called()
        self.assertEqual(output.getvalue() + errors.getvalue(), "")

    def test_success_uses_readable_embed_timeout_and_no_mentions(self):
        self.assertIs(module.notify("report", "Report ready", "Actual report", {"run": "auto_test", "score": 0}), True)
        args, kwargs = self.post.call_args
        self.assertEqual(args, (WEBHOOK,))
        self.assertEqual(kwargs["timeout"], 3)
        self.assertIs(kwargs["allow_redirects"], False)
        self.assertEqual(kwargs["json"]["allowed_mentions"], {"parse": []})
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "Report ready")
        self.assertEqual(embed["description"], "Actual report")
        self.assertEqual(embed["fields"], [{"name": "Event kind", "value": "report", "inline": True}, {"name": "run", "value": "auto_test", "inline": False}, {"name": "score", "value": "0", "inline": False}])

    def test_only_http_2xx_is_success(self):
        for index, status in enumerate((200, 201, 204, 299, 199, 301, 400, 429, 500)):
            self.clock.return_value = 100 + index * 2
            self.post.return_value = Mock(status_code=status)
            self.assertIs(module.notify("report", "Title", "Text"), 200 <= status < 300)

    def test_network_and_timeout_fail_silently_without_secret_leakage(self):
        for index, error in enumerate((module.requests.Timeout(WEBHOOK), module.requests.ConnectionError(WEBHOOK), RuntimeError(WEBHOOK))):
            self.clock.return_value = 100 + index * 2
            self.post.side_effect = error
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), self.assertNoLogs():
                self.assertIs(module.notify("kill_switch", "Title", "Text"), False)
            self.assertEqual(output.getvalue() + errors.getvalue(), "")
        self.assertEqual(self.post.call_count, 3)

    def test_two_second_boundary_and_failed_attempts_are_rate_limited(self):
        self.post.return_value.status_code = 500
        self.assertFalse(module.notify("report", "Title", "Text"))
        self.clock.return_value = 101.999
        self.assertFalse(module.notify("gray_failure", "Title", "Text"))
        self.assertEqual(self.post.call_count, 1)
        self.clock.return_value = 102
        self.post.return_value.status_code = 204
        self.assertTrue(module.notify("report", "Title", "Text"))
        self.assertEqual(self.post.call_count, 2)

    def test_concurrent_calls_are_dropped_not_queued(self):
        started, finish = threading.Event(), threading.Event()
        def send(*args, **kwargs):
            started.set()
            if not finish.wait(3):
                raise AssertionError("Test release timed out")
            return Mock(status_code=204)
        self.post.side_effect = send
        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as pool:
            first = pool.submit(module.notify, "report", "Title", "Text")
            self.assertTrue(started.wait(2))
            try:
                # Even after two seconds an in-flight send cannot run in parallel.
                self.clock.return_value = 103
                extra = [pool.submit(module.notify, "report", "Title", "Text") for _ in range(8)]
                self.assertEqual([future.result(timeout=1) for future in extra], [False] * 8)
            finally:
                finish.set()
            self.assertTrue(first.result(timeout=2))
        self.assertEqual(self.post.call_count, 1)

    def test_supported_event_colours_and_optional_fields(self):
        expected = {"kill_switch": 0xE74C3C, "gray_failure": 0xE74C3C, "fix_verified": 0x2ECC71, "fix_rolled_back": 0xE67E22, "fix_rollback_failed": 0xE74C3C, "root_cause": 0x3498DB, "mystery_reveal": 0x3498DB, "report": 0x3498DB}
        for index, (kind, color) in enumerate(expected.items()):
            self.clock.return_value = 100 + index * 2
            self.assertTrue(module.notify(kind, "Title", "Text"))
            embed = self.post.call_args.kwargs["json"]["embeds"][0]
            self.assertEqual(embed["color"], color)
            self.assertEqual(embed["fields"], [{"name": "Event kind", "value": kind, "inline": True}])

    def test_rollback_failed_runtime_payload_and_transport_safeguards(self):
        title = "Rollback FAILED: redis-durable"
        text = "redis-durable made E1 worse but docker compose could not undo it. Check the sandbox by hand."
        self.assertTrue(module.notify("fix_rollback_failed", title, text, {"fix": "redis-durable", "experiment": "E1"}))
        self.post.assert_called_once_with(WEBHOOK, json={
            "embeds": [{"title": title, "description": text, "color": 0xE74C3C,
                        "fields": [{"name": "Event kind", "value": "fix_rollback_failed", "inline": True},
                                   {"name": "fix", "value": "redis-durable", "inline": False},
                                   {"name": "experiment", "value": "E1", "inline": False}]}],
            "allowed_mentions": {"parse": []}}, timeout=3, allow_redirects=False)

    def test_rollback_failed_without_webhook_is_silent(self):
        for value in (None, "", "   "):
            with self.subTest(webhook=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ["DISCORD_WEBHOOK_URL"] = value
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), self.assertNoLogs():
                    self.assertFalse(module.notify("fix_rollback_failed", "Rollback FAILED: fix", "Could not undo"))
                self.assertEqual(output.getvalue() + errors.getvalue(), "")
        self.post.assert_not_called()

    def test_rollback_failed_timeout_and_non_2xx_are_silent_without_retry(self):
        outcomes = [module.requests.Timeout(WEBHOOK), 199, 301, 400, 429, 500]
        for index, outcome in enumerate(outcomes):
            with self.subTest(outcome=type(outcome).__name__ if isinstance(outcome, Exception) else outcome):
                self.clock.return_value = 100 + index * 2
                self.post.reset_mock()
                self.post.side_effect = outcome if isinstance(outcome, Exception) else None
                if not isinstance(outcome, Exception):
                    self.post.return_value = Mock(status_code=outcome)
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), self.assertNoLogs():
                    self.assertFalse(module.notify("fix_rollback_failed", "Rollback FAILED: fix", "Could not undo"))
                self.post.assert_called_once()
                self.assertEqual(self.post.call_args.kwargs["timeout"], 3)
                self.assertIs(self.post.call_args.kwargs["allow_redirects"], False)
                self.assertEqual(self.post.call_args.kwargs["json"]["allowed_mentions"], {"parse": []})
                self.assertEqual(output.getvalue() + errors.getvalue(), "")

    def test_rollback_failed_redacts_configured_webhook_in_every_content_position(self):
        self.assertTrue(module.notify("fix_rollback_failed", f"Rollback FAILED: {WEBHOOK}",
                                      f"Could not undo; {WEBHOOK}", {WEBHOOK: WEBHOOK}))
        embed = self.post.call_args.kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "Rollback FAILED: [redacted]")
        self.assertEqual(embed["description"], "Could not undo; [redacted]")
        self.assertEqual(embed["fields"][1], {"name": "[redacted]", "value": "[redacted]", "inline": False})
        payload = json.dumps(embed)
        self.assertNotIn(WEBHOOK, payload)
        self.assertNotIn("secret-token", payload)

    def test_rollback_failed_shares_rate_limit_in_both_directions(self):
        self.assertTrue(module.notify("report", "Report", "Ready"))
        self.clock.return_value = 101.999
        self.assertFalse(module.notify("fix_rollback_failed", "Rollback FAILED: fix", "Could not undo"))
        self.assertEqual(self.post.call_count, 1)
        self.clock.return_value = 102
        self.post.side_effect = module.requests.Timeout(WEBHOOK)
        self.assertFalse(module.notify("fix_rollback_failed", "Rollback FAILED: fix", "Could not undo"))
        self.assertEqual(self.post.call_count, 2)
        self.clock.return_value = 103.999
        self.assertFalse(module.notify("gray_failure", "Gray failure", "Detected"))
        self.assertEqual(self.post.call_count, 2)
        self.clock.return_value = 104
        self.post.side_effect = None
        self.assertTrue(module.notify("gray_failure", "Gray failure", "Detected"))
        self.assertEqual(self.post.call_count, 3)

    def test_webhook_is_redacted_from_embed_content(self):
        self.assertTrue(module.notify("report", WEBHOOK, WEBHOOK, {WEBHOOK: WEBHOOK}))
        payload = json.dumps(self.post.call_args.kwargs["json"])
        self.assertNotIn(WEBHOOK, payload)
        self.assertNotIn("secret-token", payload)
        self.assertIn("[redacted]", payload)

    def test_invalid_inputs_and_serialization_failures_do_not_raise(self):
        class BadText:
            def __str__(self):
                raise RuntimeError(WEBHOOK)
        for kind, title, fields in (("unsupported", "Title", None), ([], "Title", None), ("report", BadText(), None), ("report", "Title", [])):
            self.assertFalse(module.notify(kind, title, "Text", fields))
        self.post.assert_not_called()

    def test_empty_fields_remain_nonempty_and_within_budget(self):
        self.assertTrue(module.notify("report", "T" * 256, "D" * 4096, {"N" * 256: "V" * 1024, "": ""}))
        embed = self.post.call_args.kwargs["json"]["embeds"][0]
        for field in embed["fields"]:
            self.assertTrue(field["name"])
            self.assertTrue(field["value"])
        self.assertLessEqual(len(embed["title"]) + len(embed["description"]) + sum(len(field["name"]) + len(field["value"]) for field in embed["fields"]), 6000)

    def test_embed_limits_and_fields_are_bounded(self):
        self.assertTrue(module.notify("report", "T" * 1000, "D" * 10000, {str(index): "V" * 2000 for index in range(100)}))
        embed = self.post.call_args.kwargs["json"]["embeds"][0]
        self.assertLessEqual(len(embed["title"]), 256)
        self.assertLessEqual(len(embed["description"]), 4096)
        self.assertLessEqual(len(embed["fields"]), 25)
        total = len(embed["title"]) + len(embed["description"])
        for field in embed["fields"]:
            self.assertTrue(0 < len(field["name"]) <= 256)
            self.assertTrue(0 < len(field["value"]) <= 1024)
            total += len(field["name"]) + len(field["value"])
        self.assertLessEqual(total, 6000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
