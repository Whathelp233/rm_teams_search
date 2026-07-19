#!/usr/bin/env python3
"""Audit regional strength-rank sensitivity with chronological block jackknife.

The committed fixture contains only derived scores/ranks. Regeneration requires
the workspace SQLite source and reruns the complete nonlinear score pipeline
after deleting each of ten contiguous series blocks per region.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "public" / "data"
DEFAULT_DB = ROOT.parent / "sql" / "rmuc_2026_region_dataset.sqlite"
FIXTURE = ROOT / "test" / "fixtures" / "rank_stability.json"
REGIONS = ("南部赛区", "东部赛区", "北部赛区")
BLOCKS = 10


def compact_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def region_ranks(index):
    result = {}
    for region in REGIONS:
        regional = sorted(
            (item for item in index["teams"] if item["region"] == region),
            key=lambda item: (item["overall_rank"], item["team"]),
        )
        result.update({item["team"]: position for position, item in enumerate(regional, 1)})
    return result


def score_without_block(task):
    data_path, db_path, region, block_index, removed_series = task
    data_path, db_path = Path(data_path), Path(db_path)
    with tempfile.TemporaryDirectory(prefix=f"rmuc-rank-{block_index}-") as temporary:
        target = Path(temporary) / "data"
        teams_target = target / "teams"
        teams_target.mkdir(parents=True)
        index = json.loads((data_path / "index.json").read_text(encoding="utf-8"))
        compact_write(target / "index.json", index)
        removed = set(removed_series)
        for listing in index["teams"]:
            payload = json.loads((data_path / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
            payload["matches"] = [
                match for match in payload["matches"]
                if not (match["region"] == region and int(match["match_no"]) in removed)
            ]
            compact_write(teams_target / f"{listing['slug']}.json", payload)
        subprocess.run(
            [
                sys.executable, str(ROOT / "scripts" / "recalculate_scores.py"),
                "--db", str(db_path), "--data", str(target), "--backtest",
            ],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        scored = json.loads((target / "index.json").read_text(encoding="utf-8"))
        ranks = region_ranks(scored)
        return {
            "region": region, "block": block_index, "removed_series": sorted(removed),
            "teams": {
                item["team"]: {
                    "region_rank": ranks[item["team"]],
                    "strength": item["strength_analysis"]["score"],
                }
                for item in scored["teams"] if item["region"] == region
            },
        }


def build_fixture(data_path, db_path, workers):
    index = json.loads((data_path / "index.json").read_text(encoding="utf-8"))
    base_ranks = region_ranks(index)
    series = {region: set() for region in REGIONS}
    for listing in index["teams"]:
        payload = json.loads((data_path / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
        for match in payload["matches"]:
            series[match["region"]].add(int(match["match_no"]))

    tasks, block_contract = [], {}
    for region in REGIONS:
        ordered = sorted(series[region])
        blocks = [ordered[index * len(ordered) // BLOCKS:(index + 1) * len(ordered) // BLOCKS] for index in range(BLOCKS)]
        block_contract[region] = blocks
        tasks.extend((str(data_path), str(db_path), region, index + 1, block) for index, block in enumerate(blocks))

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        runs = list(executor.map(score_without_block, tasks))

    samples = {item["team"]: {"rank": [], "strength": []} for item in index["teams"]}
    for run in runs:
        for team, values in run["teams"].items():
            samples[team]["rank"].append(values["region_rank"])
            samples[team]["strength"].append(values["strength"])

    teams = {}
    for item in index["teams"]:
        team = item["team"]
        ranks = samples[team]["rank"]
        strengths = samples[team]["strength"]
        base_strength = float(item["strength_analysis"]["score"])
        rank_values = [base_ranks[team], *ranks]
        strength_values = [base_strength, *strengths]
        teams[team] = {
            "region": item["region"], "placement": (item.get("placement") or {}).get("label"),
            "base_global_rank": item["overall_rank"], "base_region_rank": base_ranks[team],
            "base_strength": base_strength,
            "region_rank_interval": [min(rank_values), max(rank_values)],
            "strength_interval": [round(min(strength_values), 1), round(max(strength_values), 1)],
            "rank_samples": ranks, "strength_samples": strengths,
        }
    return {
        "schema_version": "rank-stability-1.0.0",
        "score_version": index["data_version"],
        "matchup_model_version": index["matchup_validation"]["model_version"],
        "method": "10-block chronological delete-group jackknife; complete six-dimension pipeline rerun",
        "blocks_per_region": BLOCKS,
        "series_blocks": block_contract,
        "teams": teams,
    }


def audit(fixture, data_path):
    index = json.loads((data_path / "index.json").read_text(encoding="utf-8"))
    listings = {item["team"]: item for item in index["teams"]}
    failures = []
    if fixture.get("schema_version") != "rank-stability-1.0.0":
        failures.append("rank-stability fixture schema mismatch")
    if fixture.get("score_version") != index.get("data_version"):
        failures.append("rank-stability fixture score version is stale")
    if fixture.get("matchup_model_version") != index.get("matchup_validation", {}).get("model_version"):
        failures.append("rank-stability fixture matchup model version is stale")
    if set(fixture.get("teams", {})) != set(listings):
        failures.append("rank-stability fixture does not cover exactly the published teams")
    base_ranks = region_ranks(index)
    report = {
        "schema_version": fixture.get("schema_version"), "regions": {},
        "unstable_top_teams": [], "deep_run_outliers": [],
    }
    widths = {region: [] for region in REGIONS}
    for team, evidence in fixture.get("teams", {}).items():
        listing = listings.get(team)
        if not listing:
            continue
        if evidence["base_global_rank"] != listing["overall_rank"]:
            failures.append(f"{team} base global rank changed")
        if evidence["base_region_rank"] != base_ranks[team]:
            failures.append(f"{team} base region rank changed")
        if not math.isclose(evidence["base_strength"], listing["strength_analysis"]["score"], abs_tol=1e-9):
            failures.append(f"{team} base strength changed")
        if len(evidence["rank_samples"]) != BLOCKS or len(evidence["strength_samples"]) != BLOCKS:
            failures.append(f"{team} does not have {BLOCKS} jackknife samples")
        low, high = evidence["region_rank_interval"]
        if not (1 <= low <= evidence["base_region_rank"] <= high <= 32):
            failures.append(f"{team} has an invalid regional rank interval")
        width = high - low
        widths[evidence["region"]].append(width)
        if evidence["base_region_rank"] <= 8 and width >= 5:
            report["unstable_top_teams"].append({
                "team": team, "region": evidence["region"], "base_rank": evidence["base_region_rank"],
                "interval": evidence["region_rank_interval"], "placement": evidence["placement"],
            })
        if evidence["placement"] == "冠军" and evidence["base_region_rank"] > 4:
            failures.append(f"{team} is a regional champion outside the model's regional top four")
        if evidence["placement"] in {"冠军", "亚军", "季军", "殿军"} and evidence["base_region_rank"] > 8:
            report["deep_run_outliers"].append({
                "team": team, "region": evidence["region"], "placement": evidence["placement"],
                "base_rank": evidence["base_region_rank"], "interval": evidence["region_rank_interval"],
            })
    for region in REGIONS:
        values = widths[region]
        report["regions"][region] = {
            "teams": len(values), "mean_rank_width": sum(values) / max(1, len(values)),
            "max_rank_width": max(values, default=0),
            "series": sum(len(block) for block in fixture.get("series_blocks", {}).get(region, [])),
            "blocks": len(fixture.get("series_blocks", {}).get(region, [])),
        }
        if report["regions"][region]["teams"] != 32:
            failures.append(f"{region} rank stability does not cover 32 teams")
        if report["regions"][region]["blocks"] != BLOCKS:
            failures.append(f"{region} rank stability does not contain {BLOCKS} blocks")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("rank-stability audit failed:\n- " + "\n- ".join(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--write-fixture", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.write_fixture:
        if not args.db.exists():
            raise SystemExit(f"SQLite source not found: {args.db}")
        fixture = build_fixture(args.data, args.db, max(1, args.workers))
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        compact_write(FIXTURE, fixture)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    audit(fixture, args.data)


if __name__ == "__main__":
    main()
