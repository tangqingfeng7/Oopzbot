"""
Web 歌词播放器 — FastAPI 服务
由 main.py 在后台线程启动，端口 8080
"""

import json
import os
import time
from threading import Lock
from typing import Optional

import redis
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from config import REDIS_CONFIG, WEB_PLAYER_CONFIG
from logger_config import get_logger
from netease import NeteaseCloud
from web_link_token import get_token, set_token

logger = get_logger("WebPlayer")

app = FastAPI(title="Oopz Music Player", docs_url=None, redoc_url=None)

_redis: Optional[redis.Redis] = None
_netease: Optional[NeteaseCloud] = None

_lyric_cache: dict[str, dict] = {}
_lyric_lock = Lock()
_LYRIC_CACHE_MAX = 200


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(**REDIS_CONFIG)
    return _redis


def _get_netease() -> NeteaseCloud:
    global _netease
    if _netease is None:
        _netease = NeteaseCloud()
    return _netease


@app.get("/api/status")
def api_status():
    try:
        r = _get_redis()
        current_raw = r.get("music:current")
        play_state_raw = r.get("music:play_state")

        if not current_raw:
            return JSONResponse({"playing": False})

        current = json.loads(current_raw)
        progress = 0.0

        # 时长优先使用存储的毫秒字段，其次再从旧格式兼容
        duration_ms = current.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms > 0:
            duration = float(duration_ms) / 1000.0
        else:
            # 旧版本曾把毫秒存到 duration 字段，这里做一次兼容
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

        vol_raw = r.get("music:volume")
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
def api_lyric(id: int = Query(...)):
    try:
        cache_key = f"lyric:{id}"
        with _lyric_lock:
            if cache_key in _lyric_cache:
                cached = _lyric_cache[cache_key]
                return JSONResponse({"id": id, **cached})

        nc = _get_netease()
        lyric = nc.get_lyric(id)
        tlyric = None
        try:
            tlyric = nc.get_tlyric(id)
        except Exception:
            pass

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
def api_queue():
    try:
        r = _get_redis()
        items = r.lrange("music:queue", 0, -1)
        queue = []
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
def api_debug():
    """调试端点：显示 Redis 中的原始数据"""
    try:
        r = _get_redis()
        r.ping()
        current = r.get("music:current")
        play_state = r.get("music:play_state")
        queue_len = r.llen("music:queue")
        return JSONResponse({
            "redis": "connected",
            "music:current": json.loads(current) if current else None,
            "music:play_state": json.loads(play_state) if play_state else None,
            "queue_length": queue_len,
        })
    except Exception as e:
        return JSONResponse({"redis": "error", "detail": str(e)})


KEY_WEB_COMMANDS = "music:web_commands"


_liked_ids_cache: list = []


def _token_ttl_seconds() -> int:
    try:
        ttl = int(WEB_PLAYER_CONFIG.get("token_ttl_seconds", 86400) or 0)
    except (TypeError, ValueError):
        ttl = 86400
    return ttl if ttl > 0 else 0


def _cookie_max_age_seconds() -> int:
    configured = WEB_PLAYER_CONFIG.get("cookie_max_age_seconds")
    if configured is not None:
        try:
            v = int(configured)
            return v if v > 0 else 7 * 24 * 3600
        except (TypeError, ValueError):
            pass
    ttl = _token_ttl_seconds()
    return ttl if ttl > 0 else 7 * 24 * 3600


def _cookie_secure() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("cookie_secure", False))


def _active_web_token() -> str:
    """获取当前生效的 Web 播放器访问令牌。"""
    return get_token(redis_client=_get_redis())


@app.middleware("http")
async def _auth_web_api(request: Request, call_next):
    path = request.url.path or ""
    if path.startswith("/api/"):
        active = _active_web_token()
        client_token = request.cookies.get("web_token", "")
        if not active or client_token != active:
            return JSONResponse({"ok": False, "error": "未授权或链接已失效"}, status_code=403)
    return await call_next(request)


def _filter_songs_by_keyword(songs: list, keyword: str) -> list:
    """按关键词过滤歌曲（歌名、歌手、专辑，不区分大小写）"""
    if not keyword or not keyword.strip():
        return songs
    k = keyword.strip().lower()
    out = []
    for s in songs:
        name = (s.get("name") or "").lower()
        artists = (s.get("artists") or "").lower()
        album = (s.get("album") or "").lower()
        if k in name or k in artists or k in album:
            out.append(s)
    return out


@app.get("/api/liked")
def api_liked(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=50),
    keyword: Optional[str] = Query(None),
):
    """获取喜欢的音乐列表（分页）。若传 keyword 则在全部喜欢中搜索后分页返回。"""
    global _liked_ids_cache
    try:
        nc = _get_netease()
        if not _liked_ids_cache:
            uid = nc.get_user_id()
            if not uid:
                return JSONResponse({"songs": [], "error": "无法获取网易云账号"})
            _liked_ids_cache = nc.get_liked_ids(uid)
        if not _liked_ids_cache:
            return JSONResponse({"songs": [], "total": 0, "page": 1, "pages": 0})

        if keyword and keyword.strip():
            # 在全部喜欢中搜索：分批拉取详情后过滤再分页
            all_ids = list(_liked_ids_cache)
            batch_size = 50
            all_songs = []
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
        # 无关键词：按原逻辑分页
        total = len(_liked_ids_cache)
        pages = (total + limit - 1) // limit
        page = min(page, pages)
        start = (page - 1) * limit
        page_ids = _liked_ids_cache[start : start + limit]
        details = nc.get_song_details_batch(page_ids)
        return JSONResponse({"songs": details, "total": total, "page": page, "pages": pages})
    except Exception as e:
        logger.error(f"/api/liked 异常: {e}")
        return JSONResponse({"songs": [], "error": str(e)})


