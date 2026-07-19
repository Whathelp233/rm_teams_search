import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "tactical_profiles.py"
SPEC = importlib.util.spec_from_file_location("tactical_profiles", SCRIPT)
tactics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tactics)


class TacticalProfileTest(unittest.TestCase):
    def test_blue_coordinates_rotate_to_own_side(self):
        self.assertEqual(tactics.own_point(25, 12, "蓝"), (3, 3))
        self.assertEqual(tactics.own_point(3, 3, "红"), (3, 3))

    def test_lane_names_use_field_landmarks_instead_of_coordinates(self):
        self.assertEqual(tactics.lane_zone(2), "公路区与公路隧道侧")
        self.assertEqual(tactics.lane_zone(7.5), "中央高地正面")
        self.assertEqual(tactics.lane_zone(13), "梯形高地与相邻隧道侧")

    def test_wilson_interval_contains_observed_rate(self):
        low, high = tactics.wilson(8, 10)
        self.assertLess(low, .8)
        self.assertGreater(high, .8)

    def test_core_mode_takes_precedence_over_side_modifier(self):
        split = {"红": {"eligible": 10, "rate": .9}, "蓝": {"eligible": 10, "rate": .6}}
        self.assertEqual(tactics.classification(15, 20, 6, .75, (.6, .84), split), "核心模式")

    def test_low_rate_side_difference_does_not_become_preference(self):
        split = {"红": {"eligible": 10, "rate": .3}, "蓝": {"eligible": 10, "rate": 0}}
        self.assertEqual(tactics.classification(3, 20, 2, .15, (.07, .28), split), "变化模式")


if __name__ == "__main__":
    unittest.main()
