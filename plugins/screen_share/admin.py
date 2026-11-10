import logging
import re
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from oopz.name_resolver import get_resolver
from web.admin.shared._pages import render_admin_page

from .service import ScreenShareError, get_screen_share_service
from .web import announce_ended

router = APIRouter()
logger = logging.getLogger(__name__)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PAGE = {
    "page_title": "屏幕共享",
    "page_id": "screen-share",
    "brand_title": "屏幕共享",
    "brand_copy": "集中查看活动共享、频道归属和临时观看链接。",
    "topbar_actions": [{"action": "refresh-screen-shares", "label": "刷新共享"}],
    "login_title": "登录屏幕共享管理",
    "login_copy": "登录后查看当前活动共享与观看链接。",
    "login_button": "进入屏幕共享",
}


@router.get("/admin/screen-share", response_class=HTMLResponse)
def admin_screen_share_page():
    return render_admin_page(_PAGE, Path(__file__).with_name("admin_assets"))


@router.get("/admin/api/screen-shares")
async def admin_screen_shares():
    try:
        shares = await get_screen_share_service().admin_active_shares()
    except ScreenShareError as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc), "code": exc.code},
            status_code=exc.status_code,
        )
    except Exception:
        logger.warning("管理后台读取屏幕共享失败", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "屏幕共享服务暂时不可用",
                "code": "screen_share_unavailable",
            },
            status_code=503,
        )
    resolver = get_resolver()
    presenter_uids = [str(share.get("presenter_uid") or "") for share in shares]
    try:
        resolved_users = await resolver.ensure_users(presenter_uids)
    except Exception:
        logger.warning("管理后台解析屏幕共享发起者失败", exc_info=True)
        resolved_users = {}
    for share in shares:
        area_id = str(share.get("area") or "")
        channel_id = str(share.get("channel") or "")
        presenter_uid = str(share.get("presenter_uid") or "")
        share["area_name"] = resolver.area(area_id) or area_id
        share["channel_name"] = resolver.channel(channel_id) or channel_id
        share["presenter_name"] = (
            resolved_users.get(presenter_uid)
            or resolver.user(presenter_uid)
            or presenter_uid
        )
    return JSONResponse({"ok": True, "shares": shares})


@router.post("/admin/api/screen-shares/{session_id}/stop")
async def admin_stop_screen_share(session_id: str):
    normalized_id = str(session_id or "").strip()
    if not _SESSION_ID_RE.fullmatch(normalized_id):
        return JSONResponse(
            {"ok": False, "error": "屏幕共享会话 ID 无效", "code": "invalid_session_id"},
            status_code=400,
        )
    try:
        session = await get_screen_share_service().stop_by_id(
            normalized_id,
            reason="admin_stop",
        )
        if session is None:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "屏幕共享已结束或不存在",
                    "code": "session_not_found",
                },
                status_code=404,
            )
        await announce_ended(session)
    except ScreenShareError as exc:
        return JSONResponse(
            {"ok": False, "error": str(exc), "code": exc.code},
            status_code=exc.status_code,
        )
    except Exception:
        logger.warning("管理后台结束屏幕共享失败", exc_info=True)
        return JSONResponse(
            {
                "ok": False,
                "error": "屏幕共享服务暂时不可用",
                "code": "screen_share_unavailable",
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "ok": True,
            "session_id": normalized_id,
            "message": "屏幕共享已结束",
        }
    )


__all__ = ["router"]
