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
        "@bot 三角洲帮助\n"
        "@bot 三角洲登录 [qq|微信]\n"
        "@bot 三角洲角色绑定\n"
        "@bot 三角洲账号\n"
        "@bot 三角洲账号切换 <序号>\n"
        "@bot 三角洲信息\n"
        "@bot 三角洲uid\n"
        "@bot 三角洲日报 [烽火|全面]\n"
        "@bot 三角洲周报 [烽火|全面] [YYYYMMDD] [详细]\n"
        "@bot 三角洲战绩 [烽火|全面|全部] [页码]\n\n"
        "Slash: /df help | login | bind-character | accounts | switch | info | uid | daily | weekly | record"
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


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")
