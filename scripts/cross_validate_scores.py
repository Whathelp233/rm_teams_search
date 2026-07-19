#!/usr/bin/env python3
"""Rolling-origin audit for score and matchup calibration.

Each fold scores only matches already played in every region, then predicts the
next chronological block. This keeps future tactical facts and results out of
the training payload and exposes in-sample improvements that do not generalize.
"""

import argparse
import json
import math
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
DB = ROOT.parent / "sql" / "rmuc_2026_region_dataset.sqlite"
FIXTURE = ROOT / "test" / "fixtures" / "rolling_score_folds.json"
REGIONS = ("南部赛区", "东部赛区", "北部赛区")
FOLDS = ((0.55, 0.70), (0.70, 0.85), (0.85, 1.00))
RELEASE_RESULT_WEIGHTS = {"南部赛区": 0.0, "东部赛区": 0.10, "北部赛区": 0.0}
RELEASE_SCALES = {"南部赛区": 10.0, "东部赛区": 10.0, "北部赛区": 21.0}
RELEASE_STAGE_SCALE_MULTIPLIERS = {
    "南部赛区": {"小组赛": 1.0, "淘汰赛": 0.8},
    "东部赛区": {"小组赛": 1.0, "淘汰赛": 1.0},
    "北部赛区": {"小组赛": 1.0, "淘汰赛": 1.0},
}
RELEASE_GAP_SCALE_MULTIPLIERS = {
    "南部赛区": {"threshold": 10.0, "below": 1.0, "at_or_above": 0.8},
    "东部赛区": {"threshold": 10.0, "below": 1.0, "at_or_above": 1.0},
    "北部赛区": {"threshold": 10.0, "below": 1.0, "at_or_above": 1.0},
}
ELIMINATION_STARTS = {
    "南部赛区": "2026-05-16 14:10:00",
    "东部赛区": "2026-05-24 14:10:00",
    "北部赛区": "2026-06-01 14:10:00",
}
RELEASE_UNCERTAINTY_FLOORS = {"南部赛区": 13.0, "东部赛区": 13.0, "北部赛区": 12.0, "跨赛区": 15.0}
RELEASE_3_8_BASELINE = {
    "overall": {"brier": 0.2271718878310605, "accuracy": 0.6413043478260869},
    "regions": {
        "南部赛区": {"brier": 0.23075645874327472, "accuracy": 0.6304347826086957},
        "东部赛区": {"brier": 0.20993687801060476, "accuracy": 0.6923076923076923},
        "北部赛区": {"brier": 0.2404902251400687, "accuracy": 0.6021505376344086},
    },
    "folds": {
        "1": {"brier": 0.22921308579557478, "accuracy": 0.5978260869565217},
        "2": {"brier": 0.2055769270228248, "accuracy": 0.6847826086956522},
        "3": {"brier": 0.24672565067478205, "accuracy": 0.6413043478260869},
    },
}
DIMENSION_WEIGHTS = {
    "firepower": 0.08, "objective": 0.56, "spatial": 0.12,
    "defense": 0.11, "resource": 0.12, "adaptability": 0.01,
}
CURRENT_COMPONENT_WEIGHTS = {
    "firepower": {"clean_output": 0.35, "accuracy": 0.15, "kill_conversion": 0.25, "pressure_uptime": 0.25},
    "objective": {"outpost_pressure": 0.10, "outpost_conversion": 0.25, "base_pressure": 0.15, "base_conversion": 0.35, "strategic_tools": 0.15},
    "spatial": {"relative_territory": 0.25, "forward_presence": 0.30, "neutral_control": 0.35, "field_coverage": 0.10},
    "defense": {"trade_resilience": 0.35, "mobile_resilience": 0.25, "outpost_denial": 0.15, "base_denial": 0.15, "collapse_resistance": 0.10},
    "resource": {"acquisition": 0.40, "utilization": 0.05, "combat_conversion": 0.10, "objective_conversion": 0.25, "thermal_efficiency": 0.20},
    "adaptability": {"side_floor": 0.10, "opponent_floor": 0.10, "strong_opponent_response": 0.15, "setback_response": 0.35, "rematch_improvement": 0.30},
}
RELEASE_DIMENSION_WEIGHTS = {
    "南部赛区": {**DIMENSION_WEIGHTS, "spatial": 0.15, "defense": 0.08},
    "东部赛区": DIMENSION_WEIGHTS,
    "北部赛区": {**DIMENSION_WEIGHTS, "spatial": 0.05, "resource": 0.19},
}
PREVIOUS_4_2_DIMENSION_WEIGHTS = {
    "南部赛区": DIMENSION_WEIGHTS,
    "东部赛区": DIMENSION_WEIGHTS,
    "北部赛区": {**DIMENSION_WEIGHTS, "spatial": 0.08, "resource": 0.16},
}
LEGACY_COMPONENT_WEIGHTS = {
    "firepower": {"clean_output": 0.30, "accuracy": 0.25, "kill_conversion": 0.25, "pressure_uptime": 0.20},
    "objective": {"outpost_pressure": 0.15, "outpost_conversion": 0.25, "base_pressure": 0.15, "base_conversion": 0.25, "strategic_tools": 0.20},
    "spatial": {"relative_territory": 0.30, "forward_presence": 0.25, "neutral_control": 0.20, "field_coverage": 0.25},
    "defense": {"trade_resilience": 0.25, "mobile_resilience": 0.20, "outpost_denial": 0.20, "base_denial": 0.25, "collapse_resistance": 0.10},
    "resource": {"acquisition": 0.25, "utilization": 0.20, "combat_conversion": 0.20, "objective_conversion": 0.15, "thermal_efficiency": 0.20},
    "adaptability": {"side_floor": 0.10, "opponent_floor": 0.10, "strong_opponent_response": 0.15, "setback_response": 0.35, "rematch_improvement": 0.30},
}
WEIGHT_CANDIDATES = {
    "current": DIMENSION_WEIGHTS,
    "score_3_4": {"firepower": 0.20, "objective": 0.25, "spatial": 0.15, "defense": 0.18, "resource": 0.14, "adaptability": 0.08},
    "legacy_3_2": {"firepower": 0.18, "objective": 0.20, "spatial": 0.15, "defense": 0.19, "resource": 0.13, "adaptability": 0.15},
    "conservative": {"firepower": 0.20, "objective": 0.25, "spatial": 0.15, "defense": 0.16, "resource": 0.14, "adaptability": 0.10},
    "objective_focus": {"firepower": 0.20, "objective": 0.28, "spatial": 0.14, "defense": 0.15, "resource": 0.14, "adaptability": 0.09},
}


