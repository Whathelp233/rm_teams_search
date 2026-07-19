#!/usr/bin/env python3
"""Build small, browser-oriented RMUC read models from the auditable exports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tactical_profiles import build_tactical_profiles

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public" / "data"
TARGET = SOURCE / "v4"
SCHEMA = "4.0.0"


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    index = json.loads((SOURCE / "index.json").read_text(encoding="utf-8"))
    if TARGET.exists():
        shutil.rmtree(TARGET)
    teams = []
    for listing in index["teams"]:
        detail = json.loads((SOURCE / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
        overview = {
            "schema_version": SCHEMA,
            "partial": True,
            "team": detail["team"],
            "summary": detail["summary"],
            "scores": detail["scores"],
            "damage_breakdown": detail.get("damage_breakdown", []),
            "strength_analysis": detail.get("strength_analysis"),
            "opponent_score_analysis": detail.get("opponent_score_analysis"),
            "score_confidence": detail.get("score_confidence"),
            "dimension_ranks": detail.get("dimension_ranks"),
            "dimension_confidence": detail.get("dimension_confidence"),
            "placement": detail.get("placement"),
            "overall_rank": detail.get("overall_rank"),
            "rank_stability": detail.get("rank_stability"),
        }
        write(TARGET / "teams" / listing["slug"] / "overview.json", overview)
        teams.append(listing)

    catalog = {
        "schema_version": SCHEMA,
        "revision": index.get("data_version", index.get("schema_version")),
        "coordinate_notice": index.get("coordinate_notice"),
        "scoring_notice": index.get("scoring_notice"),
        "rank_stability_method": index.get("rank_stability_method"),
        "teams": teams,
    }
    write(TARGET / "catalog.json", catalog)
    tactical_count = build_tactical_profiles(SOURCE, TARGET / "tactics")
    write(TARGET / "manifest.json", {
        "schema_version": SCHEMA,
        "revision": catalog["revision"],
        "resources": {
            "catalog": "data/v4/catalog.json",
            "team_overview": "data/v4/teams/{slug}/overview.json",
            "team_detail": "data/teams/{slug}.json",
            "team_tactics": "data/v4/tactics/{slug}.json",
            "heatmap": "data/heatmaps/{slug}.json",
            "role_catalog": "data/roles/index.json",
            "tournament": "data/repechage.json",
        },
    })
    print(f"built schema {SCHEMA} read models for {len(teams)} teams and {tactical_count} tactical profiles")


if __name__ == "__main__":
    main()
