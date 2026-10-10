
"""Tests for LLM-assisted patch suggestions."""

import unittest
from unittest.mock import patch

from core.patches import suggest_patches


class TestSuggestPatches(unittest.TestCase):

    def test_no_evidence_returns_empty_list(self):
        self.assertEqual(suggest_patches({}, []), [])

    def test_irrelevant_loss_returns_empty_list(self):
        investigations = {
            "E1": {"root_cause": "CPU saturation", "summary": "High CPU"}
        }
        results = [{"id": "E1", "delivery": {"lost": 0}}]
        self.assertEqual(suggest_patches(investigations, results), [])

    @patch("core.patches.ask_json")
    def test_llm_suggestion_is_proposed_not_applied(self, mock_ask_json):
        mock_ask_json.return_value = (
            {
                "title": "Improve Redis retry handling",
                "why": "Experiment E1 observed delivery loss.",
                "diff": None,
            },
            "openai",
        )

        investigations = {
            "E1": {
                "root_cause": "Redis connection interruption",
                "summary": "Retry handling may be insufficient",
            }
        }
        results = [{"id": "E1", "delivery": {"lost": 3}}]

        suggestions = suggest_patches(investigations, results)

        self.assertEqual(len(suggestions), 1)
        suggestion = suggestions[0]
        self.assertEqual(suggestion["status"], "proposed")
        self.assertEqual(suggestion["kind"], "code_suggestion")
        self.assertEqual(suggestion["for"], ["E1"])
        self.assertIsNone(suggestion["diff"])
        mock_ask_json.assert_called_once()

    @patch("core.patches.ask_json")
    def test_llm_failure_uses_safe_fallback(self, mock_ask_json):
        mock_ask_json.return_value = (None, "none")

        investigations = {
            "E2": {"root_cause": "Redis queue connection failure"}
        }
        results = [{"id": "E2", "delivery": {"lost": 2}}]

        suggestions = suggest_patches(investigations, results)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["status"], "proposed")
        self.assertIsNone(suggestions[0]["diff"])
        self.assertIn("E2", suggestions[0]["why"])

    @patch("core.patches.ask_json")
    def test_valid_unified_diff_can_be_returned(self, mock_ask_json):
        diff = (
            "--- a/worker.py\n"
            "+++ b/worker.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old_retry()\n"
            "+new_retry()\n"
        )
        mock_ask_json.return_value = (
            {
                "title": "Improve retry handling",
                "why": "The supplied evidence supports reviewing retries.",
                "diff": diff,
            },
            "openai",
        )

        investigations = {
            "E3": {"root_cause": "Redis retry connection issue"}
        }
        results = [{"id": "E3", "delivery": {"lost": 1}}]

        suggestions = suggest_patches(investigations, results)

        self.assertEqual(suggestions[0]["diff"], diff)
        self.assertEqual(suggestions[0]["status"], "proposed")


if __name__ == "__main__":
    unittest.main()
    print("ALL CHECKS PASSED")
