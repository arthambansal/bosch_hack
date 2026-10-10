import json
import unittest
from pathlib import Path
from core.contract_v5 import validate_truth, validate_mystery, validate_memory, validate_fixes, validate_impact, validate_predictions, validate_plan_ranking

class FixtureTruthTests(unittest.TestCase):
    def test_permitted_fixture_truth_matches_authoritative_validator(self):
        directory = Path(__file__).resolve().parents[1] / "fixtures"
        for name in ("approval_pending", "completed_with_fixes", "gray_failure", "idle", "mystery_revealed"):
            with self.subTest(fixture=name):
                data = json.loads((directory / (name + ".json")).read_text(encoding="utf-8"))
                self.assertEqual(validate_truth(data["truth"]), [])

    def test_p1_fixture_shapes_use_authoritative_validators(self):
        directory = Path(__file__).resolve().parents[1] / "fixtures"
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(fixture=path.name):
                for key, validator in (("mystery", validate_mystery), ("memory", validate_memory), ("fixes", validate_fixes), ("impact", validate_impact), ("predictions", validate_predictions), ("plan_ranking", validate_plan_ranking)):
                    if data.get(key) is not None:
                        self.assertEqual(validator(data[key]), [], key)
