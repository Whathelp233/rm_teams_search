#!/usr/bin/env python3
"""Rebuild six tactical dimensions and schedule-adjusted strength from match facts.

Every tactical component follows the same pipeline: aggregate match-level facts,
convert the team aggregate to a midrank percentile, then shrink small samples
toward 50. Telemetry coverage is emitted as confidence and never adds points.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path


MOBILE_TYPES = {"英雄", "工程", "步兵3", "步兵4", "哨兵", "空中"}
COMBAT_CATEGORIES = {"17mm", "42mm", "飞镖"}
DIMENSION_WEIGHTS = {
    "firepower": 0.18,
    "objective": 0.20,
    "spatial": 0.17,
    "defense": 0.20,
    "resource": 0.10,
    "adaptability": 0.15,
}
COMPONENT_WEIGHTS = {
    "firepower": {"clean_output": 0.35, "accuracy": 0.20, "kill_conversion": 0.25, "pressure_uptime": 0.20},
    "objective": {"outpost_pressure": 0.20, "outpost_conversion": 0.25, "base_pressure": 0.20, "base_conversion": 0.25, "strategic_tools": 0.10},
    "spatial": {"relative_territory": 0.30, "forward_presence": 0.25, "neutral_control": 0.20, "field_coverage": 0.15, "mobility": 0.10},
    "defense": {"combat_containment": 0.25, "mobile_integrity": 0.20, "unit_availability": 0.15, "outpost_integrity": 0.15, "base_protection": 0.25},
    "resource": {"acquisition": 0.20, "utilization": 0.15, "combat_conversion": 0.25, "objective_conversion": 0.25, "thermal_efficiency": 0.15},
    "adaptability": {"side_balance": 0.20, "opponent_robustness": 0.15, "strong_opponent": 0.30, "setback_response": 0.25, "option_coverage": 0.10},
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../sql/rmuc_2026_region_dataset.sqlite"))
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    return parser.parse_args()


def mean(values, fallback=0.0):
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.mean(usable) if usable else fallback


def rounded(value, digits=1):
    return round(float(value), digits)


def compact_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def percentile(values, value):
    usable = [item for item in values if item is not None and math.isfinite(item)]
    if value is None or not usable:
        return 50.0
    below = sum(item < value for item in usable)
    equal = sum(item == value for item in usable)
    return 100.0 * (below + 0.5 * equal) / len(usable)


def shrink(score, samples, prior=6.0):
    confidence = max(0.0, float(samples)) / (max(0.0, float(samples)) + prior)
    return 50.0 + (float(score) - 50.0) * confidence


def sigmoid(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def infer_placements(game_rows):
    """Infer elimination finish from each region's final bracket series."""
    series = {}
    for row in game_rows:
        key = (row["region"], int(row["series_no"]))
        item = series.setdefault(key, {"teams": (row["red"], row["blue"]), "wins": defaultdict(int)})
        winner = row["red"] if row["winner"] == "红" else row["blue"]
        item["wins"][winner] += 1
    for item in series.values():
        item["winner"] = max(item["wins"], key=item["wins"].get)
        item["loser"] = next(team for team in item["teams"] if team != item["winner"])
    placements = {}
    for region in sorted({key[0] for key in series}):
        regional = {number: item for (item_region, number), item in series.items() if item_region == region}
        final_number = max(regional)
        final, third = regional[final_number], regional[final_number - 1]
        top_four = set(final["teams"]) | set(third["teams"])
        semifinal_candidates = [
            (number, item) for number, item in regional.items()
            if number < final_number - 1 and set(item["teams"]) <= top_four
        ]
        semifinals = sorted(semifinal_candidates, reverse=True)[:2]
        semifinal_cutoff = min(number for number, _ in semifinals)
        quarterfinals = {}
        for team in top_four:
            candidates = [(number, item) for number, item in regional.items() if number < semifinal_cutoff and team in item["teams"]]
            if candidates:
                number, item = max(candidates, key=lambda pair: pair[0]); quarterfinals[number] = item
        quarterfinal_cutoff = min(quarterfinals)
        quarterfinal_teams = {team for item in quarterfinals.values() for team in item["teams"]}
        round_of_16 = {}
        for team in quarterfinal_teams:
            candidates = [(number, item) for number, item in regional.items() if number < quarterfinal_cutoff and team in item["teams"]]
            if candidates:
                number, item = max(candidates, key=lambda pair: pair[0]); round_of_16[number] = item
        for item in round_of_16.values():
            placements[item["loser"]] = {"label": "16强", "tier": 16, "region": region}
        for item in quarterfinals.values():
            placements[item["loser"]] = {"label": "八强", "tier": 8, "region": region}
        placements[third["loser"]] = {"label": "殿军", "tier": 4, "region": region}
        placements[third["winner"]] = {"label": "季军", "tier": 3, "region": region}
        placements[final["loser"]] = {"label": "亚军", "tier": 2, "region": region}
        placements[final["winner"]] = {"label": "冠军", "tier": 1, "region": region}
    return placements


