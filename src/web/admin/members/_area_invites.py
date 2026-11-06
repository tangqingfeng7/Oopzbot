"""私信域邀请的后台待审批端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import AreaInviteRequestDB
from services.area_invite_inbox import normalize_area_invite_code
from web.admin.shared import _require_sender, read_json_body, require_sender

router = APIRouter()

_ACTIVE_INVITE_STATUS = "INVITE_NORMAL"


def extract_area_invite_code(value: object) -> str:
    """兼容旧调用名称；实际规范化逻辑位于私信邀请服务。"""
    return normalize_area_invite_code(value)




async def _resolve_invite(sender, value: object) -> tuple[str, dict[str, Any]]:
    code = extract_area_invite_code(value)
    detail = await sender.get_area_invite_detail(code)
    if not isinstance(detail, dict):
        raise RuntimeError("邀请信息返回格式异常")
    if detail.get("error"):
        raise RuntimeError(str(detail["error"]))

    area_id = str(detail.get("area") or "").strip()
    status = str(detail.get("status") or "").strip()
    is_area_invite = bool(detail.get("isAreaInvite"))
    if not area_id:
        raise RuntimeError("邀请信息中缺少域 ID")

    joined_areas = await sender.bot.areas.get_joined_areas()
    joined = any(item.area_id.strip() == area_id for item in joined_areas)

    reason = ""
    if not is_area_invite:
        reason = "该链接不是域邀请"
    elif status != _ACTIVE_INVITE_STATUS:
        reason = f"邀请当前不可用（{status or '未知状态'}）"
    elif joined:
        reason = "Bot 已经加入该域"

    return code, {
        "code": code,
        "status": status,
        "area": area_id,
        "areaName": str(detail.get("areaName") or ""),
        "areaAvatar": str(detail.get("areaAvatar") or ""),
        "banner": str(detail.get("banner") or ""),
        "channel": str(detail.get("channel") or ""),
        "channelName": str(detail.get("channelName") or ""),
        "channelType": str(detail.get("channelType") or ""),
        "isAreaInvite": is_area_invite,
        "joined": joined,
        "canAccept": not reason,
        "reason": reason,
    }


def _stored_invite(row: dict[str, Any], joined_area_ids: set[str]) -> dict[str, Any]:
    area_id = str(row.get("area_id") or "")
    status = str(row.get("invite_status") or "")
    joined = area_id in joined_area_ids
    reason = ""
    if not bool(row.get("is_area_invite")):
        reason = "该链接不是域邀请"
    elif status != _ACTIVE_INVITE_STATUS:
        reason = f"邀请当前不可用（{status or '未知状态'}）"
    elif joined:
        reason = "Bot 已经加入该域"
    return {
        "code": str(row.get("code") or ""),
        "status": status,
        "area": area_id,
        "areaName": str(row.get("area_name") or ""),
        "areaAvatar": str(row.get("area_avatar") or ""),
        "banner": str(row.get("banner") or ""),
        "channel": str(row.get("channel_id") or ""),
        "channelName": str(row.get("channel_name") or ""),
        "channelType": str(row.get("channel_type") or ""),
        "isAreaInvite": bool(row.get("is_area_invite")),
        "senderId": str(row.get("sender_id") or ""),
        "senderName": str(row.get("sender_name") or ""),
        "messageId": str(row.get("message_id") or ""),
        "messageTimestamp": str(row.get("message_timestamp") or ""),
        "receivedAt": str(row.get("received_at") or ""),
        "joined": joined,
        "canAccept": not reason,
        "reason": reason,
    }


@router.get("/admin/api/area-invites")
@require_sender
async def admin_area_invite_list():
    sender = _require_sender()
    rows = await AreaInviteRequestDB.list_pending()
    try:
        joined_areas = await sender.bot.areas.get_joined_areas()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    joined_ids = {
        item.area_id.strip()
        for item in joined_areas
        if item.area_id.strip()
    }
    return JSONResponse(
        {"ok": True, "invites": [_stored_invite(row, joined_ids) for row in rows]},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/admin/api/area-invites/accept")
@require_sender
async def admin_area_invite_accept(request: Request):
    body = await read_json_body(request)
    sender = _require_sender()
    try:
        code = normalize_area_invite_code(body.get("code"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    pending = await AreaInviteRequestDB.get_pending(code)
    if pending is None:
        return JSONResponse(
            {"ok": False, "error": "未找到对应的待处理私信邀请"},
            status_code=404,
        )

    try:
        _, invite = await _resolve_invite(sender, code)
    except Exception as exc:
        return JSONResponse(
            {"ok": False, "error": f"识别邀请失败: {exc}"},
            status_code=502,
        )

    if not invite["canAccept"]:
        return JSONResponse(
            {"ok": False, "error": invite["reason"], "invite": invite},
            status_code=409,
        )

    try:
        result = await sender.bot.areas.enter_area(area=invite["area"], recover=False)
        if not result.ok:
            raise RuntimeError(result.message or "Oopz 拒绝了请求")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"接受邀请失败: {exc}"}, status_code=502)

    await AreaInviteRequestDB.mark_processed(code, "accepted")
    # 让域管理页立即看到新加入的域，不等待列表缓存自然过期。
    from ._members import _areas_cache

    _areas_cache.invalidate("all")
    invite["joined"] = True
    invite["canAccept"] = False
    invite["reason"] = "Bot 已经加入该域"
    return {
        "ok": True,
        "message": result.message or f"Bot 已加入「{invite['areaName'] or invite['area']}」",
        "invite": invite,
    }


@router.post("/admin/api/area-invites/reject")
@require_sender
async def admin_area_invite_reject(request: Request):
    body = await read_json_body(request)
    try:
        code = normalize_area_invite_code(body.get("code"))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if not await AreaInviteRequestDB.mark_processed(code, "rejected"):
        return JSONResponse(
            {"ok": False, "error": "未找到对应的待处理私信邀请"},
            status_code=404,
        )
    return {"ok": True, "message": "已忽略该域邀请"}


__all__ = ["extract_area_invite_code", "router"]
