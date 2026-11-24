from __future__ import annotations

import inspect
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from web.admin.shared import (
    _require_sender,
    _resolve_area_async,
    cfg,
    get_resolver,
    logger,
    read_json_body,
    require_sender,
)

router = APIRouter()

_MAX_ARTICLE_IMAGE_BYTES = 15 * 1024 * 1024


async def _resolve_users_map(sender: Any, uids: list[str]) -> dict[str, dict[str, str]]:
    """批量补全发帖人/评论人的昵称与头像，失败时优雅降级。"""
    unique = list(dict.fromkeys(uid.strip() for uid in uids if isinstance(uid, str) and uid.strip()))
    if not unique:
        return {}

    person_map: dict[str, Any] = {}
    try:
        persons = await sender.bot.person.get_person_infos_batch(unique)
        person_map = {person.uid: person for person in persons if getattr(person, "uid", "")}
    except Exception:
        logger.debug("批量获取帖子作者信息失败", exc_info=True)

    resolver = get_resolver()
    resolved: dict[str, dict[str, str]] = {}
    for uid in unique:
        info = person_map.get(uid)
        name = resolver.user_cached(uid, fallback=False) or (getattr(info, "name", "") if info else "") or uid[:8]
        avatar = getattr(info, "avatar", "") if info else ""
        resolved[uid] = {"name": name, "avatar": avatar}
    return resolved


async def _resolve_self_uid(sender: Any) -> str:
    bot = getattr(sender, "bot", None)
    cfg_obj = getattr(bot, "config", None)
    uid = (
        getattr(cfg_obj, "person_uid", "")
        or getattr(sender, "person_uid", "")
        or cfg.OOPZ_CONFIG.get("person_uid", "")
    )
    resolved = str(uid or "").strip()
    if resolved:
        return resolved
    person = getattr(bot, "person", None)
    get_self: Any = getattr(person, "get_self_detail", None)
    if callable(get_self):
        try:
            detail = get_self()
            if inspect.isawaitable(detail):
                detail = await detail
            resolved = str(getattr(detail, "uid", "") or "").strip()
        except Exception:
            logger.debug("获取当前 Bot UID 失败", exc_info=True)
    return resolved


def _serialize_article(
    article: Any,
    users: dict[str, dict[str, str]],
    *,
    self_uid: str = "",
) -> dict[str, Any]:
    data = article.model_dump(by_alias=True)
    uid = str(data.get("authorUid") or "").strip()
    user = users.get(uid, {})
    data["authorName"] = user.get("name") or (uid[:8] if uid else "未知用户")
    data["authorAvatar"] = user.get("avatar") or ""
    is_own = bool(self_uid and uid and uid == self_uid)
    data["isOwn"] = is_own
    data["canEdit"] = is_own
    return data


def _comment_to_raw_dict(comment: Any) -> dict[str, Any]:
    if isinstance(comment, dict):
        return dict(comment)
    data = comment.model_dump(by_alias=True)
    sub = getattr(comment, "sub_comments", None)
    if isinstance(sub, list) and "subComments" not in data:
        data["subComments"] = [_comment_to_raw_dict(item) for item in sub]
    return data


def _collect_comment_uids(items: list[dict[str, Any]], acc: list[str]) -> None:
    for item in items:
        uid = str(item.get("uid") or "").strip()
        if uid:
            acc.append(uid)
        reply_uid = str(item.get("replyToUid") or "").strip()
        if reply_uid:
            acc.append(reply_uid)
        sub_items = item.get("subComments")
        if isinstance(sub_items, list):
            _collect_comment_uids([sub for sub in sub_items if isinstance(sub, dict)], acc)


def _serialize_comment(
    comment: Any,
    users: dict[str, dict[str, str]],
    *,
    self_uid: str = "",
) -> dict[str, Any]:
    data = _comment_to_raw_dict(comment)
    uid = str(data.get("uid") or "").strip()
    user = users.get(uid, {})
    data["authorName"] = user.get("name") or (uid[:8] if uid else "未知用户")
    data["authorAvatar"] = user.get("avatar") or ""
    reply_uid = str(data.get("replyToUid") or "").strip()
    if reply_uid:
        reply_user = users.get(reply_uid, {})
        data["replyToName"] = reply_user.get("name") or reply_uid[:8]
    else:
        data["replyToName"] = ""
    if not isinstance(data.get("imageList"), list):
        data["imageList"] = []
    is_own = bool(self_uid and uid and uid == self_uid)
    data["isOwn"] = is_own
    data["canDelete"] = is_own
    raw_subs = data.get("subComments")
    if isinstance(raw_subs, list):
        data["subComments"] = [
            _serialize_comment(sub, users, self_uid=self_uid)
            for sub in raw_subs
            if isinstance(sub, dict)
        ]
    else:
        data["subComments"] = []
    return data


