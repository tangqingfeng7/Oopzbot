import json
import os
import secrets
import sys
import time
import asyncio
import copy
from collections import deque
from threading import Lock
from typing import Optional

import redis
import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config as runtime_config
from database import DB_PATH, SongCache, Statistics, get_connection
from logger_config import get_logger
from netease import NeteaseCloud
from queue_manager import get_redis_client
from web_link_token import clear_token, ensure_token, get_token, set_token

logger = get_logger("WebPlayer")

app = FastAPI(title="Oopz Music Player", docs_url=None, redoc_url=None)

REDIS_CONFIG = runtime_config.REDIS_CONFIG
WEB_PLAYER_CONFIG = runtime_config.WEB_PLAYER_CONFIG
OOPZ_CONFIG = getattr(runtime_config, "OOPZ_CONFIG", {})
NETEASE_CLOUD = getattr(runtime_config, "NETEASE_CLOUD", {})
DOUBAO_CONFIG = getattr(runtime_config, "DOUBAO_CONFIG", {})
DOUBAO_IMAGE_CONFIG = getattr(runtime_config, "DOUBAO_IMAGE_CONFIG", {})
AUTO_RECALL_CONFIG = getattr(runtime_config, "AUTO_RECALL_CONFIG", {})
AREA_JOIN_NOTIFY = getattr(runtime_config, "AREA_JOIN_NOTIFY", {})
CHAT_CONFIG = getattr(runtime_config, "CHAT_CONFIG", {})
PROFANITY_CONFIG = getattr(runtime_config, "PROFANITY_CONFIG", {})

_redis: Optional[redis.Redis] = None
_netease: Optional[NeteaseCloud] = None

_lyric_cache: dict[str, dict] = {}
_lyric_lock = Lock()
_LYRIC_CACHE_MAX = 200
_started_at = time.time()

KEY_ADMIN_SESSION = "music:admin_session"
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADMIN_OVERRIDES_PATH = os.path.join(_PROJECT_ROOT, "data", "admin_runtime_config.json")
_ADMIN_ASSETS_DIR = os.path.join(_PROJECT_ROOT, "src", "admin_assets")
_WEBINTOSH_ASSETS_DIR = os.path.join(_PROJECT_ROOT, "Webintosh", "assets")


def _mount_static_if_exists(route: str, directory: str, name: str) -> None:
    if os.path.isdir(directory):
        app.mount(route, StaticFiles(directory=directory), name=name)
    else:
        logger.warning("Static assets directory missing, skip mount: %s", directory)


_mount_static_if_exists("/admin-assets", _ADMIN_ASSETS_DIR, "admin-assets")
_mount_static_if_exists("/webintosh-assets", _WEBINTOSH_ASSETS_DIR, "webintosh-assets")


def _refresh_runtime_dependents(applied_groups: set[str]) -> None:
    if "redis" not in applied_groups and "web_player" not in applied_groups:
        return
    try:
        from music import reset_web_player_url_cache
        reset_web_player_url_cache()
    except Exception as e:
        logger.debug("Refresh runtime dependents failed: %s", e)

