"""Apex Legends 数据格式化工具。"""

from __future__ import annotations

from typing import Any, Optional


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def _rank_display(rank_data: dict) -> str:
    """格式化段位信息。"""
    name = _safe_str(rank_data.get("rankName"), "未知")
    div = _safe_str(rank_data.get("rankDiv"))
    score = _safe_int(rank_data.get("rankScore"))
    img = _safe_str(rank_data.get("rankImg"))
    parts = [name]
    if div and div != "0":
        parts.append(div)
    if score:
        parts.append(f"({score} LP)")
    return " ".join(parts)


def build_help_text() -> str:
    return (
        "**Apex Legends 查询**\n"
        "\n"
        "**玩家查询**\n"
        "  @bot apex <玩家名>            |  /apex <玩家名>\n"
        "  @bot apex <玩家名> <平台>     |  /apex player <玩家名> <平台>\n"
        "  平台: PC(默认) / PS4 / Xbox / Switch\n"
        "\n"
        "**地图轮换**\n"
        "  @bot apex 地图  |  /apex map\n"
        "\n"
        "**合成轮换**\n"
        "  @bot apex 合成  |  /apex crafting\n"
        "\n"
        "**猎杀者门槛**\n"
        "  @bot apex 猎杀者  |  /apex predator\n"
        "\n"
        "  @bot apex 帮助  |  /apex help\n"
        "\n"
        "数据来源: apexlegendsstatus.com"
    )


def format_player_stats(data: dict) -> str:
    """格式化玩家统计数据。"""
    if not isinstance(data, dict):
        return "获取玩家数据失败。"

    error = data.get("_error") or data.get("Error")
    if error:
        return f"查询失败: {error}"

    global_data = data.get("global") or {}
    realtime = data.get("realtime") or {}
    legends = data.get("legends") or {}
    total = data.get("total") or {}

    name = _safe_str(global_data.get("name"), "未知玩家")
    platform = _safe_str(global_data.get("platform"), "?")
    level = _safe_int(global_data.get("level"))
    uid = _safe_str(global_data.get("uid"))

    lines = [f"**{name}** ({platform})"]

    if level:
        lines.append(f"等级: {level}")
    if uid:
        lines.append(f"UID: {uid}")

    br_rank = global_data.get("rank") or {}
    if br_rank.get("rankName"):
        lines.append(f"大逃杀段位: {_rank_display(br_rank)}")

    arena_rank = global_data.get("arena") or {}
    if arena_rank.get("rankName"):
        lines.append(f"竞技场段位: {_rank_display(arena_rank)}")

    bans = global_data.get("bpisBanned") or global_data.get("bans") or {}
    if isinstance(bans, dict) and bans.get("isActive"):
        remaining = _safe_str(bans.get("remainingSeconds"))
        reason = _safe_str(bans.get("last_banReason"), "未知")
        ban_text = f"当前封禁中 (原因: {reason})"
        if remaining and remaining != "0":
            ban_text += f" 剩余: {remaining}s"
        lines.append(ban_text)

    online_status = _safe_str(realtime.get("currentStateAsText"))
    if online_status:
        lines.append(f"状态: {online_status}")

    selected_legend = _safe_str(realtime.get("selectedLegend"))
    if selected_legend:
        lines.append(f"当前传奇: {selected_legend}")

    if isinstance(total, dict) and total.get("kills") is not None:
        kills_val = total["kills"].get("value") if isinstance(total["kills"], dict) else total["kills"]
        if kills_val is not None:
            lines.append(f"总击杀: {_safe_int(kills_val):,}")

    selected = legends.get("selected") or {}
    if isinstance(selected, dict) and selected.get("LegendName"):
        legend_name = selected["LegendName"]
        lines.append(f"\n**{legend_name} (当前选择)**")
        trackers = selected.get("data") or []
        if isinstance(trackers, list):
            for tracker in trackers[:6]:
                if not isinstance(tracker, dict):
                    continue
                t_name = _safe_str(tracker.get("name"))
                t_value = tracker.get("value")
                if t_name and t_value is not None:
                    lines.append(f"  {t_name}: {_safe_int(t_value):,}")

    return "\n".join(lines)


