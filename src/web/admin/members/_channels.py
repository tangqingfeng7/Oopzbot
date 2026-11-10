"""频道管理：列表、增删改、设置、可访问成员、在线成员与语音频道监控。"""


from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.infrastructure.oopz_connection import (
    channels_response_cache as _channels_cache,
)
from web.admin.shared import (
    _get_sender,
    _require_sender,
    _resolve_area_async,
    get_resolver,
    logger,
    read_json_body,
    require_sender,
)

router = APIRouter()

@router.get("/admin/api/channels")
async def admin_channels_list(area: str = Query("")):
    """返回指定域的频道列表(含分组)。"""
    resolved_area = area.strip() or await _resolve_area_async()
    if not resolved_area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID"})

    cached = _channels_cache.get(resolved_area)
    if cached is not None:
        return JSONResponse(cached)

    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)

    try:
        groups = await sender.bot.areas.get_area_channels(resolved_area)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    channels = []
    for g in groups:
        group_name = g.name
        for ch in g.channels:
            ch_type = ch.channel_type
            channels.append({
                "id": ch.channel_id,
                "name": ch.name,
                "group": group_name,
                "type": ch_type,
                "secret": ch.secret,
            })

    resp = {"ok": True, "channels": channels, "area": resolved_area}
    _channels_cache.set(resolved_area, resp)
    return JSONResponse(resp)


