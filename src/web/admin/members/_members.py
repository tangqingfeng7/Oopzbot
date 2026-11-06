"""成员管理：页面、域选择、成员列表/详情、禁言/封禁/角色等操作。"""

import asyncio
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from oopz_sdk.models import AreaMembersPage, UserInfo

from web.admin.shared import (
    MessageStatsDB,
    TtlCache,
    _get_sender,
    _invalidate_members_cache,
    _members_resp_cache,
    _render_admin_page,
    _require_sender,
    _resolve_area_async,
    get_resolver,
    logger,
    read_json_body,
    require_sender,
)

router = APIRouter()


@router.get("/admin/members", response_class=HTMLResponse)
def admin_members_page():
    return _render_admin_page("members")


_AREAS_CACHE_TTL = 120.0
_AREA_META_CACHE_TTL = 120.0
_areas_cache = TtlCache(_AREAS_CACHE_TTL, maxsize=1)
# 按域分槽：单槽缓存在多域间来回切时会互相挤掉，导致每次切域都要回源。
_area_meta_cache = TtlCache(_AREA_META_CACHE_TTL)


@router.get("/admin/api/areas")
async def admin_areas_list():
    """返回 Bot 已加入的域列表,供前端域选择器使用。"""
    cached = _areas_cache.get("all")
    if cached is not None:
        return JSONResponse(cached)
    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)
    try:
        areas = await sender.bot.areas.get_joined_areas()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    items = []
    for a in areas:
        items.append({
            "id": a.area_id,
            "name": a.name,
            "code": a.code,
            "avatar": a.avatar,
        })
    resp = {"ok": True, "areas": items}
    _areas_cache.set("all", resp)
    return JSONResponse(resp)


@router.get("/admin/api/areas/{area_id}/meta")
async def admin_area_meta(area_id: str):
    """返回域的表单辅助数据，如身份组列表。"""
    resolved_area = area_id.strip() or await _resolve_area_async()
    if not resolved_area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID"})

    cached = _area_meta_cache.get(resolved_area)
    if cached is not None:
        return JSONResponse(cached)

    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)

    try:
        area_info = await sender.bot.areas.get_area_info(resolved_area)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    roles = [{
        "id": str(role.role_id), "name": role.name, "sort": role.sort, "type": role.type,
    } for role in area_info.role_list]
    roles.sort(key=lambda item: (-item["sort"], item["name"], item["id"]))

    resp = {
        "ok": True,
        "area": resolved_area,
        "home_page_channel_id": area_info.home_page_channel_id,
        "roles": roles,
    }
    _area_meta_cache.set(resolved_area, resp)
    return JSONResponse(resp)


ALL_AREAS = "__all__"
# 跨域聚合时每个域最多取这么多人。上限由平台决定：实测 offset_end 取到 100 正常，
# 再往上（149 / 199）服务端直接回「查询数量超过限制」，整域取数会失败。
_CROSS_AREA_FETCH_LIMIT = 100


async def _area_name_map() -> dict[str, str]:
    """域 ID -> 域名，用于给跨域结果标注来源。"""
    sender = _get_sender()
    if not sender:
        return {}
    areas = await sender.bot.areas.get_joined_areas()
    return {a.area_id: (a.name or a.area_id) for a in areas if a.area_id}


