"""Web 播放器 — FastAPI 主应用、播放器 API 路由、共享状态。"""

from __future__ import annotations

import json
import os
import time
from threading import Lock
from typing import Optional

import redis
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from logger_config import get_logger
from netease import NeteaseCloud
from queue_manager import get_redis_client, _area_key, KEY_QUEUE, KEY_CURRENT, KEY_PLAY_STATE
from web_link_token import ensure_token, get_token, set_token

import web_player_config as cfg

logger = get_logger("WebPlayer")

# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(title="Oopz Music Player", docs_url=None, redoc_url=None)

_ADMIN_ASSETS_DIR = os.path.join(cfg.PROJECT_ROOT, "src", "admin_assets")
_WEBINTOSH_ASSETS_DIR = os.path.join(cfg.PROJECT_ROOT, "Webintosh", "assets")


def _mount_static_if_exists(route: str, directory: str, name: str) -> None:
    if os.path.isdir(directory):
        app.mount(route, StaticFiles(directory=directory), name=name)
    else:
        logger.warning("Static assets directory missing, skip mount: %s", directory)


_mount_static_if_exists("/admin-assets", _ADMIN_ASSETS_DIR, "admin-assets")
_mount_static_if_exists("/webintosh-assets", _WEBINTOSH_ASSETS_DIR, "webintosh-assets")

# ---------------------------------------------------------------------------
# 共享状态（admin 模块通过公共函数访问）
# ---------------------------------------------------------------------------

_redis: Optional[redis.Redis] = None
_netease: Optional[NeteaseCloud] = None

_lyric_cache: dict[str, dict] = {}
_lyric_lock = Lock()
_LYRIC_CACHE_MAX = 200

started_at: float = time.time()
liked_ids_cache: list = []

KEY_WEB_COMMANDS = "music:web_commands"


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = get_redis_client()
    return _redis


def reset_redis(force: bool = False) -> None:
    global _redis
    _redis = get_redis_client(force_reset=True) if force else None


def get_netease() -> NeteaseCloud:
    global _netease
    if _netease is None:
        _netease = NeteaseCloud()
    return _netease


def reset_netease() -> None:
    global _netease
    _netease = None


_sender = None


def set_sender(sender) -> None:
    global _sender
    _sender = sender


def get_sender():
    return _sender


# ---------------------------------------------------------------------------
# 启动时加载后台配置覆盖
# ---------------------------------------------------------------------------

cfg.bootstrap_admin_overrides()
cfg.bootstrap_area_overrides()

# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _auth_web_api(request: Request, call_next):
    path = request.url.path or ""
    if path.startswith("/api/"):
        active = get_token(redis_client=get_redis())
        client_token = request.cookies.get("web_token", "")
        if not active or client_token != active:
            return JSONResponse({"ok": False, "error": "未授权或链接已失效"}, status_code=403)
    if path.startswith("/admin/api/") and path not in {"/admin/api/login"}:
        if not cfg.admin_enabled():
            return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
        cookie_token = request.cookies.get(cfg.admin_cookie_name(), "")
        if not cookie_token:
            return JSONResponse({"ok": False, "error": "后台未登录或会话失效"}, status_code=401)
        try:
            active_token = get_redis().get(cfg.admin_session_key(cookie_token))
        except Exception:
            active_token = None
        if not active_token:
            return JSONResponse({"ok": False, "error": "后台未登录或会话失效"}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 共享业务逻辑（admin 模块亦调用）
# ---------------------------------------------------------------------------

def execute_control_action(action: str, body: dict, redis_client: redis.Redis, area: str = "") -> dict:
    queue_key = _area_key(KEY_QUEUE, area)
    if action == "next":
        redis_client.rpush(KEY_WEB_COMMANDS, "next")
        return {"ok": True}
    if action == "clear":
        redis_client.delete(queue_key)
        return {"ok": True}
    if action == "stop":
        redis_client.rpush(KEY_WEB_COMMANDS, "stop")
        return {"ok": True}
    if action == "pause":
        redis_client.rpush(KEY_WEB_COMMANDS, "pause")
        return {"ok": True}
    if action == "resume":
        redis_client.rpush(KEY_WEB_COMMANDS, "resume")
        return {"ok": True}
    if action == "seek":
        seek_time = body.get("time", 0)
        redis_client.rpush(KEY_WEB_COMMANDS, f"seek:{seek_time}")
        return {"ok": True}
    if action == "volume":
        vol = body.get("value", 50)
        redis_client.rpush(KEY_WEB_COMMANDS, f"volume:{vol}")
        return {"ok": True}
    return {"ok": False, "error": f"未知操作: {action}"}


def execute_queue_action(action: str, index, redis_client: redis.Redis, area: str = "") -> dict:
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return {"ok": False, "error": "索引无效"}
    queue_key = _area_key(KEY_QUEUE, area)
    queue_items = redis_client.lrange(queue_key, 0, -1)
    if idx < 0 or idx >= len(queue_items):
        return {"ok": False, "error": "索引无效"}
    if action == "remove":
        placeholder = "__REMOVED__"
        redis_client.lset(queue_key, idx, placeholder)
        redis_client.lrem(queue_key, 1, placeholder)
        return {"ok": True}
    if action == "top":
        item = queue_items[idx]
        placeholder = "__REMOVED__"
        redis_client.lset(queue_key, idx, placeholder)
        redis_client.lrem(queue_key, 1, placeholder)
        redis_client.lpush(queue_key, item)
        return {"ok": True}
    return {"ok": False, "error": f"未知操作: {action}"}


def add_song_to_queue(body: dict, area: str = "") -> dict:
    song_id = body.get("id")
    if not song_id:
        return {"ok": False, "error": "缺少歌曲 ID"}
    platform = body.get("platform", "netease")
    p = _resolve_platform(platform)
    url = p.get_song_url(song_id)
    if not url:
        return {"ok": False, "error": "无法获取播放链接，可能需要 VIP"}

    name = body.get("name", "")
    artists = body.get("artists", "")
    album = body.get("album", "")
    cover = body.get("cover", "")
    duration_ms = body.get("duration", 0)
    duration_text = body.get("durationText", "")
    song_data = {
        "platform": platform,
        "song_id": str(song_id),
        "name": name,
        "artists": artists,
        "album": album,
        "url": url,
        "cover": cover,
        "duration": duration_text,
        "duration_ms": duration_ms,
        "attachments": [],
        "channel": "",
        "area": area,
        "user": "web",
    }
    r = get_redis()
    queue_key = _area_key(KEY_QUEUE, area)
    pipe = r.pipeline(transaction=False)
    pipe.rpush(queue_key, json.dumps(song_data, ensure_ascii=False))
    pipe.llen(queue_key)
    results = pipe.execute()
    queue_len = int(results[1] or 0)
    notify = json.dumps({"name": name, "artists": artists, "position": queue_len}, ensure_ascii=False)
    r.rpush(KEY_WEB_COMMANDS, f"notify:{notify}")
    return {"ok": True, "position": queue_len, "name": name}


_platform_cache: dict = {}


def _resolve_platform(name: str = "netease"):
    """根据平台名称获取对应的音乐平台实例（缓存复用）。"""
    if not name or name == "netease":
        return get_netease()
    cached = _platform_cache.get(name)
    if cached is not None:
        return cached
    if name == "qq":
        from qq_music import QQMusic
        inst = QQMusic()
    elif name == "bilibili":
        from bilibili_music import BilibiliMusic
        inst = BilibiliMusic()
    else:
        return get_netease()
    _platform_cache[name] = inst
    return inst


def _filter_songs_by_keyword(songs: list, keyword: str) -> list:
    if not keyword or not keyword.strip():
        return songs
    k = keyword.strip().lower()
    out: list = []
    for s in songs:
        name = (s.get("name") or "").lower()
        artists = (s.get("artists") or "").lower()
        album = (s.get("album") or "").lower()
        if k in name or k in artists or k in album:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# 播放器 API 路由
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status(area: str = Query("", description="域 ID，用于多域隔离")):
    try:
        r = get_redis()
        current_key = _area_key(KEY_CURRENT, area)
        ps_key = _area_key(KEY_PLAY_STATE, area)

        pipe = r.pipeline(transaction=False)
        pipe.get(current_key)
        pipe.get(ps_key)
        pipe.get("music:volume")
        current_raw, play_state_raw, vol_raw = pipe.execute()

        if not current_raw:
            return JSONResponse({"playing": False})

        current = json.loads(current_raw)
        progress = 0.0

        duration_ms = current.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms > 0:
            duration = float(duration_ms) / 1000.0
        else:
            raw_dur = current.get("duration", 0)
            try:
                duration = float(raw_dur or 0) / 1000.0
            except (ValueError, TypeError):
                duration = 0.0

        paused = False
        if play_state_raw:
            ps = json.loads(play_state_raw)
            start = float(ps.get("start_time", 0) or 0)
            dur = float(ps.get("duration", 0) or 0)
            paused = bool(ps.get("paused"))
            if dur:
                duration = dur
            if paused:
                progress = float(ps.get("pause_elapsed", 0) or 0)
            elif start and duration:
                progress = time.time() - start

        volume = int(vol_raw) if vol_raw else 50

        song_id = current.get("song_id") or current.get("id")
        dur_text = current.get("durationText", "")
        if not dur_text:
            raw_dur = current.get("duration", "")
            if isinstance(raw_dur, str) and ":" in raw_dur:
                dur_text = raw_dur

        return JSONResponse({
            "playing": True,
            "paused": paused,
            "id": song_id,
            "name": current.get("name", ""),
            "artists": current.get("artists", ""),
            "album": current.get("album", ""),
            "cover": current.get("cover", ""),
            "duration": duration,
            "durationText": dur_text,
            "progress": round(progress, 2),
            "volume": volume,
        })
    except Exception as e:
        logger.error(f"/api/status 异常: {e}")
        return JSONResponse({"playing": False, "error": str(e)})


@app.get("/api/lyric")
def api_lyric(id: str = Query(...), platform: str = Query("netease")):
    try:
        cache_key = f"lyric:{platform}:{id}"
        with _lyric_lock:
            if cache_key in _lyric_cache:
                cached = _lyric_cache[cache_key]
                return JSONResponse({"id": id, **cached})

        p = _resolve_platform(platform)
        if platform == "netease" and hasattr(p, "get_lyrics"):
            lyric, tlyric = p.get_lyrics(id)
        else:
            lyric = p.get_lyric(id)
            tlyric = None

        result = {"lyric": lyric, "tlyric": tlyric}
        with _lyric_lock:
            if len(_lyric_cache) >= _LYRIC_CACHE_MAX:
                oldest = next(iter(_lyric_cache))
                del _lyric_cache[oldest]
            _lyric_cache[cache_key] = result

        return JSONResponse({"id": id, **result})
    except Exception as e:
        logger.error(f"/api/lyric 异常: {e}")
        return JSONResponse({"id": id, "lyric": None, "tlyric": None, "error": str(e)})


@app.get("/api/queue")
def api_queue(area: str = Query("", description="域 ID，用于多域隔离")):
    try:
        r = get_redis()
        queue_key = _area_key(KEY_QUEUE, area)
        items = r.lrange(queue_key, 0, -1)
        queue: list[dict] = []
        for item in items:
            song = json.loads(item)
            dur_text = song.get("durationText", "")
            if not dur_text:
                raw_dur = song.get("duration", "")
                if isinstance(raw_dur, str) and ":" in raw_dur:
                    dur_text = raw_dur
            queue.append({
                "id": song.get("song_id") or song.get("id"),
                "name": song.get("name", ""),
                "artists": song.get("artists", ""),
                "cover": song.get("cover", ""),
                "durationText": dur_text,
            })
        return JSONResponse({"queue": queue})
    except Exception as e:
        logger.error(f"/api/queue 异常: {e}")
        return JSONResponse({"queue": [], "error": str(e)})


@app.get("/api/debug")
def api_debug(area: str = Query("", description="域 ID")):
    """调试端点：显示 Redis 中的原始数据"""
    try:
        r = get_redis()
        r.ping()
        current_key = _area_key(KEY_CURRENT, area)
        queue_key = _area_key(KEY_QUEUE, area)
        current = r.get(current_key)
        ps_key = _area_key(KEY_PLAY_STATE, area)
        play_state = r.get(ps_key)
        queue_len = r.llen(queue_key)
        return JSONResponse({
            "redis": "connected",
            "area": area or "(default)",
            current_key: json.loads(current) if current else None,
            ps_key: json.loads(play_state) if play_state else None,
            "queue_length": queue_len,
        })
    except Exception as e:
        return JSONResponse({"redis": "error", "detail": str(e)})


@app.get("/api/liked")
def api_liked(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=50),
    keyword: Optional[str] = Query(None),
):
    """获取喜欢的音乐列表（分页）。若传 keyword 则在全部喜欢中搜索后分页返回。"""
    global liked_ids_cache
    try:
        nc = get_netease()
        if not liked_ids_cache:
            uid = nc.get_user_id()
            if not uid:
                return JSONResponse({"songs": [], "error": "无法获取网易云账号"})
            liked_ids_cache = nc.get_liked_ids(uid)
        if not liked_ids_cache:
            return JSONResponse({"songs": [], "total": 0, "page": 1, "pages": 0})

        if keyword and keyword.strip():
            all_ids = list(liked_ids_cache)
            batch_size = 50
            all_songs: list = []
            for i in range(0, len(all_ids), batch_size):
                chunk = all_ids[i : i + batch_size]
                details = nc.get_song_details_batch(chunk)
                all_songs.extend(details)
            filtered = _filter_songs_by_keyword(all_songs, keyword)
            total = len(filtered)
            pages = (total + limit - 1) // limit if total else 1
            page = min(page, max(1, pages))
            start = (page - 1) * limit
            page_songs = filtered[start : start + limit]
            return JSONResponse({"songs": page_songs, "total": total, "page": page, "pages": pages})

        total = len(liked_ids_cache)
        pages = (total + limit - 1) // limit
        page = min(page, pages)
        start = (page - 1) * limit
        page_ids = liked_ids_cache[start : start + limit]
        details = nc.get_song_details_batch(page_ids)
        return JSONResponse({"songs": details, "total": total, "page": page, "pages": pages})
    except Exception as e:
        logger.error(f"/api/liked 异常: {e}")
        return JSONResponse({"songs": [], "error": str(e)})


