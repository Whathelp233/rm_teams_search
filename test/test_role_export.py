import importlib.util
import sqlite3
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "export_role_data.py"
SPEC = importlib.util.spec_from_file_location("role_export", SCRIPT)
role_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(role_export)


class RoleExportTest(unittest.TestCase):
    def test_damage_estimate_distributes_each_hit_once_and_keeps_confidence(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE timeseries(game_id INT, 阵营 TEXT, 学校名 TEXT);
            CREATE TABLE events(game_id INT, 时刻秒 REAL, 事件类型 TEXT, robot_id INT,
              机器人类型 TEXT, 阵营 TEXT, 类别 TEXT, 数值 REAL);
            INSERT INTO timeseries VALUES (1,'红','红队'),(1,'蓝','蓝队');
            INSERT INTO events VALUES
              (1,10,'发弹',3,'步兵3','红','17mm',NULL),
              (1,10,'发弹',3,'步兵3','红','17mm',NULL),
              (1,10,'发弹',7,'哨兵','红','17mm',NULL),
              (1,10,'受击',103,'步兵3','蓝','17mm',-30),
              (1,20,'发弹',1,'英雄','红','42mm',NULL),
              (1,20,'受击',110,'基地','蓝','42mm',-200);
        """)
        result = role_export.estimate_damage_attribution(connection)
        infantry = result[("红队", 1, "步兵3")]
        sentry = result[("红队", 1, "哨兵")]
        hero = result[("红队", 1, "英雄")]
        self.assertAlmostEqual(infantry[0][1] + sentry[0][1], 30.0)
        self.assertEqual(infantry[0][1], 20.0)
        self.assertEqual(sentry[0][1], 10.0)
        self.assertEqual(infantry[0][5], 50.0)
        self.assertEqual(hero[0][1], 200.0)
        self.assertEqual(hero[0][3], "基地")
        self.assertEqual(hero[0][5], 98.0)

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
        self.assertEqual(summary["estimated_damage_dealt"], 0.0)


if __name__ == "__main__":
    unittest.main()
