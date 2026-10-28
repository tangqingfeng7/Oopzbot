"""管理后台的活动屏幕共享视图。"""

import logging
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from oopz.name_resolver import get_resolver
from screen_share import ScreenShareError, get_screen_share_service
from screen_share.web import announce_ended

router = APIRouter()
logger = logging.getLogger(__name__)
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


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
