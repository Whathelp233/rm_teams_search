#!/usr/bin/env python3
"""Validate replay v3 evidence, compact schema, coverage and payload budgets."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GAMES = ROOT / "public" / "data" / "games"
SOURCE = ROOT.parent / "sql" / "rmuc_2026_region_dataset.sqlite"


def objects(rows, columns):
    return [dict(zip(columns, row)) for row in rows]


def main():
    paths = sorted(GAMES.glob("*.json"))
    assert len(paths) == 613, f"expected 613 games, found {len(paths)}"
    sizes, assembly, hits = [], Counter(), Counter()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == "3.0.0"
        assert payload["source_cadence_hz"] == 1
        assert len(payload["facilities"]) == 4
        assert payload["frame_columns"][:11] == ["robot", "x", "y", "hp", "max_hp", "power", "heat17", "heat42", "shots17", "shots42", "valid"]
        assert {"z", "yaw", "heat17_limit", "heat42_limit", "vulnerable"}.issubset(payload["frame_columns"])
        events = objects(payload["events"], payload["event_columns"])
        effects = objects(payload["damage_effects"], payload["damage_columns"])
        for event in events:
            if event["type"] == "装配成功":
                assert event["side"] in ("红", "蓝") and event["team"]
                assert event["assembly_level"] in (1, 2, 3, 4)
                assert event["assembly_start_sec"] == event["second"] - event["assembly_duration_sec"]
                assembly[event["assembly_level"]] += 1
        for effect in effects:
            hits[effect["category"]] += 1
            if effect["kind"] in ("collision", "penalty", "dart"):
                assert effect["shooter"] is None and effect["source_x"] is None
            if effect["kind"] == "projectile" and effect["confidence"] == "high":
                assert effect["shooter"] is not None and effect["source_x"] is not None
                assert effect["angle_error"] is not None
        sizes.append(path.stat().st_size)
    assert assembly == Counter({1: 884, 2: 884, 3: 626}), assembly
    assert assembly[4] == 0
    sizes.sort()
    p95 = sizes[int((len(sizes) - 1) * .95)]
    assert p95 <= 750_000, f"replay p95 {p95} exceeds 750KB"
    assert sizes[-1] <= 850_000, f"largest replay {sizes[-1]} exceeds 850KB"

    if SOURCE.exists():
        connection = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
        raw_hits = Counter(dict(connection.execute("SELECT 类别,COUNT(*) FROM events WHERE 事件类型='受击' GROUP BY 类别")))
        connection.close()
        assert hits == raw_hits, f"hit event mismatch: exported={hits} raw={raw_hits}"
    print(f"replay audit: {len(paths)} games; assembly={dict(assembly)}; p95={p95}; max={sizes[-1]}")


if __name__ == "__main__":
    main()