@router.post("/admin/api/channels/create")
@require_sender
async def admin_channel_create(request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    name = (body.get("name") or "").strip()
    ch_type = body.get("type", "text")
    group_id = (body.get("group_id") or "").strip()
    if not area or not name:
        return JSONResponse({"ok": False, "error": "area 和 name 不能为空"}, status_code=400)
    try:
        result = await sender.bot.channels.create_channel(area=area, name=name, channel_type=ch_type, group_id=group_id)
        _channels_cache.invalidate(area)
        return JSONResponse({"ok": True, "message": "频道已创建", "result": {"channel": result.channel_id, "name": result.name}})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.delete("/admin/api/channels/{channel_id}")
@require_sender
async def admin_channel_delete(channel_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    if not area:
        return JSONResponse({"ok": False, "error": "area 不能为空"}, status_code=400)
    try:
        result = await sender.bot.channels.delete_channel(channel=channel_id, area=area)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message}, status_code=502)
        _channels_cache.invalidate(area)
        return JSONResponse({"ok": True, "message": "频道已删除"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.put("/admin/api/channels/{channel_id}")
@require_sender
async def admin_channel_update(channel_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    name = (body.get("name") or "").strip()
    if not area:
        return JSONResponse({"ok": False, "error": "area 不能为空"}, status_code=400)
    try:
        result = await sender.bot.channels.update_channel(area=area, channel_id=channel_id, name=name)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message}, status_code=502)
        _channels_cache.invalidate(area)
        return JSONResponse({"ok": True, "message": "频道已更新"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/admin/api/channels/{channel_id}/settings")
@require_sender
async def admin_channel_settings(channel_id: str, area: str = Query("")):
    """获取频道的详细设置信息。"""
    sender = _require_sender()
    try:
        data = await sender.bot.channels.get_channel_setting_info(channel_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "settings": data.model_dump(by_alias=True, exclude_none=True)})


@router.post("/admin/api/channels/{channel_id}/settings")
@require_sender
async def admin_channel_settings_edit(channel_id: str, request: Request):
    """编辑频道设置（名称、人数上限、慢速模式等）。"""
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.pop("area", "") or "").strip() or await _resolve_area_async()
    if not area:
        return JSONResponse({"ok": False, "error": "area 不能为空"}, status_code=400)
    mapping = {
        "textGapSecond": "text_gap_second", "voiceQuality": "voice_quality",
        "voiceDelay": "voice_delay", "maxMember": "max_member",
        "voiceControlEnabled": "voice_control_enabled", "textControlEnabled": "text_control_enabled",
        "accessControlEnabled": "access_control_enabled", "hasPassword": "has_password",
        "textRoles": "text_roles", "voiceRoles": "voice_roles",
        "accessible": "accessible_roles", "accessibleMembers": "accessible_members",
    }
    settings = {mapping.get(key, key): value for key, value in body.items()}
    try:
        result = await sender.bot.channels.update_channel(area=area, channel_id=channel_id, **settings)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message}, status_code=502)
        _channels_cache.invalidate(area)
        return JSONResponse({"ok": True, "message": "频道设置已保存"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/admin/api/channels/{channel_id}/accessible-members")
@require_sender
async def admin_channel_accessible_members(channel_id: str):
    """返回频道当前的可访问成员列表（含名称）。"""
    sender = _require_sender()
    try:
        setting = await sender.bot.channels.get_channel_setting_info(channel_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    uids = setting.accessible_members
    if not uids:
        return JSONResponse({"ok": True, "members": []})
    try:
        infos = {person.uid: person for person in await sender.bot.person.get_person_infos_batch(uids)}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    members = []
    for uid in uids:
        info = infos.get(uid)
        members.append({
            "uid": uid,
            "name": get_resolver().user_cached(uid, fallback=False) or (info.name if info else "") or uid[:8],
            "avatar": info.avatar if info else "",
        })
    return JSONResponse({"ok": True, "members": members})


@router.get("/admin/api/online-members")
@require_sender
async def admin_online_members(area: str = Query("")):
    """返回域内当前在线成员（用于私密频道成员选择）。"""
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    if not resolved_area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID"})
    try:
        all_members = await sender.bot.areas.get_all_area_members(resolved_area, page_size=100)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    online_members = [m for m in all_members if m.online == 1 and m.uid]
    uids = list(dict.fromkeys(m.uid for m in online_members))
    if not uids:
        return JSONResponse({"ok": True, "members": []})
    try:
        infos = {person.uid: person for person in await sender.bot.person.get_person_infos_batch(uids)}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    members = []
    for uid in uids:
        info = infos.get(uid)
        members.append({
            "uid": uid,
            "name": get_resolver().user_cached(uid, fallback=False) or (info.name if info else "") or uid[:8],
        })
    return JSONResponse({"ok": True, "members": members})


@router.get("/admin/api/voice-channels")
async def admin_voice_channels(area: str = Query("")):
    """返回域内语音频道及其在线用户。"""
    resolved_area = area.strip() or await _resolve_area_async()
    if not resolved_area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID"})

    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)

    try:
        groups = await sender.bot.areas.get_area_channels(resolved_area)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    voice_info = {}
    for g in groups:
        for ch in g.channels:
            ch_type = str(ch.channel_type).upper()
            if ch_type in ("VOICE", "AUDIO"):
                voice_info[ch.channel_id] = {
                    "name": ch.name,
                    "group": g.name,
                }

    try:
        channel_members = (await sender.bot.channels.get_voice_channel_members(resolved_area)).channel_members
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    all_uids: list[str] = []
    for ch_id in voice_info:
        for m in channel_members.get(ch_id, []):
            uid = m.uid
            if uid and uid not in all_uids:
                all_uids.append(uid)
    person_map: dict = {}
    if all_uids:
        try:
            person_map = {person.uid: person for person in await sender.bot.person.get_person_infos_batch(all_uids)}
        except Exception:
            logger.debug("批量获取语音成员信息失败", exc_info=True)

    resolver = get_resolver()
    voice_channels = []
    for ch_id, info in voice_info.items():
        raw_members = channel_members.get(ch_id, [])
        users = []
        for m in raw_members:
            uid = m.uid
            if not uid:
                continue
            pi = person_map.get(uid)
            users.append({
                "uid": uid,
                "name": resolver.user_cached(uid, fallback=False) or (pi.name if pi else "") or uid[:8],
                "avatar": pi.avatar if pi else "",
            })
        voice_channels.append({
            "id": ch_id,
            "name": info["name"],
            "group": info["group"],
            "users": users,
        })

    return JSONResponse({"ok": True, "voice_channels": voice_channels})


@router.post("/admin/api/voice-channels/dispatch")
@require_sender
async def admin_voice_dispatch(request: Request):
    """将用户从当前语音频道调度到指定语音频道。"""
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    target = (body.get("target") or "").strip()
    to_channel = (body.get("to_channel") or "").strip()
    from_channel = (body.get("from_channel") or "").strip()
    if not area:
        return JSONResponse({"ok": False, "error": "area 不能为空"}, status_code=400)
    if not target or not to_channel:
        return JSONResponse({"ok": False, "error": "target 和 to_channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.channels.drag_member(area, target, to_channel, from_channel=from_channel or "")
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})
    return JSONResponse({"ok": True, "message": result.message or "已调度"})
