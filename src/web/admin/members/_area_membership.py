"""Bot 域成员关系管理端点。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web.admin.shared import (
    _invalidate_members_cache,
    _require_sender,
    read_json_body,
    require_sender,
)

router = APIRouter()




@router.post("/admin/api/areas/leave")
@require_sender
async def admin_leave_area(request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = str(body.get("area") or "").strip()
    if not area:
        return JSONResponse({"ok": False, "error": "缺少域 ID"}, status_code=400)

    try:
        joined_areas = await sender.bot.areas.get_joined_areas()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    joined = next(
        (item for item in joined_areas if item.area_id.strip() == area),
        None,
    )
    if joined is None:
        return JSONResponse(
            {"ok": False, "error": "Bot 当前未加入该域"},
            status_code=404,
        )

    try:
        result = await sender.bot.areas.leave_area(area)
        if not result.ok:
            raise RuntimeError(result.message or "Oopz 拒绝了请求")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"退出域失败: {exc}"}, status_code=502)

    area_name = joined.name or area

    from ._channels import _channels_cache
    from ._members import _area_meta_cache, _areas_cache

    _areas_cache.invalidate("all")
    _area_meta_cache.invalidate(area)
    _channels_cache.invalidate(area)
    _invalidate_members_cache()
    return {
        "ok": True,
        "area": area,
        "message": result.message or f"Bot 已退出「{area_name}」",
    }


__all__ = ["router"]