_CONFIG_GROUPS = {
    "web_player": {
        "target": WEB_PLAYER_CONFIG,
        "fields": {
            "url": {"type": "str", "max_len": 300},
            "token_ttl_seconds": {"type": "int", "min": 0, "max": 7 * 24 * 3600},
            "cookie_max_age_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "cookie_secure": {"type": "bool"},
            "link_idle_release_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "admin_enabled": {"type": "bool"},
            "admin_password": {"type": "str", "max_len": 128, "sensitive": True},
            "admin_session_ttl_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "admin_cookie_secure": {"type": "bool"},
        },
    },
    "auto_recall": {
        "target": AUTO_RECALL_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "delay": {"type": "int", "min": 1, "max": 3600},
        },
    },
    "area_join_notify": {
        "target": AREA_JOIN_NOTIFY,
        "fields": {
            "enabled": {"type": "bool"},
            "message_template": {"type": "str", "max_len": 200},
            "message_template_leave": {"type": "str", "max_len": 200},
            "poll_interval_seconds": {"type": "int", "min": 2, "max": 3600},
        },
    },
    "chat": {
        "target": CHAT_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
        },
    },
    "profanity": {
        "target": PROFANITY_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "mute_duration": {"type": "int", "min": 1, "max": 10080},
            "skip_admins": {"type": "bool"},
            "warn_before_mute": {"type": "bool"},
            "context_detection": {"type": "bool"},
            "context_window": {"type": "int", "min": 5, "max": 300},
            "context_max_messages": {"type": "int", "min": 1, "max": 50},
            "ai_detection": {"type": "bool"},
            "ai_min_length": {"type": "int", "min": 1, "max": 50},
        },
    },
    "oopz": {
        "target": OOPZ_CONFIG,
        "fields": {
            "default_area": {"type": "str", "max_len": 128},
            "default_channel": {"type": "str", "max_len": 128},
            "use_announcement_style": {"type": "bool"},
            "proxy": {"type": "str", "max_len": 300},
        },
    },
    "netease": {
        "target": NETEASE_CLOUD,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "cookie": {"type": "str", "max_len": 3000, "sensitive": True, "expose_in_admin": True},
            "audio_download_timeout": {"type": "int", "min": 5, "max": 600},
            "audio_download_retries": {"type": "int", "min": 0, "max": 10},
            "audio_quality": {"type": "str", "max_len": 20},
        },
    },
    "redis": {
        "target": REDIS_CONFIG,
        "fields": {
            "host": {"type": "str", "max_len": 200},
            "port": {"type": "int", "min": 1, "max": 65535},
            "password": {"type": "str", "max_len": 256, "sensitive": True},
            "db": {"type": "int", "min": 0, "max": 15},
            "decode_responses": {"type": "bool"},
        },
    },
    "doubao_chat": {
        "target": DOUBAO_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "api_key": {"type": "str", "max_len": 256, "sensitive": True, "expose_in_admin": True},
            "model": {"type": "str", "max_len": 120},
            "system_prompt": {"type": "str", "max_len": 5000},
            "max_tokens": {"type": "int", "min": 1, "max": 8192},
            "temperature": {"type": "float", "min": 0, "max": 2},
        },
    },
    "doubao_image": {
        "target": DOUBAO_IMAGE_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "api_key": {"type": "str", "max_len": 256, "sensitive": True, "expose_in_admin": True},
            "model": {"type": "str", "max_len": 120},
            "size": {"type": "str", "max_len": 30},
            "watermark": {"type": "bool"},
        },
    },
}

_CONFIG_BASELINES = {
    "web_player": copy.deepcopy(WEB_PLAYER_CONFIG),
    "auto_recall": copy.deepcopy(AUTO_RECALL_CONFIG),
    "area_join_notify": copy.deepcopy(AREA_JOIN_NOTIFY),
    "chat": copy.deepcopy(CHAT_CONFIG),
    "profanity": copy.deepcopy(PROFANITY_CONFIG),
    "oopz": copy.deepcopy(OOPZ_CONFIG),
    "netease": copy.deepcopy(NETEASE_CLOUD),
    "redis": copy.deepcopy(REDIS_CONFIG),
    "doubao_chat": copy.deepcopy(DOUBAO_CONFIG),
    "doubao_image": copy.deepcopy(DOUBAO_IMAGE_CONFIG),
}


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = get_redis_client()
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


def _admin_enabled() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("admin_enabled", False))


def _admin_password() -> str:
    value = WEB_PLAYER_CONFIG.get("admin_password", "")
    return str(value).strip() if value is not None else ""


def _admin_session_ttl_seconds() -> int:
    try:
        ttl = int(WEB_PLAYER_CONFIG.get("admin_session_ttl_seconds", 43200) or 0)
    except (TypeError, ValueError):
        ttl = 43200
    return ttl if ttl > 0 else 0


def _admin_cookie_secure() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("admin_cookie_secure", _cookie_secure()))


def _admin_cookie_name() -> str:
    return "admin_session"


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    raise ValueError("布尔值格式无效")


