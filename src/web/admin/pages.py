from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from web.admin.shared import (
    _render_admin_page,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# 管理后台页面路由
# ---------------------------------------------------------------------------

@router.get("/admin", response_class=HTMLResponse)
def admin_index():
    return _render_admin_page("dashboard")


@router.get("/admin/music", response_class=HTMLResponse)
def admin_music_page():
    return _render_admin_page("music")


@router.get("/admin/config", response_class=HTMLResponse)
def admin_config_page():
    return _render_admin_page("config")


@router.get("/admin/stats", response_class=HTMLResponse)
def admin_stats_page():
    return _render_admin_page("stats")


@router.get("/admin/system", response_class=HTMLResponse)
def admin_system_page():
    return _render_admin_page("system")


@router.get("/admin/activity", response_class=HTMLResponse)
def admin_activity_page():
    return _render_admin_page("activity")


@router.get("/admin/scheduler", response_class=HTMLResponse)
def admin_scheduler_page():
    return _render_admin_page("scheduler")


@router.get("/admin/areas", response_class=HTMLResponse)
def admin_areas_page():
    return _render_admin_page("areas")


@router.get("/admin/plugins", response_class=HTMLResponse)
def admin_plugins_page():
    return _render_admin_page("plugins")


@router.get("/admin/setup", response_class=HTMLResponse)
def admin_setup_page():
    return _render_admin_page("setup")

__all__ = ["router"]
