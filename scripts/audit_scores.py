#!/usr/bin/env python3
"""Audit published score semantics and regional outcome alignment."""

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
DIMENSIONS = ("firepower", "objective", "spatial", "defense", "resource", "adaptability")
STAGES = {None: 0, "16强": 1, "八强": 2, "殿军": 3, "季军": 4, "亚军": 5, "冠军": 6}


def ranks(values):
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        shared = (start + end - 1) / 2.0
        for position in range(start, end):
            result[order[position]] = shared
        start = end
    return result


def pearson(first, second):
    first_mean = sum(first) / len(first)
    second_mean = sum(second) / len(second)
    numerator = sum((a - first_mean) * (b - second_mean) for a, b in zip(first, second))
    denominator = math.sqrt(sum((a - first_mean) ** 2 for a in first) * sum((b - second_mean) ** 2 for b in second))
    return numerator / denominator if denominator else 0.0


def spearman(first, second):
    return pearson(ranks(first), ranks(second))


def auc(labels, scores):
    positives = [score for label, score in zip(labels, scores) if label]
    negatives = [score for label, score in zip(labels, scores) if not label]
    if not positives or not negatives:
        return 0.5
    concordant = sum((positive > negative) + 0.5 * (positive == negative) for positive in positives for negative in negatives)
    return concordant / (len(positives) * len(negatives))


