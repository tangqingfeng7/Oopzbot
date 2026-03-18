"""Web 播放器管理后台路由 — 所有 /admin 和 /admin/api 端点。"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import secrets
import string
import sys
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from database import DB_PATH, SongCache, Statistics, db_connection
from logger_config import get_logger
from queue_manager import get_redis_client
from web_link_token import clear_token, ensure_token, get_token, set_token

import web_player_config as cfg

logger = get_logger("WebPlayerAdmin")

admin_router = APIRouter()


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _get_redis():
    """延迟导入，避免循环引用。"""
    from web_player import get_redis
    return get_redis()


def _get_netease():
    from web_player import get_netease
    return get_netease()


def _get_started_at() -> float:
    from web_player import started_at
    return started_at


def _get_liked_ids_cache() -> list:
    from web_player import liked_ids_cache
    return liked_ids_cache


def _set_liked_ids_cache(value: list) -> None:
    import web_player
    web_player.liked_ids_cache = value


_ADMIN_SHELL_TEMPLATE: string.Template | None = None


def _load_admin_template() -> string.Template:
    global _ADMIN_SHELL_TEMPLATE
    if _ADMIN_SHELL_TEMPLATE is None:
        tpl_path = os.path.join(os.path.dirname(__file__), "admin_assets", "admin-shell-template.html")
        with open(tpl_path, "r", encoding="utf-8") as f:
            _ADMIN_SHELL_TEMPLATE = string.Template(f.read())
    return _ADMIN_SHELL_TEMPLATE


_ADMIN_PAGES: dict[str, dict[str, str]] = {
    "dashboard": {
        "page_title": "后台总览",
        "page_id": "dashboard",
        "brand_title": "后台管理",
        "brand_copy": "顶部主导航、数据优先、专业 SaaS 工作台。",
        "topbar_actions": '<button class="btn btn-ghost" type="button" onclick="loadOverview().catch(() => {})">刷新概览</button>',
        "login_title": "登录后台总览",
        "login_copy": "登录后查看实时状态与关键指标。",
        "login_button": "进入总览",
    },
    "music": {
        "page_title": "音乐管理",
        "page_id": "music",
        "brand_title": "音乐管理",
        "brand_copy": "把播放控制、搜索加歌和队列调度整理成标准运营面板。",
        "topbar_actions": '<button class="btn btn-ghost" type="button" onclick="loadQueue().catch(() => {})">刷新队列</button>',
        "login_title": "登录音乐后台",
        "login_copy": "登录后控制播放、搜索歌曲和调整队列。",
        "login_button": "进入音乐控制台",
    },
    "config": {
        "page_title": "配置中心",
        "page_id": "config",
        "brand_title": "配置中心",
        "brand_copy": "把长表单整理成章节化配置工作台，保留原字段和保存接口。",
        "topbar_actions": (
            '<button class="btn btn-ghost" type="button" onclick="loadConfig().catch(() => {})">刷新配置</button>\n'
            '          <button class="btn btn-primary" type="button" onclick="saveConfig(true)">保存并持久化</button>'
        ),
        "login_title": "登录配置中心",
        "login_copy": "登录后调整后台配置。",
        "login_button": "进入配置中心",
    },
    "stats": {
        "page_title": "统计页",
        "page_id": "stats",
        "brand_title": "统计页",
        "brand_copy": "让摘要、榜单和危险操作形成稳定阅读顺序，而不是只摆一张表。",
        "topbar_actions": (
            '<button class="btn btn-ghost" type="button" onclick="loadTop().catch(() => {})">刷新统计</button>\n'
            '          <button class="btn btn-danger" type="button" onclick="clearHistory()">清空历史</button>'
        ),
        "login_title": "登录统计页",
        "login_copy": "登录后查看最近 7 天的播放排行。",
        "login_button": "进入统计页",
    },
    "system": {
        "page_title": "系统页",
        "page_id": "system",
        "brand_title": "系统页",
        "brand_copy": "把播放器入口、系统快照和实时日志拆成明确的运维层级。",
        "topbar_actions": (
            '<button class="btn btn-ghost" type="button" onclick="loadSys().catch(() => {})">刷新系统信息</button>\n'
            '          <button class="btn btn-ghost" type="button" onclick="loadLogs(logTailSize).catch(() => {})">刷新日志</button>'
        ),
        "login_title": "登录系统页",
        "login_copy": "登录后查看链接、系统信息和日志。",
        "login_button": "进入系统页",
    },
}


def _render_admin_page(page_key: str) -> HTMLResponse:
    if not cfg.admin_enabled():
        return HTMLResponse("管理后台未启用，请在 WEB_PLAYER_CONFIG 中开启。", status_code=404)
    pages_dir = os.path.join(os.path.dirname(__file__), "admin_assets", "pages")
    content_path = os.path.join(pages_dir, f"{page_key}_content.html")
    script_path = os.path.join(pages_dir, f"{page_key}_script.js")
    with open(content_path, "r", encoding="utf-8") as f:
        page_content = f.read()
    with open(script_path, "r", encoding="utf-8") as f:
        page_script = f.read()
    meta = _ADMIN_PAGES[page_key]
    tpl = _load_admin_template()
    html = tpl.safe_substitute(
        page_title=meta["page_title"],
        page_id=meta["page_id"],
        brand_title=meta["brand_title"],
        brand_copy=meta["brand_copy"],
        topbar_actions=meta["topbar_actions"],
        login_title=meta["login_title"],
        login_copy=meta["login_copy"],
        login_button=meta["login_button"],
        page_content=page_content,
        page_script=page_script,
    )
    return HTMLResponse(html)


def _set_admin_session_token(token: str) -> None:
    ttl = cfg.admin_session_ttl_seconds()
    r = _get_redis()
    if ttl > 0:
        r.set(cfg.admin_session_key(token), "1", ex=ttl)
    else:
        r.set(cfg.admin_session_key(token), "1")


def _clear_admin_session_token(token: str) -> None:
    if not token:
        return
    try:
        _get_redis().delete(cfg.admin_session_key(token))
    except Exception:
        pass


def _overview_payload() -> dict:
    redis_status = "connected"
    queue_len = 0
    playing: dict = {}
    try:
        r = _get_redis()
        r.ping()
        queue_len = int(r.llen("music:queue") or 0)
        current_raw = r.get("music:current")
        play_state_raw = r.get("music:play_state")
        playing = {
            "current": json.loads(current_raw) if current_raw else None,
            "play_state": json.loads(play_state_raw) if play_state_raw else None,
        }
    except Exception as e:
        redis_status = f"error: {e}"

    today = Statistics.get_today() or {}
    summary = Statistics.get_summary()
    return {
        "ok": True,
        "uptime_seconds": int(time.time() - _get_started_at()),
        "redis": redis_status,
        "queue_length": queue_len,
        "playing": playing,
        "statistics_today": today,
        "statistics_summary": summary,
    }


def _tail_file(path: str, lines: int = 200) -> list[str]:
    if not os.path.exists(path):
        return []
    max_lines = max(1, min(int(lines), 2000))
    dq: deque[str] = deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            dq.append(line.rstrip("\n"))
    return list(dq)


def _top_songs_from_play_history(page: int = 1, page_size: int = 10) -> tuple[list[dict], int]:
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 10), 100))
    offset = (page - 1) * page_size
    with db_connection() as conn:
        total_row = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM (
                SELECT sc.song_id
                FROM play_history ph
                LEFT JOIN song_cache sc ON sc.id = ph.song_cache_id
                GROUP BY sc.song_id, sc.song_name, sc.artist, sc.album
            ) t
            """
        ).fetchone()
        total = int(total_row["c"] if total_row else 0)
        rows = conn.execute(
            """
            SELECT
                sc.song_id AS song_id,
                COALESCE(sc.song_name, '') AS song_name,
                COALESCE(sc.artist, '') AS artist,
                COALESCE(sc.album, '') AS album,
                COUNT(ph.id) AS play_count,
                MAX(ph.played_at) AS last_played_at
            FROM play_history ph
            LEFT JOIN song_cache sc ON sc.id = ph.song_cache_id
            GROUP BY sc.song_id, sc.song_name, sc.artist, sc.album
            ORDER BY play_count DESC, last_played_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
    return [dict(r) for r in rows], total


def _queue_snapshot(redis_client) -> list[dict]:
    items = redis_client.lrange("music:queue", 0, -1)
    queue: list[dict] = []
    for i, item in enumerate(items):
        try:
            song = json.loads(item)
        except Exception:
            song = {}
        queue.append({
            "index": i,
            "id": song.get("song_id") or song.get("id"),
            "name": song.get("name", ""),
            "artists": song.get("artists", ""),
            "album": song.get("album", ""),
            "durationText": song.get("durationText") or song.get("duration", ""),
        })
    return queue


def _current_song_snapshot(redis_client) -> Optional[dict]:
    try:
        raw = redis_client.get("music:current")
        if not raw:
            return None
        song = json.loads(raw)
        return {
            "id": song.get("song_id") or song.get("id"),
            "name": song.get("name", ""),
            "artists": song.get("artists", ""),
            "album": song.get("album", ""),
            "durationText": song.get("durationText") or song.get("duration", ""),
        }
    except Exception:
        return None


def _execute_control_action(action: str, body: dict, redis_client) -> dict:
    from web_player import execute_control_action
    return execute_control_action(action, body, redis_client)


def _execute_queue_action(action: str, index, redis_client) -> dict:
    from web_player import execute_queue_action
    return execute_queue_action(action, index, redis_client)


def _add_song_to_queue(body: dict) -> dict:
    from web_player import add_song_to_queue
    return add_song_to_queue(body)


# ---------------------------------------------------------------------------
# 管理后台页面路由
# ---------------------------------------------------------------------------

@admin_router.get("/admin", response_class=HTMLResponse)
def admin_index():
    return _render_admin_page("dashboard")


@admin_router.get("/admin/music", response_class=HTMLResponse)
def admin_music_page():
    return _render_admin_page("music")


@admin_router.get("/admin/config", response_class=HTMLResponse)
def admin_config_page():
    return _render_admin_page("config")


@admin_router.get("/admin/stats", response_class=HTMLResponse)
def admin_stats_page():
    return _render_admin_page("stats")


@admin_router.get("/admin/system", response_class=HTMLResponse)
def admin_system_page():
    return _render_admin_page("system")


# ---------------------------------------------------------------------------
# 管理后台 API 路由
# ---------------------------------------------------------------------------

@admin_router.post("/admin/api/login")
async def admin_login(request: Request):
    if not cfg.admin_enabled():
        return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
    password = cfg.admin_password()
    if not password:
        return JSONResponse({"ok": False, "error": "未配置 admin_password"}, status_code=503)
    body = await request.json()
    submitted = str(body.get("password", ""))
    if not secrets.compare_digest(submitted, password):
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)
    token = secrets.token_urlsafe(24)
    _set_admin_session_token(token)
    ttl = cfg.admin_session_ttl_seconds()
    response = JSONResponse({"ok": True, "ttl": ttl})
    response.set_cookie(
        key=cfg.admin_cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=cfg.admin_cookie_secure(),
        max_age=ttl if ttl > 0 else None,
    )
    return response


@admin_router.post("/admin/api/logout")
def admin_logout(request: Request):
    _clear_admin_session_token(request.cookies.get(cfg.admin_cookie_name(), ""))
    response = JSONResponse({"ok": True})
    response.delete_cookie(cfg.admin_cookie_name())
    return response


@admin_router.get("/admin/api/me")
def admin_me():
    return JSONResponse({"ok": True, "role": "admin"})


@admin_router.get("/admin/api/config")
def admin_get_config():
    return JSONResponse({
        "ok": True,
        "config": cfg.config_snapshot(),
        "overrides_path": cfg.ADMIN_OVERRIDES_PATH,
    })


@admin_router.post("/admin/api/config")
async def admin_update_config(request: Request):
    body = await request.json()
    updates = body.get("updates", {})
    persist = bool(body.get("persist", True))
    applied, errors, persist_payload = cfg.apply_config_updates(updates)

    import web_player
    if "redis" in applied:
        web_player.reset_redis(force=True)
    if "netease" in applied:
        web_player.reset_netease()
        _set_liked_ids_cache([])
    cfg.refresh_runtime_dependents(set(applied))

    if persist and persist_payload:
        merged = cfg.merge_overrides(cfg.read_admin_overrides(), persist_payload)
        cfg.write_admin_overrides(merged)
    return JSONResponse({
        "ok": len(errors) == 0,
        "applied": applied,
        "errors": errors,
        "persisted": bool(persist and persist_payload),
        "config": cfg.config_snapshot(),
    })


@admin_router.post("/admin/api/config/reset")
def admin_reset_config_overrides():
    if os.path.exists(cfg.ADMIN_OVERRIDES_PATH):
        os.remove(cfg.ADMIN_OVERRIDES_PATH)
    for group_name, group in cfg.CONFIG_GROUPS.items():
        target = group.get("target")
        baseline = cfg.CONFIG_BASELINES.get(group_name)
        if isinstance(target, dict) and isinstance(baseline, dict):
            target.clear()
            target.update(copy.deepcopy(baseline))

    import web_player
    web_player.reset_redis(force=True)
    web_player.reset_netease()
    _set_liked_ids_cache([])
    cfg.refresh_runtime_dependents({"redis", "web_player"})
    return JSONResponse({"ok": True, "removed": True, "path": cfg.ADMIN_OVERRIDES_PATH})


@admin_router.get("/admin/api/overview")
def admin_overview():
    return JSONResponse(_overview_payload(), headers={"Cache-Control": "no-store"})


@admin_router.get("/admin/api/overview/stream")
async def admin_overview_stream(request: Request):
    async def _event_stream():
        last_payload = ""
        while True:
            if await request.is_disconnected():
                break
            payload = _overview_payload()
            payload_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
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


@admin_router.get("/admin/api/statistics")
def admin_statistics(
    days: int = Query(7, ge=1, le=30),
    top_page: int = Query(1, ge=1),
    top_page_size: int = Query(10, ge=1, le=100),
):
    top_items, top_total = _top_songs_from_play_history(page=top_page, page_size=top_page_size)
    top_pages = max(1, (top_total + top_page_size - 1) // top_page_size) if top_total else 1
    return JSONResponse({
        "ok": True,
        "today": Statistics.get_today() or {},
        "summary": Statistics.get_summary(),
        "recent_days": Statistics.get_recent(days=days),
        "top_songs": top_items,
        "top_total": top_total,
        "top_page": top_page,
        "top_pages": top_pages,
        "top_page_size": top_page_size,
        "recent_songs": SongCache.get_recent_songs(limit=10),
    })


@admin_router.post("/admin/api/statistics/clear_history")
def admin_clear_play_history():
    count = SongCache.clear_play_history()
    return JSONResponse({"ok": True, "deleted": count})


@admin_router.get("/admin/api/logs")
def admin_logs(
    tail: int | None = Query(default=None, ge=1, le=2000),
    lines: int | None = Query(default=None, ge=1, le=2000),
):
    tail_count = tail if tail is not None else lines
    if tail_count is None:
        tail_count = 200
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "oopz_bot.log")
    line_list = _tail_file(log_path, lines=tail_count)
    return JSONResponse(
        {"ok": True, "path": log_path, "lines": line_list, "logs": line_list, "count": len(line_list)},
        headers={"Cache-Control": "no-store"},
    )


@admin_router.post("/admin/api/control")
async def admin_control(request: Request):
    try:
        body = await request.json()
        action = str(body.get("action", ""))
        result = _execute_control_action(action=action, body=body, redis_client=_get_redis())
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@admin_router.post("/admin/api/liked/refresh")
def admin_liked_refresh():
    _set_liked_ids_cache([])
    return JSONResponse({"ok": True})


@admin_router.post("/admin/api/queue/clear")
def admin_queue_clear():
    _get_redis().delete("music:queue")
    return JSONResponse({"ok": True})


@admin_router.get("/admin/api/queue")
def admin_queue(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    r = _get_redis()
    full_queue = _queue_snapshot(r)
    total = len(full_queue)
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    page = min(page, pages)
    start = (page - 1) * page_size
    queue = full_queue[start:start + page_size]
    current = _current_song_snapshot(r)
    return JSONResponse({
        "ok": True,
        "current": current,
        "queue": queue,
        "count": len(queue),
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
    })


@admin_router.post("/admin/api/queue/action")
async def admin_queue_action(request: Request):
    body = await request.json()
    result = _execute_queue_action(
        action=body.get("action", ""),
        index=body.get("index", -1),
        redis_client=_get_redis(),
    )
    if result.get("ok"):
        result["queue"] = _queue_snapshot(_get_redis())
    return JSONResponse(result)


@admin_router.get("/admin/api/player/link")
def admin_player_link():
    token = get_token(redis_client=_get_redis())
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


@admin_router.post("/admin/api/player/link/rotate")
def admin_player_link_rotate():
    r = _get_redis()
    clear_token(redis_client=r)
    token = ensure_token(redis_client=r, ttl_seconds=cfg.token_ttl_seconds())
    base_url = cfg.display_web_base_url()
    return JSONResponse({"ok": True, "url": f"{base_url}/w/{token}"})


@admin_router.get("/admin/api/search")
def admin_search(
    keyword: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=30),
):
    try:
        nc = _get_netease()
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 30))
        offset = (page - 1) * page_size
        data = nc._get("/cloudsearch", params={
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
        return JSONResponse({
            "ok": True,
            "results": results,
            "total": total,
            "page": page,
            "pages": pages,
            "page_size": page_size,
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "results": []})


@admin_router.post("/admin/api/add")
async def admin_add(request: Request):
    try:
        body = await request.json()
        return JSONResponse(_add_song_to_queue(body=body))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@admin_router.get("/admin/api/system")
def admin_system():
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
        r = _get_redis()
        r.ping()
        info = r.info(section="server")
        data["redis"] = {
            "status": "connected",
            "dbsize": int(r.dbsize() or 0),
            "redis_version": info.get("redis_version", ""),
        }
    except Exception as e:
        data["redis"] = {"status": f"error: {e}"}
    try:
        with db_connection() as conn:
            table_rows: dict = {}
            for table in ("image_cache", "song_cache", "play_history", "statistics"):
                row = conn.execute(f"SELECT COUNT(1) AS c FROM {table}").fetchone()
                table_rows[table] = int(row["c"] if row else 0)
        data["db_tables"] = table_rows
    except Exception as e:
        data["db_tables"] = {"error": str(e)}
    return JSONResponse(data)
