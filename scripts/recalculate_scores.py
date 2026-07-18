#!/usr/bin/env python3
"""Rebuild defense, consistency, and composite strength from auditable match facts."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


DEFENSE_WEIGHTS = {
    "combat_containment": 0.25,
    "unit_survival": 0.20,
    "outpost_survival": 0.20,
    "base_protection": 0.25,
    "damage_exchange": 0.10,
}
TACTICAL_WEIGHTS = {
    "firepower": 0.20,
    "objective": 0.18,
    "spatial": 0.14,
    "defense": 0.20,
    "resource": 0.13,
    "adaptability": 0.15,
}
SPATIAL_WEIGHTS = {
    "mobility_intensity": 0.20,
    "attack_depth": 0.40,
    "deep_pressure": 0.40,
}
COMBAT_CATEGORIES = {"17mm", "42mm", "飞镖"}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../sql/rmuc_2026_region_dataset.sqlite"))
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    return parser.parse_args()


def rounded(value, digits=1):
    return round(float(value), digits)


def compact_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def percentile(values, value):
    """Midrank percentile: ties share the same neutral position."""
    below = sum(item < value for item in values)
    equal = sum(item == value for item in values)
    return 100.0 * (below + 0.5 * equal) / max(1, len(values))


def stability(values):
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not usable:
        return 50.0
    mean = statistics.mean(usable)
    raw = 100.0 if abs(mean) < 1e-9 else 100.0 / (1.0 + statistics.pstdev(usable) / abs(mean))
    confidence = len(usable) / (len(usable) + 5.0)
    return 50.0 + (raw - 50.0) * confidence


def main():
    args = parse_args()
    index_path = args.data / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["schema_version"] = "2.2.0"
    index["data_version"] = "score-2.2.0"
    listings = {item["team"]: item for item in index["teams"]}
    payloads = {}
    for team, listing in listings.items():
        path = args.data / "teams" / f"{listing['slug']}.json"
        payloads[team] = (path, json.loads(path.read_text(encoding="utf-8")))

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    damage = defaultdict(lambda: {"robot": 0.0, "base": 0.0, "outpost": 0.0, "penalty": 0.0, "collision": 0.0, "first_base": None})
    for row in connection.execute(
        "SELECT game_id,时刻秒 second,学校名 team,机器人类型 target,类别 category,数值 value FROM events WHERE 事件类型='受击'"
    ):
        key = (row["game_id"], row["team"])
        amount = max(0.0, -float(row["value"] or 0.0))
        category = row["category"] or ""
        target = row["target"] or ""
        if category == "判罚":
            damage[key]["penalty"] += amount
        elif category == "撞击":
            damage[key]["collision"] += amount
        elif category in COMBAT_CATEGORIES:
            bucket = "base" if target == "基地" else "outpost" if target == "前哨站" else "robot"
            damage[key][bucket] += amount
            if bucket == "base" and amount > 0:
                current = damage[key]["first_base"]
                damage[key]["first_base"] = float(row["second"]) if current is None else min(current, float(row["second"]))

    outpost_zero = {}
    for row in connection.execute(
        "SELECT game_id,学校名 team,MIN(CASE WHEN 当前血量<=0 THEN 时刻秒 END) zero_sec FROM timeseries WHERE 机器人类型='前哨站' GROUP BY game_id,学校名"
    ):
        outpost_zero[(row["game_id"], row["team"])] = row["zero_sec"]
    connection.close()

    offensive_baseline = {}
    for team, (_, payload) in payloads.items():
        outputs = []
        for match in payload["matches"]:
            duration = max(1.0, float(match["duration_sec"] or 0))
            outputs.append(damage[(match["game_id"], match["opponent"])]["robot"] * 420.0 / duration)
        offensive_baseline[team] = statistics.mean(outputs) if outputs else 0.0
    global_offense = statistics.median(offensive_baseline.values())

    # Spatial 2.2 measures actual territorial advance. The former score mixed
    # average distance with position validity, allowing telemetry quality to
    # account for half of a team's supposed map control. Position validity is
    # now retained only as a confidence/coverage field.
    spatial_raw = {}
    for team, (_, payload) in payloads.items():
        mobility = []
        depth = []
        pressure = []
        valid_points = 0.0
        invalid_points = 0.0
        for match in payload["matches"]:
            duration = max(1.0, float(match.get("duration_sec") or 0))
            mobility.append(float(match.get("distance_m") or 0) * 420.0 / duration)
            if match.get("mean_attack_depth_m") is not None:
                depth.append(float(match["mean_attack_depth_m"]))
            pressure.append(100.0 * float(match.get("deep_pressure_seconds") or 0) / duration)
            valid_points += float(match.get("valid_position_points") or 0)
            invalid_points += float(match.get("invalid_position_points") or 0)
        spatial_raw[team] = {
            "mobility_m_per_420": statistics.mean(mobility) if mobility else 0.0,
            "mean_attack_depth_m": statistics.mean(depth) if depth else 0.0,
            "deep_pressure_pct": statistics.mean(pressure) if pressure else 0.0,
            "position_coverage_pct": 100.0 * valid_points / max(1.0, valid_points + invalid_points),
        }
    spatial_vectors = {
        key: [metrics[key] for metrics in spatial_raw.values()]
        for key in ("mobility_m_per_420", "mean_attack_depth_m", "deep_pressure_pct")
    }
    for team, (path, payload) in payloads.items():
        raw = spatial_raw[team]
        components = {
            "mobility_intensity": percentile(spatial_vectors["mobility_m_per_420"], raw["mobility_m_per_420"]),
            "attack_depth": percentile(spatial_vectors["mean_attack_depth_m"], raw["mean_attack_depth_m"]),
            "deep_pressure": percentile(spatial_vectors["deep_pressure_pct"], raw["deep_pressure_pct"]),
        }
        spatial = sum(components[key] * weight for key, weight in SPATIAL_WEIGHTS.items())
        payload["scores"]["spatial"] = rounded(spatial)
        payload["summary"]["spatial_score"] = rounded(spatial)
        payload["spatial_analysis"] = {
            "version": "2.2.0",
            "score": rounded(spatial),
            "components": {key: rounded(value) for key, value in components.items()},
            "weights": SPATIAL_WEIGHTS,
            "raw": {key: rounded(value) for key, value in raw.items()},
            "position_coverage_is_confidence_only": True,
            "duration_normalized_to_sec": 420,
        }
        listings[team]["scores"]["spatial"] = rounded(spatial)
        compact_write(path, payload)

    defense_values = []
    for team, (path, payload) in payloads.items():
        containment_scores = []
        survival_scores = []
        outpost_scores = []
        base_scores = []
        dealt_total = 0.0
        received_total = 0.0
        excluded_penalty = 0.0
        excluded_collision = 0.0
        consistency_damage = []
        consistency_objective = []
        consistency_exchange = []
        consistency_deaths = []
        match_rows = []
        for match in payload["matches"]:
            game_id = match["game_id"]
            opponent = match["opponent"]
            duration = max(1.0, float(match["duration_sec"] or 0))
            own = damage[(game_id, team)]
            opposing = damage[(game_id, opponent)]
            robot_received = own["robot"]
            robot_dealt = opposing["robot"]
            expected = 0.5 * global_offense + 0.5 * offensive_baseline.get(opponent, global_offense)
            pressure_ratio = (robot_received * 420.0 / duration) / max(1.0, expected)
            containment = 100.0 / (1.0 + pressure_ratio)
            deaths_420 = float(match.get("deaths") or 0) * 420.0 / duration
            survival = 100.0 / (1.0 + deaths_420 / 5.0)
            zero_sec = outpost_zero.get((game_id, team))
            outpost_survival = 100.0 if zero_sec is None else 100.0 * min(1.0, max(0.0, float(zero_sec) / duration))
            base_preservation = max(0.0, 1.0 - own["base"] / 5000.0)
            base_delay = 1.0 if own["first_base"] is None else min(1.0, max(0.0, own["first_base"] / duration))
            base_protection = 100.0 * (0.6 * base_preservation + 0.4 * base_delay)
            exchange = 50.0 if robot_dealt + robot_received <= 0 else 100.0 * robot_dealt / (robot_dealt + robot_received)
            containment_scores.append(containment)
            survival_scores.append(survival)
            outpost_scores.append(outpost_survival)
            base_scores.append(base_protection)
            dealt_total += robot_dealt
            received_total += robot_received
            excluded_penalty += own["penalty"]
            excluded_collision += own["collision"]
            consistency_damage.append(robot_dealt * 420.0 / duration)
            consistency_objective.append((opposing["base"] + opposing["outpost"]) * 420.0 / duration)
            consistency_exchange.append(exchange)
            consistency_deaths.append(deaths_420)
            match_rows.append({
                "game_id": game_id,
                "opponent": opponent,
                "duration_sec": match["duration_sec"],
                "clean_robot_damage_received": rounded(robot_received, 0),
                "clean_base_damage_received": rounded(own["base"], 0),
                "clean_outpost_damage_received": rounded(own["outpost"], 0),
                "excluded_penalty_damage": rounded(own["penalty"], 0),
                "excluded_collision_damage": rounded(own["collision"], 0),
                "deaths": int(match.get("deaths") or 0),
                "outpost_destroyed_sec": None if zero_sec is None else rounded(zero_sec),
                "first_base_damage_received_sec": None if own["first_base"] is None else rounded(own["first_base"]),
            })

        components = {
            "combat_containment": statistics.mean(containment_scores) if containment_scores else 50.0,
            "unit_survival": statistics.mean(survival_scores) if survival_scores else 50.0,
            "outpost_survival": statistics.mean(outpost_scores) if outpost_scores else 50.0,
            "base_protection": statistics.mean(base_scores) if base_scores else 50.0,
            "damage_exchange": 50.0 if dealt_total + received_total <= 0 else 100.0 * dealt_total / (dealt_total + received_total),
        }
        defense = sum(components[key] * weight for key, weight in DEFENSE_WEIGHTS.items())
        consistency_components = {
            "damage_output": stability(consistency_damage),
            "objective_output": stability(consistency_objective),
            "damage_exchange": stability(consistency_exchange),
            "unit_survival": stability(consistency_deaths),
        }
        consistency = statistics.mean(consistency_components.values())
        payload["scores"]["defense"] = rounded(defense)
        payload["scores"]["adaptability"] = rounded(consistency)
        payload["summary"]["defense_score"] = rounded(defense)
        payload["summary"]["adaptability_score"] = rounded(consistency)
        payload["schema_version"] = "2.2.0"
        payload["data_version"] = "score-2.2.0"
        payload["defense_analysis"] = {
            "version": "2.1.0",
            "score": rounded(defense),
            "components": {key: rounded(value) for key, value in components.items()},
            "weights": DEFENSE_WEIGHTS,
            "excluded_penalty_damage": rounded(excluded_penalty, 0),
            "excluded_collision_damage": rounded(excluded_collision, 0),
            "opponent_adjusted": True,
            "duration_normalized_to_sec": 420,
            "matches": match_rows,
        }
        payload["consistency_analysis"] = {
            "version": "2.1.0",
            "score": rounded(consistency),
            "components": {key: rounded(value) for key, value in consistency_components.items()},
            "sample_shrinkage": "50 + (raw - 50) * games / (games + 5)",
        }
        listings[team]["scores"]["defense"] = rounded(defense)
        listings[team]["scores"]["adaptability"] = rounded(consistency)
        compact_write(path, payload)
        defense_values.append(defense)

    win_rates = {team: float(payload[1]["summary"]["win_rate"]) for team, payload in payloads.items()}
    for team, (path, payload) in payloads.items():
        games = int(payload["summary"]["games"])
        wins = int(payload["summary"]["wins"])
        shrunk_win = 100.0 * (wins + 3.0) / (games + 6.0)
        opponent_win = statistics.mean(win_rates.get(match["opponent"], 50.0) for match in payload["matches"])
        result_score = 0.8 * shrunk_win + 0.2 * opponent_win
        tactical_score = sum(payload["scores"][key] * weight for key, weight in TACTICAL_WEIGHTS.items())
        strength = 0.75 * tactical_score + 0.25 * result_score
        analysis = {
            "version": "2.2.0",
            "score": rounded(strength),
            "tactical_score": rounded(tactical_score),
            "result_score": rounded(result_score),
            "shrunk_win_rate": rounded(shrunk_win),
            "opponent_avg_win_rate": rounded(opponent_win),
            "tactical_weight": 0.75,
            "result_weight": 0.25,
            "tactical_dimension_weights": TACTICAL_WEIGHTS,
            "defense_effective_weight": 0.15,
        }
        payload["strength_analysis"] = analysis
        listings[team]["strength_analysis"] = analysis
        compact_write(path, payload)

    compact_write(index_path, index)
    print(
        f"recalculated {len(payloads)} teams; defense min/median/max "
        f"{min(defense_values):.1f}/{statistics.median(defense_values):.1f}/{max(defense_values):.1f}"
    )


if __name__ == "__main__":
    main()