def main():
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    teams = []
    for listing in index["teams"]:
        payload = json.loads((DATA / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
        payload["stage"] = STAGES[(payload.get("placement") or {}).get("label")]
        teams.append(payload)

    failures = []
    report = {"schema": index["schema_version"], "regions": {}, "dimensions": {}, "regional_dimensions": {}}
    expected_dimension_weights = {
        "firepower": 0.08, "objective": 0.56, "spatial": 0.12,
        "defense": 0.11, "resource": 0.12, "adaptability": 0.01,
    }
    expected_component_weights = {
        "firepower": {"clean_output": 0.35, "accuracy": 0.15, "kill_conversion": 0.25, "pressure_uptime": 0.25},
        "objective": {"outpost_pressure": 0.10, "outpost_conversion": 0.25, "base_pressure": 0.15, "base_conversion": 0.35, "strategic_tools": 0.15},
        "spatial": {"relative_territory": 0.25, "forward_presence": 0.30, "neutral_control": 0.35, "field_coverage": 0.10},
        "defense": {"trade_resilience": 0.35, "mobile_resilience": 0.25, "outpost_denial": 0.15, "base_denial": 0.15, "collapse_resistance": 0.10},
        "resource": {"acquisition": 0.40, "utilization": 0.05, "combat_conversion": 0.10, "objective_conversion": 0.25, "thermal_efficiency": 0.20},
        "adaptability": {"side_floor": 0.10, "opponent_floor": 0.10, "strong_opponent_response": 0.15, "setback_response": 0.35, "rematch_improvement": 0.30},
    }
    if not math.isclose(sum(expected_dimension_weights.values()), 1.0):
        failures.append("published tactical dimension weights do not sum to 1")
    for team in teams:
        actual = team["strength_analysis"]["tactical_dimension_weights"]
        if actual != expected_dimension_weights:
            failures.append(f"{team['team']} tactical dimension weights differ from score 4.0")
        alignment = team["strength_analysis"].get("victory_rule_alignment", {})
        if alignment.get("direct_dimension_weight") != 0.75 or alignment.get("enabling_dimension_weight") != 0.25:
            failures.append(f"{team['team']} victory-rule weight split differs from score 4.0")
        if team["strength_analysis"].get("tactical_weight") != 1.0 or team["strength_analysis"].get("result_weight") != 0.0:
            failures.append(f"{team['team']} release strength does not match rolling-origin selected blend")
        for dimension, expected in expected_component_weights.items():
            if team[f"{dimension}_analysis"]["weights"] != expected:
                failures.append(f"{team['team']} {dimension} component weights differ from score 4.0")
        opponent = team.get("opponent_score_analysis", {})
        if opponent.get("enters_strength") is not False or opponent.get("strength_coefficient") != 0.0:
            failures.append(f"{team['team']} transparent opponent score must not duplicate BT strength correction")
        if opponent.get("direct_matches_excluded") is not True:
            failures.append(f"{team['team']} opponent score does not exclude direct meetings")
        breakdown = opponent.get("breakdown", [])
        if len(breakdown) != opponent.get("unique_opponents"):
            failures.append(f"{team['team']} opponent evidence does not cover every unique opponent")
        if any(item.get("opponent_other_games", -1) < item.get("opponent_other_wins", 0) for item in breakdown):
            failures.append(f"{team['team']} opponent evidence has impossible records")
    for region in ("南部赛区", "东部赛区", "北部赛区"):
        regional = [team for team in teams if team["summary"]["region"] == region]
        strength = [team["strength_analysis"]["score"] for team in regional]
        tactical = [team["strength_analysis"]["tactical_score"] for team in regional]
        win_rate = [team["summary"]["win_rate"] for team in regional]
        stage = [team["stage"] for team in regional]
        metrics = {
            "strength_win_spearman": spearman(strength, win_rate),
            "strength_stage_spearman": spearman(strength, stage),
            "tactical_win_spearman": spearman(tactical, win_rate),
            "tactical_stage_spearman": spearman(tactical, stage),
            "top16_auc": auc([value >= 1 for value in stage], strength),
            "top8_auc": auc([value >= 2 for value in stage], strength),
            "top4_auc": auc([value >= 3 for value in stage], strength),
        }
        report["regions"][region] = metrics
        thresholds = {
            "strength_win_spearman": 0.82,
            "strength_stage_spearman": 0.73,
            "tactical_win_spearman": 0.70,
            "tactical_stage_spearman": 0.55,
            "top16_auc": 0.90,
            "top8_auc": 0.90,
            "top4_auc": 0.80,
        }
        for key, threshold in thresholds.items():
            if metrics[key] < threshold:
                failures.append(f"{region} {key}={metrics[key]:.3f} < {threshold:.2f}")
        dimension_thresholds = {
            "firepower": 0.55, "objective": 0.70, "spatial": 0.35,
            "defense": -0.10, "resource": 0.45, "adaptability": -0.10,
        }
        report["regional_dimensions"][region] = {}
        for dimension, threshold in dimension_thresholds.items():
            correlation = spearman([team["scores"][dimension] for team in regional], win_rate)
            report["regional_dimensions"][region][dimension] = correlation
            if correlation < threshold:
                failures.append(f"{region} {dimension} win rho={correlation:.3f} < {threshold:.2f}")

    for dimension in DIMENSIONS:
        values = [team["scores"][dimension] for team in teams]
        win_rate = [team["summary"]["win_rate"] for team in teams]
        report["dimensions"][dimension] = {
            "win_spearman": spearman(values, win_rate),
            "minimum": min(values),
            "maximum": max(values),
        }
    defense_range = report["dimensions"]["defense"]["maximum"] - report["dimensions"]["defense"]["minimum"]
    if defense_range >= 40:
        failures.append(f"defense range {defense_range:.1f} >= 40")
    adaptation = [team["scores"]["adaptability"] for team in teams]
    for dimension in DIMENSIONS[:-1]:
        correlation = abs(spearman(adaptation, [team["scores"][dimension] for team in teams]))
        if correlation >= 0.35:
            failures.append(f"adaptability duplicates {dimension}: |rho|={correlation:.3f}")

    for dimension in DIMENSIONS:
        keys = list(teams[0][f"{dimension}_analysis"]["weights"])
        for index_a, key_a in enumerate(keys):
            for key_b in keys[index_a + 1:]:
                first = [team[f"{dimension}_analysis"]["components"][key_a] for team in teams]
                second = [team[f"{dimension}_analysis"]["components"][key_b] for team in teams]
                correlation = abs(spearman(first, second))
                if correlation >= 0.98:
                    failures.append(f"{dimension} duplicate components {key_a}/{key_b}: |rho|={correlation:.3f}")

    games = {}
    strengths = {team["team"]: team["strength_analysis"]["score"] for team in teams}
    results = {team["team"]: team["strength_analysis"]["result_score"] for team in teams}
    for team in teams:
        for match in team["matches"]:
            games.setdefault(match["game_id"], (team["team"], match["opponent"], bool(match["won"]), team["summary"]["region"]))
    report["matchup_calibration"] = {}
    for region in ("全部", "南部赛区", "东部赛区", "北部赛区"):
        probabilities = []
        outcomes = []
        for primary, opponent, won, game_region in games.values():
            if region != "全部" and game_region != region:
                continue
            result_weight = 0.10 if game_region == "东部赛区" else 0.0
            scale = {"南部赛区": 10.0, "东部赛区": 10.0, "北部赛区": 23.0}[game_region]
            primary_model = (1.0 - result_weight) * strengths[primary] + result_weight * results[primary]
            opponent_model = (1.0 - result_weight) * strengths[opponent] + result_weight * results[opponent]
            probability = 1.0 / (1.0 + math.exp(-(primary_model - opponent_model) / scale))
            probabilities.append(probability)
            outcomes.append(float(won))
        brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes)) / len(outcomes)
        log_loss = -sum(
            outcome * math.log(max(probability, 1e-9)) + (1.0 - outcome) * math.log(max(1.0 - probability, 1e-9))
            for probability, outcome in zip(probabilities, outcomes)
        ) / len(outcomes)
        bias = sum(probabilities) / len(probabilities) - sum(outcomes) / len(outcomes)
        report["matchup_calibration"][region] = {"brier": brier, "log_loss": log_loss, "bias": bias}
        if brier >= 0.21:
            failures.append(f"{region} matchup Brier {brier:.3f} >= 0.21")
        if log_loss >= 0.61:
            failures.append(f"{region} matchup log loss {log_loss:.3f} >= 0.61")
        if abs(bias) >= 0.06:
            failures.append(f"{region} matchup bias {bias:+.3f} outside ±0.06")

    report["tactical_dimension_weights"] = expected_dimension_weights
    report["component_weights"] = expected_component_weights
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("score audit failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
