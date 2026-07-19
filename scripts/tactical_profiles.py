#!/usr/bin/env python3
"""Build compact, auditable phase-chain tactical profiles from published match data."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path


SCHEMA = "tactical-profile-1.0.0"
GROUND_ROLES = {"英雄", "工程", "步兵3", "步兵4", "哨兵"}
PHASES = [
    ("opening", "开局部署 · 0:00–1:30"),
    ("outpost", "前哨站攻防"),
    ("transition", "增益与目标转换"),
    ("siege", "基地攻坚"),
    ("defense", "基地防守与回防"),
    ("terminal", "终局胜负管理 · 最后60秒"),
]


def finite(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def rounded(value, digits=1):
    return None if value is None else round(float(value), digits)


def quantile(values, ratio):
    usable = sorted(finite(value) for value in values if value is not None)
    if not usable:
        return None
    at = (len(usable) - 1) * ratio
    lower = math.floor(at)
    upper = math.ceil(at)
    if lower == upper:
        return usable[lower]
    return usable[lower] * (upper - at) + usable[upper] * (at - lower)


def wilson(successes, total, z=1.2815515655446004):
    """80% Wilson interval; deliberately conservative for small regional samples."""
    if not total:
        return (0.0, 1.0)
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def own_point(x, y, side):
    return (28 - x, 15 - y) if side == "蓝" else (x, y)


def depth_zone(x):
    labels = ("己方后场", "己方前场", "中央区", "对方前场", "对方后场")
    return labels[min(4, max(0, int(x / 5.6)))]


def lane_zone(y):
    if y < 5:
        return "公路区与公路隧道侧"
    if y < 10:
        return "中央高地正面"
    return "梯形高地与相邻隧道侧"


def event_second(detail, game_id, event_type):
    rows = detail.get("events_by_game", {}).get(str(game_id), [])
    seconds = [finite(row.get("second")) for row in rows if row.get("event_type") == event_type]
    return min(seconds) if seconds else None


def game_feature(detail, match, game, opponent_match):
    team = detail["team"]
    side = match["side"]
    own_robots = {index: robot for index, robot in enumerate(game.get("robots", [])) if robot.get("team") == team}
    early_alive = early_forward = terminal_alive = terminal_forward = 0
    early_seconds = defaultdict(list)
    all_seconds = defaultdict(list)
    role_forward = Counter()
    lane_forward = Counter()
    role_shots_early = Counter()
    role_shots_total = Counter()
    duration = finite(match.get("duration_sec"), 420)
    terminal_start = max(0, duration - 60)

    for second, rows in game.get("frames", []):
        second = finite(second)
        for row in rows:
            robot = own_robots.get(row[0])
            if not robot or not row[10] or finite(row[3]) <= 0:
                continue
            role = robot.get("robot_type", "未知")
            x, y = own_point(finite(row[1]), finite(row[2]), side)
            all_seconds[int(second)].append((role, x, y))
            shots = int(finite(row[8])) + int(finite(row[9]))
            role_shots_total[role] += shots
            if second <= 90:
                role_shots_early[role] += shots
                early_seconds[int(second)].append((role, x, y))
                if role in GROUND_ROLES:
                    early_alive += 1
                    if x >= 14:
                        early_forward += 1
                        role_forward[role] += 1
                        lane_forward[lane_zone(y)] += 1
            if second >= terminal_start and role in GROUND_ROLES:
                terminal_alive += 1
                terminal_forward += int(x >= 14)

    multi_push_seconds = sum(1 for points in early_seconds.values() if sum(role in GROUND_ROLES and x >= 14 for role, x, _ in points) >= 2)
    early_depths = [x for points in early_seconds.values() for role, x, _ in points if role in GROUND_ROLES]
    own_outpost_hit = opponent_match.get("first_outpost_damage_sec") if opponent_match else None
    own_base_hit = opponent_match.get("first_base_damage_sec") if opponent_match else None
    own_base_damage = finite(opponent_match.get("base_damage")) if opponent_match else 0

    def centroid(window_start, window_end):
        values = [x for second, points in all_seconds.items() if window_start <= second <= window_end for role, x, _ in points if role in GROUND_ROLES]
        return sum(values) / len(values) if values else None

    response_delta = None
    base_guard_pct = None
    if own_outpost_hit is not None:
        before = centroid(max(0, finite(own_outpost_hit) - 15), finite(own_outpost_hit) - 1)
        after = centroid(finite(own_outpost_hit), finite(own_outpost_hit) + 15)
        response_delta = None if before is None or after is None else after - before
    if own_base_hit is not None:
        guarded = total = 0
        for second, points in all_seconds.items():
            if finite(own_base_hit) <= second <= finite(own_base_hit) + 30:
                for role, x, _ in points:
                    if role in GROUND_ROLES:
                        total += 1
                        guarded += int(x <= 7)
        base_guard_pct = guarded * 100 / total if total else None

    first_outpost = match.get("first_outpost_damage_sec")
    destroy = match.get("outpost_destroy_sec")
    first_base = match.get("first_base_damage_sec")
    rune = event_second(detail, match["game_id"], "能量机关")
    radar = event_second(detail, match["game_id"], "雷达反制UAV")
    assembly = event_second(detail, match["game_id"], "装配成功")
    dart = event_second(detail, match["game_id"], "飞镖命中")
    return {
        "game_id": match["game_id"], "opponent": match["opponent"], "side": side,
        "won": bool(match.get("won")), "duration": duration,
        "first_outpost": first_outpost, "outpost_destroy": destroy, "first_base": first_base,
        "outpost_kill_duration": None if first_outpost is None or destroy is None else max(0, finite(destroy) - finite(first_outpost)),
        "outpost_to_base": None if destroy is None or first_base is None else finite(first_base) - finite(destroy),
        "rune": rune, "radar": radar, "assembly": assembly, "dart": dart,
        "shots17": finite(match.get("shots_17")), "shots42": finite(match.get("shots_42")),
        "robot_damage": finite(match.get("robot_damage")), "outpost_damage": finite(match.get("outpost_damage")),
        "base_damage": finite(match.get("base_damage")), "base17": finite(match.get("base_damage_17")),
        "base42": finite(match.get("base_damage_42")), "base_dart": finite(match.get("base_damage_dart")),
        "damage_dealt": finite(match.get("damage_dealt")), "damage_taken": finite(match.get("damage_taken")),
        "early_forward_pct": early_forward * 100 / early_alive if early_alive else 0,
        "multi_push_seconds": multi_push_seconds,
        "early_depth": sum(early_depths) / len(early_depths) if early_depths else None,
        "early_aerial_shots": role_shots_early["空中"],
        "terminal_alive_seconds": terminal_alive,
        "terminal_forward_pct": terminal_forward * 100 / terminal_alive if terminal_alive else 0,
        "dominant_roles": [name for name, _ in role_forward.most_common(2)],
        "dominant_lane": lane_forward.most_common(1)[0][0] if lane_forward else None,
        "role_shots": dict(role_shots_total),
        "own_outpost_hit": own_outpost_hit, "own_base_hit": own_base_hit,
        "own_base_damage": own_base_damage, "response_delta": response_delta,
        "base_guard_pct": base_guard_pct,
        "own_base_final_hp": finite(match.get("own_base_final_hp"), 5000),
    }


def thresholds(features):
    keys = ["shots17", "robot_damage", "early_forward_pct", "early_aerial_shots", "multi_push_seconds", "base_damage", "base_guard_pct"]
    return {key: quantile([row.get(key) for row in features], .6) or 0 for key in keys}


def template_rows(feature, cuts):
    f = feature
    first_objective = min([value for value in (f["first_outpost"], f["first_base"]) if value is not None], default=None)
    resource_second = min([value for value in (f["rune"], f["assembly"]) if value is not None], default=None)
    source_count = sum(value > 0 for value in (f["base17"], f["base42"], f["base_dart"]))
    return [
        ("opening_forward", "opening", "开局双车越过中线建立前场", True, f["early_forward_pct"] >= max(18, cuts["early_forward_pct"]) and f["multi_push_seconds"] >= max(5, cuts["multi_push_seconds"]), f["multi_push_seconds"], ["英雄/步兵/哨兵从启动区展开", "至少两台地面机器人越过中线", "持续占据对方半场并压缩其通行路线"], f["dominant_roles"], f["dominant_lane"]),
        ("opening_outpost", "opening", "开局90秒内打出前哨站首伤", True, f["first_outpost"] is not None and f["first_outpost"] <= 90, f["first_outpost"], ["地面单位进入前哨站攻击方向", "建立17mm或42mm有效射界", "在1:30前使对方前哨站首次扣血"], f["dominant_roles"], f["dominant_lane"]),
        ("rune_outpost_chain", "opening", "取得能量机关增益后压制前哨站", f["rune"] is not None, f["rune"] is not None and f["first_outpost"] is not None and 0 <= f["first_outpost"] - f["rune"] <= 90, f["first_outpost"], ["触发能量机关并取得攻防/热量增益", "增益有效期内推进至前哨站方向", "90秒内使对方前哨站扣血"], f["dominant_roles"], f["dominant_lane"]),
        ("opening_aerial", "opening", "首轮空中支援覆盖地面推进", True, f["early_aerial_shots"] >= max(30, cuts["early_aerial_shots"]), 90, ["空中机器人进入空中支援状态", "以17mm火力压制地面机器人或前哨站", "地面单位借空中火力越过中线"], ["空中"] + f["dominant_roles"][:1], f["dominant_lane"]),
        ("opening_radar", "opening", "开局90秒内使用雷达反制空中支援", True, f["radar"] is not None and f["radar"] <= 90, f["radar"], ["雷达识别对方空中机器人位置", "确认对方进入空中支援", "在1:30前发起雷达反制"], ["雷达", "空中"], None),
        ("rapid_outpost_kill", "outpost", "前哨站首伤后180秒内完成击毁", f["first_outpost"] is not None, f["outpost_kill_duration"] is not None and f["outpost_kill_duration"] <= 180, f["outpost_destroy"], ["使对方前哨站首次扣血", "持续保持17mm/42mm输出或接入飞镖伤害", "将前哨站血量降至0，解除对方基地无敌状态"], f["dominant_roles"], f["dominant_lane"]),
        ("sustained_17", "outpost", "以17mm火力持续压制机器人与前哨站", True, f["shots17"] >= cuts["shots17"] and f["robot_damage"] >= cuts["robot_damage"], f["first_outpost"], ["步兵、哨兵或空中机器人建立17mm射界", "控制枪口热量并保持连续发弹", "压低守方机器人血量并争取前哨站输出时间"], [role for role in ("空中", "哨兵", "步兵3", "步兵4") if f["role_shots"].get(role, 0) > 0][:2], f["dominant_lane"]),
        ("outpost_base_switch", "transition", "击毁前哨站后90秒内转火基地", f["outpost_destroy"] is not None, f["outpost_to_base"] is not None and 0 <= f["outpost_to_base"] <= 90, f["first_base"], ["击毁对方前哨站并解除基地无敌", "从前哨站攻击方向转入基地攻击方向", "90秒内使对方基地首次扣血"], f["dominant_roles"], f["dominant_lane"]),
        ("resource_objective", "transition", "把能量机关或装配收益转化为目标伤害", resource_second is not None, resource_second is not None and first_objective is not None and 0 <= first_objective - resource_second <= 90, first_objective, ["取得能量机关增益或完成装配", "在增益/装备有效窗口内组织推进", "90秒内使前哨站或基地扣血"], f["dominant_roles"], f["dominant_lane"]),
        ("dart_base_combo", "transition", "飞镖命中后衔接基地攻击", True, f["base_dart"] > 0 or (f["dart"] is not None and f["first_base"] is not None and abs(f["first_base"] - f["dart"]) <= 15), f["dart"], ["在飞镖闸门开启后进入30秒发射窗口", "飞镖命中基地目标或触发对应战场效果", "地面单位利用基地攻击窗口继续扣减基地血量"], ["飞镖"], None),
        ("hero42_siege", "siege", "英雄以42mm弹丸攻坚基地", True, f["base42"] > 0, f["first_base"], ["在对方前哨站被击毁后进入基地攻击方向", "英雄建立42mm有效射界", "以42mm弹丸直接扣减基地血量"], ["英雄"], f["dominant_lane"]),
        ("mixed_base_siege", "siege", "17mm、42mm与飞镖协同攻坚基地", f["base_damage"] > 0, source_count >= 2, f["first_base"], ["击毁前哨站并打开基地攻击条件", "至少两类伤害来源先后或同时命中基地", "持续压低基地血量，争取直接击毁或终局血量优势"], (["飞镖"] if f["base_dart"] else []) + (["英雄"] if f["base42"] else []) + f["dominant_roles"][:1], f["dominant_lane"]),
        ("outpost_fallback", "defense", "前哨站受击后收缩防线", f["own_outpost_hit"] is not None, f["response_delta"] is not None and f["response_delta"] <= -.45, f["own_outpost_hit"], ["己方前哨站出现首次扣血", "15秒内地面阵型向己方半场收缩", "保护前哨站攻击方向并保留基地回防路线"], f["dominant_roles"], "己方前场"),
        ("base_guard", "defense", "基地受击后建立近区保护", f["own_base_hit"] is not None, f["base_guard_pct"] is not None and f["base_guard_pct"] >= max(30, cuts["base_guard_pct"]), f["own_base_hit"], ["己方基地出现首次扣血", "地面单位在30秒内回到己方后场", "驱离基地攻击方向上的持续输出单位"], f["dominant_roles"], "己方后场"),
        ("base_denial", "defense", "前哨站受压后仍保持基地无伤", f["own_outpost_hit"] is not None, f["own_base_damage"] <= 0, f["own_outpost_hit"], ["己方前哨站进入受击状态", "守住前哨站或封锁前哨站至基地的转场路线", "全局结束时基地未产生有效扣血"], f["dominant_roles"], "己方后场"),
        ("terminal_pressure", "terminal", "最后60秒保持对方半场压力", True, f["terminal_forward_pct"] >= 25, max(0, f["duration"] - 60), ["进入最后60秒并核对基地/前哨站血量", "地面单位继续占据对方半场", "争取基地血量、前哨站状态或总攻击伤害优势"], f["dominant_roles"], f["dominant_lane"]),
        ("terminal_base_hold", "terminal", "最后60秒守住4000以上基地血量", True, f["own_base_final_hp"] >= 4000, max(0, f["duration"] - 60), ["进入最后60秒并确认己方基地血量领先条件", "封锁基地攻击方向，减少无收益换血", "全局结束时基地保有4000以上血量"], f["dominant_roles"], "己方后场"),
    ]


def confidence(observed, eligible, opponents, interval):
    width = interval[1] - interval[0]
    if eligible >= 12 and opponents >= 5 and width <= .35:
        return "高"
    if eligible >= 6 and opponents >= 3:
        return "中"
    return "低"


def classification(observed, eligible, opponents, rate, interval, side_split):
    red = side_split.get("红", {})
    blue = side_split.get("蓝", {})
    if observed >= 4 and opponents >= 2 and rate >= .55 and interval[0] >= .40:
        return "核心模式"
    if observed >= 3 and opponents >= 2 and rate >= .20 and red.get("eligible", 0) >= 3 and blue.get("eligible", 0) >= 3 and max(red.get("rate", 0), blue.get("rate", 0)) >= .40 and abs(red.get("rate", 0) - blue.get("rate", 0)) >= .20:
        return "阵营偏好"
    if observed >= 3 and opponents >= 2 and rate >= .30:
        return "条件模式"
    if observed >= 2:
        return "变化模式"
    return "样本不足"


def aggregate_pattern(template_id, phase, label, rows):
    eligible_rows = [row for row in rows if row["eligible"]]
    observed_rows = [row for row in eligible_rows if row["observed"]]
    eligible = len(eligible_rows)
    observed = len(observed_rows)
    rate = observed / eligible if eligible else 0
    interval = wilson(observed, eligible)
    opponents = len({row["feature"]["opponent"] for row in observed_rows})
    side_split = {}
    for side in ("红", "蓝"):
        side_eligible = [row for row in eligible_rows if row["feature"]["side"] == side]
        side_observed = sum(row["observed"] for row in side_eligible)
        side_split[side] = {"observed": side_observed, "eligible": len(side_eligible), "rate": rounded(side_observed / len(side_eligible), 3) if side_eligible else None}
    with_wins = sum(row["feature"]["won"] for row in observed_rows)
    without_rows = [row for row in eligible_rows if not row["observed"]]
    without_wins = sum(row["feature"]["won"] for row in without_rows)
    timings = [row["timing"] for row in observed_rows if row["timing"] is not None]
    roles = Counter(role for row in observed_rows for role in row["roles"] if role)
    zones = Counter(row["zone"] for row in observed_rows if row["zone"])
    return {
        "pattern_id": template_id, "phase": phase, "label": label,
        "classification": classification(observed, eligible, opponents, rate, interval, side_split),
        "confidence": confidence(observed, eligible, opponents, interval),
        "observed": observed, "eligible": eligible, "opponents": opponents,
        "rate": rounded(rate, 3), "interval80": [rounded(interval[0], 3), rounded(interval[1], 3)],
        "timing": {"median": rounded(quantile(timings, .5)), "p25": rounded(quantile(timings, .25)), "p75": rounded(quantile(timings, .75))},
        "roles": [name for name, _ in roles.most_common(3)], "zones": [name for name, _ in zones.most_common(2)],
        "steps": observed_rows[0]["steps"] if observed_rows else eligible_rows[0]["steps"] if eligible_rows else rows[0]["steps"] if rows else [],
        "side_split": side_split,
        "association": {
            "with_win_pct": rounded(with_wins * 100 / observed, 1) if observed else None,
            "without_win_pct": rounded(without_wins * 100 / len(without_rows), 1) if without_rows else None,
            "win_delta_pp": rounded(with_wins * 100 / observed - without_wins * 100 / len(without_rows), 1) if observed and without_rows else None,
            "median_outpost_damage": rounded(quantile([row["feature"]["outpost_damage"] for row in observed_rows], .5), 0),
            "median_base_damage": rounded(quantile([row["feature"]["base_damage"] for row in observed_rows], .5), 0),
        },
        "evidence": [{
            "game_id": row["feature"]["game_id"], "opponent": row["feature"]["opponent"], "side": row["feature"]["side"],
            "won": row["feature"]["won"], "timing": rounded(row["timing"]),
        } for row in observed_rows[:8]],
        "counterexamples": [{
            "game_id": row["feature"]["game_id"], "opponent": row["feature"]["opponent"], "side": row["feature"]["side"], "won": row["feature"]["won"],
        } for row in without_rows[:5]],
    }


def capability_profile(detail, features):
    avg = lambda key: rounded(sum(finite(row.get(key)) for row in features) / max(1, len(features)), 1)
    radar_games = sum(row["radar"] is not None for row in features)
    return {
        "games": len(features),
        "early_forward_pct": avg("early_forward_pct"), "multi_push_seconds": avg("multi_push_seconds"),
        "attack_depth_m": rounded(detail.get("spatial_analysis", {}).get("raw", {}).get("team_territory"), 2),
        "mobility_score": rounded(detail.get("scores", {}).get("spatial")),
        "firepower_score": rounded(detail.get("scores", {}).get("firepower")),
        "objective_score": rounded(detail.get("scores", {}).get("objective")),
        "defense_score": rounded(detail.get("scores", {}).get("defense")),
        "resource_score": rounded(detail.get("scores", {}).get("resource")),
        "base_denial_pct": rounded(finite(detail.get("defense_analysis", {}).get("raw", {}).get("base_denial")) * 100, 1),
        "outpost_denial_pct": rounded(finite(detail.get("defense_analysis", {}).get("raw", {}).get("outpost_denial")) * 100, 1),
        "base_damage_per_game": rounded(detail.get("summary", {}).get("avg_base_damage"), 0),
        "outpost_damage_per_game": rounded(detail.get("summary", {}).get("avg_outpost_damage"), 0),
        "damage_per_game": rounded(detail.get("summary", {}).get("avg_damage_dealt"), 0),
        "radar_counter_game_pct": rounded(radar_games * 100 / max(1, len(features)), 1),
        "position_coverage_pct": rounded(detail.get("score_confidence", {}).get("position_coverage_pct"), 1),
    }


def counter_response(pattern, feature_lookup):
    opponent_rows = []
    opponent_names = set()
    for example in pattern["counterexamples"]:
        row = feature_lookup.get((example["game_id"], example["opponent"]))
        if row:
            opponent_rows.append(row)
            opponent_names.add(example["opponent"])
    opponents = len(opponent_names)
    if not opponent_rows:
        return {"games": 0, "opponents": 0, "usable": False}
    average = lambda key: rounded(sum(finite(row.get(key)) for row in opponent_rows) / len(opponent_rows), 1)
    return {
        "games": len(opponent_rows), "opponents": opponents,
        "usable": len(opponent_rows) >= 3 and opponents >= 2,
        "early_forward_pct": average("early_forward_pct"),
        "multi_push_seconds": average("multi_push_seconds"),
        "damage_per_game": average("damage_dealt"),
        "base_guard_pct": average("base_guard_pct"),
    }


def build_tactical_profiles(source: Path, target: Path):
    index = json.loads((source / "index.json").read_text(encoding="utf-8"))
    details = {}
    match_lookup = {}
    for listing in index["teams"]:
        detail = json.loads((source / "teams" / f"{listing['slug']}.json").read_text(encoding="utf-8"))
        details[detail["team"]] = (listing, detail)
        for match in detail.get("matches", []):
            match_lookup[(match["game_id"], detail["team"])] = match

    all_features = []
    team_features = defaultdict(list)
    game_cache = {}
    for team, (_, detail) in details.items():
        for match in detail.get("matches", []):
            game_id = match["game_id"]
            if game_id not in game_cache:
                game_cache[game_id] = json.loads((source / "games" / f"{game_id}.json").read_text(encoding="utf-8"))
            opponent_match = match_lookup.get((game_id, match["opponent"]))
            feature = game_feature(detail, match, game_cache[game_id], opponent_match)
            all_features.append(feature)
            team_features[team].append(feature)
    cuts = thresholds(all_features)
    feature_lookup = {(row["game_id"], team): row for team, rows in team_features.items() for row in rows}

    target.mkdir(parents=True, exist_ok=True)
    for team, (listing, detail) in details.items():
        grouped = defaultdict(list)
        for feature in team_features[team]:
            for template_id, phase, label, eligible, observed, timing, steps, roles, zone in template_rows(feature, cuts):
                grouped[(template_id, phase, label)].append({
                    "feature": feature, "eligible": bool(eligible), "observed": bool(observed),
                    "timing": timing, "steps": steps, "roles": roles, "zone": zone,
                })
        patterns = [aggregate_pattern(*key, rows) for key, rows in grouped.items()]
        for pattern in patterns:
            pattern["counter_response"] = counter_response(pattern, feature_lookup)
        patterns.sort(key=lambda row: (next(index for index, phase in enumerate(PHASES) if phase[0] == row["phase"]), -row["rate"], row["label"]))
        phase_payload = []
        for phase_id, label in PHASES:
            phase_patterns = [row for row in patterns if row["phase"] == phase_id]
            phase_payload.append({"phase_id": phase_id, "label": label, "patterns": phase_patterns})
        profile = {
            "schema_version": SCHEMA, "team": team, "slug": listing["slug"],
            "sample": {"games": len(team_features[team]), "opponents": len({row["opponent"] for row in team_features[team]})},
            "phases": phase_payload, "patterns": patterns,
            "capabilities": capability_profile(detail, team_features[team]),
            "coordinate_model": {"length_m": 28, "width_m": 15, "perspective": "己方归一化", "depth_bins": 5, "lane_bins": 3},
            "limitations": ["模式为区域赛历史关联，不代表因果效果。", "雷达仅使用已记录的反制UAV事件。"],
        }
        (target / f"{listing['slug']}.json").write_text(json.dumps(profile, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(details)
