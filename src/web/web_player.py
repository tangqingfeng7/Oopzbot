"""Web 播放器 — FastAPI 主应用、播放器 API 路由、共享状态。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import secrets
import time
from collections.abc import Mapping
from threading import Lock
from typing import TYPE_CHECKING, cast

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import web.web_player_config as cfg
from app.services.playback import (
    PlaybackAreaResolver,
    PlaybackAreaUnavailable,
    PlaybackControlService,
)
from core.logger_config import get_logger
from core.queue_manager import (
    KEY_CURRENT,
    KEY_PLAY_MODE,
    KEY_PLAY_STATE,
    KEY_QUEUE,
    _area_key,
    get_redis_client,
    is_degraded,
)
from core.redis_keys import (
    VOLUME as KEY_VOLUME,
)
from core.redis_keys import WEB_TOKEN_COOKIE
from core.redis_protocol import (
    PlaybackCommandStore,
    RedisDataStore,
    redis_json_object,
    redis_optional_text,
)
from music.music_platform import MusicPlatform
from music.netease import NeteaseCloud
from web.web_link_token import get_active_area, get_token, set_token, touch_access
from web.web_rate_limit import (
    SCREEN_SHARE_HEARTBEAT_IP_LIMITER,
    client_ip,
    limiter_for,
)
from web.web_request_context import cookie_secure_for

if TYPE_CHECKING:
    from oopz.sdk_gateway import AsyncOopzGateway

logger = get_logger("WebPlayer")


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(title="Oopz Music Player", docs_url=None, redoc_url=None)

_WEB_ASSETS_DIR = os.path.join(cfg.PROJECT_ROOT, "src", "web", "assets")
_ADMIN_ASSETS_DIR = os.path.join(_WEB_ASSETS_DIR, "admin")
_SCREEN_SHARE_ASSETS_DIR = os.path.join(_WEB_ASSETS_DIR, "screen-share")


class _NoStoreStaticFiles(StaticFiles):
    """避免屏幕共享页面的新旧 HTML、CSS 和 JS 被浏览器混用。"""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


def _mount_static_if_exists(
    route: str,
    directory: str,
    name: str,
    *,
    no_store: bool = False,
) -> None:
    if os.path.isdir(directory):
        static_files = _NoStoreStaticFiles if no_store else StaticFiles
        app.mount(route, static_files(directory=directory), name=name)
    else:
        logger.warning("Static assets directory missing, skip mount: %s", directory)


_mount_static_if_exists("/admin-assets", _ADMIN_ASSETS_DIR, "admin-assets")
_mount_static_if_exists(
    "/screen-share/assets",
    _SCREEN_SHARE_ASSETS_DIR,
    "screen-share-assets",
    no_store=True,
)

# ---------------------------------------------------------------------------
# 共享状态（admin 模块通过公共函数访问）
# ---------------------------------------------------------------------------

_redis: RedisDataStore | None = None
_netease: NeteaseCloud | None = None

_lyric_cache: dict[str, dict] = {}
_lyric_lock = Lock()
_LYRIC_CACHE_MAX = 200

started_at: float = time.time()
liked_ids_cache: list = []

# 可选播放模式取值（与 src/music.py 中的 PLAY_MODE_* 常量保持一致）。
# 注意：autoplay 不是可选模式，仅为队列播完自动续播时的来源标识。
PLAY_MODE_LIST = "list"
PLAY_MODE_SINGLE = "single"
PLAY_MODE_SHUFFLE = "shuffle"
PLAY_MODE_STOP = "stop"
_VALID_PLAY_MODES = {
    PLAY_MODE_LIST,
    PLAY_MODE_SINGLE,
    PLAY_MODE_SHUFFLE,
    PLAY_MODE_STOP,
}


async def _read_play_mode(redis_client: RedisDataStore, area: str = "") -> str:
    raw = await redis_client.get(_area_key(KEY_PLAY_MODE, area))
    mode = redis_optional_text(raw, field="播放模式")
    return mode if mode in _VALID_PLAY_MODES else PLAY_MODE_LIST


def _normalize_volume(value, fallback: int | None = None) -> int:
    if fallback is None:
        fallback = cfg.default_music_volume()
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    try:
        volume = int(value)
    except (TypeError, ValueError):
        volume = fallback
    return max(0, min(100, volume))


def _finite_float(value: object, fallback: float = 0.0) -> float:
    """解析来自 JSON/Redis 的有限数字。"""

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return fallback
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


async def get_redis() -> RedisDataStore:
    global _redis
    # 始终对齐全局客户端：Redis 从内存降级中恢复后，Web 层自动切回。
    client = await get_redis_client()
    if client is not _redis:
        _redis = client
    return client


async def reset_redis(force: bool = False) -> None:
    global _redis
    _redis = await get_redis_client(force_reset=True) if force else None


def _area_resolver(redis_client: RedisDataStore, active_area: str) -> PlaybackAreaResolver:
    # 活跃域已在调用方 await 取好；解析器的读取回调必须保持同步。
    return PlaybackAreaResolver(
        active_area_reader=lambda: active_area,
    )


async def _resolve_area(
    redis_client: RedisDataStore,
    area: str = "",
    *,
    required: bool = True,
) -> str:
    """解析公共播放器 area；绝不回退到全局播放键。"""
    active_area = await get_active_area(redis_client=redis_client)
    resolution = _area_resolver(redis_client, active_area).public(area)
    return resolution.require().value if required else resolution.value


def _area_unavailable_response() -> JSONResponse:
    return JSONResponse(
        {
            "ok": False,
            "code": PlaybackAreaUnavailable.code,
            "error": PlaybackAreaUnavailable.message,
        },
        status_code=409,
    )


def get_netease() -> NeteaseCloud:
    global _netease
    if _netease is None:
        _netease = NeteaseCloud()
    return _netease


def reset_netease() -> None:
    global _netease
    _netease = None


_sender: AsyncOopzGateway | None = None
_music_dependency = None
_plugin_runtime = None
_plugin_host = None
_oopz_client = None


def set_sender(sender: AsyncOopzGateway | None) -> None:
    global _sender
    _sender = sender


def get_sender() -> AsyncOopzGateway | None:
    return _sender


def set_oopz_client(client) -> None:
    """注入运行中的 OOPZ WebSocket 客户端，供后台凭据热更新刷新连接。"""
    global _oopz_client
    _oopz_client = client


def get_oopz_client():
    return _oopz_client


def set_plugin_runtime(runtime, host) -> None:
    global _plugin_runtime, _plugin_host
    _plugin_runtime = runtime
    _plugin_host = host


def get_plugin_runtime():
    return _plugin_runtime


def get_plugin_host():
    return _plugin_host


def register_runtime_dependencies(*, music=None, plugins=None, plugin_host=None) -> None:
    """兼容旧测试/调用方的运行时依赖注入入口。"""
    global _music_dependency
    if music is not None:
        _music_dependency = music
    if plugins is not None:
        set_plugin_runtime(plugins, plugin_host)


def refresh_music_platforms() -> dict:
    """在配置热更新后刷新已创建的音乐平台实例。"""
    reset_netease()
    _platform_cache.clear()
    if _music_dependency is None:
        return {"available": False, "reason": "music 未注册"}
    refresh = getattr(_music_dependency, "refresh_platforms", None)
    if callable(refresh):
        result = refresh()
        if isinstance(result, Mapping):
            return dict(result)
        return {"available": False, "reason": "音乐处理器刷新结果无效"}
    handler = getattr(_music_dependency, "_handler", None)
    refresh = getattr(handler, "refresh_platforms", None)
    if callable(refresh):
        result = refresh()
        if isinstance(result, Mapping):
            return dict(result)
        return {"available": False, "reason": "音乐处理器刷新结果无效"}
    return {"available": False, "reason": "音乐处理器尚未初始化"}


def _admin_enabled() -> bool:
    return cfg.admin_enabled()


async def _is_admin_authorized(request: Request) -> bool:
    if not _admin_enabled():
        return False
    cookie_token = request.cookies.get(cfg.admin_cookie_name(), "")
    if not cookie_token:
        return False
    try:
        active_token = await (await get_redis()).get(cfg.admin_session_key(cookie_token))
    except Exception:
        active_token = None
    return bool(active_token)


# ---------------------------------------------------------------------------
# 启动时加载独立域配置
# ---------------------------------------------------------------------------

cfg.bootstrap_area_overrides()

# ---------------------------------------------------------------------------
# 中间件
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _auth_web_api(request: Request, call_next):
    path = request.url.path or ""

    if path.startswith(("/api/", "/admin/api/", "/screen-share/api/")):
        ip = client_ip(request, cfg.trusted_proxy_cidrs())
        rate_key = ip
        ip_allowed = True
        if path == "/screen-share/api/presenter/heartbeat":
            presenter_auth = request.cookies.get(PRESENTER_COOKIE_NAME, "")
            if presenter_auth:
                digest = hashlib.sha256(presenter_auth.encode("utf-8")).hexdigest()
                rate_key = f"presenter:{digest}"
            ip_allowed = SCREEN_SHARE_HEARTBEAT_IP_LIMITER.is_allowed(ip)
        if not ip_allowed or not limiter_for(path).is_allowed(rate_key):
            return JSONResponse(
                {"ok": False, "error": "请求过于频繁，请稍后再试"},
                status_code=429,
                headers={"Retry-After": "60"},
            )

    if path.startswith("/api/"):
        active = await get_token(redis_client=await get_redis())
        client_token = request.cookies.get(WEB_TOKEN_COOKIE, "")
        if not active or not secrets.compare_digest(client_token, active):
            return JSONResponse({"ok": False, "error": "未授权或链接已失效"}, status_code=403)
        # 记一次使用，供空闲释放判定 —— 否则用户开着页面搜歌但队列恰好为空时会被误踢
        await touch_access(redis_client=await get_redis())
    if path.startswith("/admin/api/") and path not in {"/admin/api/login"}:
        if not _admin_enabled():
            return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
        if not await _is_admin_authorized(request):
            return JSONResponse({"ok": False, "error": "后台未登录或会话失效"}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 共享业务逻辑（admin 模块亦调用）
# ---------------------------------------------------------------------------

async def execute_control_action(
    action: str,
    body: dict,
    redis_client: PlaybackCommandStore,
    area: str = "",
) -> dict:
    return await PlaybackControlService(
        redis_client,
        default_volume=cfg.default_music_volume(),
    ).control(action=action, payload=body, area=area)


async def execute_queue_action(
    action: str,
    index,
    redis_client: PlaybackCommandStore,
    area: str,
) -> dict:
    return await PlaybackControlService(redis_client).mutate_queue(
        action=action,
        index=index,
        area=area,
    )


async def add_song_to_queue(body: dict, area: str = "") -> dict:
    return await PlaybackControlService(
        await get_redis(),
        redis_provider=get_redis,
        platform_resolver=_resolve_platform,
        default_volume=cfg.default_music_volume(),
    ).add_song(body=body, area=area)


_platform_cache: dict[str, MusicPlatform] = {}


def _resolve_platform(name: str = "netease") -> MusicPlatform:
    """根据平台名称获取对应的音乐平台实例（缓存复用）。"""
    if not name or name == "netease":
        return cast(MusicPlatform, get_netease())
    cached = _platform_cache.get(name)
    if cached is not None:
        return cached
    if name == "qq":
        from music.qq_music import QQMusic
        inst = QQMusic()
    elif name == "bilibili":
        from music.bilibili_music import BilibiliMusic
        inst = BilibiliMusic()
    else:
        return cast(MusicPlatform, get_netease())
    platform = cast(MusicPlatform, inst)
    _platform_cache[name] = platform
    return platform


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
async def api_status(area: str = Query("", description="域 ID，用于多域隔离")):
    try:
        r = await get_redis()
        area = await _resolve_area(r, area)
        current_key = _area_key(KEY_CURRENT, area)
        ps_key = _area_key(KEY_PLAY_STATE, area)

        pipe = r.pipeline(transaction=False)
        pipe.get(current_key)
        pipe.get(ps_key)
        pipe.get(KEY_VOLUME)
        pipe.get(_area_key(KEY_PLAY_MODE, area))
        current_raw, play_state_raw, vol_raw, mode_raw = await pipe.execute()
        volume = _normalize_volume(vol_raw)
        mode_value = redis_optional_text(mode_raw, field="播放模式")
        mode = mode_value if mode_value in _VALID_PLAY_MODES else PLAY_MODE_LIST

        if not current_raw:
            return JSONResponse({"playing": False, "volume": volume, "mode": mode})

        current = redis_json_object(current_raw, field="当前播放歌曲")
        progress = 0.0

        duration_ms = current.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms > 0:
            duration = float(duration_ms) / 1000.0
        else:
            raw_dur = current.get("duration", 0)
            duration = _finite_float(raw_dur) / 1000.0

        paused = False
        loading = False
        if play_state_raw:
            ps = redis_json_object(play_state_raw, field="播放状态")
            start = _finite_float(ps.get("start_time"))
            dur = _finite_float(ps.get("duration"))
            paused = bool(ps.get("paused"))
            loading = bool(ps.get("loading"))
            if dur:
                duration = dur
            if loading:
                progress = 0.0
            elif paused:
                progress = _finite_float(ps.get("pause_elapsed"))
            elif start and duration:
                progress = time.time() - start

        song_id = current.get("song_id") or current.get("id")
        dur_text = current.get("durationText", "")
        if not dur_text:
            raw_dur = current.get("duration", "")
            if isinstance(raw_dur, str) and ":" in raw_dur:
                dur_text = raw_dur

        return JSONResponse({
            "playing": True,
            "paused": paused,
            "loading": loading,
            "id": song_id,
            "platform": current.get("platform") or "netease",
            "name": current.get("name", ""),
            "artists": current.get("artists", ""),
            "album": current.get("album", ""),
            "cover": current.get("cover", ""),
            "duration": duration,
            "durationText": dur_text,
            "progress": round(progress, 2),
            "volume": volume,
            "mode": mode,
            "server_time": round(time.time(), 3),
        })
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        logger.error(f"/api/status 异常: {e}")
        return JSONResponse({"playing": False, "error": str(e)})


@app.get("/api/lyric")
async def api_lyric(id: str = Query(...), platform: str = Query("netease")):
    try:
        cache_key = f"lyric:{platform}:{id}"
        with _lyric_lock:
            if cache_key in _lyric_cache:
                cached = _lyric_cache[cache_key]
                return JSONResponse({"id": id, **cached})

        if platform == "netease":
            try:
                song_id = int(id)
            except ValueError as exc:
                raise ValueError("网易云歌曲 ID 必须是整数") from exc
            lyric, tlyric = await get_netease().get_lyrics(song_id)
        else:
            p = _resolve_platform(platform)
            lyric = await p.get_lyric(id)
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
async def api_queue(area: str = Query("", description="域 ID，用于多域隔离")):
    try:
        r = await get_redis()
        area = await _resolve_area(r, area)
        queue_key = _area_key(KEY_QUEUE, area)
        items = await r.lrange(queue_key, 0, -1)
        queue: list[dict] = []
        for item in items:
            song = redis_json_object(item, field="队列歌曲")
            dur_text = song.get("durationText", "")
            if not dur_text:
                raw_dur = song.get("duration", "")
                if isinstance(raw_dur, str) and ":" in raw_dur:
                    dur_text = raw_dur
            queue.append({
                "id": song.get("song_id") or song.get("id"),
                "platform": song.get("platform") or "netease",
                "name": song.get("name", ""),
                "artists": song.get("artists", ""),
                "cover": song.get("cover", ""),
                "durationText": dur_text,
            })
        return JSONResponse({"queue": queue})
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        logger.error(f"/api/queue 异常: {e}")
        return JSONResponse({"queue": [], "error": str(e)})


@app.get("/api/debug")
async def api_debug(area: str = Query("", description="域 ID")):
    """调试端点：显示 Redis 中的原始数据"""
    try:
        r = await get_redis()
        await r.ping()
        area = await _resolve_area(r, area)
        current_key = _area_key(KEY_CURRENT, area)
        queue_key = _area_key(KEY_QUEUE, area)
        current = r.get(current_key)
        ps_key = _area_key(KEY_PLAY_STATE, area)
        play_state = r.get(ps_key)
        queue_len = r.llen(queue_key)
        return JSONResponse({
            "redis": "connected",
            "area": area or "(default)",
            current_key: redis_json_object(current, field="当前播放歌曲") if current else None,
            ps_key: redis_json_object(play_state, field="播放状态") if play_state else None,
            "queue_length": queue_len,
        })
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        return JSONResponse({"redis": "error", "detail": str(e)})


@app.get("/api/liked")
async def api_liked(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=50),
    keyword: str | None = Query(None, max_length=200),
):
    """获取喜欢的音乐列表（分页）。若传 keyword 则在全部喜欢中搜索后分页返回。"""
    global liked_ids_cache
    try:
        nc = get_netease()
        if not liked_ids_cache:
            uid = await nc.get_user_id()
            if not uid:
                return JSONResponse({"songs": [], "error": "无法获取网易云账号"})
            liked_ids_cache = await nc.get_liked_ids(uid)
        if not liked_ids_cache:
            return JSONResponse({"songs": [], "total": 0, "page": 1, "pages": 0})

        if keyword and keyword.strip():
            all_ids = list(liked_ids_cache)
            batch_size = 50
            all_songs: list = []
            for i in range(0, len(all_ids), batch_size):
                chunk = all_ids[i : i + batch_size]
                details = await nc.get_song_details_batch(chunk)
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
        details = await nc.get_song_details_batch(page_ids)
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
async def api_search(
    keyword: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=30),
    platform: str = Query("netease"),
):
    """搜索歌曲，返回列表。platform 可选 netease / qq / bilibili。"""
    try:
        p = _resolve_platform(platform)
        results = await p.search_many(keyword, limit=limit)
        return JSONResponse({"results": results, "platform": platform})
    except Exception as e:
        logger.error(f"/api/search 异常: {e}")
        return JSONResponse({"results": [], "error": str(e)})


@app.post("/api/add")
async def api_add(request: Request, area: str = Query("", description="域 ID")):
    """通过歌曲 ID 添加到播放队列"""
    try:
        body = await request.json()
        area = await _resolve_area(await get_redis(), area)
        return JSONResponse(await add_song_to_queue(body=body, area=area))
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        logger.error(f"/api/add 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/control")
async def api_control(request: Request, area: str = Query("", description="域 ID")):
    """Web 端控制接口：next / clear / stop / pause / resume / seek / volume"""
    try:
        body = await request.json()
        action = body.get("action", "")
        r = await get_redis()
        area = "" if action == "volume" else await _resolve_area(r, area)
        result = await execute_control_action(action=action, body=body, redis_client=r, area=area)
        return JSONResponse(result)
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
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
        r = await get_redis()
        area = await _resolve_area(r, area)
        return JSONResponse(
            await execute_queue_action(action=action, index=index, redis_client=r, area=area)
        )
    except PlaybackAreaUnavailable:
        return _area_unavailable_response()
    except Exception as e:
        logger.error(f"/api/queue/action 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/health")
async def health_check(request: Request):
    """系统健康检查。

    存活探测（Docker healthcheck、外部 uptime 监控）无需认证，但只拿到
    ``status`` 一个字段 —— 各子系统明细里含 Redis / 数据库 / 网易云登录态、
    队列长度，以及 ``detail`` 里的原始异常文本（可能带路径或连接串），
    这些只对已登录后台的管理员返回。

    状态码在两种情况下一致（正常 200 / 异常 503），healthcheck 依赖的正是它。
    """
    checks: dict[str, dict] = {}
    overall = True

    # Redis
    try:
        r = await get_redis()
        await r.ping()
        # 内存降级时 ping 恒为 True，只看 ping 会把「Redis 完全挂掉」报成健康。
        # 但降级本身是设计中的可用状态，不计入 overall —— 判 unhealthy 会误杀容器。
        checks["redis"] = {"status": "degraded_memory" if is_degraded() else "ok"}
    except Exception as e:
        checks["redis"] = {"status": "degraded", "detail": str(e)}
        overall = False

    # 数据库
    try:
        from core.database import db_connection
        async with db_connection() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        overall = False

    # 网易云 API
    try:
        nc = get_netease()
        uid = await nc.get_user_id()
        checks["netease_api"] = {"status": "ok" if uid else "degraded", "logged_in": bool(uid)}
    except Exception as e:
        checks["netease_api"] = {"status": "error", "detail": str(e)}
        overall = False

    # 播放队列状态
    try:
        r = await get_redis()
        area = await _resolve_area(r, required=False)
        if area:
            queue_len = int(await r.llen(_area_key(KEY_QUEUE, area)) or 0)
            current = await r.get(_area_key(KEY_CURRENT, area))
            checks["music"] = {
                "status": "ok",
                "area": area,
                "queue_length": queue_len,
                "now_playing": bool(current),
            }
        else:
            checks["music"] = {
                "status": "unavailable",
                "code": "playback_area_unavailable",
                "queue_length": 0,
                "now_playing": False,
            }
    except Exception as e:
        checks["music"] = {"status": "error", "detail": str(e)}

    # 运行时间
    uptime_seconds = int(time.time() - started_at)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    status_code = 200 if overall else 503
    status = "healthy" if overall else "degraded"

    if not await _is_admin_authorized(request):
        return JSONResponse({"status": status}, status_code=status_code)

    return JSONResponse(
        {
            "status": status,
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
async def index_with_token(token: str, request: Request):
    r = await get_redis()
    active = await get_token(redis_client=r)
    if not active or not secrets.compare_digest(token, active):
        return HTMLResponse("播放器链接无效或已失效，请重新让 Bot 发送最新链接。", status_code=403)
    await set_token(token, redis_client=r, ttl_seconds=cfg.token_ttl_seconds())
    area = (request.query_params.get("area") or "").strip()
    html_path = os.path.join(_WEB_ASSETS_DIR, "player.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace(
        "</head>",
        f"<script>window.__OOPZ_AREA__={json.dumps(area)};</script></head>",
        1,
    )
    resp = HTMLResponse(html)
    resp.set_cookie(
        key=WEB_TOKEN_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure_for(
            request,
            cfg.cookie_secure(),
            cfg.trusted_proxy_cidrs(),
        ),
        max_age=cfg.cookie_max_age_seconds(),
    )
    return resp


# ---------------------------------------------------------------------------
# 注册管理后台路由（放在所有定义之后以避免循环导入）
# ---------------------------------------------------------------------------

from screen_share.web import (  # noqa: E402
    PRESENTER_COOKIE_NAME,
)
from screen_share.web import (  # noqa: E402
    router as screen_share_router,
)
from screen_share.web import (  # noqa: E402
    start_watchdog as start_screen_share_watchdog,
)
from screen_share.web import (  # noqa: E402
    stop_watchdog as stop_screen_share_watchdog,
)
from web.web_player_admin import admin_router  # noqa: E402

app.include_router(admin_router)
app.include_router(screen_share_router)
app.router.add_event_handler("startup", start_screen_share_watchdog)
app.router.add_event_handler("shutdown", stop_screen_share_watchdog)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------

def run_server(host: str | None = None, port: int | None = None) -> None:
    host = host or cfg.web_host()
    port = port or cfg.web_port()
    display = f"[{host}]" if ":" in host else host
    logger.info(f"Web 播放器启动: http://{display}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        proxy_headers=False,
    )


class WebPlayerService:
    """与 Bot 共用事件循环的可停止 Uvicorn 服务。"""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        self.host = host or cfg.web_host()
        self.port = port or cfg.web_port()
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            proxy_headers=False,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(
            self._server.serve(),
            name="web-player-uvicorn",
        )
        await asyncio.sleep(0)
        if self._task.done():
            await self._task

    async def stop(self, timeout: float = 5.0) -> None:
        server = self._server
        task = self._task
        if server is None and task is None:
            return
        if server is not None:
            server.should_exit = True
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, timeout))
            except asyncio.TimeoutError:
                logger.warning("服务停止超时: WebPlayerUvicorn，任务仍未退出")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        elif task is not None:
            await asyncio.gather(task, return_exceptions=True)
        self._server = None
        self._task = None
        # Web 播放器持有自己的网易云客户端（/api/search、/api/lyric 用），
        # 与音乐服务那个是两个实例，`platforms.close()` 覆盖不到它；
        # 不在这里关掉，关停时会留下 aiohttp 会话与连接器未释放。
        global _netease
        netease = _netease
        _netease = None
        if netease is not None:
            try:
                await netease.close()
            except Exception as exc:
                logger.warning("关闭 Web 播放器网易云会话失败: %s", exc)
