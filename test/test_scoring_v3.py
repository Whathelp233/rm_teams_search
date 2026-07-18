import importlib.util
import math
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "recalculate_scores_v3.py"
SPEC = importlib.util.spec_from_file_location("scoring_v3", SCRIPT)
scoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scoring)


class ScoringV3Test(unittest.TestCase):
    def test_every_weight_set_sums_to_one(self):
        self.assertTrue(math.isclose(sum(scoring.DIMENSION_WEIGHTS.values()), 1.0))
        for weights in scoring.COMPONENT_WEIGHTS.values():
            self.assertTrue(math.isclose(sum(weights.values()), 1.0))

    def test_percentile_uses_shared_midrank_for_ties(self):
        self.assertEqual(scoring.percentile([1.0, 2.0, 2.0, 4.0], 2.0), 50.0)

    def test_small_samples_shrink_toward_neutral(self):
        self.assertEqual(scoring.shrink(90.0, 0), 50.0)
        self.assertAlmostEqual(scoring.shrink(90.0, 6), 70.0)
        self.assertGreater(scoring.shrink(90.0, 20), 70.0)

    def test_missing_component_is_neutral_not_zero(self):
        result = scoring.analysis(
            {"a": {"metric": None}, "b": {"metric": 3.0}},
            {"metric": 1.0},
            {"a": 0, "b": 10},
            {"a": {"metric": 0}, "b": {"metric": 10}},
        )
        self.assertEqual(result["a"]["score"], 50.0)


if __name__ == "__main__":
    unittest.main()
