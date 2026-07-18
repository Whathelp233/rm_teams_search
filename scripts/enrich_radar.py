#!/usr/bin/env python3
"""Add auditable radar counter-UAV facts from the raw RMUC event database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import median


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../sql/rmuc_2026_region_dataset.sqlite"))
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    return parser.parse_args()


def compact_write(path: Path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main():
    args = parse_args()
    index_path = args.data / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    slugs = {item["team"]: item["slug"] for item in index["teams"]}
    events = defaultdict(list)

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT e.game_id,e.时刻秒 second,e.学校名 countered_team,e.阵营 countered_side,
               e.备注,m.红方学校 red_team,m.蓝方学校 blue_team
          FROM events e JOIN matches m USING(game_id)
         WHERE e.事件类型='雷达反制UAV'
         ORDER BY e.game_id,e.时刻秒
        """
    )
    for row in rows:
        counter_side = (row["备注"] or "").replace("反制方=", "")
        if counter_side not in ("红", "蓝"):
            continue
        counter_team = row["red_team"] if counter_side == "红" else row["blue_team"]
        countered_team = row["countered_team"]
        fact = {
            "game_id": row["game_id"],
            "second": row["second"],
            "counter_team": counter_team,
            "countered_team": countered_team,
        }
        events[counter_team].append({**fact, "role": "发起反制", "opponent": countered_team})
        events[countered_team].append({**fact, "role": "己方空中被反制", "opponent": counter_team})
    connection.close()

    for team, slug in slugs.items():
        path = args.data / "teams" / f"{slug}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        facts = events.get(team, [])
        uses = [item for item in facts if item["role"] == "发起反制"]
        received = [item for item in facts if item["role"] == "己方空中被反制"]
        games = max(1, int(payload["summary"]["games"]))
        use_seconds = [float(item["second"]) for item in uses]
        payload["radar_analysis"] = {
            "source_event": "雷达反制UAV",
            "counter_uses": len(uses),
            "counter_use_games": len({item["game_id"] for item in uses}),
            "counter_use_game_pct": round(len({item["game_id"] for item in uses}) * 100 / games, 1),
            "median_counter_sec": round(median(use_seconds), 1) if use_seconds else None,
            "early_counter_pct": round(sum(value <= 90 for value in use_seconds) * 100 / len(use_seconds), 1) if use_seconds else None,
            "countered_events": len(received),
            "countered_games": len({item["game_id"] for item in received}),
            "events": facts,
            "available_fields": ["反制方", "被反制方", "触发时刻", "对局"],
            "unavailable_fields": ["雷达标记进度", "双倍易伤触发", "加密等级", "密钥解析结果"],
        }
        compact_write(path, payload)

    print(f"enriched {len(slugs)} teams with {sum(len(items) for items in events.values()) // 2} radar events")


if __name__ == "__main__":
    main()
