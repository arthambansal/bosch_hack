import json
import unittest
from pathlib import Path
from core.contract_v5 import validate_truth

class FixtureTruthTests(unittest.TestCase):
    def test_permitted_fixture_truth_matches_authoritative_validator(self):
        directory = Path(__file__).resolve().parents[1] / "fixtures"
        for name in ("approval_pending", "completed_with_fixes", "gray_failure", "idle", "mystery_revealed"):
            with self.subTest(fixture=name):
                data = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(validate_truth(data["truth"]), [])
