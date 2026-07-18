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
    report = {"schema": index["schema_version"], "regions": {}, "dimensions": {}}
    for region in ("南部赛区", "东部赛区", "北部赛区"):
        regional = [team for team in teams if team["summary"]["region"] == region]
        strength = [team["strength_analysis"]["score"] for team in regional]
        win_rate = [team["summary"]["win_rate"] for team in regional]
        stage = [team["stage"] for team in regional]
        metrics = {
            "strength_win_spearman": spearman(strength, win_rate),
            "strength_stage_spearman": spearman(strength, stage),
            "top16_auc": auc([value >= 1 for value in stage], strength),
            "top8_auc": auc([value >= 2 for value in stage], strength),
            "top4_auc": auc([value >= 3 for value in stage], strength),
        }
        report["regions"][region] = metrics
        thresholds = {
            "strength_win_spearman": 0.82,
            "strength_stage_spearman": 0.75,
            "top16_auc": 0.90,
            "top8_auc": 0.90,
            "top4_auc": 0.80,
        }
        for key, threshold in thresholds.items():
            if metrics[key] < threshold:
                failures.append(f"{region} {key}={metrics[key]:.3f} < {threshold:.2f}")

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
    for team in teams:
        for match in team["matches"]:
            games.setdefault(match["game_id"], (team["team"], match["opponent"], bool(match["won"])))
    probabilities = []
    outcomes = []
    for primary, opponent, won in games.values():
        probability = 1.0 / (1.0 + math.exp(-(strengths[primary] - strengths[opponent]) / 10.0))
        probabilities.append(probability)
        outcomes.append(float(won))
    brier = sum((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes)) / len(outcomes)
    report["matchup_brier_scale_10"] = brier
    if brier >= 0.18:
        failures.append(f"matchup Brier {brier:.3f} >= 0.18")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("score audit failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