def release_scale(region, stage=None, difference=None):
    gap_profile = RELEASE_GAP_SCALE_MULTIPLIERS[region]
    gap_multiplier = 1.0 if difference is None else (
        gap_profile["below"] if abs(difference) < gap_profile["threshold"] else gap_profile["at_or_above"]
    )
    return RELEASE_SCALES[region] * RELEASE_STAGE_SCALE_MULTIPLIERS[region].get(stage, 1.0) * gap_multiplier


def probability(first, second, region, stage=None):
    difference = first - second
    scale = release_scale(region, stage, difference)
    return 1.0 / (1.0 + math.exp(-difference / scale))


def release_result_weight(region):
    return RELEASE_RESULT_WEIGHTS[region]


def release_dimension_weights(region):
    return RELEASE_DIMENSION_WEIGHTS[region]


def release_tactical_diff(dimension_diff, region):
    return sum(dimension_diff[key] * weight for key, weight in release_dimension_weights(region).items())


def release_strength_diff(record):
    region = record["region"]
    result_weight = release_result_weight(region)
    return (
        (1 - result_weight) * release_tactical_diff(record["dimension_diff"], region)
        + result_weight * record["result_diff"]
    )


def match_stage(region, started_at):
    return "淘汰赛" if started_at >= ELIMINATION_STARTS[region] else "小组赛"


def reconstruct_dimension_diffs(record, component_weights):
    return {
        dimension: sum(record["component_diff"][dimension][component] * weight for component, weight in weights.items())
        for dimension, weights in component_weights.items()
    }


def component_probability(record, component_weights):
    region = record["region"]
    tactical_diff = release_tactical_diff(reconstruct_dimension_diffs(record, component_weights), region)
    result_weight = release_result_weight(region)
    difference = (1 - result_weight) * tactical_diff + result_weight * record["result_diff"]
    return probability(difference, 0.0, region, record.get("stage"))


def metrics(rows):
    if not rows:
        return {"games": 0, "brier": None, "log_loss": None, "accuracy": None}
    outcomes = [float(row[1]) for row in rows]
    probabilities = [min(1 - 1e-9, max(1e-9, row[0])) for row in rows]
    return {
        "games": len(rows),
        "brier": sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(rows),
        "log_loss": -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(probabilities, outcomes)) / len(rows),
        "accuracy": sum((p >= 0.5) == bool(y) for p, y in zip(probabilities, outcomes)) / len(rows),
    }


def residual_metrics(rows):
    summary = metrics(rows)
    if not rows:
        return {**summary, "mean_prediction": None, "observed_win_rate": None, "residual": None}
    mean_prediction = sum(row[0] for row in rows) / len(rows)
    observed = sum(float(row[1]) for row in rows) / len(rows)
    return {
        **summary,
        "mean_prediction": mean_prediction,
        "observed_win_rate": observed,
        "residual": observed - mean_prediction,
    }


def confidence_calibration(rows):
    buckets = [[] for _ in range(5)]
    for predicted, outcome in rows:
        confidence = max(predicted, 1.0 - predicted)
        correct = (predicted >= 0.5) == bool(outcome)
        bucket = min(4, max(0, int((confidence - 0.5) / 0.1)))
        buckets[bucket].append((confidence, float(correct)))
    result, ece = [], 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        predicted = sum(item[0] for item in bucket) / len(bucket)
        observed = sum(item[1] for item in bucket) / len(bucket)
        ece += len(bucket) / max(1, len(rows)) * abs(predicted - observed)
        result.append({
            "range": f"{50 + index * 10}–{60 + index * 10}%", "games": len(bucket),
            "predicted": predicted, "observed": observed,
        })
    return {"ece": ece, "bins": result}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-fixture", action="store_true", help="regenerate the derived CI fixture from the private SQLite source")
    parser.add_argument("--fixture-only", action="store_true", help="audit the committed derived fixture without opening SQLite")
    return parser.parse_args()