# ---------------------------------------------------------------------------
# 分区管理
# ---------------------------------------------------------------------------


@router.get("/admin/api/articles/sections")
@require_sender
async def admin_article_sections(
    area: str = Query(""),
    channel: str = Query(""),
):
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        sections = await sender.bot.articles.get_sections(resolved_area, channel_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({
        "ok": True,
        "sections": [
            {"id": sec.section_id, "name": sec.name, "sort": sec.sort}
            for sec in sections
        ],
    })


@router.post("/admin/api/articles/sections")
@require_sender
async def admin_article_section_create(request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    name = (body.get("name") or "").strip()
    if not area or not channel or not name:
        return JSONResponse({"ok": False, "error": "area、channel 和 name 不能为空"}, status_code=400)
    try:
        sec = await sender.bot.articles.create_section(area, channel, name)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({
        "ok": True,
        "message": "分区已创建",
        "section": {"id": sec.section_id, "name": sec.name, "sort": sec.sort},
    })


@router.put("/admin/api/articles/sections/{section_id}")
@require_sender
async def admin_article_section_edit(section_id: int, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    name = (body.get("name") or "").strip()
    if not area or not channel or not name:
        return JSONResponse({"ok": False, "error": "area、channel 和 name 不能为空"}, status_code=400)
    try:
        sec = await sender.bot.articles.edit_section(area, channel, section_id, name)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({
        "ok": True,
        "message": "分区已更新",
        "section": {"id": sec.section_id, "name": sec.name, "sort": sec.sort},
    })


@router.delete("/admin/api/articles/sections/{section_id}")
@require_sender
async def admin_article_section_delete(section_id: int, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.articles.delete_section(area, channel, section_id)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "删除分区失败"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "message": "分区已删除"})


# ---------------------------------------------------------------------------
# 图片上传
# ---------------------------------------------------------------------------


@router.post("/admin/api/articles/upload-image")
@require_sender
async def admin_article_upload_image(
    file: Annotated[UploadFile, File(...)],
    area: Annotated[str, Form()] = "",
    channel: Annotated[str, Form()] = "",
):
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)

    payload = await file.read()
    if not payload:
        return JSONResponse({"ok": False, "error": "上传文件为空"}, status_code=400)
    if len(payload) > _MAX_ARTICLE_IMAGE_BYTES:
        return JSONResponse({"ok": False, "error": "图片大小不能超过 15 MB"}, status_code=400)

    try:
        attachment = await sender.bot.articles.upload_image(resolved_area, channel_id, payload)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    return JSONResponse({
        "ok": True,
        "attachment": attachment.to_request_dict(),
    })


# ---------------------------------------------------------------------------
# 帖子列表、详情、发帖、编辑、删除、点赞
# ---------------------------------------------------------------------------


@router.get("/admin/api/articles")
@require_sender
async def admin_articles_list(
    area: str = Query(""),
    channel: str = Query(""),
    section_id: int = Query(0),
    cursor: int = Query(0),
    cursor_state: str = Query(""),
):
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        page = await sender.bot.articles.get_articles(
            resolved_area,
            channel_id,
            section_id=section_id,
            cursor=max(0, cursor),
            cursor_state=cursor_state.strip(),
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    self_uid = await _resolve_self_uid(sender)
    users = await _resolve_users_map(sender, [item.author_uid for item in page.items])
    return JSONResponse({
        "ok": True,
        "selfUid": self_uid,
        "items": [_serialize_article(item, users, self_uid=self_uid) for item in page.items],
        "nextCursor": page.next_cursor,
        "nextCursorState": page.next_cursor_state,
        "pageSize": page.page_size,
        "hasMore": page.next_cursor > 0,
    })


@router.post("/admin/api/articles")
@require_sender
async def admin_article_create(request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    title = (body.get("title") or "").strip()
    content = str(body.get("content") or "")
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    if not title:
        return JSONResponse({"ok": False, "error": "帖子标题不能为空"}, status_code=400)

    try:
        section_id = max(0, int(body.get("sectionId") or 0))
        cover_index = max(0, int(body.get("coverIndex") or 0))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "分区或封面索引格式无效"}, status_code=400)

    attachments = body.get("attachments")
    if attachments is not None and not isinstance(attachments, list):
        return JSONResponse({"ok": False, "error": "attachments 必须是数组"}, status_code=400)
    show_cover = bool(body.get("showCover", True))

    try:
        result = await sender.bot.articles.create_article(
            area,
            channel,
            title,
            content,
            section_id=section_id,
            attachments=attachments or [],
            cover_index=cover_index,
            show_cover=show_cover,
        )
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    return JSONResponse({
        "ok": True,
        "message": "帖子已发布",
        "articleId": result.article_id,
        "state": result.state,
    })


@router.get("/admin/api/articles/{article_id}")
@require_sender
async def admin_article_detail(
    article_id: str,
    area: str = Query(""),
    channel: str = Query(""),
):
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        detail = await sender.bot.articles.get_article_detail(resolved_area, channel_id, article_id)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    self_uid = await _resolve_self_uid(sender)
    users = await _resolve_users_map(sender, [detail.author_uid])
    return JSONResponse({
        "ok": True,
        "selfUid": self_uid,
        "article": _serialize_article(detail, users, self_uid=self_uid),
    })


@router.put("/admin/api/articles/{article_id}")
@require_sender
async def admin_article_edit(article_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)

    kwargs: dict[str, Any] = {}
    if "title" in body:
        title = (body.get("title") or "").strip()
        if not title:
            return JSONResponse({"ok": False, "error": "帖子标题不能为空"}, status_code=400)
        kwargs["title"] = title
    if "content" in body:
        kwargs["content"] = str(body.get("content") or "")
    raw_section = body.get("sectionId")
    if "sectionId" in body and raw_section is not None:
        try:
            kwargs["section_id"] = max(0, int(raw_section))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "sectionId 格式无效"}, status_code=400)
    if "attachments" in body and body.get("attachments") is not None:
        if not isinstance(body.get("attachments"), list):
            return JSONResponse({"ok": False, "error": "attachments 必须是数组"}, status_code=400)
        kwargs["attachments"] = body.get("attachments")
    raw_cover = body.get("coverIndex")
    if "coverIndex" in body and raw_cover is not None:
        try:
            kwargs["cover_index"] = max(0, int(raw_cover))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "coverIndex 格式无效"}, status_code=400)
    if "showCover" in body and body.get("showCover") is not None:
        kwargs["show_cover"] = bool(body.get("showCover"))

    try:
        result = await sender.bot.articles.edit_article(area, channel, article_id, **kwargs)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    return JSONResponse({
        "ok": True,
        "message": "帖子已更新",
        "articleId": result.article_id,
        "state": result.state,
    })


