#!/usr/bin/env python3
"""Audit the committed public role-data contract without the private SQLite."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
DOWNLOADS = ROOT / "public" / "downloads" / "roles"
EXPECTED = ["英雄", "工程", "步兵3", "步兵4", "哨兵", "空中", "飞镖"]


def main():
    failures = []
    catalog = json.loads((DATA / "roles" / "index.json").read_text(encoding="utf-8"))
    if catalog.get("schema_version") != "role-data-1.1.0":
        failures.append("role catalog schema is not role-data-1.1.0")
    if [item["role"] for item in catalog.get("roles", [])] != EXPECTED:
        failures.append("role catalog does not contain the seven ordered roles")
    if catalog.get("total_second_rows") != 2_990_075:
        failures.append("role catalog does not preserve all 2,990,075 robot seconds")
    report = {"schema": catalog.get("schema_version"), "total_second_rows": catalog.get("total_second_rows"), "roles": {}}
    for role in catalog.get("roles", []):
        path = DATA / "roles" / role["role_slug"] / "index.json"
        listing = json.loads(path.read_text(encoding="utf-8"))
        if len(listing.get("teams", [])) != 96:
            failures.append(f"{role['role']} index does not retain all 96 team entries")
        counted_games = sum(
            team["summary"].get("role_present_games", team["summary"].get("games", 0))
            for team in listing.get("teams", [])
        )
        if counted_games != listing["counts"]["games"]:
            failures.append(f"{role['role']} game count does not reconstruct from team summaries")
        for team in listing.get("teams", []):
            team_path = DATA / "roles" / role["role_slug"] / "teams" / f"{team['slug']}.json"
            if not team_path.exists():
                failures.append(f"missing {role['role']} payload for {team['team']}")
            availability = team["summary"].get("availability_pct")
            if availability is not None and not 0 <= availability <= 100:
                failures.append(f"{role['role']} availability out of range for {team['team']}")
            confidence = team["summary"].get("estimated_damage_confidence_pct")
            if confidence is not None and not 0 <= confidence <= 100:
                failures.append(f"{role['role']} damage attribution confidence out of range for {team['team']}")
        for download in role["downloads"].values():
            file_path = ROOT / "public" / download
            if not file_path.exists() or file_path.stat().st_size == 0:
                failures.append(f"missing role download {download}")
        report["roles"][role["role"]] = role["counts"]
    manifest = json.loads((DOWNLOADS / "manifest.json").read_text(encoding="utf-8"))
    if len(manifest.get("files", [])) != 14:
        failures.append("role download manifest must contain fourteen archives")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit("role data audit failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    main()