@router.get("/admin/api/members")
async def admin_members_list(
    offset: int = Query(0, ge=0),
    # 上限放宽到 500 是给跨域聚合用的：那条路径从内存池切片、不回源，一次多给点
    # 才能把各域成员一起铺出来。单域仍受平台分页限制约束（见 _CROSS_AREA_FETCH_LIMIT）。
    limit: int = Query(50, ge=1, le=500),
    keyword: str = Query(""),
    area: str = Query(""),
):
    if area.strip() == ALL_AREAS:
        return await _members_across_all_areas(offset=offset, limit=limit, keyword=keyword)
    limit = min(limit, _CROSS_AREA_FETCH_LIMIT)

    resolved_area = area.strip() if area.strip() else await _resolve_area_async()
    cache_key = f"{resolved_area}:{offset}:{limit}"
    if not keyword:
        cached = _members_resp_cache.get(cache_key)
        if cached is not None:
            return JSONResponse(cached)

    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)

    if not resolved_area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID，请检查配置"})

    try:
        page = await sender.bot.areas.get_area_members(
            area=resolved_area, offset_start=offset, offset_end=offset + limit - 1,
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    members = page.members
    total = page.total_count or len(members)
    online = sum(item.count for item in page.role_count if item.role != -1)
    if not page.role_count:
        online = sum(member.online == 1 for member in page.members)

    uids = [m.uid for m in members if m.uid]
    person_map: dict = {}
    if uids:
        try:
            person_map = {person.uid: person for person in await sender.bot.person.get_person_infos_batch(uids)}
        except Exception:
            logger.debug("批量获取用户信息失败", exc_info=True)

    area_info = None
    try:
        area_info = await sender.bot.areas.get_area_info(area=resolved_area)
    except Exception:
        logger.debug("获取域信息失败 (area=%s)", resolved_area[:8] if resolved_area else "")
    role_name_map: dict[int, str] = {}
    if area_info:
        role_name_map = {role.role_id: role.name for role in area_info.role_list}

    if keyword:
        kw = keyword.lower()
        filtered = []
        for m in members:
            uid = m.uid
            pi = person_map.get(uid)
            name = get_resolver().user_cached(uid, fallback=False) or (pi.name if pi else "") or uid[:8]
            if kw in name.lower() or kw in uid.lower() or kw in ((pi.pid if pi else "") or "").lower():
                filtered.append(m)
        members = filtered
        total = len(filtered)

    from config import ADMIN_UIDS
    admin_set = set(ADMIN_UIDS)

    items = []
    for m in members:
        uid = m.uid
        pi = person_map.get(uid)
        role_id = m.role
        items.append({
            "uid": uid,
            "name": get_resolver().user_cached(uid, fallback=False) or (pi.name if pi else "") or uid[:8],
            "avatar": (pi.avatar if pi else ""),
            "pid": (pi.pid if pi else ""),
            "online": m.online == 1,
            "role": role_id,
            "roleName": role_name_map.get(int(role_id), "") if role_id else "",
            "roleSort": m.role_sort,
            "playingState": m.playing_state,
            "displayType": m.display_type,
            "is_bot_admin": uid in admin_set,
        })
    resp_data: dict = {
        "ok": True,
        "members": items,
        "total": total,
        "online": online,
        "offset": offset,
        "limit": limit,
    }
    if not keyword:
        _members_resp_cache.set(cache_key, resp_data)
    return JSONResponse(resp_data)


async def _members_across_all_areas(*, offset: int, limit: int, keyword: str) -> JSONResponse:
    """聚合全部已加入域的成员，用于全域搜索与合并列表。

    各域并发拉取，结果按域标注来源，再统一做关键词过滤与分页。没有关键词时也缓存，
    这样在合并列表里翻页、按域筛选都不必反复回源。
    """
    sender = _get_sender()
    if not sender:
        return JSONResponse({"ok": False, "error": "sender 未初始化"}, status_code=503)

    cache_key = f"{ALL_AREAS}:pool"
    pool = _members_resp_cache.get(cache_key)
    if pool is None:
        try:
            names = await _area_name_map()
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        if not names:
            return JSONResponse({"ok": False, "error": "未找到任何已加入的域"})

        async def one(area_id: str) -> tuple[str, AreaMembersPage | None]:
            try:
                return area_id, await sender.bot.areas.get_area_members(
                    area=area_id, offset_start=0,
                    offset_end=_CROSS_AREA_FETCH_LIMIT - 1,
                )
            except Exception as exc:
                logger.debug("跨域取成员失败 area=%s: %s", area_id[:8], exc)
                return area_id, None

        results = await asyncio.gather(*(one(aid) for aid in names))

        # 同一个人可能同时在多个域，按 uid 合并成一行并记录全部所属域。
        # 保持一人一行，既避免列表里重复出现，也让前端能一次展示所有域标签。
        by_uid: dict[str, dict] = {}
        failed: list[str] = []
        for area_id, result in results:
            if result is None:
                failed.append(names.get(area_id, area_id))
                continue
            members = result.members
            uids = [m.uid for m in members if m.uid]
            person_map: dict = {}
            if uids:
                try:
                    person_map = {person.uid: person for person in await sender.bot.person.get_person_infos_batch(uids)}
                except Exception:
                    logger.debug("跨域批量取用户信息失败 area=%s", area_id[:8], exc_info=True)
            for m in members:
                uid = m.uid
                if not uid:
                    continue
                membership = {
                    "areaId": area_id,
                    "areaName": names.get(area_id, area_id),
                    "role": m.role,
                    "roleSort": m.role_sort,
                }
                entry = by_uid.get(uid)
                if entry is None:
                    info = person_map.get(uid)
                    by_uid[uid] = {
                        "uid": uid,
                        "name": get_resolver().user_cached(uid, fallback=False) or (info.name if info else "") or uid[:8],
                        "avatar": (info.avatar if info else ""),
                        "pid": (info.pid if info else ""),
                        "online": m.online == 1,
                        "role": m.role,
                        "roleName": "",
                        "roleSort": m.role_sort,
                        "playingState": m.playing_state,
                        "displayType": m.display_type,
                        "areas": [membership],
                    }
                    continue
                entry["areas"].append(membership)
                # 在任一域在线就算在线；权限取各域中最高的，避免合并后被低权限域盖掉
                if m.online == 1:
                    entry["online"] = True
                    if m.playing_state:
                        entry["playingState"] = m.playing_state
                        entry["displayType"] = m.display_type
                if m.role_sort > entry["roleSort"]:
                    entry["roleSort"] = m.role_sort
                    entry["role"] = m.role

        merged = list(by_uid.values())
        for entry in merged:
            entry["areas"].sort(key=lambda a: -a["roleSort"])
            # 兼容单域视图的字段：主域取权限最高的那个
            entry["areaId"] = entry["areas"][0]["areaId"]
            entry["areaName"] = entry["areas"][0]["areaName"]
        pool = {"members": merged, "failed": failed}
        if not failed:
            _members_resp_cache.set(cache_key, pool)

    from config import ADMIN_UIDS

    admin_set = set(ADMIN_UIDS)
    items = list(pool["members"])
    if keyword:
        kw = keyword.lower()
        items = [
            m for m in items
            if kw in m["name"].lower() or kw in m["uid"].lower() or kw in (m["pid"] or "").lower()
        ]

    total = len(items)
    page = items[offset:offset + limit]
    for m in page:
        m["is_bot_admin"] = m["uid"] in admin_set

    resp: dict = {
        "ok": True,
        "members": page,
        "total": total,
        "online": sum(1 for m in items if m["online"]),
        "offset": offset,
        "limit": limit,
        "crossArea": True,
    }
    if pool["failed"]:
        resp["partial"] = pool["failed"]
    return JSONResponse(resp)


@router.get("/admin/api/members/blocks")
@require_sender
async def admin_members_blocks(area: str = Query("")):
    sender = _require_sender()
    area = area.strip() or await _resolve_area_async()

    def _parse(data: list[UserInfo], area_id: str, area_name: str) -> list[dict]:
        resolver = get_resolver()
        parsed = []
        for item in data:
            uid = item.uid
            name = resolver.user(uid) if uid else ""
            parsed.append({
                "uid": uid,
                "name": name or uid[:12],
                "areaId": area_id,
                "areaName": area_name,
            })
        return parsed

    # 「全部域」不是真实域 ID，必须逐域查询后合并；封禁是按域生效的，
    # 每条都要带上来源域，否则解封会打到错误的域。
    if area == ALL_AREAS:
        try:
            names = await _area_name_map()
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        if not names:
            return JSONResponse({"ok": True, "blocks": [], "error_hint": "未找到任何已加入的域"})

        async def one(area_id: str) -> tuple[str, list, str]:
            try:
                return area_id, await sender.bot.moderation.get_area_blocks(area_id), ""
            except Exception as exc:
                return area_id, [], str(exc)

        blocks: list[dict] = []
        failed = []
        for area_id, data, error in await asyncio.gather(*(one(aid) for aid in names)):
            if error:
                failed.append({"areaId": area_id, "areaName": names[area_id], "error": error})
            else:
                blocks.extend(_parse(data, area_id, names[area_id]))
        if len(failed) == len(names):
            return JSONResponse({"ok": False, "error": "所有域的封禁列表查询失败", "partial": failed}, status_code=502)
        return JSONResponse({"ok": True, "blocks": blocks, "crossArea": True, "partial": failed})

    if not area:
        return JSONResponse({"ok": False, "error": "未找到可用域 ID"}, status_code=400)
    try:
        data = await sender.bot.moderation.get_area_blocks(area)
        names = await _area_name_map()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "blocks": _parse(data, area, names.get(area, ""))})


