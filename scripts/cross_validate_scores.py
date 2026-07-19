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


def probability(first, second, region):
    scale = RELEASE_SCALES[region]
    return 1.0 / (1.0 + math.exp(-(first - second) / scale))


def release_result_weight(region):
    return RELEASE_RESULT_WEIGHTS[region]


def release_dimension_weights(region):
    if region == "北部赛区":
        return {**DIMENSION_WEIGHTS, "spatial": 0.08, "resource": 0.16}
    return DIMENSION_WEIGHTS


def release_tactical_diff(dimension_diff, region):
    return sum(dimension_diff[key] * weight for key, weight in release_dimension_weights(region).items())


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
            FIXTURE.write_text(json.dumps({"schema_version": "4.0.0", "records": records}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        if fixture.get("schema_version") != "4.0.0":
            raise SystemExit("rolling score fixture does not match score schema 4.0.0")
        records = fixture["records"]

    rows = {model: defaultdict(list) for model in ("strength", "tactical", "result")}
    observations = defaultdict(list)
    fold_rows = defaultdict(list)
    for record in records:
        dimension_diff = record["dimension_diff"]
        result_diff = record["result_diff"]
        tactical_diff = release_tactical_diff(dimension_diff, record["region"])
        result_weight = release_result_weight(record["region"])
        strength_diff = (1 - result_weight) * tactical_diff + result_weight * result_diff
        model_diffs = {"strength": strength_diff, "tactical": tactical_diff, "result": result_diff}
        for model, difference in model_diffs.items():
            row = (probability(difference, 0.0, record["region"]), record["won"])
            rows[model][record["region"]].append(row)
            if model == "strength":
                fold_rows[record["fold"]].append(row)
        observations[record["region"]].append((dimension_diff, result_diff, record["won"]))
    fold_report = [
        {"fold": fold_number, "train_fraction": train_fraction, "test_fraction": test_fraction, **metrics(fold_rows[fold_number])}
        for fold_number, (train_fraction, test_fraction) in enumerate(FOLDS, 1)
    ]

    report = {"folds": fold_report, "regions": {}, "overall": {}, "candidate": {}, "calibration": {}, "north_profile_validation": {}, "head_to_head_adjustment": {}, "opponent_score_adjustment": {}, "component_weight_validation": {}, "weight_candidates": {}, "dimension_ablation": {}, "blend_grid": {}}
    failures = []
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
        scale = RELEASE_SCALES[region]
        result_weight = release_result_weight(region)
        candidate_rows = [
            (1.0 / (1.0 + math.exp(-((1 - result_weight) * release_tactical_diff(dimension_diff, region) + result_weight * result_diff) / scale)), won)
            for dimension_diff, result_diff, won in observations[region]
        ]
        report["candidate"][region] = {"result_weight": result_weight, "scale": scale, **metrics(candidate_rows)}
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
        base_probability = probability(difference, 0.0, region)
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
            row = (probability(difference, 0.0, record["region"]), record["won"])
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
            row = (probability(difference, 0.0, record["region"]), record["won"])
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
            scale = RELEASE_SCALES[region]
            result_weight = release_result_weight(region)
            weights = release_dimension_weights(region) if name == "current" else candidate_weights
            regional_rows = [
                (1.0 / (1.0 + math.exp(-((1 - result_weight) * sum(dimension_diff[key] * weight for key, weight in weights.items()) + result_weight * result_diff) / scale)), won)
                for dimension_diff, result_diff, won in observations[region]
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
        for region in REGIONS:
            weights = {key: value for key, value in release_dimension_weights(region).items() if key != removed}
            total = sum(weights.values())
            weights = {key: value / total for key, value in weights.items()}
            scale = RELEASE_SCALES[region]
            result_weight = release_result_weight(region)
            ablation_rows.extend([
                (1.0 / (1.0 + math.exp(-((1 - result_weight) * sum(dimension_diff[key] * weight for key, weight in weights.items()) + result_weight * result_diff) / scale)), won)
                for dimension_diff, result_diff, won in observations[region]
            ])
        report["dimension_ablation"]["all" if removed is None else f"without_{removed}"] = metrics(ablation_rows)
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