def format_map_rotation(data: dict) -> str:
    """格式化地图轮换信息。"""
    if not isinstance(data, dict):
        return "获取地图轮换数据失败。"

    error = data.get("_error")
    if error:
        return f"查询失败: {error}"

    lines = ["**Apex Legends 地图轮换**"]

    br = data.get("battle_royale") or {}
    if br:
        current = br.get("current") or {}
        next_map = br.get("next") or {}
        lines.append("\n**大逃杀 (匹配)**")
        if current.get("map"):
            remaining = _safe_str(current.get("remainingTimer"), "?")
            lines.append(f"  当前: {current['map']} (剩余 {remaining})")
        if next_map.get("map"):
            duration = _safe_str(next_map.get("DurationInMinutes"))
            dur_text = f" ({duration}分钟)" if duration else ""
            lines.append(f"  下一个: {next_map['map']}{dur_text}")

    ranked = data.get("ranked") or {}
    if ranked:
        current = ranked.get("current") or {}
        next_map = ranked.get("next") or {}
        lines.append("\n**大逃杀 (排位)**")
        if current.get("map"):
            remaining = _safe_str(current.get("remainingTimer"), "?")
            lines.append(f"  当前: {current['map']} (剩余 {remaining})")
        if next_map.get("map"):
            lines.append(f"  下一个: {next_map['map']}")

    ltm = data.get("ltm") or {}
    if ltm:
        current = ltm.get("current") or {}
        if current.get("map"):
            remaining = _safe_str(current.get("remainingTimer"), "?")
            event = _safe_str(current.get("eventName"))
            label = f" [{event}]" if event else ""
            lines.append(f"\n**限时模式{label}**")
            lines.append(f"  当前: {current['map']} (剩余 {remaining})")

    if len(lines) == 1:
        lines.append("暂无地图轮换数据。")

    return "\n".join(lines)


def format_crafting_rotation(data: Any) -> str:
    """格式化复制器合成轮换。"""
    if not isinstance(data, list):
        if isinstance(data, dict):
            error = data.get("_error")
            if error:
                return f"查询失败: {error}"
        return "获取合成轮换数据失败。"

    lines = ["**Apex Legends 复制器合成**"]

    for bundle in data:
        if not isinstance(bundle, dict):
            continue
        bundle_type = _safe_str(bundle.get("bundleType"), "未知")
        start = _safe_str(bundle.get("startDate"))
        end = _safe_str(bundle.get("endDate"))
        items = bundle.get("bundleContent") or []

        type_labels = {
            "daily": "每日轮换",
            "weekly": "每周轮换",
            "permanent": "永久",
        }
        label = type_labels.get(bundle_type.lower(), bundle_type)
        lines.append(f"\n**{label}**")

        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("itemType") or {}
                name = _safe_str(item_type.get("name") if isinstance(item_type, dict) else None)
                rarity = _safe_str(item_type.get("rarity") if isinstance(item_type, dict) else None)
                cost = _safe_int(item.get("cost"))
                if name:
                    parts = [f"  {name}"]
                    if rarity:
                        parts.append(f"[{rarity}]")
                    if cost:
                        parts.append(f"- {cost} 材料")
                    lines.append(" ".join(parts))

    if len(lines) == 1:
        lines.append("暂无合成轮换数据。")

    return "\n".join(lines)


def format_predator(data: dict) -> str:
    """格式化猎杀者门槛数据。"""
    if not isinstance(data, dict):
        return "获取猎杀者数据失败。"

    error = data.get("_error")
    if error:
        return f"查询失败: {error}"

    lines = ["**Apex Legends 猎杀者门槛**"]

    rp = data.get("RP") or {}
    ap = data.get("AP") or {}

    def _format_platform(platform_data: dict, label: str) -> list[str]:
        result = []
        if not isinstance(platform_data, dict):
            return result
        for key, display in (("PC", "PC"), ("PS4", "PlayStation"), ("X1", "Xbox"), ("SWITCH", "Switch")):
            info = platform_data.get(key) or {}
            if not isinstance(info, dict):
                continue
            val = _safe_int(info.get("val"))
            total_masters = _safe_int(info.get("totalMastersAndPreds"))
            if val:
                entry = f"  {display}: {val:,} {label}"
                if total_masters:
                    entry += f" (大师及以上: {total_masters:,}人)"
                result.append(entry)
        return result

    br_lines = _format_platform(rp, "RP")
    if br_lines:
        lines.append("\n**大逃杀**")
        lines.extend(br_lines)

    arena_lines = _format_platform(ap, "AP")
    if arena_lines:
        lines.append("\n**竞技场**")
        lines.extend(arena_lines)

    if len(lines) == 1:
        lines.append("暂无猎杀者门槛数据。")

    return "\n".join(lines)