def _coerce_config_value(meta: dict, raw):
    value_type = meta.get("type")
    if value_type == "bool":
        return _to_bool(raw)
    if value_type == "float":
        try:
            v = float(raw)
        except (TypeError, ValueError):
            raise ValueError("浮点数格式无效")
        min_v = meta.get("min")
        max_v = meta.get("max")
        if min_v is not None and v < min_v:
            raise ValueError(f"必须 >= {min_v}")
        if max_v is not None and v > max_v:
            raise ValueError(f"必须 <= {max_v}")
        return v
    if value_type == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise ValueError("整数格式无效")
        min_v = meta.get("min")
        max_v = meta.get("max")
        if min_v is not None and v < min_v:
            raise ValueError(f"必须 >= {min_v}")
        if max_v is not None and v > max_v:
            raise ValueError(f"必须 <= {max_v}")
        return v
    if value_type == "str":
        text = "" if raw is None else str(raw)
        max_len = meta.get("max_len")
        if max_len is not None and len(text) > max_len:
            raise ValueError(f"长度不能超过 {max_len}")
        return text
    raise ValueError(f"未知类型: {value_type}")


def _read_admin_overrides() -> dict:
    if not os.path.exists(_ADMIN_OVERRIDES_PATH):
        return {}
    try:
        with open(_ADMIN_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"读取后台配置覆盖文件失败: {e}")
        return {}


def _write_admin_overrides(payload: dict):
    os.makedirs(os.path.dirname(_ADMIN_OVERRIDES_PATH), exist_ok=True)
    with open(_ADMIN_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _apply_config_updates(updates: dict) -> tuple[dict, list[str], dict]:
    applied = {}
    errors = []
    persist_payload = {}
    for group_name, patch in (updates or {}).items():
        group = _CONFIG_GROUPS.get(group_name)
        if not group:
            errors.append(f"未知配置分组: {group_name}")
            continue
        if not isinstance(patch, dict):
            errors.append(f"配置分组 {group_name} 必须是对象")
            continue
        target = group.get("target")
        fields = group.get("fields", {})
        if not isinstance(target, dict):
            errors.append(f"配置分组 {group_name} 不可写")
            continue
        for field, raw in patch.items():
            meta = fields.get(field)
            if not meta:
                errors.append(f"配置项不允许修改: {group_name}.{field}")
                continue
            if meta.get("sensitive") and (raw is None or str(raw).strip() == ""):
                continue
            try:
                value = _coerce_config_value(meta, raw)
            except Exception as e:
                errors.append(f"配置项 {group_name}.{field} 校验失败: {e}")
                continue
            target[field] = value
            applied.setdefault(group_name, {})
            persist_payload.setdefault(group_name, {})
            if meta.get("sensitive"):
                applied[group_name][field] = "***"
            else:
                applied[group_name][field] = value
            persist_payload[group_name][field] = value
    return applied, errors, persist_payload


def _merge_overrides(base: dict, patch: dict) -> dict:
    out = {}
    for k, v in (base or {}).items():
        out[k] = dict(v) if isinstance(v, dict) else v
    for group, values in (patch or {}).items():
        if isinstance(values, dict):
            if not isinstance(out.get(group), dict):
                out[group] = {}
            out[group].update(values)
        else:
            out[group] = values
    return out


def _config_snapshot() -> dict:
    result = {}
    for group_name, group in _CONFIG_GROUPS.items():
        target = group.get("target")
        fields = group.get("fields", {})
        if not isinstance(target, dict):
            continue
        section = {}
        for field, meta in fields.items():
            if meta.get("sensitive"):
                value = target.get(field, "")
                section[field] = value if meta.get("expose_in_admin") else ""
                section[f"{field}_configured"] = bool(value)
            else:
                section[field] = target.get(field)
        result[group_name] = section
    return result


def _bootstrap_admin_overrides():
    existing = _read_admin_overrides()
    if not existing:
        return
    _, errors, _ = _apply_config_updates(existing)
    if errors:
        logger.warning("加载后台配置覆盖时存在问题: %s", " | ".join(errors))


def _admin_session_key(token: str) -> str:
    return f"{KEY_ADMIN_SESSION}:{token}"


def _set_admin_session_token(token: str):
    ttl = _admin_session_ttl_seconds()
    r = _get_redis()
    if ttl > 0:
        r.set(_admin_session_key(token), "1", ex=ttl)
    else:
        r.set(_admin_session_key(token), "1")


def _clear_admin_session_token(token: str):
    if not token:
        return
    try:
        _get_redis().delete(_admin_session_key(token))
    except Exception:
        pass


def _is_admin_authorized(request: Request) -> bool:
    cookie_token = request.cookies.get(_admin_cookie_name(), "")
    if not cookie_token:
        return False
    try:
        active_token = _get_redis().get(_admin_session_key(cookie_token))
    except Exception:
        return False
    return bool(active_token)


def _active_web_token() -> str:
    """获取当前生效的 Web 播放器访问令牌。"""
    return get_token(redis_client=_get_redis())


def _display_web_base_url() -> str:
    configured = str(WEB_PLAYER_CONFIG.get("url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    host = str(WEB_PLAYER_CONFIG.get("host", "127.0.0.1") or "127.0.0.1").strip()
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = WEB_PLAYER_CONFIG.get("port", 8080)
    return f"http://{host}:{port}"


_bootstrap_admin_overrides()


@app.middleware("http")
async def _auth_web_api(request: Request, call_next):
    path = request.url.path or ""
    if path.startswith("/api/"):
        active = _active_web_token()
        client_token = request.cookies.get("web_token", "")
        if not active or client_token != active:
            return JSONResponse({"ok": False, "error": "未授权或链接已失效"}, status_code=403)
    if path.startswith("/admin/api/") and path not in {"/admin/api/login"}:
        if not _admin_enabled():
            return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
        if not _is_admin_authorized(request):
            return JSONResponse({"ok": False, "error": "后台未登录或会话失效"}, status_code=401)
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
        return JSONResponse(_add_song_to_queue(body=body))
    except Exception as e:
        logger.error(f"/api/add 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/control")
async def api_control(request: Request):
    """Web 端控制接口：next / clear / stop / pause / resume / seek / volume"""
    try:
        body = await request.json()
        action = body.get("action", "")
        result = _execute_control_action(action=action, body=body, redis_client=_get_redis())
        return JSONResponse(result)
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
        return JSONResponse(_execute_queue_action(action=action, index=index, redis_client=_get_redis()))
    except Exception as e:
        logger.error(f"/api/queue/action 异常: {e}")
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse("请使用 Bot 发送的网页播放器链接访问。", status_code=403)


def _execute_control_action(action: str, body: dict, redis_client: redis.Redis) -> dict:
    if action == "next":
        redis_client.rpush(KEY_WEB_COMMANDS, "next")
        return {"ok": True}
    if action == "clear":
        redis_client.delete("music:queue")
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


def _queue_snapshot(redis_client: redis.Redis) -> list[dict]:
    items = redis_client.lrange("music:queue", 0, -1)
    queue = []
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


def _current_song_snapshot(redis_client: redis.Redis) -> Optional[dict]:
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


def _top_songs_from_play_history(page: int = 1, page_size: int = 10) -> tuple[list[dict], int]:
    conn = get_connection()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 10), 100))
    offset = (page - 1) * page_size
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
    conn.close()
    return [dict(r) for r in rows], total