@router.delete("/admin/api/articles/{article_id}")
@require_sender
async def admin_article_delete(article_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.articles.delete_article(area, channel, article_id)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "删除帖子失败"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "message": "帖子已删除"})


@router.post("/admin/api/articles/{article_id}/like")
@require_sender
async def admin_article_like(article_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    liked = bool(body.get("liked", True))
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.articles.like_article(area, channel, article_id, liked=liked)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "操作失败"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "liked": liked})


# ---------------------------------------------------------------------------
# 评论浏览与管理
# ---------------------------------------------------------------------------


@router.get("/admin/api/articles/{article_id}/comments")
@require_sender
async def admin_article_comments(
    article_id: str,
    area: str = Query(""),
    channel: str = Query(""),
    cursor: int = Query(0),
    page_size: int = Query(30),
):
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    clamped_size = max(1, min(page_size, 50))
    safe_cursor = max(0, cursor)

    try:
        # SDK 0.17.0 的 ArticleComment 模型未声明 subComments 字段会被 extra="ignore" 过滤，
        # 这里优先通过 transport 拉取完整响应以保留楼中楼回复列表；若无 transport 则回退 SDK 方法。
        transport = getattr(sender.bot.articles, "transport", None)
        request_data = getattr(transport, "request_data", None)
        if callable(request_data):
            raw = request_data(
                "GET",
                "/uni/area/article/comment/v1/list",
                params={
                    "area": resolved_area,
                    "channel": channel_id,
                    "articleId": article_id,
                    "cursor": safe_cursor,
                    "pageSize": clamped_size,
                },
            )
            if inspect.isawaitable(raw):
                raw = await raw
            raw_dict = raw if isinstance(raw, dict) else {}
            raw_items = [item for item in (raw_dict.get("list") or []) if isinstance(item, dict)]
            comment_count = int(raw_dict.get("commentCount") or 0)
            next_cursor = int(raw_dict.get("nextCursor") or 0)
            resp_page_size = int(raw_dict.get("pageSize") or clamped_size)
        else:
            page = await sender.bot.articles.get_comments(
                resolved_area,
                channel_id,
                article_id,
                cursor=safe_cursor,
                page_size=clamped_size,
            )
            raw_items = [_comment_to_raw_dict(item) for item in page.items]
            comment_count = page.comment_count
            next_cursor = page.next_cursor
            resp_page_size = page.page_size
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    self_uid = await _resolve_self_uid(sender)
    uids: list[str] = []
    _collect_comment_uids(raw_items, uids)
    users = await _resolve_users_map(sender, uids)

    return JSONResponse({
        "ok": True,
        "selfUid": self_uid,
        "commentCount": comment_count,
        "items": [_serialize_comment(item, users, self_uid=self_uid) for item in raw_items],
        "nextCursor": next_cursor,
        "hasMore": next_cursor > 0 and len(raw_items) >= resp_page_size,
    })


