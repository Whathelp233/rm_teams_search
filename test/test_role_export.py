import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "export_role_data.py"
SPEC = importlib.util.spec_from_file_location("role_export", SCRIPT)
role_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(role_export)


class RoleExportTest(unittest.TestCase):
    def test_summary_keeps_full_frames_but_trims_stability_window(self):
        frames = []
        for second in range(31):
            hp = 0 if 15 <= second < 18 else 100
            frames.append([second, hp, 100, min(28, second / 2), 5, 0, 0, 20, 0, 100, 0, 0, 0, 0, 100, 20, 0])
        summary = role_export.game_summary(frames, [], {"duration_sec": 30, "side": "红"})
        self.assertEqual(summary["tracked_seconds"], 31)
        self.assertEqual(summary["analysis_seconds"], 11)
        self.assertEqual(summary["alive_seconds"], 8)
        self.assertEqual(summary["deaths"], 1)
        self.assertEqual(summary["recoveries"], 1)
        self.assertEqual(summary["first_death_sec"], 15.0)

    def test_received_damage_keeps_combat_penalty_and_collision_separate(self):
        frame = [10, 100, 100, 2, 2, 0, 0, 20, 0, 100, 0, 0, 0, 0, 100, 20, 0]
        events = [
            [10, "受击", "17mm", -20, None, None, None],
            [10, "受击", "判罚", -30, None, None, None],
            [10, "受击", "撞击", -2, None, None, None],
        ]
        summary = role_export.game_summary([frame], events, {"duration_sec": 30, "side": "红"})
        self.assertEqual(summary["combat_damage_received"], 20.0)
        self.assertEqual(summary["damage_received"], {"17mm": 20.0, "判罚": 30.0, "撞击": 2.0})


if __name__ == "__main__":
    unittest.main()