@router.get("/admin/api/members/{uid}")
@require_sender
async def admin_member_detail(uid: str, area: str = Query("")):
    sender = _require_sender()
    area = area.strip() or await _resolve_area_async()
    if not area:
        return JSONResponse({"ok": False, "error": "未找到域 ID"}, status_code=400)
    try:
        detail = await sender.bot.areas.get_area_user_detail(area, uid)
        person = await sender.bot.person.get_person_info(uid)
        assignable = await sender.bot.areas.get_area_can_give_list(area, uid)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    default_area = area
    stats_data = await MessageStatsDB.get_user_ranking(
        area_id=default_area,
        days=7,
        limit=100,
    )
    user_msg_count = 0
    for s in stats_data:
        if s.get("user_id") == uid:
            user_msg_count = s.get("total", 0)
            break

    person_data = {
        "name": person.name or uid[:8],
        "avatar": person.avatar,
        "pid": person.pid or person.user_common_id,
        "online": person.online,
        "introduction": person.introduction,
    }
    roles_out = [{"roleID": role.role_id, "name": role.name} for role in detail.roles]
    disable_text_to = int(detail.disable_text_to or 0)
    disable_voice_to = int(detail.disable_voice_to or 0)
    now_ms = int(time.time() * 1000)
    is_muted = disable_text_to > now_ms
    is_mic_muted = disable_voice_to > now_ms

    from config import ADMIN_UIDS
    is_bot_admin = uid in ADMIN_UIDS

    return JSONResponse({
        "ok": True,
        "uid": uid,
        "person": person_data,
        "roles": roles_out,
        "muted": is_muted,
        "muted_until": int(disable_text_to) if is_muted else 0,
        "mic_muted": is_mic_muted,
        "mic_muted_until": int(disable_voice_to) if is_mic_muted else 0,
        "assignable_roles": [role.model_dump(by_alias=True, exclude_none=True) for role in assignable],
        "messages_7d": user_msg_count,
        "is_bot_admin": is_bot_admin,
    })