@router.get("/admin/api/articles/{article_id}/comments/{parent_id}/replies")
@require_sender
async def admin_article_comment_replies(
    article_id: str,
    parent_id: str,
    area: str = Query(""),
    channel: str = Query(""),
    cursor: int = Query(0),
    page_size: int = Query(30),
):
    """分页拉取指定父评论下的全部子回复。"""
    sender = _require_sender()
    resolved_area = area.strip() or await _resolve_area_async()
    channel_id = channel.strip()
    if not resolved_area or not channel_id:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    clamped_size = max(1, min(page_size, 50))
    safe_cursor = max(0, cursor)

    try:
        transport = getattr(sender.bot.articles, "transport", None)
        request_data = getattr(transport, "request_data", None)
        if not callable(request_data):
            return JSONResponse({"ok": False, "error": "当前客户端不支持拉取子回复列表"}, status_code=501)
        raw = request_data(
            "GET",
            "/uni/area/article/comment/v1/subList",
            params={
                "area": resolved_area,
                "channel": channel_id,
                "articleId": article_id,
                "parentId": parent_id,
                "cursor": safe_cursor,
                "pageSize": clamped_size,
            },
        )
        if inspect.isawaitable(raw):
            raw = await raw
        raw_dict = raw if isinstance(raw, dict) else {}
        raw_items = [item for item in (raw_dict.get("list") or []) if isinstance(item, dict)]
        child_count = int(raw_dict.get("childCount") or len(raw_items))
        next_cursor = int(raw_dict.get("nextCursor") or 0)
        resp_page_size = int(raw_dict.get("pageSize") or clamped_size)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    self_uid = await _resolve_self_uid(sender)
    uids: list[str] = []
    _collect_comment_uids(raw_items, uids)
    users = await _resolve_users_map(sender, uids)

    return JSONResponse({
        "ok": True,
        "selfUid": self_uid,
        "parentId": parent_id,
        "childCount": child_count,
        "items": [_serialize_comment(item, users, self_uid=self_uid) for item in raw_items],
        "nextCursor": next_cursor,
        "hasMore": next_cursor > 0 and len(raw_items) >= resp_page_size,
    })


@router.post("/admin/api/articles/{article_id}/comments")
@require_sender
async def admin_article_comment_create(article_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    content = str(body.get("content") or "")
    parent_id = (body.get("parentId") or "").strip()
    reply_id = (body.get("replyId") or "").strip()
    image_list = body.get("imageList") or []
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    if not isinstance(image_list, list):
        return JSONResponse({"ok": False, "error": "imageList 必须是数组"}, status_code=400)
    if not content.strip() and not image_list:
        return JSONResponse({"ok": False, "error": "评论内容和图片不能同时为空"}, status_code=400)

    try:
        if parent_id:
            result = await sender.bot.articles.reply_comment(
                area,
                channel,
                article_id,
                parent_id,
                content,
                reply_id=reply_id or parent_id,
                image_list=image_list,
            )
        else:
            result = await sender.bot.articles.create_comment(
                area,
                channel,
                article_id,
                content,
                image_list=image_list,
            )
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    return JSONResponse({
        "ok": True,
        "message": "评论已发表",
        "commentId": result.comment_id,
    })


@router.delete("/admin/api/articles/{article_id}/comments/{comment_id}")
@require_sender
async def admin_article_comment_delete(article_id: str, comment_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.articles.delete_comment(area, channel, article_id, comment_id)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "删除评论失败"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "message": "评论已删除"})


@router.post("/admin/api/articles/{article_id}/comments/{comment_id}/like")
@require_sender
async def admin_article_comment_like(article_id: str, comment_id: str, request: Request):
    sender = _require_sender()
    body = await read_json_body(request)
    area = (body.get("area") or "").strip() or await _resolve_area_async()
    channel = (body.get("channel") or "").strip()
    liked = bool(body.get("liked", True))
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "area 和 channel 不能为空"}, status_code=400)
    try:
        result = await sender.bot.articles.like_comment(area, channel, article_id, comment_id, liked=liked)
        if not result.ok:
            return JSONResponse({"ok": False, "error": result.message or "操作失败"}, status_code=502)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, "liked": liked})