def load_source():
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    payloads = {}
    games = {}
    for listing in index["teams"]:
        payload = json.loads((DATA / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
        payloads[payload["team"]] = (listing["slug"], payload)
        for match in payload["matches"]:
            games.setdefault(match["game_id"], {
                "game_id": match["game_id"], "region": match["region"], "started_at": match["started_at"],
                "primary": payload["team"], "opponent": match["opponent"], "won": bool(match["won"]),
                "side": match["side"], "match_no": match["match_no"], "round_no": match["round_no"],
                "stage": match_stage(match["region"], match["started_at"]),
            })
    regional = {region: sorted((game for game in games.values() if game["region"] == region), key=lambda game: (game["started_at"], game["game_id"])) for region in REGIONS}
    return index, payloads, regional


def score_fold(index, payloads, train_ids, directory):
    data = directory / "data"
    teams_dir = data / "teams"
    teams_dir.mkdir(parents=True)
    (data / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    counts = Counter()
    for team, (slug, payload) in payloads.items():
        filtered = dict(payload)
        filtered["matches"] = [match for match in payload["matches"] if match["game_id"] in train_ids]
        counts[team] = len(filtered["matches"])
        (teams_dir / f"{slug}.json").write_text(json.dumps(filtered, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "recalculate_scores.py"), "--db", str(DB), "--data", str(data), "--backtest"],
        cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
    )
    scored = {}
    for team, (slug, _) in payloads.items():
        payload = json.loads((teams_dir / f"{slug}.json").read_text(encoding="utf-8"))
        scored[team] = {
            "strength": payload["strength_analysis"],
            "scores": payload["scores"],
            "components": {
                dimension: payload[f"{dimension}_analysis"]["components"]
                for dimension in DIMENSION_WEIGHTS
            },
            "opponent_score": payload["opponent_score_analysis"]["score"],
        }
    return scored, counts


def build_records():
    index, payloads, regional = load_source()
    records = []
    with tempfile.TemporaryDirectory(prefix="rmuc-score-cv-") as temporary:
        root = Path(temporary)
        for fold_number, (train_fraction, test_fraction) in enumerate(FOLDS, 1):
            train_ids, tests = set(), []
            for region, games in regional.items():
                train_end = round(len(games) * train_fraction)
                test_end = round(len(games) * test_fraction)
                train_ids.update(game["game_id"] for game in games[:train_end])
                tests.extend(games[train_end:test_end])
            fold_dir = root / f"fold-{fold_number}"
            scored, counts = score_fold(index, payloads, train_ids, fold_dir)
            eligible = [game for game in tests if counts[game["primary"]] >= 3 and counts[game["opponent"]] >= 3]
            for game in eligible:
                first, second = scored[game["primary"]], scored[game["opponent"]]
                first_strength, second_strength = first["strength"], second["strength"]
                direct_history = [
                    match for match in payloads[game["primary"]][1]["matches"]
                    if match["game_id"] in train_ids and match["opponent"] == game["opponent"]
                ]
                records.append({
                    "fold": fold_number, "region": game["region"], "won": game["won"],
                    "side": game["side"], "stage": game["stage"],
                    "match_no": game["match_no"], "round_no": game["round_no"],
                    "dimension_diff": {dimension: round(first["scores"][dimension] - second["scores"][dimension], 3) for dimension in DIMENSION_WEIGHTS},
                    "component_diff": {
                        dimension: {
                            component: round(value - second["components"][dimension][component], 3)
                            for component, value in first["components"][dimension].items()
                        }
                        for dimension in DIMENSION_WEIGHTS
                    },
                    "result_diff": round(first_strength["result_score"] - second_strength["result_score"], 3),
                    "opponent_score_diff": round(first["opponent_score"] - second["opponent_score"], 3),
                    "h2h_games": len(direct_history),
                    "h2h_wins": sum(bool(match.get("won")) for match in direct_history),
                })
    return records


def main():
    args = parse_args()
    if DB.exists() and not args.fixture_only:
        records = build_records()
        if args.write_fixture:
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text(json.dumps({"schema_version": "4.1.0", "records": records}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        if fixture.get("schema_version") != "4.1.0":
            raise SystemExit("rolling score fixture does not match score schema 4.1.0")
        records = fixture["records"]

    rows = {model: defaultdict(list) for model in ("strength", "tactical", "result")}
    observations = defaultdict(list)
    fold_rows = defaultdict(list)
    regional_fold_rows = defaultdict(list)
    for record in records:
        dimension_diff = record["dimension_diff"]
        result_diff = record["result_diff"]
        tactical_diff = release_tactical_diff(dimension_diff, record["region"])
        result_weight = release_result_weight(record["region"])
        strength_diff = (1 - result_weight) * tactical_diff + result_weight * result_diff
        model_diffs = {"strength": strength_diff, "tactical": tactical_diff, "result": result_diff}
        for model, difference in model_diffs.items():
            row = (probability(difference, 0.0, record["region"], record.get("stage")), record["won"])
            rows[model][record["region"]].append(row)
            if model == "strength":
                fold_rows[record["fold"]].append(row)
                regional_fold_rows[(record["region"], record["fold"])].append(row)
        observations[record["region"]].append((dimension_diff, result_diff, record["won"]))
    fold_report = [
        {"fold": fold_number, "train_fraction": train_fraction, "test_fraction": test_fraction, **metrics(fold_rows[fold_number])}
        for fold_number, (train_fraction, test_fraction) in enumerate(FOLDS, 1)
    ]

    report = {"folds": fold_report, "regions": {}, "overall": {}, "candidate": {}, "calibration": {}, "fold_calibration": {}, "stratified_residuals": {}, "structural_correction_validation": {}, "south_scale_validation": {}, "north_profile_validation": {}, "regional_profile_validation": {}, "head_to_head_adjustment": {}, "opponent_score_adjustment": {}, "component_weight_validation": {}, "component_reconstruction": {}, "component_ablation_by_region_fold": {}, "component_weight_perturbation": {}, "weight_candidates": {}, "dimension_ablation": {}, "dimension_ablation_by_region_fold": {}, "blend_grid": {}}
    failures = []
    for dimension, weights in CURRENT_COMPONENT_WEIGHTS.items():
        errors = [
            abs(sum(record["component_diff"][dimension][component] * weight for component, weight in weights.items()) - record["dimension_diff"][dimension])
            for record in records
        ]
        report["component_reconstruction"][dimension] = {
            "max_abs_error": max(errors),
            "mean_abs_error": sum(errors) / len(errors),
            "rounding_tolerance": 0.15,
        }
        if max(errors) > 0.15:
            failures.append(f"{dimension} component weights no longer reconstruct the published dimension difference")

    def component_profile(component_weights):
        profile_rows = defaultdict(lambda: defaultdict(list))
        for record in records:
            profile_rows[record["region"]][record["fold"]].append((component_probability(record, component_weights), record["won"]))
        return {
            region: {
                "overall": metrics([row for fold in range(1, len(FOLDS) + 1) for row in profile_rows[region][fold]]),
                "folds": {str(fold): metrics(profile_rows[region][fold]) for fold in range(1, len(FOLDS) + 1)},
            }
            for region in REGIONS
        }

    component_baseline = component_profile(CURRENT_COMPONENT_WEIGHTS)
    for dimension, weights in CURRENT_COMPONENT_WEIGHTS.items():
        for removed in weights:
            remaining = {key: value for key, value in weights.items() if key != removed}
            total = sum(remaining.values())
            candidate_weights = {name: dict(values) for name, values in CURRENT_COMPONENT_WEIGHTS.items()}
            candidate_weights[dimension] = {key: value / total for key, value in remaining.items()}
            candidate_profile = component_profile(candidate_weights)
            key = f"{dimension}.{removed}"
            report["component_ablation_by_region_fold"][key] = {
                region: {
                    "overall_brier_delta": candidate_profile[region]["overall"]["brier"] - component_baseline[region]["overall"]["brier"],
                    "folds": {
                        str(fold): {
                            "brier_delta": candidate_profile[region]["folds"][str(fold)]["brier"] - component_baseline[region]["folds"][str(fold)]["brier"],
                            "accuracy_delta": candidate_profile[region]["folds"][str(fold)]["accuracy"] - component_baseline[region]["folds"][str(fold)]["accuracy"],
                        }
                        for fold in range(1, len(FOLDS) + 1)
                    },
                }
                for region in REGIONS
            }

    perturbations = []
    for dimension, weights in CURRENT_COMPONENT_WEIGHTS.items():
        for donor in weights:
            for receiver in weights:
                if donor == receiver:
                    continue
                for shift in (0.01, 0.02, 0.03, 0.04, 0.05):
                    if weights[donor] < shift:
                        continue
                    candidate_weights = {name: dict(values) for name, values in CURRENT_COMPONENT_WEIGHTS.items()}
                    candidate_weights[dimension][donor] -= shift
                    candidate_weights[dimension][receiver] += shift
                    candidate_profile = component_profile(candidate_weights)
                    brier_deltas, accuracy_deltas = [], []
                    for region in REGIONS:
                        for fold in range(1, len(FOLDS) + 1):
                            key = str(fold)
                            brier_deltas.append(candidate_profile[region]["folds"][key]["brier"] - component_baseline[region]["folds"][key]["brier"])
                            accuracy_deltas.append(candidate_profile[region]["folds"][key]["accuracy"] - component_baseline[region]["folds"][key]["accuracy"])
                    perturbations.append({
                        "dimension": dimension, "move": f"{donor}→{receiver}", "weight_shift": shift,
                        "max_fold_brier_delta": max(brier_deltas), "sum_fold_brier_delta": sum(brier_deltas),
                        "min_fold_accuracy_delta": min(accuracy_deltas),
                        "non_worse_brier_folds": sum(delta <= 1e-12 for delta in brier_deltas),
                    })
    perturbations.sort(key=lambda item: (item["max_fold_brier_delta"], item["sum_fold_brier_delta"]))
    passing_perturbations = [
        item for item in perturbations
        if item["max_fold_brier_delta"] <= 1e-12 and item["min_fold_accuracy_delta"] >= -1e-12
    ]
    report["component_weight_perturbation"] = {
        "selected": "current",
        "tested_steps": [0.01, 0.02, 0.03, 0.04, 0.05],
        "region_fold_tests_per_candidate": len(REGIONS) * len(FOLDS),
        "passing_candidates": passing_perturbations,
        "best_by_worst_fold": perturbations[:10],
        "reason": "keep globally comparable component weights unless a one-to-five-point transfer improves or preserves Brier and accuracy in all nine region-fold tests",
    }
    if passing_perturbations:
        failures.append("a component-weight transfer now dominates the release in all region-fold tests; recalibration is required")
    for region in REGIONS:
        report["regions"][region] = {model: metrics(rows[model][region]) for model in rows}
        strength = report["regions"][region]["strength"]
        if strength["games"] < 50:
            failures.append(f"{region} has only {strength['games']} eligible chronological test games")
    for model in rows:
        combined = [row for region in REGIONS for row in rows[model][region]]
        report["overall"][model] = metrics(combined)
    candidate_all = []
    candidate_rows_by_region = {}
    for region in REGIONS:
        result_weight = release_result_weight(region)
        candidate_rows = [
            (probability(release_strength_diff(record), 0.0, region, record.get("stage")), record["won"])
            for record in records if record["region"] == region
        ]
        report["candidate"][region] = {
            "result_weight": result_weight,
            "base_scale": RELEASE_SCALES[region],
            "stage_scale_multipliers": RELEASE_STAGE_SCALE_MULTIPLIERS[region],
            "gap_scale_multipliers": RELEASE_GAP_SCALE_MULTIPLIERS[region],
            **metrics(candidate_rows),
        }
        candidate_rows_by_region[region] = candidate_rows
        candidate_all.extend(candidate_rows)
        if report["candidate"][region]["brier"] >= 0.25:
            failures.append(f"{region} candidate chronological Brier {report['candidate'][region]['brier']:.3f} >= 0.25")
        if report["candidate"][region]["log_loss"] >= 0.70:
            failures.append(f"{region} candidate chronological log loss {report['candidate'][region]['log_loss']:.3f} >= 0.70")
        if report["candidate"][region]["accuracy"] < 0.55:
            failures.append(f"{region} candidate chronological accuracy {report['candidate'][region]['accuracy']:.3f} < 0.55")
    report["candidate"]["全部"] = metrics(candidate_all)
    if report["candidate"]["全部"]["brier"] >= 0.24:
        failures.append(f"overall candidate chronological Brier {report['candidate']['全部']['brier']:.3f} >= 0.24")
    if report["candidate"]["全部"]["accuracy"] < 0.60:
        failures.append(f"overall candidate chronological accuracy {report['candidate']['全部']['accuracy']:.3f} < 0.60")
    for region, calibration_rows in [*candidate_rows_by_region.items(), ("全部", candidate_all)]:
        calibration = confidence_calibration(calibration_rows)
        report["calibration"][region] = calibration
        threshold = 0.06 if region == "全部" else 0.10
        if calibration["ece"] >= threshold:
            failures.append(f"{region} confidence calibration ECE {calibration['ece']:.3f} >= {threshold:.2f}")

    # Diagnose systematic residuals on facts that are known before a game:
    # actual alliance colour, competition stage, and pre-game strength gap.
    # These groups are diagnostic rather than extra score inputs; tiny groups
    # are retained in the report but never used to justify a release change.
    stratified = defaultdict(lambda: defaultdict(list))
    for record in records:
        difference = release_strength_diff(record)
        predicted = probability(difference, 0.0, record["region"], record.get("stage"))
        absolute_gap = abs(difference)
        gap_bucket = "0–5" if absolute_gap < 5 else "5–10" if absolute_gap < 10 else "10–20" if absolute_gap < 20 else "20+"
        row = (predicted, record["won"])
        scopes = ("全部", record["region"])
        for scope in scopes:
            stratified[scope][f"红蓝方/{record['side']}"].append(row)
            stratified[scope][f"赛段/{record['stage']}"].append(row)
            stratified[scope][f"强弱差/{gap_bucket}"].append(row)
    report["stratified_residuals"] = {
        scope: {group: residual_metrics(group_rows) for group, group_rows in sorted(groups.items())}
        for scope, groups in stratified.items()
    }

    def correction_profile(region, transform):
        by_fold = defaultdict(list)
        for record in records:
            if record["region"] != region:
                continue
            release_difference = release_strength_diff(record)
            difference, scale = transform(
                record, release_difference, release_scale(region, record.get("stage"), release_difference)
            )
            by_fold[record["fold"]].append((1.0 / (1.0 + math.exp(-difference / scale)), record["won"]))
        combined = [row for fold in range(1, len(FOLDS) + 1) for row in by_fold[fold]]
        return {
            "overall": metrics(combined),
            "folds": {str(fold): metrics(by_fold[fold]) for fold in range(1, len(FOLDS) + 1)},
        }

    def correction_candidate(region, family, value):
        if family == "side_intercept":
            return correction_profile(region, lambda record, difference, scale: (
                difference + (value if record["side"] == "红" else -value), scale
            ))
        if family == "elimination_scale":
            return correction_profile(region, lambda record, difference, scale: (
                difference, scale * (value if record["stage"] == "淘汰赛" else 1.0)
            ))
        low_multiplier, high_multiplier = value
        return correction_profile(region, lambda record, difference, scale: (
            difference, scale * (low_multiplier if abs(difference) < 10 else high_multiplier)
        ))

    correction_grids = {
        "side_intercept": [step / 2 for step in range(-8, 9)],
        "elimination_scale": [step / 10 for step in range(7, 14)],
        "segmented_scale": [(low / 10, high / 10) for low in range(8, 13) for high in range(8, 13)],
    }
    correction_report = {}
    for region in REGIONS:
        baseline_profile = correction_profile(region, lambda record, difference, scale: (difference, scale))
        region_report = {"baseline": baseline_profile, "families": {}}
        for family, values in correction_grids.items():
            candidates = []
            for value in values:
                profile = correction_candidate(region, family, value)
                brier_deltas = [
                    profile["folds"][str(fold)]["brier"] - baseline_profile["folds"][str(fold)]["brier"]
                    for fold in range(1, len(FOLDS) + 1)
                ]
                accuracy_deltas = [
                    profile["folds"][str(fold)]["accuracy"] - baseline_profile["folds"][str(fold)]["accuracy"]
                    for fold in range(1, len(FOLDS) + 1)
                ]
                candidates.append({
                    "value": list(value) if isinstance(value, tuple) else value,
                    "overall": profile["overall"],
                    "folds": profile["folds"],
                    "overall_brier_delta": profile["overall"]["brier"] - baseline_profile["overall"]["brier"],
                    "max_fold_brier_delta": max(brier_deltas),
                    "min_fold_accuracy_delta": min(accuracy_deltas),
                })
            candidates.sort(key=lambda item: (item["max_fold_brier_delta"], item["overall_brier_delta"]))
            stable = [
                candidate for candidate in candidates
                if candidate["max_fold_brier_delta"] <= 1e-12
                and candidate["min_fold_accuracy_delta"] >= -1e-12
                and candidate["overall_brier_delta"] <= -0.001
            ]
            region_report["families"][family] = {
                "selection": "release",
                "minimum_overall_brier_gain": 0.001,
                "stable_candidates": stable,
                "best_by_worst_fold": candidates[:5],
            }
            if stable:
                failures.append(f"{region} {family} has a stable structural correction; release calibration must be reviewed")
        correction_report[region] = region_report
    report["structural_correction_validation"] = correction_report

    for region in REGIONS:
        folds = {str(fold): confidence_calibration(regional_fold_rows[(region, fold)]) for fold in range(1, len(FOLDS) + 1)}
        mean_ece_pct = 100.0 * sum(item["ece"] for item in folds.values()) / len(folds)
        report["fold_calibration"][region] = {
            "folds": folds,
            "mean_ece_pct": mean_ece_pct,
            "uncertainty_floor_pct": RELEASE_UNCERTAINTY_FLOORS[region],
        }
        if RELEASE_UNCERTAINTY_FLOORS[region] + 1e-9 < math.ceil(mean_ece_pct):
            failures.append(f"{region} uncertainty floor is narrower than mean rolling-fold ECE")
    south_scale_rows = {"uniform_scale_10": defaultdict(list), "release_stage_and_gap_scale": defaultdict(list)}
    for record in records:
        if record["region"] != "南部赛区":
            continue
        difference = release_tactical_diff(record["dimension_diff"], record["region"])
        south_scale_rows["uniform_scale_10"][record["fold"]].append((1.0 / (1.0 + math.exp(-difference / 10.0)), record["won"]))
        south_scale_rows["release_stage_and_gap_scale"][record["fold"]].append((probability(difference, 0.0, record["region"], record.get("stage")), record["won"]))
    for profile, by_fold in south_scale_rows.items():
        combined = [row for fold in range(1, len(FOLDS) + 1) for row in by_fold[fold]]
        report["south_scale_validation"][profile] = {
            "overall": metrics(combined),
            "folds": {str(fold): metrics(by_fold[fold]) for fold in range(1, len(FOLDS) + 1)},
        }
    south_uniform = report["south_scale_validation"]["uniform_scale_10"]
    south_release = report["south_scale_validation"]["release_stage_and_gap_scale"]
    if south_release["overall"]["brier"] >= south_uniform["overall"]["brier"] - 0.001:
        failures.append("South stage-aware scale does not improve overall chronological Brier by at least 0.001")
    for fold in range(1, len(FOLDS) + 1):
        key = str(fold)
        if south_release["folds"][key]["brier"] > south_uniform["folds"][key]["brier"] + 1e-12:
            failures.append(f"South stage-aware scale worsens fold {fold} chronological Brier")
        if south_release["folds"][key]["accuracy"] < south_uniform["folds"][key]["accuracy"]:
            failures.append(f"South stage-aware scale reduces fold {fold} chronological accuracy")
    for region in REGIONS:
        profiles = {"previous_4_2": defaultdict(list), "release_4_3": defaultdict(list)}
        for record in records:
            if record["region"] != region:
                continue
            for name, weights in (("previous_4_2", PREVIOUS_4_2_DIMENSION_WEIGHTS[region]), ("release_4_3", RELEASE_DIMENSION_WEIGHTS[region])):
                tactical_diff = sum(record["dimension_diff"][key] * weight for key, weight in weights.items())
                result_weight = release_result_weight(region)
                difference = (1 - result_weight) * tactical_diff + result_weight * record["result_diff"]
                profiles[name][record["fold"]].append((probability(difference, 0.0, region, record.get("stage")), record["won"]))
        report["regional_profile_validation"][region] = {}
        for name, by_fold in profiles.items():
            combined = [row for fold in range(1, len(FOLDS) + 1) for row in by_fold[fold]]
            report["regional_profile_validation"][region][name] = {
                "weights": PREVIOUS_4_2_DIMENSION_WEIGHTS[region] if name == "previous_4_2" else RELEASE_DIMENSION_WEIGHTS[region],
                "overall": metrics(combined),
                "folds": {str(fold): metrics(by_fold[fold]) for fold in range(1, len(FOLDS) + 1)},
            }
        if region in ("南部赛区", "北部赛区"):
            previous = report["regional_profile_validation"][region]["previous_4_2"]
            release_profile = report["regional_profile_validation"][region]["release_4_3"]
            if release_profile["overall"]["brier"] >= previous["overall"]["brier"] - 0.001:
                failures.append(f"{region} 4.3 profile does not improve overall chronological Brier by at least 0.001")
            for fold in range(1, len(FOLDS) + 1):
                key = str(fold)
                if release_profile["folds"][key]["brier"] >= previous["folds"][key]["brier"]:
                    failures.append(f"{region} 4.3 profile does not improve fold {fold} chronological Brier")
                if release_profile["folds"][key]["accuracy"] < previous["folds"][key]["accuracy"]:
                    failures.append(f"{region} 4.3 profile reduces fold {fold} chronological accuracy")
    north_profiles = {"global": defaultdict(list), "release": defaultdict(list)}
    for record in records:
        if record["region"] != "北部赛区":
            continue
        global_diff = sum(record["dimension_diff"][key] * weight for key, weight in DIMENSION_WEIGHTS.items())
        release_diff = release_tactical_diff(record["dimension_diff"], record["region"])
        north_profiles["global"][record["fold"]].append((1.0 / (1.0 + math.exp(-global_diff / 23.0)), record["won"]))
        north_profiles["release"][record["fold"]].append((1.0 / (1.0 + math.exp(-release_diff / RELEASE_SCALES["北部赛区"])), record["won"]))
    for profile, by_fold in north_profiles.items():
        combined = [row for fold in range(1, len(FOLDS) + 1) for row in by_fold[fold]]
        report["north_profile_validation"][profile] = {
            "overall": metrics(combined),
            "folds": {str(fold): metrics(by_fold[fold]) for fold in range(1, len(FOLDS) + 1)},
        }
    north_global = report["north_profile_validation"]["global"]
    north_release = report["north_profile_validation"]["release"]
    if north_release["overall"]["brier"] >= north_global["overall"]["brier"] - 0.001:
        failures.append("North regional profile does not improve chronological Brier by at least 0.001")
    if north_release["overall"]["accuracy"] < north_global["overall"]["accuracy"]:
        failures.append("North regional profile reduces chronological accuracy")
    for fold in range(1, len(FOLDS) + 1):
        key = str(fold)
        if north_release["folds"][key]["brier"] > north_global["folds"][key]["brier"]:
            failures.append(f"North regional profile worsens fold {fold} chronological Brier")
        if north_release["folds"][key]["accuracy"] < north_global["folds"][key]["accuracy"]:
            failures.append(f"North regional profile reduces fold {fold} chronological accuracy")
    h2h_rows = {"release": defaultdict(list), "legacy_blend": defaultdict(list)}
    h2h_history_rows = {"release": [], "legacy_blend": []}
    for record in records:
        dimension_diff, result_diff, region = record["dimension_diff"], record["result_diff"], record["region"]
        result_weight = release_result_weight(region)
        difference = (1 - result_weight) * release_tactical_diff(dimension_diff, region) + result_weight * result_diff
        base_probability = probability(difference, 0.0, region, record.get("stage"))
        games, wins = int(record.get("h2h_games", 0)), int(record.get("h2h_wins", 0))
        smoothed_rate = (wins + 1) / (games + 2)
        legacy_weight = min(0.30, games * 0.06)
        legacy_probability = base_probability * (1 - legacy_weight) + smoothed_rate * legacy_weight
        for name, predicted in (("release", base_probability), ("legacy_blend", legacy_probability)):
            row = (predicted, record["won"])
            h2h_rows[name][region].append(row)
            if games:
                h2h_history_rows[name].append(row)
    for name in h2h_rows:
        combined = [row for region in REGIONS for row in h2h_rows[name][region]]
        report["head_to_head_adjustment"][name] = {
            "overall": metrics(combined),
            "with_history": metrics(h2h_history_rows[name]),
            "regions": {region: metrics(h2h_rows[name][region]) for region in REGIONS},
        }
    h2h_release = report["head_to_head_adjustment"]["release"]
    h2h_legacy = report["head_to_head_adjustment"]["legacy_blend"]
    if h2h_release["overall"]["brier"] >= h2h_legacy["overall"]["brier"] - 0.0001:
        failures.append("disabling direct-meeting probability blend does not improve chronological Brier")
    if h2h_release["overall"]["accuracy"] < h2h_legacy["overall"]["accuracy"] - 0.01:
        failures.append("disabling direct-meeting probability blend reduces chronological accuracy by more than one point")
    # A transparent Buchholz-like opponent score is useful schedule context,
    # but BT already performs the scored opponent correction.  Test positive
    # coefficients explicitly so a future release cannot silently double count it.
    opponent_candidates = {}
    for coefficient in (0.0, 0.05, 0.10, 0.25):
        candidate_by_region = defaultdict(list)
        candidate_by_fold = defaultdict(list)
        for record in records:
            tactical_diff = release_tactical_diff(record["dimension_diff"], record["region"])
            result_weight = release_result_weight(record["region"])
            difference = (
                (1 - result_weight) * tactical_diff
                + result_weight * record["result_diff"]
                + coefficient * record["opponent_score_diff"]
            )
            row = (probability(difference, 0.0, record["region"], record.get("stage")), record["won"])
            candidate_by_region[record["region"]].append(row)
            candidate_by_fold[record["fold"]].append(row)
        combined = [row for region in REGIONS for row in candidate_by_region[region]]
        opponent_candidates[f"coefficient_{coefficient:.2f}"] = {
            "overall": metrics(combined),
            "regions": {region: metrics(candidate_by_region[region]) for region in REGIONS},
            "folds": {str(fold): metrics(candidate_by_fold[fold]) for fold in range(1, len(FOLDS) + 1)},
        }
    report["opponent_score_adjustment"] = {
        "selected_coefficient": 0.0,
        "enters_strength": False,
        "reason": "Bradley-Terry and opponent score remain schedule evidence; neither is added to tactical strength because positive schedule coefficients do not improve rolling-origin validation",
        "candidates": opponent_candidates,
    }
    release_opponent = opponent_candidates["coefficient_0.00"]["overall"]
    if abs(release_opponent["brier"] - report["overall"]["strength"]["brier"]) > 1e-12:
        failures.append("zero opponent-score coefficient does not reconstruct release strength")
    component_models = {"score_4_0": defaultdict(list), "score_3_8": defaultdict(list)}
    component_folds = {name: defaultdict(list) for name in component_models}
    for record in records:
        regional_weights = release_dimension_weights(record["region"])
        current_tactical = sum(record["dimension_diff"][dimension] * weight for dimension, weight in regional_weights.items())
        legacy_tactical = sum(
            regional_weights[dimension] * sum(
                record["component_diff"][dimension][component] * weight
                for component, weight in LEGACY_COMPONENT_WEIGHTS[dimension].items()
            )
            for dimension in DIMENSION_WEIGHTS
        )
        for name, tactical_diff in (("score_4_0", current_tactical), ("score_3_8", legacy_tactical)):
            result_weight = release_result_weight(record["region"])
            difference = (1 - result_weight) * tactical_diff + result_weight * record["result_diff"]
            row = (probability(difference, 0.0, record["region"], record.get("stage")), record["won"])
            component_models[name][record["region"]].append(row)
            component_folds[name][record["fold"]].append(row)
    for name in component_models:
        combined = [row for region in REGIONS for row in component_models[name][region]]
        report["component_weight_validation"][name] = {
            "overall": metrics(combined),
            "regions": {region: metrics(component_models[name][region]) for region in REGIONS},
            "folds": {str(fold): metrics(component_folds[name][fold]) for fold in range(1, len(FOLDS) + 1)},
        }
    component_release = report["component_weight_validation"]["score_4_0"]
    component_legacy = report["component_weight_validation"]["score_3_8"]
    # The reconstructed legacy view isolates internal component weights while
    # keeping 4.0 raw facts. Publication gates compare against the immutable
    # score-3.8 rolling fixture metrics, so changed terminal-HP facts cannot make
    # the baseline move with the candidate.
    report["release_3_8_baseline"] = RELEASE_3_8_BASELINE
    if component_release["overall"]["brier"] >= RELEASE_3_8_BASELINE["overall"]["brier"]:
        failures.append("score 4.0 does not improve overall chronological Brier over released score 3.8")
    if component_release["overall"]["accuracy"] < RELEASE_3_8_BASELINE["overall"]["accuracy"]:
        failures.append("score 4.0 reduces overall chronological accuracy versus released score 3.8")
    for region in REGIONS:
        baseline = RELEASE_3_8_BASELINE["regions"][region]
        if component_release["regions"][region]["brier"] >= baseline["brier"]:
            failures.append(f"score 4.0 does not improve {region} chronological Brier over released score 3.8")
        if component_release["regions"][region]["accuracy"] < baseline["accuracy"]:
            failures.append(f"score 4.0 reduces {region} chronological accuracy versus released score 3.8")
    for fold in range(1, len(FOLDS) + 1):
        key = str(fold)
        baseline = RELEASE_3_8_BASELINE["folds"][key]
        if component_release["folds"][key]["brier"] >= baseline["brier"]:
            failures.append(f"score 4.0 does not improve fold {fold} chronological Brier over released score 3.8")
        if component_release["folds"][key]["accuracy"] < baseline["accuracy"]:
            failures.append(f"score 4.0 reduces fold {fold} chronological accuracy versus released score 3.8")
    for name, candidate_weights in WEIGHT_CANDIDATES.items():
        candidate_rows = []
        regional_metrics = {}
        for region in REGIONS:
            result_weight = release_result_weight(region)
            weights = release_dimension_weights(region) if name == "current" else candidate_weights
            regional_rows = [
                (
                    probability(
                        (1 - result_weight) * sum(record["dimension_diff"][key] * weight for key, weight in weights.items())
                        + result_weight * record["result_diff"],
                        0.0, region, record.get("stage"),
                    ),
                    record["won"],
                )
                for record in records if record["region"] == region
            ]
            regional_metrics[region] = metrics(regional_rows)
            candidate_rows.extend(regional_rows)
        report["weight_candidates"][name] = {"regions": regional_metrics, "overall": metrics(candidate_rows)}
    baseline = report["weight_candidates"]["score_3_4"]
    release = report["weight_candidates"]["current"]
    if release["overall"]["brier"] >= baseline["overall"]["brier"] - 0.001:
        failures.append("score 4.0 weights do not improve chronological Brier by at least 0.001 over score 3.4")
    if release["overall"]["accuracy"] < baseline["overall"]["accuracy"]:
        failures.append("score 4.0 weights reduce chronological accuracy versus score 3.4")
    for region in REGIONS:
        if release["regions"][region]["brier"] > baseline["regions"][region]["brier"]:
            failures.append(f"score 4.0 weights worsen {region} chronological Brier versus score 3.4")
    for removed in (None, *DIMENSION_WEIGHTS):
        ablation_rows = []
        ablation_regions = defaultdict(list)
        ablation_folds = defaultdict(lambda: defaultdict(list))
        for region in REGIONS:
            weights = {key: value for key, value in release_dimension_weights(region).items() if key != removed}
            total = sum(weights.values())
            weights = {key: value / total for key, value in weights.items()}
            result_weight = release_result_weight(region)
            regional_rows = [
                (
                    probability(
                        (1 - result_weight) * sum(record["dimension_diff"][key] * weight for key, weight in weights.items())
                        + result_weight * record["result_diff"],
                        0.0, region, record.get("stage"),
                    ),
                    record["won"],
                )
                for record in records if record["region"] == region
            ]
            ablation_rows.extend(regional_rows)
            ablation_regions[region].extend(regional_rows)
            for record in records:
                if record["region"] != region:
                    continue
                tactical_diff = sum(record["dimension_diff"][key] * weight for key, weight in weights.items())
                difference = (1 - result_weight) * tactical_diff + result_weight * record["result_diff"]
                ablation_folds[region][record["fold"]].append((probability(difference, 0.0, region, record.get("stage")), record["won"]))
        ablation_name = "all" if removed is None else f"without_{removed}"
        report["dimension_ablation"][ablation_name] = metrics(ablation_rows)
        report["dimension_ablation_by_region_fold"][ablation_name] = {
            region: {
                "overall": metrics(ablation_regions[region]),
                "folds": {str(fold): metrics(ablation_folds[region][fold]) for fold in range(1, len(FOLDS) + 1)},
            }
            for region in REGIONS
        }
    for result_weight in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25):
        regional_best = {}
        combined_rows = []
        for region in REGIONS:
            candidates = []
            for scale in range(8, 31):
                candidate_rows = [
                    (1.0 / (1.0 + math.exp(-((1 - result_weight) * sum(dimension_diff[key] * weight for key, weight in release_dimension_weights(region).items()) + result_weight * result_diff) / scale)), won)
                    for dimension_diff, result_diff, won in observations[region]
                ]
                candidates.append((metrics(candidate_rows)["brier"], scale, candidate_rows))
            best_brier, best_scale, best_rows = min(candidates, key=lambda item: item[0])
            regional_best[region] = {"scale": best_scale, "brier": best_brier}
            combined_rows.extend(best_rows)
        report["blend_grid"][f"result_{result_weight:.2f}"] = {
            "regional_best": regional_best, "overall": metrics(combined_rows),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("cross-validation audit failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