def analysis(raw_by_team, weights, games_by_team, samples_by_team=None):
    vectors = {key: [raw.get(key) for raw in raw_by_team.values()] for key in weights}
    result = {}
    for team, raw in raw_by_team.items():
        components = {}
        component_samples = {}
        for key in weights:
            samples = (samples_by_team or {}).get(team, {}).get(key, games_by_team[team])
            component_samples[key] = samples
            components[key] = shrink(percentile(vectors[key], raw.get(key)), samples)
        score = sum(components[key] * weights[key] for key in weights)
        result[team] = {
            "score": rounded(score),
            "components": {key: rounded(value) for key, value in components.items()},
            "weights": weights,
            "raw": {key: (None if value is None else rounded(value, 3)) for key, value in raw.items()},
            "component_samples": component_samples,
        }
    return result


def main():
    args = parse_args()
    index_path = args.data / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    listings = {item["team"]: item for item in index["teams"]}
    payloads = {}
    matches = {}
    game_teams = {}
    for team, listing in listings.items():
        path = args.data / "teams" / f"{listing['slug']}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads[team] = (path, payload)
        for match in payload["matches"]:
            matches[(match["game_id"], team)] = match
            game_teams.setdefault(match["game_id"], {})[team] = match["opponent"]
    teams = list(payloads)
    games_by_team = {team: len(payload["matches"]) for team, (_, payload) in payloads.items()}
    win_rates = {team: float(payload["summary"]["win_rate"]) for team, (_, payload) in payloads.items()}

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row

    outpost_zero = {}
    for row in connection.execute(
        "SELECT game_id,学校名 team,MIN(CASE WHEN 当前血量<=0 THEN 时刻秒 END) zero_sec "
        "FROM timeseries WHERE 机器人类型='前哨站' GROUP BY game_id,学校名"
    ):
        outpost_zero[(row["game_id"], row["team"])] = row["zero_sec"]

    damage = defaultdict(lambda: {"robot": 0.0, "base": 0.0, "outpost": 0.0, "penalty": 0.0, "collision": 0.0})
    first_attack = {}
    attack_seconds = defaultdict(set)
    robot_hits = defaultdict(float)
    source_damage = defaultdict(lambda: defaultdict(float))
    post_setback_damage = defaultdict(float)
    for row in connection.execute(
        "SELECT game_id,时刻秒 second,学校名 victim,机器人类型 target,类别 category,数值 value "
        "FROM events WHERE 事件类型='受击'"
    ):
        game_id, victim = row["game_id"], row["victim"]
        if (game_id, victim) not in matches:
            continue
        amount = max(0.0, -float(row["value"] or 0.0))
        category, target = row["category"] or "", row["target"] or ""
        incoming = damage[(game_id, victim)]
        if category == "判罚":
            incoming["penalty"] += amount
            continue
        if category == "撞击":
            incoming["collision"] += amount
            continue
        if category not in COMBAT_CATEGORIES:
            continue
        bucket = "base" if target == "基地" else "outpost" if target == "前哨站" else "robot"
        incoming[bucket] += amount
        attacker = matches[(game_id, victim)]["opponent"]
        second = float(row["second"] or 0.0)
        first_attack[(game_id, attacker, bucket)] = min(second, first_attack.get((game_id, attacker, bucket), second))
        source_damage[(game_id, attacker)][f"{bucket}_{category}"] += amount
        if bucket == "robot":
            attack_seconds[(game_id, attacker)].add(int(second))
            if category in {"17mm", "42mm"}:
                robot_hits[(game_id, attacker)] += 1
        own_zero = outpost_zero.get((game_id, attacker))
        if own_zero is not None and second >= float(own_zero):
            post_setback_damage[(game_id, attacker)] += amount

    hp = {}
    nx = "CASE WHEN 阵营='蓝' THEN 28.0-x ELSE x END"
    ny = "CASE WHEN 阵营='蓝' THEN 15.0-y ELSE y END"
    mobile = "机器人类型 IN ('英雄','工程','步兵3','步兵4','哨兵','空中')"
    valid = "x BETWEEN 0 AND 28 AND y BETWEEN 0 AND 15 AND NOT (x=0 AND y=0)"
    query = f"""
        SELECT game_id,学校名 team,
          AVG(CASE WHEN {mobile} AND 最大血量>0 THEN MAX(0,MIN(1,当前血量/最大血量)) END) mobile_hp,
          AVG(CASE WHEN {mobile} THEN 当前血量>0 END) availability,
          AVG(CASE WHEN 机器人类型='前哨站' AND 最大血量>0 THEN MAX(0,MIN(1,当前血量/最大血量)) END) outpost_hp,
          AVG(CASE WHEN 机器人类型='基地' AND 最大血量>0 THEN MAX(0,MIN(1,当前血量/最大血量)) END) base_hp,
          AVG(CASE WHEN {mobile} AND {valid} AND 当前血量>0 THEN {nx} END) attack_depth,
          AVG(CASE WHEN {mobile} AND {valid} AND 当前血量>0 THEN {nx}>=14 END) forward_share,
          AVG(CASE WHEN {mobile} AND {valid} AND 当前血量>0 THEN {nx} BETWEEN 10 AND 18 END) neutral_share,
          COUNT(DISTINCT CASE WHEN {mobile} AND {valid} AND 当前血量>0 THEN printf('%d:%d',CAST(({nx})*2 AS INT),CAST(({ny})*2 AS INT)) END) cells,
          SUM(CASE WHEN {mobile} AND MAX(CASE WHEN 小热量上限>0 THEN 小热量/小热量上限 ELSE 0 END,CASE WHEN 大热量上限>0 THEN 大热量/大热量上限 ELSE 0 END)>=.9 THEN 1 ELSE 0 END) hot_samples,
          SUM(CASE WHEN {mobile} THEN 1 ELSE 0 END) mobile_samples
        FROM timeseries GROUP BY game_id,学校名
    """
    for row in connection.execute(query):
        hp[(row["game_id"], row["team"])] = dict(row)

    game_results = list(connection.execute(
        "SELECT game_id,赛区 region,场次号 series_no,红方学校 red,蓝方学校 blue,胜方 winner,开始时间 started FROM matches ORDER BY 开始时间,game_id"
    ))
    connection.close()

    clean_output_baseline = {}
    clean_allowed_baseline = {}
    for team, (_, payload) in payloads.items():
        outputs, allowed = [], []
        for match in payload["matches"]:
            duration = max(1.0, float(match.get("duration_sec") or 0))
            outputs.append(damage[(match["game_id"], match["opponent"])]["robot"] * 420.0 / duration)
            allowed.append(damage[(match["game_id"], team)]["robot"] * 420.0 / duration)
        clean_output_baseline[team], clean_allowed_baseline[team] = mean(outputs), mean(allowed)
    global_output = statistics.median(clean_output_baseline.values())
    global_allowed = statistics.median(clean_allowed_baseline.values())

    fire_raw, objective_raw, spatial_raw, defense_raw, resource_raw = {}, {}, {}, {}, {}
    performance_by_match = {}
    strategy_modes = defaultdict(lambda: defaultdict(int))
    excluded = {}
    for team, (_, payload) in payloads.items():
        fire = defaultdict(list); objective = defaultdict(list); spatial = defaultdict(list)
        defense = defaultdict(list); resource = defaultdict(list)
        penalty = collision = 0.0
        for match in payload["matches"]:
            game_id, opponent = match["game_id"], match["opponent"]
            duration = max(1.0, float(match.get("duration_sec") or 0))
            own_in, opp_in = damage[(game_id, team)], damage[(game_id, opponent)]
            robot_dealt, objective_dealt = opp_in["robot"], opp_in["base"] + opp_in["outpost"]
            opponent_allowance = 0.5 * global_allowed + 0.5 * clean_allowed_baseline.get(opponent, global_allowed)
            fire["clean_output"].append((robot_dealt * 420.0 / duration) / max(1.0, opponent_allowance))
            shots = float(match.get("shots_17") or 0) + float(match.get("shots_42") or 0)
            fire["accuracy"].append(robot_hits[(game_id, team)] / max(1.0, shots))
            opponent_match = matches.get((game_id, opponent), {})
            fire["kill_conversion"].append(float(opponent_match.get("deaths") or 0) * 420.0 / duration)
            fire["pressure_uptime"].append(len(attack_seconds[(game_id, team)]) / duration)

            first_outpost = first_attack.get((game_id, team, "outpost"))
            first_base = first_attack.get((game_id, team, "base"))
            objective["outpost_pressure"].append(0.0 if first_outpost is None else 0.5 + 0.5 * max(0.0, 1.0 - first_outpost / duration))
            zero = outpost_zero.get((game_id, opponent))
            killed = zero is not None and first_outpost is not None and float(zero) >= first_outpost
            objective["outpost_conversion"].append(0.0 if not killed else 0.5 + 0.5 * max(0.0, 1.0 - (float(zero) - first_outpost) / duration))
            objective["base_pressure"].append(0.0 if first_base is None else 0.5 + 0.5 * max(0.0, 1.0 - first_base / duration))
            objective["base_conversion"].append(min(1.0, opp_in["base"] / 5000.0))
            tools = float(match.get("dart_hits") or 0) + 0.5 * float(match.get("rune_events") or 0) + 0.25 * float(match.get("radar_counter_events") or 0)
            objective["strategic_tools"].append(tools * 420.0 / duration)

            own_space, opp_space = hp.get((game_id, team), {}), hp.get((game_id, opponent), {})
            own_depth, opp_depth = own_space.get("attack_depth"), opp_space.get("attack_depth")
            spatial["relative_territory"].append(None if own_depth is None or opp_depth is None else own_depth - opp_depth)
            spatial["forward_presence"].append(own_space.get("forward_share"))
            own_neutral, opp_neutral = own_space.get("neutral_share"), opp_space.get("neutral_share")
            spatial["neutral_control"].append(None if own_neutral is None or opp_neutral is None else own_neutral / max(1e-6, own_neutral + opp_neutral))
            active_minutes = max(1.0 / 60.0, duration / 60.0)
            spatial["field_coverage"].append(float(own_space.get("cells") or 0) / active_minutes)
            spatial["mobility"].append(float(match.get("distance_m") or 0) * 420.0 / duration)

            expected_attack = 0.5 * global_output + 0.5 * clean_output_baseline.get(opponent, global_output)
            defense["combat_containment"].append(-((own_in["robot"] * 420.0 / duration) / max(1.0, expected_attack)))
            defense["mobile_integrity"].append(own_space.get("mobile_hp"))
            defense["unit_availability"].append(own_space.get("availability"))
            defense["outpost_integrity"].append(own_space.get("outpost_hp"))
            base_delay = 1.0 if first_attack.get((game_id, opponent, "base")) is None else min(1.0, first_attack[(game_id, opponent, "base")] / duration)
            defense["base_protection"].append(0.6 * float(own_space.get("base_hp") or 0) + 0.4 * base_delay)

            total = float(match.get("total_coins_final") or 0); remaining = float(match.get("remaining_coins_final") or 0)
            spent = max(1.0, total - remaining)
            resource["acquisition"].append(total * 420.0 / duration)
            resource["utilization"].append((total - remaining) / max(1.0, total))
            resource["combat_conversion"].append(robot_dealt / spent)
            resource["objective_conversion"].append(objective_dealt / spent)
            hot = float(own_space.get("hot_samples") or 0)
            resource["thermal_efficiency"].append(robot_dealt / (1.0 + hot))

            performance_by_match[(game_id, team)] = (robot_dealt + 0.8 * opp_in["outpost"] + 1.2 * opp_in["base"]) * 420.0 / duration
            strategy_modes[team]["early_outpost"] += int(first_outpost is not None and first_outpost <= 90)
            strategy_modes[team]["base_42"] += int(source_damage[(game_id, team)]["base_42mm"] > 0)
            strategy_modes[team]["dart"] += int(float(match.get("dart_hits") or 0) > 0)
            strategy_modes[team]["rune"] += int(float(match.get("rune_events") or 0) > 0)
            strategy_modes[team]["radar"] += int(float(match.get("radar_counter_events") or 0) > 0)
            penalty += own_in["penalty"]; collision += own_in["collision"]
        fire_raw[team] = {key: mean(fire[key]) for key in COMPONENT_WEIGHTS["firepower"]}
        objective_raw[team] = {key: mean(objective[key]) for key in COMPONENT_WEIGHTS["objective"]}
        spatial_raw[team] = {key: mean(spatial[key], None) for key in COMPONENT_WEIGHTS["spatial"]}
        defense_raw[team] = {key: mean(defense[key], None) for key in COMPONENT_WEIGHTS["defense"]}
        resource_raw[team] = {key: mean(resource[key]) for key in COMPONENT_WEIGHTS["resource"]}
        excluded[team] = {"penalty_damage": rounded(penalty, 0), "collision_damage": rounded(collision, 0)}

    perf_values = list(performance_by_match.values())
    perf_pct = {key: percentile(perf_values, value) for key, value in performance_by_match.items()}
    opponent_median = statistics.median(win_rates.values())
    adaptation_raw, adaptation_samples = {}, {}
    for team, (_, payload) in payloads.items():
        by_side, by_opponent, strong, setback = defaultdict(list), defaultdict(list), [], []
        for match in payload["matches"]:
            key = (match["game_id"], team); value = perf_pct[key]
            by_side[match["side"]].append(value); by_opponent[match["opponent"]].append(value)
            if win_rates.get(match["opponent"], 50.0) >= opponent_median:
                strong.append(value)
            zero = outpost_zero.get(key)
            if zero is not None and float(zero) < float(match.get("duration_sec") or 0) - 10:
                remaining = max(1.0, float(match["duration_sec"]) - float(zero))
                overall = performance_by_match[key] / 420.0
                setback.append((post_setback_damage[key] / remaining) / max(1.0, overall))
        side_n = min((len(values) for values in by_side.values()), default=0) if len(by_side) >= 2 else 0
        opponent_n = len(by_opponent)
        side_balance = -abs(mean(by_side.get("红", [])) - mean(by_side.get("蓝", []))) if side_n else None
        opponent_means = [mean(values) for values in by_opponent.values()]
        opponent_robustness = -statistics.pstdev(opponent_means) if opponent_n >= 2 else None
        mode_score = mean(min(1.0, strategy_modes[team][mode] / max(1.0, games_by_team[team] * 0.2)) for mode in strategy_modes[team])
        adaptation_raw[team] = {
            "side_balance": side_balance,
            "opponent_robustness": opponent_robustness,
            "strong_opponent": mean(strong, None),
            "setback_response": mean(setback, None),
            "option_coverage": mode_score,
        }
        adaptation_samples[team] = {
            "side_balance": side_n, "opponent_robustness": opponent_n, "strong_opponent": len(strong),
            "setback_response": len(setback), "option_coverage": games_by_team[team],
        }

    raw_dimensions = {"firepower": fire_raw, "objective": objective_raw, "spatial": spatial_raw, "defense": defense_raw, "resource": resource_raw}
    analyses = {name: analysis(raw, COMPONENT_WEIGHTS[name], games_by_team) for name, raw in raw_dimensions.items()}
    analyses["adaptability"] = analysis(adaptation_raw, COMPONENT_WEIGHTS["adaptability"], games_by_team, adaptation_samples)

    ratings = {team: 0.0 for team in teams}; side_bias = 0.0
    for iteration in range(1200):
        gradients = {team: -0.01 * ratings[team] for team in teams}; bias_gradient = -0.01 * side_bias
        for game in game_results:
            red, blue = game["red"], game["blue"]
            if red not in ratings or blue not in ratings:
                continue
            target = 1.0 if game["winner"] == "红" else 0.0
            error = target - sigmoid(ratings[red] - ratings[blue] + side_bias)
            gradients[red] += error; gradients[blue] -= error; bias_gradient += error
        rate = 0.015 / (1.0 + iteration / 400.0)
        scale = max(1.0, len(game_results))
        for team in teams:
            ratings[team] += rate * gradients[team] * 100.0 / scale
        side_bias += rate * bias_gradient * 100.0 / scale
        center = mean(ratings.values())
        for team in teams:
            ratings[team] -= center
    rating_values = list(ratings.values())
    placements = infer_placements(game_results)
    dimension_ranks = {
        team: {
            dimension: 1 + sum(analyses[dimension][other]["score"] > analyses[dimension][team]["score"] for other in teams)
            for dimension in COMPONENT_WEIGHTS
        }
        for team in teams
    }
    result_scores = {team: shrink(percentile(rating_values, ratings[team]), games_by_team[team]) for team in teams}
    tactical_scores = {
        team: sum(analyses[name][team]["score"] * DIMENSION_WEIGHTS[name] for name in DIMENSION_WEIGHTS)
        for team in teams
    }
    strength_scores = {team: 0.75 * tactical_scores[team] + 0.25 * result_scores[team] for team in teams}
    overall_ranks = {team: 1 + sum(strength_scores[other] > strength_scores[team] for other in teams) for team in teams}

    index["schema_version"] = "3.0.0"
    index["data_version"] = "score-3.0.1"
    index["placement_method"] = {
        "format": "参赛手册规定的16进8、8进4、半决赛、季军争夺战和冠军争夺战，结合数据库实际胜负推导",
        "sources": [
            "RMUC 2026 东部赛区参赛手册 V2.0.0",
            "RMUC 2026 南部赛区参赛手册 V2.0.0",
            "RMUC 2026 北部赛区参赛手册 V2.0.0",
        ],
    }
    index["scoring_notice"] = "六维逐局事实、统一百分位、小样本收缩；覆盖率仅作置信度；综合强度含正则化赛程强度"
    for team, (path, payload) in payloads.items():
        scores = {name: analyses[name][team]["score"] for name in COMPONENT_WEIGHTS}
        tactical, result, strength = tactical_scores[team], result_scores[team], strength_scores[team]
        position_points = sum(float(match.get("valid_position_points") or 0) for match in payload["matches"])
        invalid_points = sum(float(match.get("invalid_position_points") or 0) for match in payload["matches"])
        position_coverage = position_points / max(1.0, position_points + invalid_points)
        confidence = 100.0 * games_by_team[team] / (games_by_team[team] + 8.0) * math.sqrt(position_coverage)
        payload["schema_version"] = "3.0.0"; payload["data_version"] = "score-3.0.1"
        payload.pop("consistency_analysis", None)
        payload["scores"] = scores
        payload["dimension_ranks"] = dimension_ranks[team]
        payload["overall_rank"] = overall_ranks[team]
        payload["placement"] = placements.get(team)
        for name, score in scores.items():
            payload["summary"][f"{name}_score"] = score
            detail = analyses[name][team]
            detail.update({"version": "3.0.0", "method": "team fact percentile with games/(games+6) shrinkage"})
            payload[f"{name}_analysis"] = detail
        payload["defense_analysis"]["excluded"] = excluded[team]
        payload["score_confidence"] = {
            "overall": rounded(confidence), "games": games_by_team[team],
            "position_coverage_pct": rounded(position_coverage * 100), "enters_score": False,
        }
        payload["strength_analysis"] = {
            "version": "3.0.0", "score": rounded(strength), "tactical_score": rounded(tactical),
            "result_score": rounded(result), "schedule_rating": rounded(ratings[team], 3),
            "tactical_weight": 0.75, "result_weight": 0.25,
            "tactical_dimension_weights": DIMENSION_WEIGHTS,
            "model": "regularized Bradley-Terry with red-side intercept",
            "red_side_intercept": rounded(side_bias, 3),
        }
        listing = listings[team]
        listing["scores"] = scores; listing["strength_analysis"] = payload["strength_analysis"]
        listing["score_confidence"] = payload["score_confidence"]
        listing["dimension_ranks"] = dimension_ranks[team]
        listing["overall_rank"] = overall_ranks[team]
        listing["placement"] = placements.get(team)
        compact_write(path, payload)
    compact_write(index_path, index)
    print(f"recalculated {len(teams)} teams with score schema 3.0.0")


if __name__ == "__main__":
    main()
