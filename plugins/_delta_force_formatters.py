"""
Formatting helpers for Delta Force plugin responses.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Iterable, Optional

from ._delta_force_assets import mode_name, pick_avatar_url, pick_nickname, qq_avatar_url


def _num(value: object, default: str = "-") -> str:
    if value is None or value == "":
        return default
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        try:
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)


def _section(title: str, rows: Iterable[tuple[str, object]]) -> str:
    inner = []
    for label, value in rows:
        if value is None or value == "":
            continue
        inner.append(
            f"<div class='row'><span class='label'>{escape(str(label))}</span>"
            f"<span class='value'>{escape(str(value))}</span></div>"
        )
    if not inner:
        inner.append("<div class='empty'>暂无数据</div>")
    return f"<section class='panel'><h3>{escape(title)}</h3>{''.join(inner)}</section>"


def _status_rows(role_info: dict, career_data: dict) -> list[tuple[str, object]]:
    prop_capital = role_info.get("propcapital")
    haf_coin = role_info.get("hafcoinnum")
    total_assets = "-"
    try:
        total_assets = f"{(float(prop_capital or 0) + float(haf_coin or 0)) / 1_000_000:.2f}M"
    except (TypeError, ValueError):
        pass
    return [
        ("昵称", pick_nickname({"data": {"userData": {}}, "roleInfo": role_info})),
        ("UID", role_info.get("uid") or "-"),
        ("烽火等级", role_info.get("level") or "-"),
        ("全面等级", role_info.get("tdmlevel") or "-"),
        ("总资产", total_assets),
        ("烽火总对局", _num(career_data.get("soltotalfght"))),
        ("烽火总淘汰", _num(career_data.get("soltotalkill"))),
        ("全面总对局", _num(career_data.get("tdmtotalfight"))),
        ("全面总淘汰", _num(career_data.get("tdmtotalkill"))),
    ]


def build_help_text() -> str:
    return (
        "三角洲插件命令:\n"
        "@bot 三角洲帮助  /df help\n"
        "@bot 三角洲登录 [qq|微信]  /df login [qq|wechat]\n"
        "@bot 三角洲角色绑定  /df bind-character\n"
        "@bot 三角洲账号  /df accounts\n"
        "@bot 三角洲账号切换 <序号>  /df switch <序号>\n"
        "@bot 三角洲信息  /df info\n"
        "@bot 三角洲uid  /df uid\n"
        "@bot 三角洲每日密码  /df daily-keyword\n"
        "@bot 三角洲开启每日密码推送  /df daily-keyword-push on\n"
        "@bot 三角洲关闭每日密码推送  /df daily-keyword-push off\n"
        "@bot 三角洲特勤处状态  /df place-status\n"
        "@bot 三角洲开启特勤处推送  /df place-push on\n"
        "@bot 三角洲关闭特勤处推送  /df place-push off\n"
        "@bot 三角洲藏品 [类型]  /df collection [类型]\n"
        "@bot 三角洲物品 <关键词或ID>  /df object-search <关键词或ID>\n"
        "@bot 三角洲价格历史 <关键词或ID>  /df price-history <关键词或ID>\n"
        "@bot 三角洲货币  /df money\n"
        "@bot 三角洲封号记录  /df ban-history\n"
        "@bot 三角洲大红收藏 [赛季]  /df red-collection [赛季]\n"
        "@bot 三角洲大红记录  /df red-records\n"
        "@bot 三角洲社区改枪码 [武器] [最小价,最大价]  /df solution-list [武器] [最小价,最大价]\n"
        "@bot 三角洲改枪码详情 <ID>  /df solution-detail <ID>\n"
        "@bot 三角洲日报 [烽火|全面]  /df daily [sol|mp]\n"
        "@bot 三角洲周报 [烽火|全面] [YYYYMMDD] [详细]  /df weekly [sol|mp] [YYYYMMDD] [detail]\n"
        "@bot 三角洲战绩 [烽火|全面|全部] [页码]  /df record [sol|mp|all] [页码]"
    )


def format_accounts(accounts: list[dict], active_token: Optional[str]) -> str:
    if not accounts:
        return "当前没有已绑定账号，请先执行三角洲登录。"
    lines = ["已绑定账号列表:"]
    for index, item in enumerate(accounts, start=1):
        token = str(item.get("frameworkToken") or "")
        token_mask = f"{token[:4]}****{token[-4:]}" if len(token) >= 8 else token or "-"
        token_type = str(item.get("tokenType") or "unknown").upper()
        status = "有效" if item.get("isValid") else "失效"
        current = " <- 当前" if active_token and token == active_token else ""
        qq_number = str(item.get("qqNumber") or "").strip()
        qq_text = f" ({qq_number[:4]}****)" if len(qq_number) >= 4 else ""
        lines.append(f"{index}. [{token_type}] {token_mask}{qq_text} [{status}]{current}")
    return "\n".join(lines)


def build_info_context(user_id: str, personal_info: dict) -> dict:
    role_info = personal_info.get("roleInfo") or {}
    career_data = (personal_info.get("data") or {}).get("careerData") or {}
    return {
        "title": "三角洲个人信息",
        "subtitle": f"用户 {user_id}",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": _section("账号概览", _status_rows(role_info, career_data)),
    }


def info_fallback_text(personal_info: dict) -> str:
    role_info = personal_info.get("roleInfo") or {}
    career_data = (personal_info.get("data") or {}).get("careerData") or {}
    rows = _status_rows(role_info, career_data)
    return "\n".join(f"{label}: {value}" for label, value in rows if value not in (None, ""))


def build_uid_text(personal_info: dict) -> str:
    role_info = personal_info.get("roleInfo") or {}
    return f"昵称: {pick_nickname(personal_info)}\nUID: {role_info.get('uid') or '-'}"


def _collection_categories(collection_payload: dict, collection_map_payload: dict, type_filter: str = "") -> dict[str, list[dict]]:
    collection_data = collection_payload.get("data") or {}
    user_items = collection_data.get("userData") or []
    weapon_items = collection_data.get("weponData") or []
    all_items = []
    if isinstance(user_items, list):
        all_items.extend(user_items)
    if isinstance(weapon_items, list):
        all_items.extend(weapon_items)
    if not all_items:
        return {}

    map_data = collection_map_payload.get("data") if isinstance(collection_map_payload.get("data"), list) else []
    collection_map = {}
    for item in map_data:
        if isinstance(item, dict):
            collection_map[str(item.get("id") or "")] = item

    categories: dict[str, list[dict]] = {}
    for item in all_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("ItemId") or "")
        meta = collection_map.get(item_id, {})
        category = str(meta.get("type") or "其他资产")
        if type_filter and type_filter not in category and category not in type_filter:
            continue
        categories.setdefault(category, []).append({
            "id": item_id,
            "name": str(meta.get("name") or item_id or "未知物品"),
        })
    return categories


def build_collection_context(
    user_id: str,
    personal_info: dict,
    collection_payload: dict,
    collection_map_payload: dict,
    type_filter: str = "",
) -> dict:
    categories = _collection_categories(collection_payload, collection_map_payload, type_filter)
    if not categories:
        body_html = "<section class='panel'><div class='empty'>暂无符合条件的藏品数据</div></section>"
    else:
        total = sum(len(items) for items in categories.values())
        sections = [
            _section(
                "统计概览",
                [
                    ("筛选类型", type_filter or "全部"),
                    ("分类数量", len(categories)),
                    ("藏品总数", total),
                ],
            )
        ]
        for category in sorted(categories.keys()):
            items = categories[category]
            rows: list[tuple[str, object]] = []
            for index, item in enumerate(items[:6], start=1):
                rows.append((f"藏品 {index}", item.get("name") or "未知物品"))
            if len(items) > 6:
                rows.append(("更多", f"另有 {len(items) - 6} 项未展开"))
            sections.append(_section(f"{category} ({len(items)})", rows))
        body_html = "".join(sections)
    return {
        "title": "三角洲藏品一览",
        "subtitle": f"筛选: {type_filter or '全部'}",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": body_html,
    }


def collection_fallback_text(collection_payload: dict, collection_map_payload: dict, type_filter: str = "") -> str:
    categories = _collection_categories(collection_payload, collection_map_payload, type_filter)
    collection_data = collection_payload.get("data") or {}
    has_items = bool(collection_data.get("userData") or collection_data.get("weponData"))
    if not has_items:
        return "您的藏品库为空。"

    if not categories:
        return f'未找到类型"{type_filter}"的藏品。'

    title = f"三角洲藏品统计（{type_filter or '全部'}）"
    lines = [title]
    total = 0
    for category in sorted(categories.keys()):
        items = categories[category]
        total += len(items)
        names = "、".join(v["name"] for v in items[:5])
        extra = "" if len(items) <= 5 else f" 等 {len(items)} 项"
        lines.append(f"{category}: {len(items)}")
        if names:
            lines.append(f"  {names}{extra}")
    lines.append(f"总计: {total}")
    return "\n".join(lines)


def build_money_context(user_id: str, personal_info: dict, money_payload: dict) -> dict:
    data = money_payload.get("data")
    rows: list[tuple[str, object]] = []
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("moneyName") or "未知货币")
            rows.append((name, _num(item.get("totalMoney"), default="0")))
    body_html = _section("货币总览", rows)
    return {
        "title": "三角洲货币信息",
        "subtitle": f"币种 {len(rows)} 项" if rows else "暂无货币数据",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": body_html,
    }


def money_fallback_text(money_payload: dict) -> str:
    data = money_payload.get("data")
    if not isinstance(data, list) or not data:
        return "未查询到任何货币信息。"
    lines = ["三角洲货币信息"]
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("moneyName") or "未知货币")
        amount = item.get("totalMoney")
        lines.append(f"{name}: {_num(amount, default='0')}")
    return "\n".join(lines)


def _format_ban_ts(value: object) -> str:
    try:
        ts = int(float(value))
        if ts <= 0:
            return "N/A"
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "N/A"


def _format_ban_duration(value: object) -> str:
    try:
        seconds = int(float(value))
        days = seconds // (3600 * 24)
        hours = (seconds % (3600 * 24)) // 3600
        return "永久" if days > 365 * 9 else f"{days}天{hours}小时"
    except (TypeError, ValueError):
        return "N/A"


def build_ban_history_context(user_id: str, personal_info: dict, ban_payload: dict) -> dict:
    data = ban_payload.get("data")
    sections = []
    if isinstance(data, list) and data:
        sections.append(
            _section(
                "记录概览",
                [
                    ("记录总数", len(data)),
                    ("展示数量", min(len(data), 5)),
                ],
            )
        )
        for index, item in enumerate(data[:5], start=1):
            if not isinstance(item, dict):
                continue
            sections.append(
                _section(
                    f"违规记录 {index}",
                    [
                        ("游戏", item.get("game_name") or "游戏"),
                        ("大区", item.get("zone") or "-"),
                        ("类型", item.get("type") or "-"),
                        ("原因", item.get("reason") or "未知原因"),
                        ("开始时间", _format_ban_ts(item.get("start_stmp"))),
                        ("处罚时长", _format_ban_duration(item.get("duration"))),
                    ],
                )
            )
        if len(data) > 5:
            sections.append(_section("补充说明", [("提示", f"共 {len(data)} 条，仅展示前 5 条")]))
    else:
        sections.append("<section class='panel'><div class='empty'>该账号暂无违规记录</div></section>")
    return {
        "title": "三角洲违规记录",
        "subtitle": f"记录 {min(len(data), 5)} / {len(data)}" if isinstance(data, list) and data else "暂无违规记录",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": "".join(sections),
    }


def ban_history_fallback_text(ban_payload: dict) -> str:
    data = ban_payload.get("data")
    if not isinstance(data, list) or not data:
        return "该账号暂无违规记录。"

    lines = ["三角洲违规记录"]
    for index, item in enumerate(data[:5], start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"{index}. {item.get('game_name') or '游戏'} / {item.get('zone') or '-'} | "
            f"{item.get('type') or '-'} | {item.get('reason') or '未知原因'}"
        )
        lines.append(
            f"   开始: {_format_ban_ts(item.get('start_stmp'))} | 时长: {_format_ban_duration(item.get('duration'))}"
        )
    if len(data) > 5:
        lines.append(f"共 {len(data)} 条，仅显示前 5 条。")
    return "\n".join(lines)


def format_collection_text(collection_payload: dict, collection_map_payload: dict, type_filter: str = "") -> str:
    return collection_fallback_text(collection_payload, collection_map_payload, type_filter)


def format_money_text(money_payload: dict) -> str:
    return money_fallback_text(money_payload)


def format_ban_history_text(ban_payload: dict) -> str:
    return ban_history_fallback_text(ban_payload)


def _find_daily_sol(detail: dict) -> dict:
    if detail.get("data", {}).get("data", {}).get("solDetail"):
        return detail["data"]["data"]["solDetail"]
    return {}


def _find_daily_mp(detail: dict) -> dict:
    if detail.get("data", {}).get("data", {}).get("mpDetail"):
        return detail["data"]["data"]["mpDetail"]
    return {}


def build_daily_context(user_id: str, personal_info: dict, daily_payload: dict, mode: str, date_text: str) -> dict:
    if mode:
        detail = (daily_payload.get("data") or {}) if isinstance(daily_payload.get("data"), dict) else {}
        sol_detail = _find_daily_sol(detail) if mode == "sol" else {}
        mp_detail = _find_daily_mp(detail) if mode == "mp" else {}
    else:
        root = daily_payload.get("data") or {}
        sol_detail = _find_daily_sol(root.get("sol") or {}) if isinstance(root.get("sol"), dict) else {}
        mp_detail = _find_daily_mp(root.get("mp") or {}) if isinstance(root.get("mp"), dict) else {}

    sections = []
    if not mode or mode == "sol":
        sections.append(
            _section(
                "烽火地带",
                [
                    ("最近日期", sol_detail.get("recentGainDate") or sol_detail.get("recentDate") or "暂无数据"),
                    ("今日收益", _num(sol_detail.get("gainPrice"))),
                    ("今日总价值", _num(sol_detail.get("recentPrice"))),
                    ("今日击杀", _num(sol_detail.get("totalKillNum"))),
                    ("撤离次数", _num(sol_detail.get("totalEscapeNum"))),
                ],
            )
        )
    if not mode or mode == "mp":
        sections.append(
            _section(
                "全面战场",
                [
                    ("最近日期", mp_detail.get("recentDate") or "暂无数据"),
                    ("今日对局", _num(mp_detail.get("totalFightNum"))),
                    ("今日胜场", _num(mp_detail.get("totalWinNum"))),
                    ("今日击杀", _num(mp_detail.get("totalKillNum"))),
                    ("今日得分", _num(mp_detail.get("totalScore"))),
                ],
            )
        )
    return {
        "title": "三角洲日报",
        "subtitle": date_text,
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": "".join(sections) or "<section class='panel'><div class='empty'>暂无日报数据</div></section>",
    }


def daily_fallback_text(daily_payload: dict, mode: str) -> str:
    root = daily_payload.get("data") or {}
    if not root:
        return "暂无日报数据"
    if mode == "sol":
        detail = _find_daily_sol(root)
        return f"烽火地带\n最近日期: {detail.get('recentGainDate') or '-'}\n今日收益: {_num(detail.get('gainPrice'))}"
    if mode == "mp":
        detail = _find_daily_mp(root)
        return f"全面战场\n最近日期: {detail.get('recentDate') or '-'}\n今日对局: {_num(detail.get('totalFightNum'))}"
    return "日报查询成功，请检查图片渲染环境。"


def build_weekly_context(
    user_id: str,
    personal_info: dict,
    weekly_payload: dict,
    mode: str,
    date_text: str,
) -> dict:
    data_root = weekly_payload.get("data") or {}
    if mode:
        detail = (data_root.get("data") or {}).get("data") or {}
        sol_data = detail if mode == "sol" else {}
        mp_data = detail if mode == "mp" else {}
    else:
        sol_data = ((data_root.get("sol") or {}).get("data") or {}).get("data") or {}
        mp_data = ((data_root.get("mp") or {}).get("data") or {}).get("data") or {}

    sections = []
    if not mode or mode == "sol":
        sections.append(
            _section(
                "烽火地带周报",
                [
                    ("总对局", _num(sol_data.get("total_sol_num"))),
                    ("总收益", _num(sol_data.get("Gained_Price"))),
                    ("总消耗", _num(sol_data.get("consume_Price"))),
                    ("击杀", _num(sol_data.get("Total_Kill_Player_Num"))),
                    ("撤离", _num(sol_data.get("Total_Escape_Num"))),
                ],
            )
        )
    if not mode or mode == "mp":
        sections.append(
            _section(
                "全面战场周报",
                [
                    ("总对局", _num(mp_data.get("total_mp_num"))),
                    ("总胜场", _num(mp_data.get("total_win_num"))),
                    ("总击杀", _num(mp_data.get("Total_Kill_Num"))),
                    ("总助攻", _num(mp_data.get("Total_Assist_Num"))),
                    ("总得分", _num(mp_data.get("Total_Score"))),
                ],
            )
        )
    return {
        "title": "三角洲周报",
        "subtitle": date_text,
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": "".join(sections) or "<section class='panel'><div class='empty'>暂无周报数据</div></section>",
    }


def weekly_fallback_text(weekly_payload: dict, mode: str) -> str:
    root = weekly_payload.get("data") or {}
    if not root:
        return "暂无周报数据"
    if mode == "sol":
        data = ((root.get("data") or {}).get("data") or {})
        return f"烽火地带周报\n总对局: {_num(data.get('total_sol_num'))}\n总收益: {_num(data.get('Gained_Price'))}"
    if mode == "mp":
        data = ((root.get("data") or {}).get("data") or {})
        return f"全面战场周报\n总对局: {_num(data.get('total_mp_num'))}\n总胜场: {_num(data.get('total_win_num'))}"
    return "周报查询成功，请检查图片渲染环境。"


def build_record_context(
    user_id: str,
    personal_info: dict,
    records: list[dict],
    mode: str,
    page: int,
) -> dict:
    items = []
    for index, item in enumerate(records[:5], start=1):
        if mode == "sol":
            status = item.get("EscapeFailReason")
            status_text = {
                1: "撤离成功",
                "1": "撤离成功",
                2: "被玩家击杀",
                "2": "被玩家击杀",
                3: "被人机击杀",
                "3": "被人机击杀",
                10: "撤离失败",
                "10": "撤离失败",
            }.get(status, "撤离失败")
            metrics = f"价值 {_num(item.get('FinalPrice'))} / 玩家击杀 {_num(item.get('KillCount'))}"
        else:
            result = {
                1: "胜利",
                "1": "胜利",
                2: "失败",
                "2": "失败",
                3: "中途退出",
                "3": "中途退出",
            }.get(item.get("MatchResult"), "未知")
            status_text = result
            metrics = (
                f"KDA {_num(item.get('KillNum'))}/"
                f"{_num(item.get('Death'))}/{_num(item.get('Assist'))} / 得分 {_num(item.get('TotalScore'))}"
            )
        items.append(
            "<div class='record'>"
            f"<div class='record-title'>{index + (max(1, page) - 1) * 5}. {escape(str(item.get('dtEventTime') or '-'))}</div>"
            f"<div class='record-meta'>{escape(mode_name(mode))} | {escape(status_text)}</div>"
            f"<div class='record-metrics'>{escape(metrics)}</div>"
            "</div>"
        )

    body_html = "".join(items) or "<section class='panel'><div class='empty'>没有更多战绩记录</div></section>"
    return {
        "title": f"三角洲战绩 · {mode_name(mode)}",
        "subtitle": f"第 {max(1, page)} 页",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": f"<section class='panel record-list'>{body_html}</section>",
    }


def record_fallback_text(records: list[dict], mode: str, page: int) -> str:
    if not records:
        return f"{mode_name(mode)} 第 {page} 页暂无更多战绩。"
    lines = [f"{mode_name(mode)} 第 {page} 页战绩:"]
    for idx, item in enumerate(records[:5], start=1):
        lines.append(f"{idx}. {item.get('dtEventTime') or '-'}")
    return "\n".join(lines)


def _short_num(value: object) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value or "0")
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    return str(int(num))


def build_place_status_context(user_id: str, personal_info: dict, place_payload: dict) -> dict:
    data = place_payload.get("data") if isinstance(place_payload.get("data"), dict) else {}
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    places = data.get("places") if isinstance(data.get("places"), list) else []
    sections = [
        _section(
            "总体状态",
            [
                ("总设施", _num(stats.get("total"), default="0")),
                ("生产中", _num(stats.get("producing"), default="0")),
                ("闲置", _num(stats.get("idle"), default="0")),
            ],
        )
    ]
    active_rows: list[tuple[str, object]] = []
    idle_rows: list[tuple[str, object]] = []
    for place in places[:8]:
        if not isinstance(place, dict):
            continue
        place_name = str(place.get("placeName") or place.get("placeType") or "未知设施")
        level = _num(place.get("level"), default="0")
        detail = place.get("objectDetail") if isinstance(place.get("objectDetail"), dict) else {}
        if detail:
            object_name = str(detail.get("objectName") or detail.get("name") or "未知物品")
            left_time = place.get("leftTime")
            try:
                seconds = max(0, int(float(left_time or 0)))
                h = seconds // 3600
                m = (seconds % 3600) // 60
                s = seconds % 60
                left_text = f"{h}小时{m}分{s}秒"
            except (TypeError, ValueError):
                left_text = "N/A"
            active_rows.append((f"{place_name} Lv.{level}", f"{object_name} · 剩余 {left_text}"))
        else:
            idle_rows.append((f"{place_name} Lv.{level}", str(place.get("status") or "闲置")))
    if active_rows:
        sections.append(_section("生产中设施", active_rows))
    if idle_rows:
        sections.append(_section("空闲设施", idle_rows))
    if len(sections) == 1:
        sections.append("<section class='panel'><div class='empty'>暂无特勤处状态数据</div></section>")
    return {
        "title": "三角洲特勤处状态",
        "subtitle": f"设施 {len(places)} 项",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": "".join(sections),
    }


def place_status_fallback_text(place_payload: dict) -> str:
    data = place_payload.get("data") if isinstance(place_payload.get("data"), dict) else {}
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
    places = data.get("places") if isinstance(data.get("places"), list) else []
    if not places and not stats:
        return "未能查询到任何特勤处设施信息。"
    lines = [
        "三角洲特勤处状态",
        f"总设施: {_num(stats.get('total'), default='0')} | 生产中: {_num(stats.get('producing'), default='0')} | 闲置: {_num(stats.get('idle'), default='0')}",
    ]
    for place in places[:6]:
        if not isinstance(place, dict):
            continue
        name = str(place.get("placeName") or place.get("placeType") or "未知设施")
        level = _num(place.get("level"), default="0")
        detail = place.get("objectDetail") if isinstance(place.get("objectDetail"), dict) else {}
        if detail:
            item = str(detail.get("objectName") or detail.get("name") or "未知物品")
            lines.append(f"{name} Lv.{level}: 生产中 · {item}")
        else:
            lines.append(f"{name} Lv.{level}: {place.get('status') or '闲置'}")
    return "\n".join(lines)


def _extract_sol_detail(personal_data_payload: dict) -> dict:
    data = personal_data_payload.get("data") if isinstance(personal_data_payload, dict) else {}
    if not isinstance(data, dict):
        return {}
    sol = data.get("sol") if isinstance(data.get("sol"), dict) else {}
    sol_data = sol.get("data") if isinstance(sol.get("data"), dict) else {}
    inner = sol_data.get("data") if isinstance(sol_data.get("data"), dict) else {}
    detail = inner.get("solDetail") if isinstance(inner.get("solDetail"), dict) else {}
    return detail


def _keywords_list(payload: dict) -> list[dict]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    keywords = data.get("keywords") if isinstance(data.get("keywords"), list) else []
    return [item for item in keywords if isinstance(item, dict)]


def _object_meta_map(search_payload: dict) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for item in _keywords_list(search_payload):
        mapping[str(item.get("objectID") or item.get("id") or "")] = item
    return mapping


def build_red_collection_context(
    user_id: str,
    personal_info: dict,
    personal_data_payload: dict,
    title_payload: dict,
    object_list_payload: dict,
    search_payload: dict,
    season_display: str,
) -> dict:
    sol_detail = _extract_sol_detail(personal_data_payload)
    title_data = title_payload.get("data") if isinstance(title_payload.get("data"), dict) else {}
    red_detail = sol_detail.get("redCollectionDetail") if isinstance(sol_detail.get("redCollectionDetail"), list) else []
    object_meta = _object_meta_map(search_payload)
    all_red_objects = [item for item in _keywords_list(object_list_payload) if int(item.get("grade") or 0) == 6]
    collected_ids = {str(item.get("objectID") or "") for item in red_detail if isinstance(item, dict)}
    top_items = sorted(
        [item for item in red_detail if isinstance(item, dict)],
        key=lambda item: float(item.get("price") or 0),
        reverse=True,
    )[:6]
    top_rows = []
    for item in top_items:
        object_id = str(item.get("objectID") or "")
        meta = object_meta.get(object_id, {})
        name = str(meta.get("gameName") or meta.get("objectName") or object_id or "未知物品")
        top_rows.append((name, f"{_num(item.get('count'), default='1')} 个 · {_short_num(item.get('price') or 0)}"))
    uncollected = [item for item in all_red_objects if str(item.get("objectID") or "") not in collected_ids]
    uncollected = sorted(uncollected, key=lambda item: float(item.get("avgPrice") or 0), reverse=True)[:3]
    unlocked_rows = [
        (
            str(item.get("gameName") or item.get("objectName") or "未知物品"),
            f"参考价 {_short_num(item.get('avgPrice') or 0)}",
        )
        for item in uncollected
    ]
    sections = [
        _section(
            "收藏概览",
            [
                ("赛季", season_display),
                ("大红种数", len(collected_ids)),
                ("大红总数", _num(sol_detail.get("redTotalCount"), default="0")),
                ("收藏价值", _short_num(sol_detail.get("redTotalMoney") or 0)),
            ],
        ),
        _section("已收藏高价值大红", top_rows),
        _section("未解锁推荐", unlocked_rows),
    ]
    subtitle = str(title_data.get("title") or "大红收藏馆")
    return {
        "title": "三角洲大红收藏",
        "subtitle": f"{subtitle} · {season_display}",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": "".join(sections),
    }


def red_collection_fallback_text(
    personal_data_payload: dict,
    title_payload: dict,
    object_list_payload: dict,
    search_payload: dict,
    season_display: str,
) -> str:
    sol_detail = _extract_sol_detail(personal_data_payload)
    red_detail = sol_detail.get("redCollectionDetail") if isinstance(sol_detail.get("redCollectionDetail"), list) else []
    if not red_detail:
        return "您还没有任何大红收藏品。"
    object_meta = _object_meta_map(search_payload)
    top_items = sorted(
        [item for item in red_detail if isinstance(item, dict)],
        key=lambda item: float(item.get("price") or 0),
        reverse=True,
    )[:5]
    lines = [
        f"三角洲大红收藏（{season_display}）",
        f"收藏大红种数: {len({str(item.get('objectID') or '') for item in red_detail if isinstance(item, dict)})}",
        f"收藏大红个数: {_num(sol_detail.get('redTotalCount'), default='0')}",
        f"收藏价值: {_short_num(sol_detail.get('redTotalMoney') or 0)}",
    ]
    for index, item in enumerate(top_items, start=1):
        object_id = str(item.get("objectID") or "")
        meta = object_meta.get(object_id, {})
        name = str(meta.get("gameName") or meta.get("objectName") or object_id or "未知物品")
        lines.append(f"{index}. {name} · {_num(item.get('count'), default='1')} 个 · {_short_num(item.get('price') or 0)}")
    return "\n".join(lines)


def build_red_record_context(
    user_id: str,
    personal_info: dict,
    red_list_payload: dict,
    search_payload: dict,
) -> dict:
    data = red_list_payload.get("data") if isinstance(red_list_payload.get("data"), dict) else {}
    records = data.get("records") if isinstance(data.get("records"), dict) else {}
    entries = records.get("list") if isinstance(records.get("list"), list) else []
    object_meta = _object_meta_map(search_payload)
    aggregated: dict[str, dict] = {}
    total_count = 0
    total_value = 0.0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        object_id = str(entry.get("itemId") or "")
        count = int(entry.get("num") or 1)
        meta = object_meta.get(object_id, {})
        name = str(meta.get("gameName") or meta.get("objectName") or object_id or "未知物品")
        price = float(meta.get("avgPrice") or 0)
        total_count += count
        total_value += price * count
        row = aggregated.setdefault(object_id, {"name": name, "count": 0, "value": 0.0})
        row["count"] += count
        row["value"] += price * count
    top_items = sorted(aggregated.values(), key=lambda item: float(item.get("value") or 0), reverse=True)[:6]
    item_rows = [
        (
            str(item.get("name") or "未知物品"),
            f"{_num(item.get('count'), default='0')} 个 · {_short_num(item.get('value') or 0)}",
        )
        for item in top_items
    ]
    body_html = "".join(
        [
            _section(
                "记录概览",
                [
                    ("大红种数", len(aggregated)),
                    ("大红总数", total_count),
                    ("估算总价值", _short_num(total_value)),
                    ("原始记录数", _num(records.get("total") or len(entries), default="0")),
                ],
            ),
            _section("高价值出红记录", item_rows),
        ]
    )
    return {
        "title": "三角洲大红记录",
        "subtitle": f"最近记录 {len(entries)} 条",
        "hero_name": pick_nickname(personal_info),
        "hero_image": pick_avatar_url(personal_info) or qq_avatar_url(user_id),
        "body_html": body_html,
    }


def red_record_fallback_text(red_list_payload: dict, search_payload: dict) -> str:
    data = red_list_payload.get("data") if isinstance(red_list_payload.get("data"), dict) else {}
    records = data.get("records") if isinstance(data.get("records"), dict) else {}
    entries = records.get("list") if isinstance(records.get("list"), list) else []
    if not entries:
        return "您还没有任何藏品解锁记录。"
    object_meta = _object_meta_map(search_payload)
    aggregated: dict[str, dict] = {}
    total_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        object_id = str(entry.get("itemId") or "")
        count = int(entry.get("num") or 1)
        meta = object_meta.get(object_id, {})
        name = str(meta.get("gameName") or meta.get("objectName") or object_id or "未知物品")
        row = aggregated.setdefault(object_id, {"name": name, "count": 0, "value": 0.0})
        row["count"] += count
        row["value"] += float(meta.get("avgPrice") or 0) * count
        total_count += count
    top_items = sorted(aggregated.values(), key=lambda item: float(item.get("value") or 0), reverse=True)[:5]
    lines = [
        "三角洲大红记录",
        f"大红种数: {len(aggregated)}",
        f"大红总数: {total_count}",
    ]
    for index, item in enumerate(top_items, start=1):
        lines.append(f"{index}. {item['name']} · {item['count']} 个 · {_short_num(item['value'])}")
    return "\n".join(lines)


def format_daily_keyword_text(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    entries = data.get("list") if isinstance(data.get("list"), list) else []
    if not entries:
        return "今日暂无每日密码数据。"
    lines = ["【每日密码】"]
    for item in entries:
        if not isinstance(item, dict):
            continue
        lines.append(f"【{item.get('mapName') or '未知地图'}】: {item.get('secret') or '-'}")
    return "\n".join(lines)


def _solution_items(payload: dict) -> list[dict]:
    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("list"), list):
            return [item for item in data.get("list") if isinstance(item, dict)]
        if isinstance(data.get("keywords"), list):
            return [item for item in data.get("keywords") if isinstance(item, dict)]
    return []


def format_solution_list_text(payload: dict, weapon_name: str = "", price_range: str = "") -> str:
    items = _solution_items(payload)
    if not items:
        return "未找到符合条件的社区改枪码。"
    filters = []
    if weapon_name:
        filters.append(f"武器:{weapon_name}")
    if price_range:
        filters.append(f"价格:{price_range}")
    title = "社区改枪码列表"
    if filters:
        title += f"（{'，'.join(filters)}）"
    lines = [title]
    for index, item in enumerate(items[:8], start=1):
        solution_id = item.get("id") or item.get("solutionId") or "-"
        code = str(item.get("solutionCode") or "-")
        weapon = str(item.get("weaponName") or "未知武器")
        mode = "烽火地带" if str(item.get("type") or "sol") == "sol" else "全面战场"
        price = _num(item.get("totalPrice"), default="未知")
        author = str(item.get("authorNickname") or item.get("author") or "匿名")
        lines.append(f"{index}. ID {solution_id} | {weapon} | {mode} | {price}")
        lines.append(f"   改枪码: {code}")
        lines.append(f"   作者: {author}")
    if len(items) > 8:
        lines.append(f"共 {len(items)} 条，仅显示前 8 条。")
    return "\n".join(lines)


def format_solution_detail_text(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not data:
        return "未找到该改枪码详情。"
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    stats = data.get("statistics") if isinstance(data.get("statistics"), dict) else {}
    weapon = data.get("weapon") if isinstance(data.get("weapon"), dict) else {}
    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    attachments = data.get("attachments") if isinstance(data.get("attachments"), list) else []
    lines = [
        "社区改枪码详情",
        f"方案ID: {data.get('id') or data.get('solutionId') or '-'}",
        f"改枪码: {data.get('solutionCode') or '-'}",
        f"武器: {weapon.get('objectName') or data.get('weaponName') or '未知武器'}",
        f"模式: {'烽火地带' if str(meta.get('type') or 'sol') == 'sol' else '全面战场'}",
        f"总价格: {_num(stats.get('totalPrice'), default='未知')}",
        f"作者: {author.get('platformID') or data.get('authorNickname') or '匿名'}",
        f"浏览: {_num(stats.get('views'), default='0')} | 👍 {_num(stats.get('likes'), default='0')} | 👎 {_num(stats.get('dislikes'), default='0')}",
    ]
    desc = str(data.get("description") or data.get("desc") or "").strip()
    if desc:
        lines.append(f"描述: {desc}")
    if attachments:
        lines.append("配件:")
        for idx, item in enumerate(attachments[:6], start=1):
            if not isinstance(item, dict):
                continue
            lines.append(f"{idx}. {item.get('objectName') or item.get('objectID') or '未知配件'} - {_num(item.get('price'), default='未知')}")
    return "\n".join(lines)


def format_object_search_text(payload: dict, query: str) -> str:
    items = _keywords_list(payload)
    if not items:
        return f"未找到与“{query}”相关的物品。"
    lines = [f"物品搜索结果（{query}）"]
    for index, item in enumerate(items[:8], start=1):
        object_id = item.get("objectID") or item.get("id") or "-"
        name = str(item.get("gameName") or item.get("objectName") or "未知物品")
        primary = str(item.get("primaryClass") or item.get("primary") or "").strip()
        second = str(item.get("secondClass") or item.get("second") or "").strip()
        avg_price = item.get("avgPrice")
        type_bits = " / ".join(part for part in (primary, second) if part)
        lines.append(f"{index}. {name} (ID: {object_id})")
        if type_bits:
            lines.append(f"   分类: {type_bits}")
        if avg_price not in (None, ""):
            lines.append(f"   参考均价: {_num(avg_price, default='未知')}")
    if len(items) > 8:
        lines.append(f"共 {len(items)} 条，仅显示前 8 条。")
    return "\n".join(lines)


def format_price_history_text(search_payload: dict, history_payload: dict, query: str) -> str:
    item = None
    items = _keywords_list(search_payload)
    if items:
        item = items[0]
    object_name = str((item or {}).get("gameName") or (item or {}).get("objectName") or query or "未知物品")
    object_id = str((item or {}).get("objectID") or (item or {}).get("id") or "").strip()

    data = history_payload.get("data") if isinstance(history_payload.get("data"), dict) else {}
    history = data.get("history") if isinstance(data.get("history"), list) else []
    stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}

    if not history:
        # V1 / 兼容结构
        alt_history = data.get("list") if isinstance(data.get("list"), list) else []
        if alt_history:
            history = alt_history
        elif isinstance(data, list):
            history = data
    if not history and not stats:
        return f"{object_name} 暂无价格历史数据。"

    lines = [f"{object_name} 价格历史"]
    if object_id:
        lines.append(f"物品ID: {object_id}")
    if stats:
        latest = stats.get("latestPrice")
        avg = stats.get("avgPrice")
        high = stats.get("maxPrice")
        low = stats.get("minPrice")
        spread = stats.get("priceRange")
        if latest not in (None, ""):
            lines.append(f"当前价格: {_num(latest)}")
        if avg not in (None, ""):
            lines.append(f"平均价格: {_num(avg)}")
        if high not in (None, ""):
            lines.append(f"最高价格: {_num(high)}")
        if low not in (None, ""):
            lines.append(f"最低价格: {_num(low)}")
        if spread not in (None, ""):
            lines.append(f"价格波动: {_num(spread)}")
    if history:
        lines.append("最近记录:")
        recent = history[:5]
        for entry in recent:
            if not isinstance(entry, dict):
                continue
            timestamp = entry.get("timestamp") or entry.get("time") or "-"
            if isinstance(timestamp, (int, float)):
                try:
                    ts_val = int(timestamp)
                    if ts_val > 10_000_000_000:
                        dt = datetime.fromtimestamp(ts_val / 1000)
                    else:
                        dt = datetime.fromtimestamp(ts_val)
                    time_text = dt.strftime("%m-%d %H:%M")
                except Exception:
                    time_text = str(timestamp)
            else:
                time_text = str(timestamp)
            price = entry.get("avgPrice")
            if price in (None, ""):
                price = entry.get("price")
            lines.append(f"- {time_text}: {_num(price, default='未知')}")
    return "\n".join(lines)


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")