async def _extract_area(body: dict) -> str:
    return (body.get("area") or "").strip() or await _resolve_area_async()


@router.post("/admin/api/members/{uid}/mute")
@require_sender
async def admin_member_mute(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        duration = int(body.get("duration", 5))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "duration 必须为整数"}, status_code=400)
    try:
        result = await sender.bot.moderation.mute_user(area, uid, duration=duration)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已禁言")})


@router.post("/admin/api/members/{uid}/unmute")
@require_sender
async def admin_member_unmute(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        result = await sender.bot.moderation.unmute_user(area, uid)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已解除禁言")})


@router.post("/admin/api/members/{uid}/mute-mic")
@require_sender
async def admin_member_mute_mic(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        duration = int(body.get("duration", 10))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "duration 必须为整数"}, status_code=400)
    try:
        result = await sender.bot.moderation.mute_mic(area, uid, duration=duration)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已禁麦")})


@router.post("/admin/api/members/{uid}/unmute-mic")
@require_sender
async def admin_member_unmute_mic(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        result = await sender.bot.moderation.unmute_mic(area, uid)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已解除禁麦")})


@router.post("/admin/api/members/{uid}/kick")
@require_sender
async def admin_member_kick(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        result = await sender.bot.moderation.remove_from_area(area, uid)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已踢出")})


@router.post("/admin/api/members/{uid}/block")
@require_sender
async def admin_member_block(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        result = await sender.bot.moderation.block_user_in_area(area, uid)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已封禁")})


@router.post("/admin/api/members/{uid}/unblock")
@require_sender
async def admin_member_unblock(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        result = await sender.bot.moderation.unblock_user_in_area(area, uid)
        if not result.ok:
            raise RuntimeError(result.message or "操作被拒绝")
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    _invalidate_members_cache(area)
    return JSONResponse({"ok": True, "message": (result.message or "已解封")})


@router.post("/admin/api/members/{uid}/role")
@require_sender
async def admin_member_role(uid: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = await _extract_area(body)
    try:
        role_id = int(body.get("role_id", 0))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "role_id 必须为整数"}, status_code=400)
    action = str(body.get("action", "add"))
    if not role_id:
        return JSONResponse({"ok": False, "error": "role_id 不能为空"}, status_code=400)
    try:
        result = await sender.edit_user_role(uid, role_id, add=(action == "add"), area=area)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "修改身份组被拒绝"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "message": result.message or "角色已更新"})
