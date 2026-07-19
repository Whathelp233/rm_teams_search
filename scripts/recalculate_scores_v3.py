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
    "firepower": 0.08,
    "objective": 0.56,
    "spatial": 0.12,
    "defense": 0.11,
    "resource": 0.12,
    "adaptability": 0.01,
}
COMPONENT_WEIGHTS = {
    "firepower": {"clean_output": 0.35, "accuracy": 0.15, "kill_conversion": 0.25, "pressure_uptime": 0.25},
    "objective": {"outpost_pressure": 0.10, "outpost_conversion": 0.25, "base_pressure": 0.15, "base_conversion": 0.35, "strategic_tools": 0.15},
    "spatial": {"relative_territory": 0.25, "forward_presence": 0.30, "neutral_control": 0.35, "field_coverage": 0.10},
    "defense": {"trade_resilience": 0.35, "mobile_resilience": 0.25, "outpost_denial": 0.15, "base_denial": 0.15, "collapse_resistance": 0.10},
    "resource": {"acquisition": 0.40, "utilization": 0.05, "combat_conversion": 0.10, "objective_conversion": 0.25, "thermal_efficiency": 0.20},
    "adaptability": {"side_floor": 0.10, "opponent_floor": 0.10, "strong_opponent_response": 0.15, "setback_response": 0.35, "rematch_improvement": 0.30},
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("../sql/rmuc_2026_region_dataset.sqlite"))
    parser.add_argument("--data", type=Path, default=Path("public/data"))
    parser.add_argument("--backtest", action="store_true", help="score a historical subset without inferring final placements")
    return parser.parse_args()


def mean(values, fallback=0.0):
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.mean(usable) if usable else fallback