@app.post("/api/liked/refresh")
def api_liked_refresh():
    """刷新喜欢列表缓存"""
    global liked_ids_cache
    liked_ids_cache = []
    return JSONResponse({"ok": True})


@app.get("/api/search")
def api_search(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=30),
    platform: str = Query("netease"),
):
    """搜索歌曲，返回列表。platform 可选 netease / qq / bilibili。"""
    try:
        p = _resolve_platform(platform)
        results = p.search_many(keyword, limit=limit)
        return JSONResponse({"results": results, "platform": platform})
    except Exception as e:
        logger.error(f"/api/search 异常: {e}")
        return JSONResponse({"results": [], "error": str(e)})


@app.post("/api/add")
async def api_add(request: Request, area: str = Query("", description="域 ID")):
    """通过歌曲 ID 添加到播放队列"""
    try:
        body = await request.json()
        return JSONResponse(add_song_to_queue(body=body, area=area))
    except Exception as e:
        logger.error(f"/api/add 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/control")
async def api_control(request: Request, area: str = Query("", description="域 ID")):
    """Web 端控制接口：next / clear / stop / pause / resume / seek / volume"""
    try:
        body = await request.json()
        action = body.get("action", "")
        result = execute_control_action(action=action, body=body, redis_client=get_redis(), area=area)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"/api/control 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/queue/action")
