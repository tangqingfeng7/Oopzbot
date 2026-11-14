from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse

from core.database import MessageStatsDB
from core.logger_config import get_logger
from oopz.name_resolver import get_resolver
from web.admin.shared._pages import render_admin_page

router = APIRouter()
logger = get_logger("StatsAdmin")
_PAGE = {
    "page_title": "活跃统计",
    "page_id": "activity",
    "brand_title": "活跃统计",
    "brand_copy": "频道消息趋势与用户活跃排行一览。",
    "topbar_actions": [{"action": "refresh-activity", "label": "刷新统计"}],
    "login_title": "登录活跃统计",
    "login_copy": "登录后查看消息趋势与活跃排行。",
    "login_button": "进入活跃统计",
}


@router.get("/admin/activity", response_class=HTMLResponse)
def admin_activity_page():
    return render_admin_page(_PAGE, Path(__file__).with_name("admin_assets"))


@router.get("/admin/api/message-stats/daily")
async def admin_message_stats_daily(days: int = Query(14, ge=1, le=90)):
    daily = await MessageStatsDB.get_all_daily(days=days)
    return JSONResponse({"ok": True, "daily": daily})


@router.get("/admin/api/message-stats/ranking")
async def admin_message_stats_ranking(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
    area_id: str = Query(""),
):
    # area_id 留空时跨全部域聚合，与日趋势/概览口径一致
    ranking = await MessageStatsDB.get_user_ranking(area_id, days=days, limit=limit)
    resolver = get_resolver()
    try:
        await resolver.ensure_users([item["user_id"] for item in ranking])
    except Exception:
        logger.warning("消息排行榜补全用户昵称失败", exc_info=True)
    for item in ranking:
        item["display_name"] = resolver.user(item["user_id"])
    return JSONResponse({"ok": True, "ranking": ranking})


@router.get("/admin/api/message-stats/overview")
async def admin_message_stats_overview():
    return JSONResponse({
        "ok": True,
        "today_messages": await MessageStatsDB.get_today_total(),
        "week_messages": await MessageStatsDB.get_week_total(),
        "active_users_today": await MessageStatsDB.get_active_users_today(),
    })


__all__ = ["router"]