def _execute_queue_action(action: str, index, redis_client: redis.Redis) -> dict:
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return {"ok": False, "error": "索引无效"}
    queue_items = redis_client.lrange("music:queue", 0, -1)
    if idx < 0 or idx >= len(queue_items):
        return {"ok": False, "error": "索引无效"}
    if action == "remove":
        placeholder = "__REMOVED__"
        redis_client.lset("music:queue", idx, placeholder)
        redis_client.lrem("music:queue", 1, placeholder)
        return {"ok": True}
    if action == "top":
        item = queue_items[idx]
        placeholder = "__REMOVED__"
        redis_client.lset("music:queue", idx, placeholder)
        redis_client.lrem("music:queue", 1, placeholder)
        redis_client.lpush("music:queue", item)
        return {"ok": True}
    return {"ok": False, "error": f"未知操作: {action}"}


def _add_song_to_queue(body: dict) -> dict:
    song_id = body.get("id")
    if not song_id:
        return {"ok": False, "error": "缺少歌曲 ID"}
    nc = _get_netease()
    url = nc.get_song_url(int(song_id))
    if not url:
        return {"ok": False, "error": "无法获取播放链接，可能需要 VIP"}

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
    queue_len = int(r.llen("music:queue") or 0)
    notify = json.dumps({"name": name, "artists": artists, "position": queue_len}, ensure_ascii=False)
    r.rpush(KEY_WEB_COMMANDS, f"notify:{notify}")
    return {"ok": True, "position": queue_len, "name": name}