async def api_queue_action(request: Request, area: str = Query("", description="域 ID")):
    """队列项操作：top(置顶) / remove(删除)"""
    try:
        body = await request.json()
        action = body.get("action", "")
        index = body.get("index", -1)
        return JSONResponse(execute_queue_action(action=action, index=index, redis_client=get_redis(), area=area))
    except Exception as e:
        logger.error(f"/api/queue/action 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/health")
def health_check():
    """系统健康检查 -- 汇报各子系统状态，无需认证。"""
    checks: dict[str, dict] = {}
    overall = True

    # Redis
    try:
        r = get_redis()
        r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "degraded", "detail": str(e)}
        overall = False

    # 数据库
    try:
        from database import get_connection
        conn = get_connection()
        conn.execute("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        overall = False

    # 网易云 API
    try:
        nc = get_netease()
        uid = nc.get_user_id()
        checks["netease_api"] = {"status": "ok" if uid else "degraded", "logged_in": bool(uid)}
    except Exception as e:
        checks["netease_api"] = {"status": "error", "detail": str(e)}
        overall = False

    # 播放队列状态
    try:
        r = get_redis()
        queue_len = int(r.llen(KEY_QUEUE) or 0)
        current = r.get(KEY_CURRENT)
        checks["music"] = {
            "status": "ok",
            "queue_length": queue_len,
            "now_playing": bool(current),
        }
    except Exception as e:
        checks["music"] = {"status": "error", "detail": str(e)}

    # 运行时间
    uptime_seconds = int(time.time() - started_at)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    status_code = 200 if overall else 503
    return JSONResponse(
        {
            "status": "healthy" if overall else "degraded",
            "uptime": f"{hours}h {minutes}m {seconds}s",
            "uptime_seconds": uptime_seconds,
            "checks": checks,
        },
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("请使用 Bot 发送的网页播放器链接访问。", status_code=403)


@app.get("/w/{token}", response_class=HTMLResponse)
def index_with_token(token: str):
    active = get_token(redis_client=get_redis())
    if not active or token != active:
        return HTMLResponse("播放器链接无效或已失效，请重新让 Bot 发送最新链接。", status_code=403)
    set_token(token, redis_client=get_redis(), ttl_seconds=cfg.token_ttl_seconds())
    html_path = os.path.join(os.path.dirname(__file__), "player.html")
    with open(html_path, "r", encoding="utf-8") as f:
        resp = HTMLResponse(f.read())
    resp.set_cookie(
        key="web_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_secure(),
        max_age=cfg.cookie_max_age_seconds(),
    )
    return resp


# ---------------------------------------------------------------------------
# 注册管理后台路由（放在所有定义之后以避免循环导入）
# ---------------------------------------------------------------------------

from web_player_admin import admin_router  # noqa: E402

app.include_router(admin_router)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def run_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    display = f"[{host}]" if ":" in host else host
    logger.info(f"Web 播放器启动: http://{display}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
