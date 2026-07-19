#!/usr/bin/env python3
"""Build compact, auditable match replay payloads from the regional SQLite data."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT.parent / "sql" / "rmuc_2026_region_dataset.sqlite"
DEFAULT_OUTPUT = ROOT / "public" / "data" / "games"
MOBILE_TYPES = ("英雄", "工程", "步兵3", "步兵4", "空中", "哨兵")
FIRING_TYPES = {"英雄", "步兵3", "步兵4", "空中", "哨兵"}
FACILITY_ANCHORS = {
    "红": {"基地": (2.4, 7.5), "前哨站": (6.6, 7.5)},
    "蓝": {"基地": (25.6, 7.5), "前哨站": (21.4, 7.5)},
}
FRAME_COLUMNS = [
    "robot", "x", "y", "hp", "max_hp", "power", "heat17", "heat42",
    "shots17", "shots42", "valid", "z", "yaw", "heat17_limit",
    "heat42_limit", "vulnerable",
]
TEAM_FRAME_COLUMNS = [
    "side", "total_coins", "remaining_coins", "base_hp", "base_max_hp",
    "outpost_hp", "outpost_max_hp",
]
EVENT_COLUMNS = [
    "second", "type", "team", "side", "robot", "robot_type", "category", "value", "note",
    "target_robot_id", "target_type", "confidence", "damage", "assembly_level",
    "assembly_duration_sec", "assembly_start_sec", "start_confidence",
]
DAMAGE_COLUMNS = [
    "id", "second", "kind", "category", "damage", "target", "target_robot_id", "target_type",
    "target_side", "target_team", "x", "y", "position_confidence", "shooter", "shooter_robot_id",
    "shooter_type", "shooter_side", "shooter_team", "source_x", "source_y", "source_yaw",
    "angle_error", "attribution_score", "confidence", "basis", "candidates",
]
CANDIDATE_COLUMNS = [
    "robot_id", "robot_type", "shots", "same_second_shots", "previous_second_shots",
    "x", "y", "yaw", "distance_m", "bearing", "angle_error", "time_offset_sec",
    "evidence_score", "verdict", "reason", "position_basis",
]
ENGAGEMENT_COLUMNS = [
    "id", "start_sec", "end_sec", "focus_sec", "type", "attacker_side", "attacker_team",
    "defender_team", "damage", "hit_count", "deaths", "targets", "confidence", "basis",
]


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def rounded(value, digits=1):
    if value is None:
        return None
    number = float(value)
    return round(number, digits) if math.isfinite(number) else None


def valid_position(row):
    return bool(
        row and row["x"] is not None and row["y"] is not None
        and 0 <= float(row["x"]) <= 28 and 0 <= float(row["y"]) <= 15
        and not (float(row["x"]) == 0 and float(row["y"]) == 0)
    )


def angle_difference(first, second):
    return abs((float(first) - float(second) + 180) % 360 - 180)


def bearing(source, target):
    return math.degrees(math.atan2(float(target["y"]) - float(source["y"]), float(target["x"]) - float(source["x"])))


def existing_metadata(output):
    result = {}
    for path in output.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            old_events = payload.get("events", [])
            if old_events and isinstance(old_events[0], list):
                columns = payload.get("event_columns", [])
                old_events = [dict(zip(columns, row)) for row in old_events]
            result[int(payload["game"]["game_id"])] = {
                "rule_version": payload["game"].get("rule_version", "V2.0.1"),
                "map": payload.get("map", "current"),
                "old_events": old_events,
            }
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    return result


def compact_write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def compact_rows(rows, columns):
    return [[row.get(column) for column in columns] for row in rows]


def row_position(positions, second, robot_id):
    current = positions.get((second, robot_id))
    if valid_position(current):
        return current, "current"
    previous = positions.get((second - 1, robot_id))
    return (previous, "previous") if valid_position(previous) else (None, "missing")


def target_position(hit, positions):
    target_type, side = hit["机器人类型"], hit["阵营"]
    if target_type in ("基地", "前哨站"):
        x, y = FACILITY_ANCHORS[side][target_type]
        return {"x": x, "y": y}, "facility"
    return row_position(positions, int(float(hit["时刻秒"])), hit["robot_id"])


def candidate_details(candidates, same_second, second, positions, target):
    details = []
    for (robot_id, robot_type), count in candidates.items():
        same_count = same_second.get((robot_id, robot_type), 0)
        time_offset = 0 if same_count else -1
        source, position_basis = row_position(positions, second if same_count else second - 1, robot_id)
        angle = distance = target_bearing = None
        if source and target and source["枪口朝向"] is not None:
            target_bearing = bearing(source, target)
            angle = angle_difference(float(source["枪口朝向"]), target_bearing)
        if source and target:
            distance = math.hypot(float(target["x"]) - float(source["x"]), float(target["y"]) - float(source["y"]))
        score = 45.0 if same_count else 25.0
        if angle is not None:
            score += max(0.0, 35.0 - angle)
        if distance is not None:
            score += max(0.0, 20.0 - 1.5 * distance)
        details.append({
            "robot_id": robot_id,
            "robot_type": robot_type,
            "shots": count,
            "same_second_shots": same_count,
            "previous_second_shots": max(0, count - same_count),
            "x": rounded(source["x"], 3) if source else None,
            "y": rounded(source["y"], 3) if source else None,
            "yaw": rounded(source["枪口朝向"], 2) if source else None,
            "distance_m": rounded(distance, 2),
            "bearing": rounded(target_bearing, 1),
            "angle_error": rounded(angle, 1),
            "time_offset_sec": time_offset,
            "evidence_score": rounded(min(100.0, score)),
            "verdict": "candidate",
            "reason": "同秒发弹" if same_count else "前1秒发弹",
            "position_basis": position_basis,
        })
    return sorted(details, key=lambda item: (-item["evidence_score"], item["robot_id"]))


def attribute_hit(hit, shots, positions, robot_index, team_by_side):
    second = int(float(hit["时刻秒"]))
    victim_side = hit["阵营"]
    attacker_side = "蓝" if victim_side == "红" else "红"
    ammo = hit["类别"] or "未知"
    target, target_basis = target_position(hit, positions)
    damage = max(0.0, -float(hit["数值"] or 0))
    effect = {
        "id": f"{second}-{hit['row_id']}",
        "second": second,
        "kind": "projectile" if ammo in ("17mm", "42mm") else "dart" if ammo == "飞镖" else "collision" if ammo == "撞击" else "penalty" if ammo == "判罚" else "other",
        "category": ammo,
        "damage": rounded(damage),
        "target": robot_index.get(hit["robot_id"]),
        "target_robot_id": hit["robot_id"],
        "target_type": hit["机器人类型"] or "未知",
        "target_side": victim_side,
        "target_team": hit["学校名"],
        "x": rounded(target["x"], 3) if target else None,
        "y": rounded(target["y"], 3) if target else None,
        "position_confidence": "high" if target_basis in ("current", "facility") else "low" if target else "missing",
        "shooter": None,
        "shooter_robot_id": None,
        "shooter_type": None,
        "shooter_side": attacker_side,
        "shooter_team": team_by_side.get(attacker_side),
        "source_x": None,
        "source_y": None,
        "source_yaw": None,
        "angle_error": None,
        "attribution_score": None,
        "confidence": "high" if ammo not in ("17mm", "42mm") else "low",
        "basis": "裁判系统受击事件",
        "candidates": [],
    }
    if ammo not in ("17mm", "42mm"):
        if ammo == "撞击":
            effect["basis"] = "裁判系统撞击扣血；不属于弹丸命中"
        elif ammo == "判罚":
            effect["basis"] = "裁判系统判罚扣血；不属于交战伤害"
        elif ammo == "飞镖":
            effect["basis"] = "裁判系统飞镖受击事件；无可靠发射坐标"
        return effect

    same = shots.get((second, attacker_side, ammo), Counter())
    window = same.copy()
    window.update(shots.get((second - 1, attacker_side, ammo), Counter()))
    details = candidate_details(window, same, second, positions, target)
    effect["candidates"] = details

    selected = None
    if ammo == "42mm":
        hero = next((item for item in details if item["robot_type"] == "英雄"), None)
        if hero:
            selected = hero
            aligned = hero["angle_error"] is not None and hero["angle_error"] <= 30
            effect["confidence"] = "high" if aligned else "medium"
            effect["basis"] = "42mm仅由英雄发射；同秒/前1秒发弹" + ("且枪口方向吻合" if aligned else "，枪口方向证据不足")
        else:
            effect["shooter_type"] = "英雄"
            effect["confidence"] = "medium"
            effect["basis"] = "42mm兵种唯一，但时间窗内未记录发弹"
    elif len(details) == 1:
        selected = details[0]
        same_second = any(key[0] == selected["robot_id"] for key in same)
        angle = selected["angle_error"]
        if same_second and angle is not None and angle <= 25:
            effect["confidence"] = "high"
            effect["basis"] = "同秒唯一17mm射手，枪口方向与受击目标吻合"
        else:
            effect["confidence"] = "medium"
            effect["basis"] = "同秒/前1秒唯一17mm发弹候选"
    elif len(details) > 1:
        geometric = sorted((item for item in details if item["angle_error"] is not None), key=lambda item: item["angle_error"])
        if len(geometric) >= 2 and geometric[0]["angle_error"] <= 15 and geometric[1]["angle_error"] - geometric[0]["angle_error"] >= 15:
            selected = geometric[0]
            effect["confidence"] = "medium"
            effect["basis"] = "多个17mm候选中，枪口夹角最小且领先第二候选至少15°"
        else:
            effect["basis"] = "同秒/前1秒存在多个17mm射手，无法可靠区分"
    else:
        effect["basis"] = "受击已确认，但同秒/前1秒没有发弹候选"

    if selected:
        effect.update({
            "shooter": robot_index.get(selected["robot_id"]),
            "shooter_robot_id": selected["robot_id"],
            "shooter_type": selected["robot_type"],
            "source_x": selected["x"],
            "source_y": selected["y"],
            "source_yaw": selected["yaw"],
            "angle_error": selected["angle_error"],
            "attribution_score": selected["evidence_score"],
        })
    for item in details:
        if selected and item["robot_id"] == selected["robot_id"]:
            item["verdict"] = "selected"
            item["reason"] += "；在候选中证据最强"
        elif selected:
            item["verdict"] = "rejected"
            item["reason"] += "；夹角、时刻或距离证据弱于入选候选"
        else:
            item["reason"] += "；现有证据不足以唯一归因"
    return effect


def clustered(rows, gap):
    groups = []
    for row in sorted(rows, key=lambda item: item["second"]):
        if not groups or row["second"] - groups[-1][-1]["second"] > gap:
            groups.append([row])
        else:
            groups[-1].append(row)
    return groups


def build_engagements(effects, events, duration, team_by_side):
    """Derive clickable evidence windows without inventing unobserved actions."""
    result = []

    def append_segment(kind, attacker_side, rows, basis, confidence="high"):
        if not rows:
            return
        start, end = rows[0]["second"], rows[-1]["second"]
        focus = max(rows, key=lambda item: float(item.get("damage") or 0))["second"]
        targets = sorted({row.get("target_type") or "未知目标" for row in rows})
        deaths = sum(
            event.get("type") == "阵亡" and start <= float(event.get("second") or 0) <= end + 2
            for event in events
        )
        defender_side = "蓝" if attacker_side == "红" else "红"
        result.append({
            "id": f"{kind}-{attacker_side}-{start}-{end}",
            "start_sec": max(0, start - 2), "end_sec": min(float(duration or 420), end + 3),
            "focus_sec": focus, "type": kind, "attacker_side": attacker_side,
            "attacker_team": team_by_side.get(attacker_side), "defender_team": team_by_side.get(defender_side),
            "damage": rounded(sum(float(row.get("damage") or 0) for row in rows), 0),
            "hit_count": len(rows), "deaths": deaths, "targets": "、".join(targets),
            "confidence": confidence, "basis": basis,
        })

    combat = [effect for effect in effects if effect["kind"] in ("projectile", "dart")]
    for side in ("红", "蓝"):
        attacking = [effect for effect in combat if effect["shooter_side"] == side]
        for target_type, label in (("前哨站", "前哨攻坚"), ("基地", "基地攻坚")):
            for group in clustered([effect for effect in attacking if effect["target_type"] == target_type], 10):
                append_segment(label, side, group, f"同一方对{target_type}的受击事件，连续间隔不超过10秒")
        for group in clustered([effect for effect in attacking if effect["target_type"] not in ("前哨站", "基地")], 4):
            damage = sum(float(effect.get("damage") or 0) for effect in group)
            if len(group) >= 3 or damage >= 100:
                append_segment("集中交战", side, group, "机器人受击事件连续间隔不超过4秒，且至少3次受击或累计100点伤害", "medium")
        for group in clustered([effect for effect in attacking if effect["kind"] == "dart"], 12):
            append_segment("飞镖打击", side, group, "裁判系统记录的飞镖受击事件")

    death_events = [event for event in events if event.get("type") == "阵亡"]
    for group in clustered(death_events, 8):
        if len(group) < 2:
            continue
        victim_sides = {event.get("side") for event in group}
        if len(victim_sides) != 1:
            continue
        victim_side = next(iter(victim_sides))
        attacker_side = "蓝" if victim_side == "红" else "红"
        synthetic = [{"second": event["second"], "damage": 0, "target_type": event.get("robot_type")} for event in group]
        append_segment("连续减员", attacker_side, synthetic, "同一方在8秒窗口内连续至少2台机器人阵亡")

    for index, event in enumerate(event for event in events if event.get("type") == "雷达反制UAV"):
        second, side = float(event.get("second") or 0), event.get("side")
        result.append({
            "id": f"雷达反制-{index}-{second}", "start_sec": max(0, second - 5),
            "end_sec": min(float(duration or 420), second + 12), "focus_sec": second,
            "type": "雷达反制", "attacker_side": side, "attacker_team": team_by_side.get(side),
            "defender_team": team_by_side.get("蓝" if side == "红" else "红"), "damage": 0,
            "hit_count": 0, "deaths": 0, "targets": "空中机器人", "confidence": "high",
            "basis": "裁判系统雷达反制UAV事件，窗口取触发前5秒至后12秒",
        })
    priority = {"基地攻坚": 0, "前哨攻坚": 1, "连续减员": 2, "飞镖打击": 3, "雷达反制": 4, "集中交战": 5}
    result.sort(key=lambda item: (item["start_sec"], priority.get(item["type"], 9)))
    return result


def build_game(connection, match, prior):
    game_id = match["game_id"]
    rows = connection.execute(
        """SELECT 时刻秒,robot_id,机器人类型,阵营,学校名,当前血量,最大血量,
                  x,y,z,枪口朝向,底盘功率,小热量,小热量上限,大热量,大热量上限,
                  累计17mm发弹,累计42mm发弹,队伍总金币,队伍剩余金币,是否易伤
             FROM timeseries WHERE game_id=? ORDER BY 时刻秒,rowid""",
        (game_id,),
    ).fetchall()
    robots_by_id = {}
    for row in rows:
        if row["机器人类型"] in MOBILE_TYPES:
            robots_by_id[row["robot_id"]] = {
                "robot_id": row["robot_id"], "robot_type": row["机器人类型"],
                "team": row["学校名"], "side": row["阵营"],
            }
    robots = sorted(robots_by_id.values(), key=lambda item: item["robot_id"])
    robot_index = {item["robot_id"]: index for index, item in enumerate(robots)}
    team_by_side = {"红": match["红方学校"], "蓝": match["蓝方学校"]}

    frame_map = defaultdict(list)
    team_state = defaultdict(dict)
    positions = {}
    previous_shots = {}
    previous_hp = {}
    transition_events = []
    for row in rows:
        second = int(float(row["时刻秒"]))
        robot_id, robot_type, side = row["robot_id"], row["机器人类型"], row["阵营"]
        positions[(second, robot_id)] = row
        side_state = team_state[second].setdefault(side, {
            "total_coins": row["队伍总金币"], "remaining_coins": row["队伍剩余金币"],
            "base_hp": None, "base_max_hp": None, "outpost_hp": None, "outpost_max_hp": None,
        })
        if side_state["total_coins"] is None:
            side_state["total_coins"] = row["队伍总金币"]
            side_state["remaining_coins"] = row["队伍剩余金币"]
        if robot_type == "基地":
            side_state["base_hp"], side_state["base_max_hp"] = row["当前血量"], row["最大血量"]
        elif robot_type == "前哨站":
            side_state["outpost_hp"], side_state["outpost_max_hp"] = row["当前血量"], row["最大血量"]
        if robot_type not in MOBILE_TYPES:
            continue
        idx = robot_index[robot_id]
        current17, current42 = row["累计17mm发弹"], row["累计42mm发弹"]
        prev17, prev42 = previous_shots.get(robot_id, (current17, current42))
        delta17 = max(0, int((current17 or 0) - (prev17 or current17 or 0)))
        delta42 = max(0, int((current42 or 0) - (prev42 or current42 or 0)))
        previous_shots[robot_id] = (current17, current42)
        hp = float(row["当前血量"] or 0)
        prior_hp = previous_hp.get(robot_id)
        if prior_hp is not None and prior_hp > 0 >= hp:
            transition_events.append({"second": second, "type": "阵亡", "team": row["学校名"], "side": side, "robot": idx, "robot_type": robot_type, "confidence": "high"})
        elif prior_hp is not None and prior_hp <= 0 < hp:
            transition_events.append({"second": second, "type": "恢复在场", "team": row["学校名"], "side": side, "robot": idx, "robot_type": robot_type, "confidence": "high"})
        previous_hp[robot_id] = hp
        frame_map[second].append([
            idx, rounded(row["x"], 3), rounded(row["y"], 3), rounded(row["当前血量"]), rounded(row["最大血量"]),
            rounded(row["底盘功率"]), rounded(row["小热量"]), rounded(row["大热量"]), delta17, delta42,
            int(valid_position(row)), rounded(row["z"], 3), rounded(row["枪口朝向"], 2), rounded(row["小热量上限"]),
            rounded(row["大热量上限"]), int(row["是否易伤"] or 0),
        ])

    team_frames = []
    previous_team_values = None
    for second in sorted(team_state):
        values = []
        for side in ("红", "蓝"):
            state = team_state[second].get(side, {})
            values.append([
                side, rounded(state.get("total_coins")), rounded(state.get("remaining_coins")),
                rounded(state.get("base_hp")), rounded(state.get("base_max_hp")),
                rounded(state.get("outpost_hp")), rounded(state.get("outpost_max_hp")),
            ])
        if values != previous_team_values:
            team_frames.append([second, values])
            previous_team_values = values

    raw_events = connection.execute(
        """SELECT rowid row_id,时刻秒,事件类型,robot_id,机器人类型,阵营,学校名,
                  目标robot_id,目标类型,类别,数值,备注
             FROM events WHERE game_id=? ORDER BY 时刻秒,rowid""",
        (game_id,),
    ).fetchall()
    shots = defaultdict(Counter)
    for event in raw_events:
        if event["事件类型"] == "发弹" and event["类别"] in ("17mm", "42mm") and event["机器人类型"] in FIRING_TYPES:
            shots[(int(float(event["时刻秒"])), event["阵营"], event["类别"])][(event["robot_id"], event["机器人类型"])] += 1

    events = list(transition_events)
    effects = []
    for event in raw_events:
        event_type = event["事件类型"]
        if event_type == "发弹":
            continue
        if event_type == "受击":
            effect = attribute_hit(event, shots, positions, robot_index, team_by_side)
            effects.append(effect)
            continue
        item = {
            "second": rounded(event["时刻秒"]), "type": event_type, "team": event["学校名"], "side": event["阵营"],
            "robot": robot_index.get(event["robot_id"]), "robot_type": event["机器人类型"] or None,
            "category": event["类别"] or None, "value": rounded(event["数值"]), "note": event["备注"] or None,
            "target_robot_id": event["目标robot_id"], "target_type": event["目标类型"] or None, "confidence": "high",
        }
        if event_type == "装配成功":
            level_text = event["类别"] or ""
            level = int(level_text.replace("等级", "")) if level_text.startswith("等级") and level_text.replace("等级", "").isdigit() else None
            item.update({
                "assembly_level": level,
                "assembly_duration_sec": rounded(event["数值"]),
                "assembly_start_sec": rounded(float(event["时刻秒"]) - float(event["数值"] or 0)),
                "start_confidence": "inferred",
            })
        events.append(item)

    # Retain inferred card incidents from the prior analysis payload; raw data only contains penalty HP loss.
    for item in prior.get("old_events", []):
        if "牌" not in str(item.get("type", "")):
            continue
        copy = dict(item)
        copy.setdefault("confidence", "low")
        if copy not in events:
            events.append(copy)

    game = {
        "game_id": game_id, "region": match["赛区"], "match_no": match["场次号"], "schedule": match["赛程"],
        "round_no": match["局号"], "web_game_id": match["web_game_id"], "red_team": match["红方学校"],
        "blue_team": match["蓝方学校"], "winner": match["胜方"], "started_at": match["开始时间"],
        "duration_sec": match["时长秒"], "rule_version": prior.get("rule_version", "V2.0.1"),
    }
    facilities = [
        {"side": side, "team": team_by_side[side], "type": facility, "x": point[0], "y": point[1]}
        for side in ("红", "蓝") for facility, point in FACILITY_ANCHORS[side].items()
    ]
    ordered_events = sorted(events, key=lambda item: (float(item.get("second") or 0), item.get("type") or ""))
    ordered_effects = sorted(effects, key=lambda item: (item["second"], item["id"]))
    engagements = build_engagements(ordered_effects, ordered_events, match["时长秒"], team_by_side)
    for effect in ordered_effects:
        effect["candidates"] = compact_rows(effect.get("candidates", []), CANDIDATE_COLUMNS)
    return {
        "schema_version": "3.1.0", "game": game, "map": prior.get("map", "current"), "robots": robots,
        "facilities": facilities, "frame_columns": FRAME_COLUMNS,
        "frames": [[second, frame_map[second]] for second in sorted(frame_map)],
        "team_frame_columns": TEAM_FRAME_COLUMNS, "team_frames": team_frames,
        "event_columns": EVENT_COLUMNS, "events": compact_rows(ordered_events, EVENT_COLUMNS),
        "damage_columns": DAMAGE_COLUMNS, "candidate_columns": CANDIDATE_COLUMNS,
        "damage_effects": compact_rows(ordered_effects, DAMAGE_COLUMNS),
        "engagement_columns": ENGAGEMENT_COLUMNS, "engagements": compact_rows(engagements, ENGAGEMENT_COLUMNS),
        "source_cadence_hz": 1,
        "limitations": [
            "原始位置、血量与状态数据为1Hz；页面动画帧为插值，不是更高频率的真实遥测。",
            "弹丸受击与伤害为裁判系统事实；17mm射手按同秒/前1秒发弹、枪口朝向和目标几何关系分级推定。",
            "装配开始时刻由成功时刻减去事件记录耗时推定；当前数据未观测到四级装配成功。",
        ],
    }


def main():
    args = arguments()
    args.output.mkdir(parents=True, exist_ok=True)
    prior = existing_metadata(args.output)
    connection = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        matches = connection.execute("SELECT * FROM matches ORDER BY game_id").fetchall()
        for index, match in enumerate(matches, 1):
            metadata = prior.get(match["game_id"], {})
            compact_write(args.output / f"{match['game_id']}.json", build_game(connection, match, metadata))
            if index % 50 == 0 or index == len(matches):
                print(f"replay v3: {index}/{len(matches)}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