@app.post("/api/liked/refresh")
def api_liked_refresh():
    """刷新喜欢列表缓存"""
    global _liked_ids_cache
    _liked_ids_cache = []
    return JSONResponse({"ok": True})


@app.get("/api/search")
def api_search(keyword: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=30)):
    """搜索歌曲，返回列表"""
    try:
        nc = _get_netease()
        results = nc.search_many(keyword, limit=limit)
        return JSONResponse({"results": results})
    except Exception as e:
        logger.error(f"/api/search 异常: {e}")
        return JSONResponse({"results": [], "error": str(e)})


@app.post("/api/add")
async def api_add(request: Request):
    """通过歌曲 ID 添加到播放队列"""
    try:
        body = await request.json()
        song_id = body.get("id")
        if not song_id:
            return JSONResponse({"ok": False, "error": "缺少歌曲 ID"})

        nc = _get_netease()
        url = nc.get_song_url(int(song_id))
        if not url:
            return JSONResponse({"ok": False, "error": "无法获取播放链接，可能需要 VIP"})

        name = body.get("name", "")
        artists = body.get("artists", "")
        album = body.get("album", "")
        cover = body.get("cover", "")
        duration_ms = body.get("duration", 0)
        duration_text = body.get("durationText", "")

        song_data = {
            "platform": "netease",
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
            "area": "",
            "user": "web",
        }

        r = _get_redis()
        r.rpush("music:queue", json.dumps(song_data, ensure_ascii=False))
        queue_len = r.llen("music:queue")

        notify = json.dumps({"name": name, "artists": artists, "position": queue_len}, ensure_ascii=False)
        r.rpush("music:web_commands", f"notify:{notify}")

        return JSONResponse({"ok": True, "position": queue_len, "name": name})
    except Exception as e:
        logger.error(f"/api/add 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/control")
async def api_control(request: Request):
    """Web 端控制接口：next / clear / stop / pause / resume / seek / volume"""
    try:
        body = await request.json()
        action = body.get("action", "")
        r = _get_redis()

        if action == "next":
            r.rpush(KEY_WEB_COMMANDS, "next")
            return JSONResponse({"ok": True})
        elif action == "clear":
            r.delete("music:queue")
            return JSONResponse({"ok": True})
        elif action == "stop":
            r.rpush(KEY_WEB_COMMANDS, "stop")
            return JSONResponse({"ok": True})
        elif action == "pause":
            r.rpush(KEY_WEB_COMMANDS, "pause")
            return JSONResponse({"ok": True})
        elif action == "resume":
            r.rpush(KEY_WEB_COMMANDS, "resume")
            return JSONResponse({"ok": True})
        elif action == "seek":
            seek_time = body.get("time", 0)
            r.rpush(KEY_WEB_COMMANDS, f"seek:{seek_time}")
            return JSONResponse({"ok": True})
        elif action == "volume":
            vol = body.get("value", 50)
            r.rpush(KEY_WEB_COMMANDS, f"volume:{vol}")
            return JSONResponse({"ok": True})
        else:
            return JSONResponse({"ok": False, "error": f"未知操作: {action}"})
    except Exception as e:
        logger.error(f"/api/control 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/queue/action")
async def api_queue_action(request: Request):
    """队列项操作：top(置顶) / remove(删除)"""
    try:
        body = await request.json()
        action = body.get("action", "")
        index = body.get("index", -1)
        r = _get_redis()

        queue_items = r.lrange("music:queue", 0, -1)
        if index < 0 or index >= len(queue_items):
            return JSONResponse({"ok": False, "error": "索引无效"})

        if action == "remove":
            placeholder = "__REMOVED__"
            r.lset("music:queue", index, placeholder)
            r.lrem("music:queue", 1, placeholder)
            return JSONResponse({"ok": True})
        elif action == "top":
            item = queue_items[index]
            placeholder = "__REMOVED__"
            r.lset("music:queue", index, placeholder)
            r.lrem("music:queue", 1, placeholder)
            r.lpush("music:queue", item)
            return JSONResponse({"ok": True})
        else:
            return JSONResponse({"ok": False, "error": f"未知操作: {action}"})
    except Exception as e:
        logger.error(f"/api/queue/action 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("请使用 Bot 发送的网页播放器链接访问。", status_code=403)


@app.get("/w/{token}", response_class=HTMLResponse)
def index_with_token(token: str):
    active = _active_web_token()
    if not active or token != active:
        return HTMLResponse("播放器链接无效或已失效，请重新让 Bot 发送最新链接。", status_code=403)
    # 命中正确令牌后，刷新 Redis 过期时间（若启用 TTL）。
    set_token(token, redis_client=_get_redis(), ttl_seconds=_token_ttl_seconds())
    html_path = os.path.join(os.path.dirname(__file__), "player.html")
    with open(html_path, "r", encoding="utf-8") as f:
        resp = HTMLResponse(f.read())
    resp.set_cookie(
        key="web_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=_cookie_max_age_seconds(),
    )
    return resp


def run_server(host: str = "0.0.0.0", port: int = 8080):
    display = f"[{host}]" if ":" in host else host
    logger.info(f"Web 播放器启动: http://{display}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
