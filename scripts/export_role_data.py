#!/usr/bin/env python3
"""Export auditable per-role RMUC data for the static site and downloads.

Robot state is preserved at the source 1 Hz grain. Team summaries exclude the
first and last ten seconds only for availability/stability metrics; exports keep
the complete timeline. Hit events identify the victim and ammunition type but
not the shooter. Dealt damage is therefore an explicitly labelled estimate:
42mm is role-exclusive, while 17mm is distributed across opposing roles that
fired in the hit second or the preceding second. Every hit is allocated once.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import shutil
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parent / "sql" / "rmuc_2026_region_dataset.sqlite"
DEFAULT_DATA = ROOT / "public" / "data"
DEFAULT_DOWNLOADS = ROOT / "public" / "downloads" / "roles"
SCHEMA_VERSION = "role-data-1.1.0"
ROLES = (
    ("英雄", "hero", "second"),
    ("工程", "engineer", "second"),
    ("步兵3", "infantry-3", "second"),
    ("步兵4", "infantry-4", "second"),
    ("哨兵", "sentry", "second"),
    ("空中", "aerial", "second"),
    ("飞镖", "dart", "event"),
)
FRAME_COLUMNS = [
    "second", "hp", "max_hp", "x", "y", "z", "yaw", "power",
    "heat17", "heat17_limit", "heat42", "heat42_limit", "shots17",
    "shots42", "total_coins", "remaining_coins", "vulnerable",
]
EVENT_COLUMNS = ["second", "type", "category", "value", "target_robot_id", "target_type", "note", "robot_id"]
DAMAGE_ESTIMATE_COLUMNS = [
    "second", "estimated_damage", "target_robot_id", "target_type", "ammo",
    "confidence_pct", "candidate_roles", "basis",
]
CSV_COLUMNS = [
    "record_type", "region", "match_no", "schedule", "round_no", "game_id",
    "web_game_id", "started_at", "duration_sec", "team", "opponent", "side",
    "won", "robot_id", "robot_type", *FRAME_COLUMNS, "event_type",
    "event_category", "event_value", "event_target_robot_id", "event_target_type",
    "event_note",
]
RANK_METRICS = {
    "availability_pct": "desc",
    "deaths_per_game": "asc",
    "terminal_hp_pct": "desc",
    "distance_per_game_m": "desc",
    "attack_depth_m": "desc",
    "forward_presence_pct": "desc",
    "combat_damage_per_alive_min": "asc",
    "shots_per_game": "desc",
    "high_heat_seconds_per_game": "asc",
    "position_coverage_pct": "desc",
    "estimated_damage_per_game": "desc",
    "estimated_base_damage_per_game": "desc",
    "estimated_outpost_damage_per_game": "desc",
    "estimated_robot_damage_per_game": "desc",
    "estimated_damage_confidence_pct": "desc",
    "hits": "desc",
    "damage": "desc",
    "hit_game_pct": "desc",
    "median_first_hit_sec": "asc",
    "gate_events": "desc",
}
FIRING_ROLES = {"英雄", "步兵3", "步兵4", "哨兵", "空中"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS)
    return parser.parse_args()


def rounded(value, digits=1):
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def median(values):
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.median(usable) if usable else None


def compact_write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def gzip_write(path, write):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as compressed:
            write(compressed)


def file_fact(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.relative_to(ROOT / "public")), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def load_context(data):
    index = json.loads((data / "index.json").read_text(encoding="utf-8"))
    slugs = {item["team"]: item["slug"] for item in index["teams"]}
    listings = {item["team"]: item for item in index["teams"]}
    team_matches, matches = {}, {}
    for team, slug in slugs.items():
        payload = json.loads((data / "teams" / f"{slug}.json").read_text(encoding="utf-8"))
        team_matches[team] = payload["matches"]
        for match in payload["matches"]:
            matches[(team, match["game_id"])] = match
    return index, slugs, listings, team_matches, matches


def valid_position(row):
    x, y = row[3], row[4]
    return x is not None and y is not None and 0 <= x <= 28 and 0 <= y <= 15 and not (x == 0 and y == 0)


def estimate_damage_attribution(connection):
    """Allocate combat hit damage to roles without asserting a shooter identity."""
    shots = defaultdict(Counter)
    team_by_side = {}
    for row in connection.execute("SELECT DISTINCT game_id,阵营 side,学校名 team FROM timeseries"):
        team_by_side[(row["game_id"], row["side"])] = row["team"]
    shot_query = """
        SELECT game_id,时刻秒 second,机器人类型 role,阵营 side,类别 ammo
        FROM events WHERE 事件类型='发弹' AND 类别 IN ('17mm','42mm')
        ORDER BY game_id,时刻秒,rowid
    """
    for row in connection.execute(shot_query):
        if row["role"] in FIRING_ROLES:
            shots[(row["game_id"], row["side"], row["ammo"], float(row["second"]))][row["role"]] += 1

    attributed = defaultdict(list)
    hit_query = """
        SELECT game_id,时刻秒 second,robot_id target_robot_id,机器人类型 target_type,
          阵营 victim_side,类别 ammo,数值 value
        FROM events WHERE 事件类型='受击' AND 类别 IN ('17mm','42mm') AND 数值<0
        ORDER BY game_id,时刻秒,rowid
    """
    for hit in connection.execute(hit_query):
        second = float(hit["second"])
        attacker_side = "蓝" if hit["victim_side"] == "红" else "红"
        attacker_team = team_by_side.get((hit["game_id"], attacker_side))
        if not attacker_team:
            continue
        if hit["ammo"] == "42mm":
            nearby = sum(shots[(hit["game_id"], attacker_side, "42mm", second - offset)]["英雄"] for offset in (0, 1))
            shares = {"英雄": 1.0}
            confidence = 98.0 if nearby else 90.0
            basis = "42mm兵种唯一+时间窗" if nearby else "42mm兵种唯一"
        else:
            weights = Counter()
            for offset, time_weight in ((0, 1.0), (1, 0.7)):
                for role, count in shots[(hit["game_id"], attacker_side, "17mm", second - offset)].items():
                    weights[role] += count * time_weight
            total_weight = sum(weights.values())
            if not total_weight:
                continue
            shares = {role: weight / total_weight for role, weight in weights.items()}
            concentration = sum(share * share for share in shares.values())
            same_second = sum(shots[(hit["game_id"], attacker_side, "17mm", second)].values())
            confidence = 100 * (0.90 if same_second else 0.70) * concentration
            basis = "17mm同秒/前1秒发弹份额"
        damage = max(0.0, -float(hit["value"] or 0))
        candidates = sorted(shares)
        for role, share in shares.items():
            attributed[(attacker_team, hit["game_id"], role)].append([
                rounded(second), rounded(damage * share, 3), hit["target_robot_id"], hit["target_type"],
                hit["ammo"], rounded(confidence), candidates, basis,
            ])
    return attributed


def damage_estimate_summary(rows):
    total = sum(float(row[1] or 0) for row in rows)
    by_target = Counter()
    confidence_damage = high_confidence = 0.0
    for row in rows:
        damage = float(row[1] or 0)
        by_target[row[3] or "未知"] += damage
        confidence_damage += damage * float(row[5] or 0) / 100
        if float(row[5] or 0) >= 70:
            high_confidence += damage
    return {
        "estimated_damage_dealt": rounded(total),
        "estimated_robot_damage": rounded(sum(value for key, value in by_target.items() if key not in {"基地", "前哨站"})),
        "estimated_outpost_damage": rounded(by_target.get("前哨站", 0)),
        "estimated_base_damage": rounded(by_target.get("基地", 0)),
        "estimated_damage_confidence_pct": rounded(100 * confidence_damage / total if total else None),
        "high_confidence_estimated_damage": rounded(high_confidence),
        "estimated_hit_events": len(rows),
    }


def game_summary(frames, events, match, damage_estimates=None):
    duration = max(0.0, float(match.get("duration_sec") or 0))
    analysis = [row for row in frames if 10 <= float(row[0]) <= duration - 10]
    alive_analysis = [row for row in analysis if float(row[1] or 0) > 0]
    valid_analysis = [row for row in alive_analysis if valid_position(row)]
    deaths = recoveries = 0
    first_death = None
    previous = None
    distance = 0.0
    for row in frames:
        alive = float(row[1] or 0) > 0
        if previous is not None:
            previous_alive = float(previous[1] or 0) > 0
            if previous_alive and not alive:
                deaths += 1
                if first_death is None:
                    first_death = float(row[0])
            elif not previous_alive and alive:
                recoveries += 1
            if previous_alive and alive and valid_position(previous) and valid_position(row) and 0 < float(row[0]) - float(previous[0]) <= 1.5:
                distance += math.hypot(float(row[3]) - float(previous[3]), float(row[4]) - float(previous[4]))
        previous = row
    side = match.get("side")
    depths = [float(row[3]) if side == "红" else 28.0 - float(row[3]) for row in valid_analysis]
    cells = {(int(float(row[3]) * 2), int(float(row[4]) * 2)) for row in valid_analysis}
    heat_ratios = []
    for row in alive_analysis:
        ratios = []
        if float(row[9] or 0) > 0:
            ratios.append(float(row[8] or 0) / float(row[9]))
        if float(row[11] or 0) > 0:
            ratios.append(float(row[10] or 0) / float(row[11]))
        heat_ratios.append(max(ratios, default=0.0))
    event_counts = Counter(row[1] for row in events)
    shots = sum(1 for row in events if row[1] == "发弹")
    firing_seconds = len({row[0] for row in events if row[1] == "发弹"})
    damage = defaultdict(float)
    buffs = Counter()
    for row in events:
        if row[1] == "受击":
            damage[row[2] or "未知"] += max(0.0, -float(row[3] or 0))
        elif row[1] == "增益":
            buffs[row[2] or "未知"] += 1
    combat_damage = sum(damage.get(key, 0.0) for key in ("17mm", "42mm", "飞镖"))
    final = frames[-1] if frames else None
    final_ratio = None if not final or not float(final[2] or 0) else 100 * float(final[1] or 0) / float(final[2])
    return {
        "tracked_seconds": len(frames),
        "analysis_seconds": len(analysis),
        "alive_seconds": len(alive_analysis),
        "availability_pct": rounded(100 * len(alive_analysis) / max(1, len(analysis))),
        "hp_area_pct": rounded(100 * sum(max(0.0, min(1.0, float(row[1] or 0) / max(1.0, float(row[2] or 0)))) for row in analysis) / max(1, len(analysis))),
        "terminal_hp_pct": rounded(final_ratio),
        "deaths": deaths,
        "recoveries": recoveries,
        "first_death_sec": rounded(first_death),
        "distance_m": rounded(distance),
        "attack_depth_m": rounded(sum(depths) / len(depths) if depths else None),
        "forward_presence_pct": rounded(100 * sum(value >= 14 for value in depths) / max(1, len(depths))),
        "neutral_presence_pct": rounded(100 * sum(10 <= value <= 18 for value in depths) / max(1, len(depths))),
        "field_cells": len(cells),
        "position_coverage_pct": rounded(100 * len(valid_analysis) / max(1, len(alive_analysis))),
        "mean_power": rounded(sum(float(row[7] or 0) for row in alive_analysis) / max(1, len(alive_analysis))),
        "mean_heat_pct": rounded(100 * sum(heat_ratios) / max(1, len(heat_ratios))),
        "high_heat_seconds": sum(value >= 0.9 for value in heat_ratios),
        "vulnerable_seconds": sum(bool(row[16]) for row in analysis),
        "shots": shots,
        "firing_seconds": firing_seconds,
        "combat_damage_received": rounded(combat_damage),
        "damage_received": {key: rounded(value) for key, value in sorted(damage.items())},
        "buffs": dict(sorted(buffs.items())),
        "event_counts": dict(sorted(event_counts.items())),
        **damage_estimate_summary(damage_estimates or []),
    }


def team_summary(games, team_matches):
    facts = [game["summary"] for game in games]
    game_count = len(team_matches)
    analysis_seconds = sum(item["analysis_seconds"] for item in facts)
    alive_seconds = sum(item["alive_seconds"] for item in facts)
    combat_damage = sum(item["combat_damage_received"] or 0 for item in facts)
    shots = sum(item["shots"] for item in facts)
    role_present_games = len(games)
    position_base = sum(item["alive_seconds"] for item in facts)
    estimated_damage = sum(item["estimated_damage_dealt"] or 0 for item in facts)
    estimated_confidence_damage = sum(
        (item["estimated_damage_dealt"] or 0) * (item["estimated_damage_confidence_pct"] or 0) / 100
        for item in facts
    )
    weighted = lambda key, weight: rounded(sum((item[key] or 0) * item[weight] for item in facts) / max(1, sum(item[weight] for item in facts)))
    return {
        "games": game_count,
        "role_present_games": role_present_games,
        "wins": sum(bool(match.get("won")) for match in team_matches),
        "tracked_seconds": sum(item["tracked_seconds"] for item in facts),
        "analysis_seconds": analysis_seconds,
        "alive_seconds": alive_seconds,
        "availability_pct": rounded(100 * alive_seconds / max(1, analysis_seconds)),
        "hp_area_pct": weighted("hp_area_pct", "analysis_seconds"),
        "terminal_hp_pct": rounded(sum(item["terminal_hp_pct"] or 0 for item in facts) / max(1, len(facts))),
        "deaths": sum(item["deaths"] for item in facts),
        "recoveries": sum(item["recoveries"] for item in facts),
        "deaths_per_game": rounded(sum(item["deaths"] for item in facts) / max(1, role_present_games), 2),
        "median_first_death_sec": rounded(median(item["first_death_sec"] for item in facts)),
        "distance_m": rounded(sum(item["distance_m"] or 0 for item in facts)),
        "distance_per_game_m": rounded(sum(item["distance_m"] or 0 for item in facts) / max(1, role_present_games)),
        "attack_depth_m": weighted("attack_depth_m", "alive_seconds"),
        "forward_presence_pct": weighted("forward_presence_pct", "alive_seconds"),
        "neutral_presence_pct": weighted("neutral_presence_pct", "alive_seconds"),
        "field_cells_per_game": rounded(sum(item["field_cells"] for item in facts) / max(1, role_present_games)),
        "position_coverage_pct": rounded(100 * sum((item["position_coverage_pct"] or 0) * item["alive_seconds"] / 100 for item in facts) / max(1, position_base)),
        "mean_power": weighted("mean_power", "alive_seconds"),
        "mean_heat_pct": weighted("mean_heat_pct", "alive_seconds"),
        "high_heat_seconds": sum(item["high_heat_seconds"] for item in facts),
        "high_heat_seconds_per_game": rounded(sum(item["high_heat_seconds"] for item in facts) / max(1, role_present_games)),
        "vulnerable_seconds": sum(item["vulnerable_seconds"] for item in facts),
        "shots": shots,
        "shots_per_game": rounded(shots / max(1, role_present_games)),
        "shots_per_alive_min": rounded(shots * 60 / max(1, alive_seconds)),
        "firing_seconds": sum(item["firing_seconds"] for item in facts),
        "combat_damage_received": rounded(combat_damage),
        "combat_damage_per_alive_min": rounded(combat_damage * 60 / max(1, alive_seconds)),
        "estimated_damage_dealt": rounded(estimated_damage),
        "estimated_damage_per_game": rounded(estimated_damage / max(1, role_present_games)),
        "estimated_robot_damage_per_game": rounded(sum(item["estimated_robot_damage"] or 0 for item in facts) / max(1, role_present_games)),
        "estimated_outpost_damage_per_game": rounded(sum(item["estimated_outpost_damage"] or 0 for item in facts) / max(1, role_present_games)),
        "estimated_base_damage_per_game": rounded(sum(item["estimated_base_damage"] or 0 for item in facts) / max(1, role_present_games)),
        "estimated_damage_confidence_pct": rounded(100 * estimated_confidence_damage / estimated_damage if estimated_damage else None),
        "high_confidence_estimated_damage": rounded(sum(item["high_confidence_estimated_damage"] or 0 for item in facts)),
        "estimated_hit_events": sum(item["estimated_hit_events"] for item in facts),
        "damage_received": dict(sum((Counter(item["damage_received"]) for item in facts), Counter())),
        "buffs": dict(sum((Counter(item["buffs"]) for item in facts), Counter())),
        "window_rule": "availability/stability summaries exclude first and last 10 seconds",
    }


def assign_ranks(entries):
    for metric, direction in RANK_METRICS.items():
        usable = [entry for entry in entries if entry["summary"].get(metric) is not None]
        for entry in entries:
            value = entry["summary"].get(metric)
            if value is None or not usable:
                entry.setdefault("ranks", {})[metric] = None
                continue
            entry.setdefault("ranks", {})[metric] = 1 + sum(
                (other["summary"][metric] > value if direction == "desc" else other["summary"][metric] < value)
                for other in usable
            )


def event_rows(connection, role):
    if role == "飞镖":
        query = """
            SELECT game_id,时刻秒 second,事件类型 event_type,robot_id,学校名 team,阵营 side,
              类别 category,数值 value,目标robot_id target_robot_id,目标类型 target_type,备注 note
            FROM events WHERE 事件类型 IN ('飞镖闸门开','飞镖命中') ORDER BY 学校名,game_id,时刻秒,rowid
        """
        params = ()
    else:
        query = """
            SELECT game_id,时刻秒 second,事件类型 event_type,robot_id,学校名 team,阵营 side,
              类别 category,数值 value,目标robot_id target_robot_id,目标类型 target_type,备注 note
            FROM events WHERE 机器人类型=? AND 事件类型 IN ('发弹','受击','增益','雷达反制UAV')
            ORDER BY 学校名,game_id,时刻秒,rowid
        """
        params = (role,)
    return [dict(row) for row in connection.execute(query, params)]


def dart_payloads(events, slugs, listings, team_matches, matches):
    grouped = defaultdict(lambda: defaultdict(list))
    for event in events:
        grouped[event["team"]][event["game_id"]].append([
            rounded(event["second"]), event["event_type"], event["category"], rounded(event["value"]),
            event["target_robot_id"], event["target_type"], event["note"], event["robot_id"],
        ])
    payloads, entries = [], []
    for team in sorted(slugs):
        games = []
        all_events = []
        for match in team_matches[team]:
            rows = grouped[team].get(match["game_id"], [])
            hits = [row for row in rows if row[1] == "飞镖命中"]
            facts = {
                "gate_events": sum(row[1] == "飞镖闸门开" for row in rows),
                "hits": len(hits),
                "damage": rounded(sum(float(row[3] or 0) for row in hits)),
                "first_hit_sec": rounded(min((row[0] for row in hits), default=None)),
                "base_hits": sum(row[5] == "基地" for row in hits),
                "outpost_hits": sum(row[5] == "前哨站" for row in hits),
            }
            games.append({
                "game_id": match["game_id"], "opponent": match["opponent"], "side": match["side"],
                "won": bool(match["won"]), "duration_sec": match["duration_sec"], "summary": facts, "events": rows,
            })
            all_events.extend(rows)
        hits = [row for row in all_events if row[1] == "飞镖命中"]
        summary = {
            "games": len(team_matches[team]), "wins": sum(bool(match.get("won")) for match in team_matches[team]),
            "gate_events": sum(row[1] == "飞镖闸门开" for row in all_events), "hits": len(hits),
            "hit_games": sum(bool(game["summary"]["hits"]) for game in games),
            "hit_game_pct": rounded(100 * sum(bool(game["summary"]["hits"]) for game in games) / max(1, len(games))),
            "damage": rounded(sum(float(row[3] or 0) for row in hits)),
            "median_first_hit_sec": rounded(median(game["summary"]["first_hit_sec"] for game in games)),
            "base_hits": sum(row[5] == "基地" for row in hits), "outpost_hits": sum(row[5] == "前哨站" for row in hits),
        }
        payload = {
            "schema_version": SCHEMA_VERSION, "mode": "event", "role": "飞镖", "role_slug": "dart",
            "team": team, "team_slug": slugs[team], "region": listings[team]["region"],
            "event_columns": EVENT_COLUMNS, "summary": summary, "games": games,
            "limitations": ["飞镖没有连续机器人状态，只提供闸门与命中事件。"],
        }
        payloads.append(payload)
        entries.append({"team": team, "slug": slugs[team], "region": listings[team]["region"], "summary": summary})
    assign_ranks(entries)
    rank_lookup = {entry["team"]: entry["ranks"] for entry in entries}
    for payload in payloads:
        payload["ranks"] = rank_lookup[payload["team"]]
    return payloads, entries


def robot_payloads(connection, role, role_slug, events, damage_attribution, slugs, listings, team_matches, matches, csv_writer):
    grouped_events = defaultdict(lambda: defaultdict(list))
    for event in events:
        grouped_events[event["team"]][event["game_id"]].append([
            rounded(event["second"]), event["event_type"], event["category"], rounded(event["value"]),
            event["target_robot_id"], event["target_type"], event["note"], event["robot_id"],
        ])
    query = """
        SELECT 赛区 region,场次号 match_no,赛程 schedule,局号 round_no,game_id,时刻秒 second,
          robot_id,机器人类型 role,阵营 side,学校名 team,对手学校 opponent,当前血量 hp,最大血量 max_hp,
          x,y,z,枪口朝向 yaw,底盘功率 power,小热量 heat17,小热量上限 heat17_limit,
          大热量 heat42,大热量上限 heat42_limit,累计17mm发弹 shots17,累计42mm发弹 shots42,
          队伍总金币 total_coins,队伍剩余金币 remaining_coins,是否易伤 vulnerable
        FROM timeseries WHERE 机器人类型=? ORDER BY 学校名,game_id,时刻秒,rowid
    """
    team_games = defaultdict(lambda: defaultdict(list))
    robot_ids = {}
    for raw in connection.execute(query, (role,)):
        row = dict(raw)
        match = matches.get((row["team"], row["game_id"]), {})
        frame = [
            rounded(row["second"]), rounded(row["hp"]), rounded(row["max_hp"]), rounded(row["x"], 3),
            rounded(row["y"], 3), rounded(row["z"], 3), rounded(row["yaw"], 3), rounded(row["power"], 3),
            rounded(row["heat17"], 3), rounded(row["heat17_limit"], 3), rounded(row["heat42"], 3),
            rounded(row["heat42_limit"], 3), rounded(row["shots17"]), rounded(row["shots42"]),
            rounded(row["total_coins"]), rounded(row["remaining_coins"]), int(row["vulnerable"] or 0),
        ]
        team_games[row["team"]][row["game_id"]].append(frame)
        robot_ids[(row["team"], row["game_id"])] = row["robot_id"]
        csv_writer.writerow({
            "record_type": "second", "region": row["region"], "match_no": row["match_no"], "schedule": row["schedule"],
            "round_no": row["round_no"], "game_id": row["game_id"], "web_game_id": match.get("web_game_id"),
            "started_at": match.get("started_at"), "duration_sec": match.get("duration_sec"), "team": row["team"],
            "opponent": row["opponent"], "side": row["side"], "won": int(bool(match.get("won"))),
            "robot_id": row["robot_id"], "robot_type": role, **dict(zip(FRAME_COLUMNS, frame)),
        })
    for event in events:
        match = matches.get((event["team"], event["game_id"]), {})
        csv_writer.writerow({
            "record_type": "event", "region": match.get("region"), "match_no": match.get("match_no"),
            "schedule": match.get("schedule"), "round_no": match.get("round_no"), "game_id": event["game_id"],
            "web_game_id": match.get("web_game_id"), "started_at": match.get("started_at"),
            "duration_sec": match.get("duration_sec"), "team": event["team"], "opponent": match.get("opponent"),
            "side": event["side"], "won": int(bool(match.get("won"))), "robot_id": event["robot_id"], "robot_type": role,
            "second": rounded(event["second"]), "event_type": event["event_type"], "event_category": event["category"],
            "event_value": rounded(event["value"]), "event_target_robot_id": event["target_robot_id"],
            "event_target_type": event["target_type"], "event_note": event["note"],
        })
    payloads, entries = [], []
    for team in sorted(slugs):
        games = []
        for match in team_matches[team]:
            frames = team_games[team].get(match["game_id"], [])
            if not frames:
                continue
            event_data = grouped_events[team].get(match["game_id"], [])
            damage_estimates = damage_attribution.get((team, match["game_id"], role), [])
            for estimate in damage_estimates:
                csv_writer.writerow({
                    "record_type": "damage_estimate", "region": match.get("region"), "match_no": match.get("match_no"),
                    "schedule": match.get("schedule"), "round_no": match.get("round_no"), "game_id": match["game_id"],
                    "web_game_id": match.get("web_game_id"), "started_at": match.get("started_at"),
                    "duration_sec": match.get("duration_sec"), "team": team, "opponent": match.get("opponent"),
                    "side": match.get("side"), "won": int(bool(match.get("won"))), "robot_type": role,
                    "second": estimate[0], "event_type": "推定造成伤害", "event_category": estimate[4],
                    "event_value": estimate[1], "event_target_robot_id": estimate[2],
                    "event_target_type": estimate[3], "event_note": f"置信度{estimate[5]}%;{estimate[7]};候选{','.join(estimate[6])}",
                })
            games.append({
                "game_id": match["game_id"], "opponent": match["opponent"], "side": match["side"],
                "won": bool(match["won"]), "duration_sec": match["duration_sec"], "rule_version": match.get("rule_version"),
                "robot_id": robot_ids.get((team, match["game_id"])),
                "summary": game_summary(frames, event_data, match, damage_estimates),
                "frames": frames, "events": event_data, "damage_estimates": damage_estimates,
            })
        summary = team_summary(games, team_matches[team])
        if role == "工程":
            for key in ("shots", "shots_per_game", "shots_per_alive_min", "firing_seconds"):
                summary[key] = None
            for key in (
                "estimated_damage_dealt", "estimated_damage_per_game", "estimated_robot_damage_per_game",
                "estimated_outpost_damage_per_game", "estimated_base_damage_per_game",
                "estimated_damage_confidence_pct", "high_confidence_estimated_damage", "estimated_hit_events",
            ):
                summary[key] = None
        payload = {
            "schema_version": SCHEMA_VERSION, "mode": "second", "role": role, "role_slug": role_slug,
            "team": team, "team_slug": slugs[team], "region": listings[team]["region"],
            "frame_columns": FRAME_COLUMNS, "event_columns": EVENT_COLUMNS,
            "damage_estimate_columns": DAMAGE_ESTIMATE_COLUMNS, "summary": summary, "games": games,
            "limitations": [
                "造成伤害为推定值：42mm按兵种唯一性归因；17mm按同秒/前1秒发弹份额分配；不代表射手身份或命中率。",
                "在场率与稳定性汇总排除比赛前10秒和后10秒；frames保留完整时间。",
            ],
        }
        payloads.append(payload)
        entries.append({"team": team, "slug": slugs[team], "region": listings[team]["region"], "summary": summary})
    assign_ranks(entries)
    rank_lookup = {entry["team"]: entry["ranks"] for entry in entries}
    for payload in payloads:
        payload["ranks"] = rank_lookup[payload["team"]]
    return payloads, entries


def write_role_archive(path, role, role_slug, mode, payloads):
    def write(handle):
        wrapper = io.TextIOWrapper(handle, encoding="utf-8", newline="")
        json.dump({
            "schema_version": SCHEMA_VERSION, "role": role, "role_slug": role_slug,
            "mode": mode, "teams": payloads,
        }, wrapper, ensure_ascii=False, separators=(",", ":"))
        wrapper.flush()
    gzip_write(path, write)


def write_dart_csv(path, events, matches):
    def write(handle):
        wrapper = io.TextIOWrapper(handle, encoding="utf-8", newline="")
        writer = csv.DictWriter(wrapper, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            match = matches.get((event["team"], event["game_id"]), {})
            writer.writerow({
                "record_type": "event", "region": match.get("region"), "match_no": match.get("match_no"),
                "schedule": match.get("schedule"), "round_no": match.get("round_no"), "game_id": event["game_id"],
                "web_game_id": match.get("web_game_id"), "started_at": match.get("started_at"),
                "duration_sec": match.get("duration_sec"), "team": event["team"], "opponent": match.get("opponent"),
                "side": event["side"], "won": int(bool(match.get("won"))), "robot_id": event["robot_id"], "robot_type": "飞镖",
                "second": rounded(event["second"]), "event_type": event["event_type"], "event_category": event["category"],
                "event_value": rounded(event["value"]), "event_target_robot_id": event["target_robot_id"],
                "event_target_type": event["target_type"], "event_note": event["note"],
            })
        wrapper.flush()
    gzip_write(path, write)


def main():
    args = parse_args()
    index, slugs, listings, team_matches, matches = load_context(args.data)
    role_root = args.data / "roles"
    if role_root.exists():
        shutil.rmtree(role_root)
    if args.downloads.exists():
        shutil.rmtree(args.downloads)
    role_root.mkdir(parents=True)
    args.downloads.mkdir(parents=True)
    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    damage_attribution = estimate_damage_attribution(connection)
    role_index = []
    manifest_files = []
    for role, role_slug, mode in ROLES:
        events = event_rows(connection, role)
        csv_path = args.downloads / f"{role_slug}.csv.gz"
        if mode == "second":
            holder = {}
            def write_csv(handle):
                wrapper = io.TextIOWrapper(handle, encoding="utf-8", newline="")
                writer = csv.DictWriter(wrapper, fieldnames=CSV_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                payloads, entries = robot_payloads(
                    connection, role, role_slug, events, damage_attribution,
                    slugs, listings, team_matches, matches, writer,
                )
                holder["payloads"], holder["entries"] = payloads, entries
                wrapper.flush()
            gzip_write(csv_path, write_csv)
            payloads, entries = holder["payloads"], holder["entries"]
        else:
            payloads, entries = dart_payloads(events, slugs, listings, team_matches, matches)
            write_dart_csv(csv_path, events, matches)
        team_dir = role_root / role_slug / "teams"
        for payload in payloads:
            compact_write(team_dir / f"{payload['team_slug']}.json", payload)
        archive_path = args.downloads / f"{role_slug}.json.gz"
        write_role_archive(archive_path, role, role_slug, mode, payloads)
        rows = sum(len(game.get("frames", [])) for payload in payloads for game in payload["games"])
        event_count = sum(len(game.get("events", [])) for payload in payloads for game in payload["games"])
        role_listing = {
            "schema_version": SCHEMA_VERSION, "role": role, "role_slug": role_slug, "mode": mode,
            "frame_columns": FRAME_COLUMNS if mode == "second" else [], "event_columns": EVENT_COLUMNS,
            "damage_estimate_columns": DAMAGE_ESTIMATE_COLUMNS if mode == "second" else [],
            "teams": entries, "counts": {"teams": sum(bool(payload["games"]) for payload in payloads), "games": sum(len(payload["games"]) for payload in payloads), "rows": rows, "events": event_count},
            "downloads": {"csv_gz": f"downloads/roles/{role_slug}.csv.gz", "json_gz": f"downloads/roles/{role_slug}.json.gz"},
            "ranking_note": "事实指标与标注为推定的伤害指标分别排名，不合成兵种总分。",
        }
        compact_write(role_root / role_slug / "index.json", role_listing)
        role_index.append({key: role_listing[key] for key in ("role", "role_slug", "mode", "counts", "downloads")})
        manifest_files.extend([file_fact(csv_path), file_fact(archive_path)])
        print(f"exported {role}: {rows} second rows, {event_count} events")
    connection.close()
    compact_write(role_root / "index.json", {
        "schema_version": SCHEMA_VERSION, "roles": role_index,
        "total_second_rows": sum(item["counts"]["rows"] for item in role_index),
        "total_events": sum(item["counts"]["events"] for item in role_index),
        "limitations": ["受击事件没有射手身份；造成伤害按弹种与1秒发弹时间窗推定，并单独提供置信度。"],
    })
    compact_write(args.downloads / "manifest.json", {
        "schema_version": SCHEMA_VERSION, "generated_from": args.db.name, "roles": role_index, "files": manifest_files,
    })


if __name__ == "__main__":
    main()