def _tail_file(path: str, lines: int = 200) -> list[str]:
    if not os.path.exists(path):
        return []
    max_lines = max(1, min(int(lines), 2000))
    dq = deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            dq.append(line.rstrip("\n"))
    return list(dq)


@app.get("/admin", response_class=HTMLResponse)
def admin_index():
    if not _admin_enabled():
        return HTMLResponse("管理后台未启用，请在 WEB_PLAYER_CONFIG 中开启。", status_code=404)
    html_path = os.path.join(os.path.dirname(__file__), "admin_dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


def _admin_page(page_file: str) -> HTMLResponse:
    if not _admin_enabled():
        return HTMLResponse("管理后台未启用，请在 WEB_PLAYER_CONFIG 中开启。", status_code=404)
    html_path = os.path.join(os.path.dirname(__file__), page_file)
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/admin/music", response_class=HTMLResponse)
def admin_music_page():
    return _admin_page("admin_music.html")


@app.get("/admin/config", response_class=HTMLResponse)
def admin_config_page():
    return _admin_page("admin_config.html")


@app.get("/admin/stats", response_class=HTMLResponse)
def admin_stats_page():
    return _admin_page("admin_stats.html")


@app.get("/admin/system", response_class=HTMLResponse)
def admin_system_page():
    return _admin_page("admin_system.html")


@app.post("/admin/api/login")
async def admin_login(request: Request):
    if not _admin_enabled():
        return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
    password = _admin_password()
    if not password:
        return JSONResponse({"ok": False, "error": "未配置 admin_password"}, status_code=503)
    body = await request.json()
    submitted = str(body.get("password", ""))
    if not secrets.compare_digest(submitted, password):
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)
    token = secrets.token_urlsafe(24)
    _set_admin_session_token(token)
    ttl = _admin_session_ttl_seconds()
    response = JSONResponse({"ok": True, "ttl": ttl})
    response.set_cookie(
        key=_admin_cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=_admin_cookie_secure(),
        max_age=ttl if ttl > 0 else None,
    )
    return response


@app.post("/admin/api/logout")
def admin_logout(request: Request):
    _clear_admin_session_token(request.cookies.get(_admin_cookie_name(), ""))
    response = JSONResponse({"ok": True})
    response.delete_cookie(_admin_cookie_name())
    return response


@app.get("/admin/api/me")
def admin_me():
    return JSONResponse({"ok": True, "role": "admin"})


@app.get("/admin/api/config")
def admin_get_config():
    return JSONResponse({
        "ok": True,
        "config": _config_snapshot(),
        "overrides_path": _ADMIN_OVERRIDES_PATH,
    })


@app.post("/admin/api/config")
async def admin_update_config(request: Request):
    global _redis, _netease, _liked_ids_cache
    body = await request.json()
    updates = body.get("updates", {})
    persist = bool(body.get("persist", True))
    applied, errors, persist_payload = _apply_config_updates(updates)
    if "redis" in applied:
        _redis = get_redis_client(force_reset=True)
    if "netease" in applied:
        _netease = None
        _liked_ids_cache = []
    _refresh_runtime_dependents(set(applied))
    if persist and persist_payload:
        merged = _merge_overrides(_read_admin_overrides(), persist_payload)
        _write_admin_overrides(merged)
    return JSONResponse({
        "ok": len(errors) == 0,
        "applied": applied,
        "errors": errors,
        "persisted": bool(persist and persist_payload),
        "config": _config_snapshot(),
    })


@app.post("/admin/api/config/reset")
def admin_reset_config_overrides():
    global _redis, _netease, _liked_ids_cache
    if os.path.exists(_ADMIN_OVERRIDES_PATH):
        os.remove(_ADMIN_OVERRIDES_PATH)
    for group_name, group in _CONFIG_GROUPS.items():
        target = group.get("target")
        baseline = _CONFIG_BASELINES.get(group_name)
        if isinstance(target, dict) and isinstance(baseline, dict):
            target.clear()
            target.update(copy.deepcopy(baseline))
    _redis = get_redis_client(force_reset=True)
    _netease = None
    _liked_ids_cache = []
    _refresh_runtime_dependents({"redis", "web_player"})
    return JSONResponse({"ok": True, "removed": True, "path": _ADMIN_OVERRIDES_PATH})