def quantile(values, fraction, fallback=None):
    usable = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if not usable:
        return fallback
    position = (len(usable) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return usable[lower]
    return usable[lower] * (upper - position) + usable[upper] * (position - lower)


def typical_with_floor(values, fallback=None):
    """Typical performance with a controlled penalty for repeatable downside."""
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not usable:
        return fallback
    return 0.7 * statistics.median(usable) + 0.3 * quantile(usable, 0.25)


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


def build_opponent_scores(payloads):
    """Transparent two-level strength-of-schedule score.

    An opponent's win rate is calculated after removing games against the team
    being evaluated, then receives a Beta(1, 1) prior.  This prevents a team
    from making its own schedule look stronger merely by beating an opponent.
    Repeated games in one series do not duplicate that opponent.
    """
    records = {}
    for team, (_, payload) in payloads.items():
        matches = payload["matches"]
        records[team] = {
            "games": len(matches),
            "wins": sum(bool(match.get("won")) for match in matches),
            "by_opponent": defaultdict(list),
        }
        for match in matches:
            records[team]["by_opponent"][match["opponent"]].append(bool(match.get("won")))

    first_order, opponent_rates = {}, {}
    for team, record in records.items():
        rates, details = [], []
        for opponent in record["by_opponent"]:
            if opponent not in records:
                continue
            opponent_record = records[opponent]
            direct = opponent_record["by_opponent"].get(team, [])
            other_games = opponent_record["games"] - len(direct)
            other_wins = opponent_record["wins"] - sum(direct)
            adjusted = (other_wins + 1.0) / (other_games + 2.0)
            rates.append(adjusted)
            details.append({
                "opponent": opponent,
                "meetings": len(record["by_opponent"][opponent]),
                "opponent_other_games": other_games,
                "opponent_other_wins": other_wins,
                "adjusted_win_rate_pct": rounded(adjusted * 100.0),
            })
        first_order[team] = mean(rates, 0.5)
        opponent_rates[team] = details

    raw_scores = {}
    for team, record in records.items():
        opponents = [opponent for opponent in record["by_opponent"] if opponent in first_order]
        second_order = mean((first_order[opponent] for opponent in opponents), 0.5)
        raw_scores[team] = 100.0 * (0.75 * first_order[team] + 0.25 * second_order)

    scores = {}
    for team, record in records.items():
        opponents = [opponent for opponent in record["by_opponent"] if opponent in raw_scores]
        sample = len(opponents)
        score = shrink(raw_scores[team], sample, prior=3.0)
        scores[team] = {
            "score": rounded(score),
            "opponent_win_rate_pct": rounded(first_order[team] * 100.0),
            "opponent_opponent_win_rate_pct": rounded(mean((first_order[opponent] for opponent in opponents), 0.5) * 100.0),
            "unique_opponents": sample,
            "direct_matches_excluded": True,
            "enters_strength": False,
            "strength_coefficient": 0.0,
            "correction_path": "regularized Bradley-Terry result_score",
            "breakdown": [
                {
                    **detail,
                    "second_order_pct": rounded(first_order.get(detail["opponent"], 0.5) * 100.0),
                    "display_weight_pct": rounded(100.0 / max(1, sample)),
                }
                for detail in sorted(opponent_rates[team], key=lambda item: (-item["adjusted_win_rate_pct"], item["opponent"]))
            ],
            "method": "75% direct-opponent adjusted win rate + 25% second-order opponent rate; unique opponents; Beta(1,1) prior. The display score is not added again because result_score already applies opponent correction through Bradley-Terry.",
        }
    return scores


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


DEFENSE_ANCHORS = {
    "trade_resilience": (0.50, 0.35),
    "mobile_resilience": (0.80, 0.20),
    "outpost_denial": (0.62, 0.38),
    "base_denial": (0.90, 0.10),
    "collapse_resistance": (0.62, 0.38),
}


def defense_analysis(raw_by_team, weights, games_by_team):
    """Blend meaningful absolute anchors with relative standing.

    Pure percentiles turn tiny structure-HP differences into huge score gaps.
    The absolute half preserves tactical meaning; the relative half still
    distinguishes teams within this field without allowing one outlier to set
    the whole scale.
    """
    vectors = {key: [raw.get(key) for raw in raw_by_team.values()] for key in weights}
    result = {}
    for team, raw in raw_by_team.items():
        components = {}
        for key in weights:
            value = raw.get(key)
            if value is None:
                components[key] = 50.0
                continue
            anchor, band = DEFENSE_ANCHORS[key]
            absolute = max(15.0, min(85.0, 50.0 + 35.0 * (value - anchor) / band))
            relative = percentile(vectors[key], value)
            components[key] = shrink(0.55 * absolute + 0.45 * relative, games_by_team[team])
        score = sum(components[key] * weights[key] for key in weights)
        result[team] = {
            "score": rounded(score),
            "components": {key: rounded(value) for key, value in components.items()},
            "weights": weights,
            "raw": {key: (None if value is None else rounded(value, 3)) for key, value in raw.items()},
            "component_samples": {key: games_by_team[team] for key in weights},
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
    # Derive opponent strength only from the matches present in this scoring
    # run. This is equivalent to the published summary on the full dataset,
    # and prevents future results leaking into chronological backtests.
    win_rates = {
        team: 100.0 * sum(bool(match.get("won")) for match in payload["matches"]) / max(1, len(payload["matches"]))
        for team, (_, payload) in payloads.items()
    }

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

    final_hp = {}
    final_query = f"""
        SELECT game_id,team,
          MAX(CASE WHEN robot='基地' THEN current_hp END) base_final_hp,
          MAX(CASE WHEN robot='基地' THEN max_hp END) base_final_max_hp,
          MAX(CASE WHEN robot='前哨站' THEN current_hp END) outpost_final_hp,
          MAX(CASE WHEN robot='前哨站' THEN max_hp END) outpost_final_max_hp,
          SUM(CASE WHEN robot IN ('英雄','工程','步兵3','步兵4','哨兵','空中') THEN current_hp ELSE 0 END) mobile_final_hp,
          SUM(CASE WHEN robot IN ('英雄','工程','步兵3','步兵4','哨兵','空中') THEN max_hp ELSE 0 END) mobile_final_max_hp
        FROM (
          SELECT game_id,学校名 team,机器人类型 robot,当前血量 current_hp,最大血量 max_hp,
            ROW_NUMBER() OVER (PARTITION BY game_id,学校名,机器人类型 ORDER BY 时刻秒 DESC) row_number
          FROM timeseries
        ) latest
        WHERE row_number=1
        GROUP BY game_id,team
    """
    for row in connection.execute(final_query):
        final_hp[(row["game_id"], row["team"])] = dict(row)

    game_results = [row for row in connection.execute(
        "SELECT game_id,赛区 region,场次号 series_no,红方学校 red,蓝方学校 blue,胜方 winner,开始时间 started FROM matches ORDER BY 开始时间,game_id"
    ) if row["game_id"] in game_teams]
    connection.close()

    clean_output_baseline = {}
    clean_allowed_baseline = {}
    outpost_attack_baseline = {}
    base_attack_baseline = {}
    for team, (_, payload) in payloads.items():
        outputs, allowed, outpost_attacks, base_attacks = [], [], [], []
        for match in payload["matches"]:
            duration = max(1.0, float(match.get("duration_sec") or 0))
            outputs.append(damage[(match["game_id"], match["opponent"])]["robot"] * 420.0 / duration)
            allowed.append(damage[(match["game_id"], team)]["robot"] * 420.0 / duration)
            outpost_attacks.append(damage[(match["game_id"], match["opponent"])]["outpost"] * 420.0 / duration)
            base_attacks.append(damage[(match["game_id"], match["opponent"])]["base"] * 420.0 / duration)
        clean_output_baseline[team], clean_allowed_baseline[team] = mean(outputs), mean(allowed)
        outpost_attack_baseline[team], base_attack_baseline[team] = mean(outpost_attacks), mean(base_attacks)
    global_output = statistics.median(clean_output_baseline.values())
    global_allowed = statistics.median(clean_allowed_baseline.values())
    global_outpost_attack = statistics.median(outpost_attack_baseline.values())
    global_base_attack = statistics.median(base_attack_baseline.values())

    fire_raw, objective_raw, spatial_raw, defense_raw, resource_raw = {}, {}, {}, {}, {}
    performance_by_match = {}
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
            # Finishing efficiency is deaths converted per unit of robot damage,
            # not another copy of damage volume.
            fire["kill_conversion"].append(float(opponent_match.get("deaths") or 0) / max(1.0, robot_dealt / 1000.0))
            fire["pressure_uptime"].append(len(attack_seconds[(game_id, team)]) / duration)

            first_outpost = first_attack.get((game_id, team, "outpost"))
            first_base = first_attack.get((game_id, team, "base"))
            objective["outpost_pressure"].append(0.0 if first_outpost is None else 0.5 + 0.5 * max(0.0, 1.0 - first_outpost / duration))
            zero = outpost_zero.get((game_id, opponent))
            killed = zero is not None and first_outpost is not None and float(zero) >= first_outpost
            objective["outpost_conversion"].append(0.0 if not killed else 0.5 + 0.5 * max(0.0, 1.0 - (float(zero) - first_outpost) / duration))
            objective["base_pressure"].append(0.0 if first_base is None else 0.5 + 0.5 * max(0.0, 1.0 - first_base / duration))
            objective["base_conversion"].append(
                0.0 if first_base is None else opp_in["base"] / max(30.0, duration - first_base)
            )
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

            expected_attack = 0.5 * global_output + 0.5 * clean_output_baseline.get(opponent, global_output)
            normalized_dealt = (robot_dealt * 420.0 / duration) / max(1.0, opponent_allowance)
            normalized_taken = (own_in["robot"] * 420.0 / duration) / max(1.0, expected_attack)
            exchange_total = normalized_dealt + normalized_taken
            trade_resilience = 0.5 if exchange_total <= 0 else normalized_dealt / exchange_total
            terminal = final_hp.get((game_id, team), {})
            mobile_hp, availability = own_space.get("mobile_hp"), own_space.get("availability")
            terminal_mobile = (
                None if not terminal.get("mobile_final_max_hp")
                else float(terminal["mobile_final_hp"] or 0.0) / float(terminal["mobile_final_max_hp"])
            )
            mobile_resilience = (
                None if mobile_hp is None or availability is None
                else 0.45 * mobile_hp + 0.30 * availability + 0.25 * (terminal_mobile if terminal_mobile is not None else mobile_hp)
            )
            outpost_first = first_attack.get((game_id, opponent, "outpost"))
            outpost_delay = 1.0 if outpost_first is None else min(1.0, outpost_first / duration)
            own_outpost_zero = outpost_zero.get((game_id, team))
            outpost_survival = 1.0 if own_outpost_zero is None else min(1.0, float(own_outpost_zero) / duration)
            outpost_hp = own_space.get("outpost_hp")
            outpost_final = (
                None if not terminal.get("outpost_final_max_hp")
                else float(terminal["outpost_final_hp"] or 0.0) / float(terminal["outpost_final_max_hp"])
            )
            outpost_survival = 1.0 if own_outpost_zero is None else min(1.0, max(0.0, float(own_outpost_zero) / duration))
            expected_outpost_attack = 0.5 * global_outpost_attack + 0.5 * outpost_attack_baseline.get(opponent, global_outpost_attack)
            outpost_suppression = 1.0 - min(1.0, own_in["outpost"] / max(250.0, expected_outpost_attack))
            outpost_denial = (
                None if outpost_hp is None
                else 0.45 * outpost_survival + 0.20 * (outpost_final if outpost_final is not None else outpost_hp)
                + 0.15 * outpost_delay + 0.20 * outpost_suppression
            )
            base_first = first_attack.get((game_id, opponent, "base"))
            base_delay = 1.0 if base_first is None else min(1.0, base_first / duration)
            base_hp = own_space.get("base_hp")
            base_final = (
                None if not terminal.get("base_final_max_hp")
                else float(terminal["base_final_hp"] or 0.0) / 5000.0
            )
            expected_base_attack = 0.5 * global_base_attack + 0.5 * base_attack_baseline.get(opponent, global_base_attack)
            base_suppression = 1.0 - min(1.0, own_in["base"] / max(250.0, expected_base_attack))
            base_denial = (
                None if base_hp is None
                else 0.45 * (base_final if base_final is not None else base_hp) + 0.15 * base_delay
                + 0.25 * base_suppression + 0.15 * outpost_survival
            )
            collapse_layers = [
                (trade_resilience, 0.25), (mobile_resilience, 0.20),
                (outpost_denial, 0.25), (base_denial, 0.30),
            ]
            collapse_available = [(value, weight) for value, weight in collapse_layers if value is not None]
            collapse_resistance = (
                sum(value * weight for value, weight in collapse_available) / sum(weight for _, weight in collapse_available)
                if collapse_available else None
            )
            defense["trade_resilience"].append(trade_resilience)
            defense["mobile_resilience"].append(mobile_resilience)
            defense["outpost_denial"].append(outpost_denial)
            defense["base_denial"].append(base_denial)
            defense["collapse_resistance"].append(collapse_resistance)

            total = float(match.get("total_coins_final") or 0); remaining = float(match.get("remaining_coins_final") or 0)
            spent = max(1.0, total - remaining)
            resource["acquisition"].append(total * 420.0 / duration)
            resource["utilization"].append((total - remaining) / max(1.0, total))
            resource["combat_conversion"].append(robot_dealt / spent)
            resource["objective_conversion"].append(objective_dealt / spent)
            hot = float(own_space.get("hot_samples") or 0)
            resource["thermal_efficiency"].append(robot_dealt / (1.0 + hot))

            performance_by_match[(game_id, team)] = (robot_dealt + 0.8 * opp_in["outpost"] + 1.2 * opp_in["base"]) * 420.0 / duration
            penalty += own_in["penalty"]; collision += own_in["collision"]
        fire_raw[team] = {key: mean(fire[key]) for key in COMPONENT_WEIGHTS["firepower"]}
        objective_raw[team] = {key: mean(objective[key]) for key in COMPONENT_WEIGHTS["objective"]}
        spatial_raw[team] = {key: mean(spatial[key], None) for key in COMPONENT_WEIGHTS["spatial"]}
        defense_raw[team] = {
            key: (quantile(defense[key], 0.25, None) if key == "collapse_resistance" else typical_with_floor(defense[key], None))
            for key in COMPONENT_WEIGHTS["defense"]
        }
        resource_raw[team] = {key: mean(resource[key]) for key in COMPONENT_WEIGHTS["resource"]}
        excluded[team] = {"penalty_damage": rounded(penalty, 0), "collision_damage": rounded(collision, 0)}

    perf_values = list(performance_by_match.values())
    perf_pct = {key: percentile(perf_values, value) for key, value in performance_by_match.items()}
    opponent_median = statistics.median(win_rates.values())
    expectation_rows = [
        (win_rates.get(matches[key]["opponent"], opponent_median), value)
        for key, value in perf_pct.items()
    ]
    expectation_x = mean(row[0] for row in expectation_rows)
    expectation_y = mean(row[1] for row in expectation_rows)
    expectation_variance = sum((row[0] - expectation_x) ** 2 for row in expectation_rows)
    expectation_slope = (
        sum((row[0] - expectation_x) * (row[1] - expectation_y) for row in expectation_rows) / expectation_variance
        if expectation_variance else 0.0
    )
    conditional_perf = {
        key: value - (expectation_y + expectation_slope * (win_rates.get(matches[key]["opponent"], opponent_median) - expectation_x))
        for key, value in perf_pct.items()
    }
    adaptation_raw, adaptation_samples = {}, {}
    for team, (_, payload) in payloads.items():
        by_side, by_opponent, strong_residual, setback = defaultdict(list), defaultdict(list), [], []
        for match in payload["matches"]:
            key = (match["game_id"], team); value = conditional_perf[key]
            by_side[match["side"]].append(value); by_opponent[match["opponent"]].append(value)
            if win_rates.get(match["opponent"], 50.0) >= opponent_median:
                strong_residual.append(value)
            zero = outpost_zero.get(key)
            duration = float(match.get("duration_sec") or 0)
            if zero is not None and 45.0 <= float(zero) <= duration - 45.0:
                total_damage = damage[(match["game_id"], match["opponent"])]["robot"] + damage[(match["game_id"], match["opponent"])]["outpost"] + damage[(match["game_id"], match["opponent"])]["base"]
                post_damage = min(total_damage, post_setback_damage[key])
                pre_rate = max(0.0, total_damage - post_damage) / float(zero)
                post_rate = post_damage / max(1.0, duration - float(zero))
                setback.append(max(-2.0, min(2.0, math.log((post_rate + 1.0) / (pre_rate + 1.0)))))
        side_n = min((len(values) for values in by_side.values()), default=0) if len(by_side) >= 2 else 0
        opponent_n = len(by_opponent)
        red_mean, blue_mean = mean(by_side.get("红", []), None), mean(by_side.get("蓝", []), None)
        # Adaptation must reward a usable performance floor, not merely a small
        # red/blue gap: two equally poor sides are not evidence of adaptability.
        side_floor = None if side_n == 0 else min(red_mean, blue_mean)
        opponent_means = [mean(values) for values in by_opponent.values()]
        opponent_floor = (
            None if opponent_n < 3
            else quantile(opponent_means, 0.25)
        )
        rematch_adjustments = []
        matches_by_opponent = defaultdict(list)
        for match in payload["matches"]:
            matches_by_opponent[match["opponent"]].append(match)
        for opponent_matches in matches_by_opponent.values():
            ordered = sorted(opponent_matches, key=lambda match: (match.get("started_at") or "", match["game_id"]))
            for previous, current in zip(ordered, ordered[1:]):
                if bool(previous.get("won")):
                    continue
                previous_value = conditional_perf[(previous["game_id"], team)]
                current_value = conditional_perf[(current["game_id"], team)]
                rematch_adjustments.append(max(-40.0, min(40.0, current_value - previous_value)))
        adaptation_raw[team] = {
            "side_floor": side_floor,
            "opponent_floor": opponent_floor,
            "strong_opponent_response": typical_with_floor(strong_residual, None),
            "setback_response": typical_with_floor(setback, None),
            "rematch_improvement": typical_with_floor(rematch_adjustments, None),
        }
        adaptation_samples[team] = {
            "side_floor": side_n * 2, "opponent_floor": opponent_n,
            "strong_opponent_response": len(strong_residual), "setback_response": len(setback),
            "rematch_improvement": len(rematch_adjustments),
        }

    raw_dimensions = {"firepower": fire_raw, "objective": objective_raw, "spatial": spatial_raw, "defense": defense_raw, "resource": resource_raw}
    analyses = {name: analysis(raw, COMPONENT_WEIGHTS[name], games_by_team) for name, raw in raw_dimensions.items() if name != "defense"}
    analyses["defense"] = defense_analysis(defense_raw, COMPONENT_WEIGHTS["defense"], games_by_team)
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
    placements = {} if args.backtest else infer_placements(game_results)
    dimension_ranks = {
        team: {
            dimension: 1 + sum(analyses[dimension][other]["score"] > analyses[dimension][team]["score"] for other in teams)
            for dimension in COMPONENT_WEIGHTS
        }
        for team in teams
    }
    dimension_confidence = {
        team: {
            dimension: rounded(100.0 * sum(
                analyses[dimension][team]["weights"][component]
                * analyses[dimension][team]["component_samples"].get(component, 0)
                / (analyses[dimension][team]["component_samples"].get(component, 0) + 6.0)
                for component in analyses[dimension][team]["weights"]
            ))
            for dimension in COMPONENT_WEIGHTS
        }
        for team in teams
    }
    result_scores = {team: shrink(percentile(rating_values, ratings[team]), games_by_team[team]) for team in teams}
    tactical_scores = {
        team: sum(analyses[name][team]["score"] * DIMENSION_WEIGHTS[name] for name in DIMENSION_WEIGHTS)
        for team in teams
    }
    opponent_scores = build_opponent_scores(payloads)
    opponent_ranks = {
        team: 1 + sum(opponent_scores[other]["score"] > opponent_scores[team]["score"] for other in teams)
        for team in teams
    }
    opponent_region_ranks = {}
    opponent_region_sizes = {}
    for team in teams:
        region = payloads[team][1]["summary"]["region"]
        regional = [other for other in teams if payloads[other][1]["summary"]["region"] == region]
        opponent_region_ranks[team] = 1 + sum(opponent_scores[other]["score"] > opponent_scores[team]["score"] for other in regional)
        opponent_region_sizes[team] = len(regional)
    # Rolling-origin validation shows that adding historical W/L to the already
    # opponent-normalized tactical facts worsens future-match Brier overall and
    # in South/North. Keep BT as transparent schedule context, not a second score input.
    strength_scores = dict(tactical_scores)
    overall_ranks = {team: 1 + sum(strength_scores[other] > strength_scores[team] for other in teams) for team in teams}

    index["schema_version"] = "4.0.0"
    index["data_version"] = "score-4.0.0"
    index["placement_method"] = {
        "format": "参赛手册规定的16进8、8进4、半决赛、季军争夺战和冠军争夺战，结合数据库实际胜负推导",
        "sources": [
            "RMUC 2026 东部赛区参赛手册 V2.0.0",
            "RMUC 2026 南部赛区参赛手册 V2.0.0",
            "RMUC 2026 北部赛区参赛手册 V2.0.0",
        ],
    }
    index["scoring_notice"] = "六维4.0：按规则5.8胜负优先级设置权重先验；滚动时间窗回测选择六维战术事实作为综合强度，Bradley-Terry赛果与逐对手分作为独立赛程证据，不重复加分"
    for team, (path, payload) in payloads.items():
        scores = {name: analyses[name][team]["score"] for name in COMPONENT_WEIGHTS}
        tactical, result, strength = tactical_scores[team], result_scores[team], strength_scores[team]
        position_points = sum(float(match.get("valid_position_points") or 0) for match in payload["matches"])
        invalid_points = sum(float(match.get("invalid_position_points") or 0) for match in payload["matches"])
        position_coverage = position_points / max(1.0, position_points + invalid_points)
        confidence = 100.0 * games_by_team[team] / (games_by_team[team] + 8.0) * math.sqrt(position_coverage)
        payload["schema_version"] = "4.0.0"; payload["data_version"] = "score-4.0.0"
        payload.pop("consistency_analysis", None)
        payload["scores"] = scores
        payload["dimension_ranks"] = dimension_ranks[team]
        payload["dimension_confidence"] = dimension_confidence[team]
        payload["overall_rank"] = overall_ranks[team]
        payload["placement"] = placements.get(team)
        for name, score in scores.items():
            payload["summary"][f"{name}_score"] = score
            detail = analyses[name][team]
            method = "terminal base/outpost/mobile HP and clean damage exchange, blended with typical/downside aggregation" if name == "defense" else "team fact percentile with games/(games+6) shrinkage"
            if name == "adaptability":
                method = "paired-condition transfer and residual response with component-specific evidence shrinkage"
            detail.update({"version": "4.0.0", "method": method})
            payload[f"{name}_analysis"] = detail
        payload["defense_analysis"]["excluded"] = excluded[team]
        payload["score_confidence"] = {
            "overall": rounded(confidence), "games": games_by_team[team],
            "position_coverage_pct": rounded(position_coverage * 100), "enters_score": False,
        }
        payload["opponent_score_analysis"] = {
            **opponent_scores[team], "rank": opponent_ranks[team],
            "region_rank": opponent_region_ranks[team], "region_size": opponent_region_sizes[team],
        }
        payload["strength_analysis"] = {
            "version": "4.0.0", "score": rounded(strength), "tactical_score": rounded(tactical),
            "result_score": rounded(result), "schedule_rating": rounded(ratings[team], 3),
            "raw_win_rate_pct": rounded(100.0 * sum(bool(match.get("won")) for match in payload["matches"]) / max(1, len(payload["matches"]))),
            "opponent_adjustment": "result_score is estimated jointly from every opponent and red/blue side; transparent opponent score is audit evidence and is not added twice",
            "tactical_weight": 1.0, "result_weight": 0.0,
            "matchup_model_version": "4.2.0",
            "matchup_result_weights": {"南部赛区": 0.0, "东部赛区": 0.10, "北部赛区": 0.0, "跨赛区": 0.0},
            "matchup_scales": {"南部赛区": 10.0, "东部赛区": 10.0, "北部赛区": 21.0, "跨赛区": 22.0},
            "matchup_uncertainty_floor_pct": {"南部赛区": 12.0, "东部赛区": 13.0, "北部赛区": 12.0, "跨赛区": 15.0},
            "matchup_mean_fold_ece_pct": {"南部赛区": 11.1, "东部赛区": 12.2, "北部赛区": 8.9, "跨赛区": None},
            "matchup_dimension_weights": {
                "全国统一": DIMENSION_WEIGHTS,
                "北部赛区": {**DIMENSION_WEIGHTS, "spatial": 0.08, "resource": 0.16},
            },
            "tactical_dimension_weights": DIMENSION_WEIGHTS,
            "victory_rule_alignment": {
                "source": "RMUC 2026比赛规则手册V2.0.1 第5.8节",
                "priority": ["基地终局血量", "前哨是否被毁及终局血量", "全队攻击伤害", "全队总剩余血量"],
                "direct_dimension_weight": 0.75,
                "enabling_dimension_weight": 0.25,
            },
            "model": "rule-aligned tactical composite; rolling-origin matchup calibration uses 10% regularized Bradley-Terry for East, a lower-spatial/higher-resource tactical profile for North, and fold-ECE uncertainty floors",
            "red_side_intercept": rounded(side_bias, 3),
        }
        listing = listings[team]
        listing["scores"] = scores; listing["strength_analysis"] = payload["strength_analysis"]
        listing["score_confidence"] = payload["score_confidence"]
        listing["opponent_score_analysis"] = payload["opponent_score_analysis"]
        listing["dimension_ranks"] = dimension_ranks[team]
        listing["dimension_confidence"] = dimension_confidence[team]
        listing["overall_rank"] = overall_ranks[team]
        listing["placement"] = placements.get(team)
        compact_write(path, payload)
    compact_write(index_path, index)
    print(f"recalculated {len(teams)} teams with score schema 4.0.0")


if __name__ == "__main__":
    main()
