import asyncio
import os
import sys
import time
from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.services.playback import PlaybackAreaUnavailable
from core.json_utils import compact_json
from core.redis_protocol import RedisAdminClient
from web.admin.shared import (
    DB_PATH,
    SongCache,
    Statistics,
    TtlCache,
    _add_song_to_queue,
    _current_song_snapshot,
    _execute_control_action,
    _execute_queue_action,
    _get_netease,
    _get_redis,
    _get_started_at,
    _music_area_context,
    _overview_payload,
    _playback_area_unavailable_payload,
    _queue_snapshot,
    _require_music_area,
    _set_liked_ids_cache,
    _tail_file,
    _top_songs_from_play_history,
    cfg,
    clear_token,
    db_connection,
    ensure_token,
    get_token,
    read_json_body,
)

router = APIRouter()
# 多个后台标签页各自每秒推送一次，共享同一份快照避免重复查询 Redis/SQLite。
_overview_stream_cache = TtlCache(0.9, maxsize=1)


def _area_unavailable_response() -> JSONResponse:
    return JSONResponse(_playback_area_unavailable_payload(), status_code=409)

@router.get("/admin/api/overview")
async def admin_overview():
    return JSONResponse(await _overview_payload(), headers={"Cache-Control": "no-store"})


@router.get("/admin/api/overview/stream")
async def admin_overview_stream(request: Request):
    cookie_token = request.cookies.get(cfg.admin_cookie_name(), "")

    async def _event_stream():
        last_payload = ""
        check_counter = 0
        while True:
            if await request.is_disconnected():
                break
            check_counter += 1
            if check_counter % 30 == 0 and cookie_token:
                try:
                    alive = await (await _get_redis()).get(cfg.admin_session_key(cookie_token))
                except Exception:
                    alive = None
                if not alive:
                    break
            payload_text = _overview_stream_cache.get("overview")
            if payload_text is None:
                payload_text = compact_json(await _overview_payload())
                _overview_stream_cache.set("overview", payload_text)
            if payload_text != last_payload:
                yield f"event: overview\ndata: {payload_text}\n\n"
                last_payload = payload_text
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/admin/api/statistics")
async def admin_statistics(
    days: int = Query(7, ge=1, le=30),
    top_page: int = Query(1, ge=1),
    top_page_size: int = Query(10, ge=1, le=100),
):
    top_items, top_total = await _top_songs_from_play_history(page=top_page, page_size=top_page_size)
    top_pages = max(1, (top_total + top_page_size - 1) // top_page_size) if top_total else 1
    return JSONResponse({
        "ok": True,
        "today": (await Statistics.get_today()) or {},
        "summary": await Statistics.get_summary(),
        "recent_days": await Statistics.get_recent(days=days),
        "top_songs": top_items,
        "top_total": top_total,
        "top_page": top_page,
        "top_pages": top_pages,
        "top_page_size": top_page_size,
        "recent_songs": await SongCache.get_recent_songs(limit=10),
    })


@router.post("/admin/api/statistics/clear_history")
async def admin_clear_play_history():
    count = await SongCache.clear_play_history()
    return JSONResponse({"ok": True, "deleted": count})


@router.get("/admin/api/logs")
def admin_logs(
    tail: int | None = Query(default=None, ge=1, le=2000),
    lines: int | None = Query(default=None, ge=1, le=2000),
):
    tail_count = tail if tail is not None else lines
    if tail_count is None:
        tail_count = 200
    log_path = os.path.join(cfg.PROJECT_ROOT, "logs", "oopz_bot.log")
    line_list = _tail_file(log_path, lines=tail_count)
    return JSONResponse(
        {"ok": True, "path": log_path, "lines": line_list, "logs": line_list, "count": len(line_list)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/admin/api/control")
async def admin_control(request: Request):
    try:
        body = await request.json()
        action = str(body.get("action", ""))
        area = "" if action == "volume" else await _require_music_area()
        result = await _execute_control_action(
            action=action, body=body, redis_client=await _get_redis(), area=area
        )
        return JSONResponse(result)
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.post("/admin/api/liked/refresh")
def admin_liked_refresh():
    _set_liked_ids_cache([])
    return JSONResponse({"ok": True})


@router.post("/admin/api/queue/clear")
async def admin_queue_clear():
    try:
        area = await _require_music_area()
        return JSONResponse(
            await _execute_control_action(
                action="clear",
                body={},
                redis_client=await _get_redis(),
                area=area,
            )
        )
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()


@router.get("/admin/api/queue")
async def admin_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    r = await _get_redis()
    area_context = await _music_area_context(r)
    area = area_context.get("area", "")
    if not area:
        return _area_unavailable_response()
    full_queue = await _queue_snapshot(r, area=area)
    total = len(full_queue)
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    page = min(page, pages)
    start = (page - 1) * page_size
    queue = full_queue[start:start + page_size]
    current = await _current_song_snapshot(r, area=area)
    return JSONResponse({
        "ok": True,
        "area": area,
        "music_area": area_context,
        "current": current,
        "queue": queue,
        "count": len(queue),
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    })


@router.post("/admin/api/queue/action")
async def admin_queue_action(request: Request):
    body = await read_json_body(request)
    try:
        area = await _require_music_area()
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    result = await _execute_queue_action(
        action=body.get("action", ""),
        index=body.get("index", -1),
        redis_client=await _get_redis(),
        area=area,
    )
    if result.get("ok"):
        result["queue"] = await _queue_snapshot(await _get_redis(), area=area)
    return JSONResponse(result)


@router.get("/admin/api/player/link")
async def admin_player_link():
    token = await get_token(redis_client=await _get_redis())
    path = f"/w/{token}" if token else ""
    base_url = cfg.display_web_base_url()
    full_url = f"{base_url}{path}" if token else ""
    return JSONResponse({
        "ok": True,
        "has_token": bool(token),
        "path": path,
        "url": full_url,
        "base_url": base_url,
    })


@router.post("/admin/api/player/link/rotate")
async def admin_player_link_rotate():
    r = await _get_redis()
    await clear_token(redis_client=r)
    token = await ensure_token(redis_client=r, ttl_seconds=cfg.token_ttl_seconds())
    base_url = cfg.display_web_base_url()
    return JSONResponse({"ok": True, "url": f"{base_url}/w/{token}"})


@router.get("/admin/api/search")
async def admin_search(
    keyword: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=30),
    platform: str = Query("netease"),
):
    try:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 30))
        offset = (page - 1) * page_size

        if platform == "netease":
            nc = _get_netease()
            data = await nc._get("/cloudsearch", params={
                "keywords": keyword,
                "limit": page_size,
                "offset": offset,
                "type": 1,
            })
            if not data or data.get("code") != 200:
                return JSONResponse({"ok": False, "error": "搜索失败", "results": []})
            songs = data.get("result", {}).get("songs", [])
            total = int(data.get("result", {}).get("songCount", 0) or 0)
            pages = max(1, (total + page_size - 1) // page_size) if total else 1
            results = []
            for song in songs:
                parsed = nc._parse_song(song)
                if parsed:
                    results.append(parsed)
        else:
            from web.web_player import _resolve_platform
            p = _resolve_platform(platform)
            results = await p.search_many(keyword, limit=page_size, offset=offset)
            total = len(results)
            pages = 1

        return JSONResponse({
            "ok": True,
            "results": results,
            "total": total,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "platform": platform,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "results": []})


@router.post("/admin/api/add")
async def admin_add(request: Request):
    try:
        body = await request.json()
        return JSONResponse(await _add_song_to_queue(body=body, area=await _require_music_area()))
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/admin/api/system")
async def admin_system():
    data: dict = {
        "ok": True,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "project_root": cfg.PROJECT_ROOT,
        "db_path": DB_PATH,
        "db_exists": os.path.exists(DB_PATH),
        "db_size_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "log_path": os.path.join(cfg.PROJECT_ROOT, "logs", "oopz_bot.log"),
        "uptime_seconds": int(time.time() - _get_started_at()),
    }
    log_path = data["log_path"]
    data["log_size_bytes"] = os.path.getsize(log_path) if os.path.exists(log_path) else 0
    try:
        r = await _get_redis()
        await r.ping()
        admin_redis = cast(RedisAdminClient, r)
        info = await admin_redis.info(section="server")
        data["redis"] = {
            "status": "connected",
            "dbsize": await admin_redis.dbsize(),
            "redis_version": info.get("redis_version", ""),
        }
    except Exception as e:
        data["redis"] = {"status": f"error: {e}"}
    try:
        async with db_connection() as conn:
            table_rows: dict = {}
            for table in ("image_cache", "song_cache", "play_history", "statistics"):
                async with conn.execute(f"SELECT COUNT(1) AS c FROM {table}") as cursor:
                    row = await cursor.fetchone()
                table_rows[table] = int(row["c"] if row else 0)
        data["db_tables"] = table_rows
    except Exception as e:
        data["db_tables"] = {"error": str(e)}
    return JSONResponse(data)

__all__ = ["router"]