def _overview_payload() -> dict:
    redis_status = "connected"
    queue_len = 0
    playing = {}
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
        "uptime_seconds": int(time.time() - _started_at),
        "redis": redis_status,
        "queue_length": queue_len,
        "playing": playing,
        "statistics_today": today,
        "statistics_summary": summary,
    }


@app.get("/admin/api/overview")
def admin_overview():
    return JSONResponse(_overview_payload(), headers={"Cache-Control": "no-store"})


@app.get("/admin/api/overview/stream")
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
                # Keep-alive comment to prevent proxy idle timeout.
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


@app.get("/admin/api/statistics")
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


@app.post("/admin/api/statistics/clear_history")
def admin_clear_play_history():
    count = SongCache.clear_play_history()
    return JSONResponse({"ok": True, "deleted": count})


@app.get("/admin/api/logs")
def admin_logs(
    tail: int | None = Query(default=None, ge=1, le=2000),
    lines: int | None = Query(default=None, ge=1, le=2000),
):
    # Backward compatible: support both ?tail= and ?lines=
    tail_count = tail if tail is not None else lines
    if tail_count is None:
        tail_count = 200
    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "oopz_bot.log")
    line_list = _tail_file(log_path, lines=tail_count)
    return JSONResponse(
        {"ok": True, "path": log_path, "lines": line_list, "logs": line_list, "count": len(line_list)},
        headers={"Cache-Control": "no-store"},
    )


@app.post("/admin/api/control")
async def admin_control(request: Request):
    try:
        body = await request.json()
        action = str(body.get("action", ""))
        result = _execute_control_action(action=action, body=body, redis_client=_get_redis())
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/admin/api/liked/refresh")
def admin_liked_refresh():
    global _liked_ids_cache
    _liked_ids_cache = []
    return JSONResponse({"ok": True})


@app.post("/admin/api/queue/clear")
def admin_queue_clear():
    _get_redis().delete("music:queue")
    return JSONResponse({"ok": True})


@app.get("/admin/api/queue")
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


@app.post("/admin/api/queue/action")
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


@app.get("/admin/api/player/link")
def admin_player_link():
    token = _active_web_token()
    path = f"/w/{token}" if token else ""
    base_url = _display_web_base_url()
    full_url = f"{base_url}{path}" if token else ""
    return JSONResponse({
        "ok": True,
        "has_token": bool(token),
        "path": path,
        "url": full_url,
        "base_url": base_url,
    })


@app.post("/admin/api/player/link/rotate")
def admin_player_link_rotate():
    clear_token(redis_client=_get_redis())
    token = ensure_token(redis_client=_get_redis(), ttl_seconds=_token_ttl_seconds())
    base_url = _display_web_base_url()
    return JSONResponse({"ok": True, "url": f"{base_url}/w/{token}"})


@app.get("/admin/api/search")
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


@app.post("/admin/api/add")
async def admin_add(request: Request):
    try:
        body = await request.json()
        return JSONResponse(_add_song_to_queue(body=body))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@app.get("/admin/api/system")
def admin_system():
    data = {
        "ok": True,
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "project_root": _PROJECT_ROOT,
        "db_path": DB_PATH,
        "db_exists": os.path.exists(DB_PATH),
        "db_size_bytes": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "log_path": os.path.join(_PROJECT_ROOT, "logs", "oopz_bot.log"),
        "uptime_seconds": int(time.time() - _started_at),
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
        conn = get_connection()
        table_rows = {}
        for table in ("image_cache", "song_cache", "play_history", "statistics"):
            row = conn.execute(f"SELECT COUNT(1) AS c FROM {table}").fetchone()
            table_rows[table] = int(row["c"] if row else 0)
        conn.close()
        data["db_tables"] = table_rows
    except Exception as e:
        data["db_tables"] = {"error": str(e)}
    return JSONResponse(data)


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