"""屏幕共享会话、角色授权和声网 Token 编排。"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from core.area_config import get_area_registry
from core.queue_manager import get_redis_client, is_degraded
from core.redis_protocol import (
    RedisDataStore,
    RedisScriptExecutor,
    redis_int,
    redis_json_object,
    redis_optional_text,
)

from .agora_token import build_rtc_token

logger = logging.getLogger(__name__)

_PREFIX = "screen_share"
_HEARTBEAT_TIMEOUT_SECONDS = 60
_SESSION_STORAGE_GRACE_SECONDS = 60
_CREATE_LUA = """
if redis.call('exists', KEYS[1]) == 1 then return 'USER_BUSY' end
redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[3])
redis.call('set', KEYS[2], ARGV[1], 'EX', ARGV[3])
redis.call('set', KEYS[3], ARGV[1], 'EX', ARGV[3])
redis.call('set', KEYS[4], ARGV[2], 'EX', ARGV[3])
return 'OK'
"""
_CLAIM_LUA = """
local sid = redis.call('get', KEYS[1])
if not sid then return 'INVALID' end
local payload = redis.call('get', KEYS[2])
if not payload then return 'INVALID' end
local data = cjson.decode(payload)
if data['status'] ~= 'pending' then return 'CLAIMED' end
data['status'] = 'claimed'
data['claimed_at'] = tonumber(ARGV[2])
data['expires_at'] = tonumber(ARGV[2]) + tonumber(ARGV[3])
data['presenter_auth_hash'] = ARGV[1]
redis.call('del', KEYS[1])
redis.call('set', KEYS[3], sid, 'EX', ARGV[4])
redis.call('set', KEYS[2], cjson.encode(data), 'EX', ARGV[4])
redis.call('expire', KEYS[4], ARGV[4])
redis.call('expire', KEYS[5], ARGV[4])
return cjson.encode(data)
"""
_READY_LUA = """
local sid = redis.call('get', KEYS[3])
if not sid or sid ~= ARGV[5] then return 'INVALID' end
local payload = redis.call('get', KEYS[1])
if not payload then return 'INVALID' end
local data = cjson.decode(payload)
if data['presenter_auth_hash'] ~= ARGV[4] then return 'INVALID' end
if data['status'] == 'active' then
  data['_first_ready'] = false
  return cjson.encode(data)
end
if data['status'] ~= 'claimed' then return 'INVALID_STATE' end
data['status'] = 'active'
data['viewer_token_hash'] = ARGV[1]
data['ready_at'] = tonumber(ARGV[2])
data['last_heartbeat'] = tonumber(ARGV[2])
redis.call('set', KEYS[1], cjson.encode(data), 'EX', ARGV[6])
redis.call('set', KEYS[2], sid, 'EX', ARGV[3])
data['_first_ready'] = true
return cjson.encode(data)
"""
_HEARTBEAT_LUA = """
local sid = redis.call('get', KEYS[2])
if not sid or sid ~= ARGV[2] then return 'INVALID' end
local payload = redis.call('get', KEYS[1])
if not payload then return 'INVALID' end
local data = cjson.decode(payload)
if data['presenter_auth_hash'] ~= ARGV[3] then return 'INVALID' end
if data['status'] ~= 'claimed' and data['status'] ~= 'active' then return 'INVALID_STATE' end
local ttl = tonumber(data['expires_at']) - tonumber(ARGV[1])
if ttl <= 0 then return 'EXPIRED' end
data['last_heartbeat'] = tonumber(ARGV[1])
redis.call('set', KEYS[1], cjson.encode(data), 'EX', ttl + tonumber(ARGV[4]))
return cjson.encode(data)
"""
_RECORD_VIEWER_MESSAGE_LUA = """
-- RECORD_VIEWER_MESSAGE
local payload = redis.call('get', KEYS[1])
if not payload then return 'INVALID' end
local data = cjson.decode(payload)
if data['status'] ~= 'active' then return 'INVALID' end
local ttl = tonumber(data['expires_at']) - tonumber(ARGV[3])
if ttl <= 0 then return 'EXPIRED' end
data['viewer_message_id'] = ARGV[1]
data['viewer_message_timestamp'] = ARGV[2]
redis.call('set', KEYS[1], cjson.encode(data), 'EX', ttl + tonumber(ARGV[4]))
return 'OK'
"""
_STOP_LUA = """
local payload = redis.call('get', KEYS[1])
if not payload then return '' end
local data = cjson.decode(payload)
redis.call('del', KEYS[1], KEYS[2], KEYS[3], KEYS[4], KEYS[5], KEYS[7])
local legacy_sid = redis.call('get', KEYS[6])
if legacy_sid and legacy_sid == data['id'] then redis.call('del', KEYS[6]) end
return payload
"""


class ScreenShareError(RuntimeError):
    def __init__(self, message: str, *, code: str = "screen_share_error", status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ShareLinks:
    session_id: str
    presenter_url: str
    viewer_url: str
    expires_at: int


class ScreenShareRedis(RedisDataStore, RedisScriptExecutor, Protocol):
    """屏幕共享只接受同时支持数据命令和 Lua 的真实 Redis。"""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _viewer_uid(viewer_token: str, viewer_instance: str) -> int:
    """为单个浏览器标签页派生稳定的 RTC UID。"""
    instance = str(viewer_instance or "").strip()
    if not instance or len(instance) > 128:
        raise ScreenShareError(
            "观看端实例标识无效",
            code="invalid_viewer_instance",
            status_code=400,
        )
    value = hashlib.sha256(f"{viewer_token}\0{instance}".encode()).digest()
    return int.from_bytes(value[:4], "big") % 0xFFFFFFFE + 1


def _scope_key(area: str, channel: str) -> str:
    return _digest(f"{area}\0{channel}")


def _session_key(session_id: str) -> str:
    return f"{_PREFIX}:session:{session_id}"


def _config() -> dict[str, Any]:
    try:
        # 使用配置后台持有的运行时字典，保存后无需重启即可生效。
        from web.web_player_config import SCREEN_SHARE_CONFIG
        raw = SCREEN_SHARE_CONFIG
    except Exception:
        try:
            import config as runtime_config
            raw = getattr(runtime_config, "SCREEN_SHARE_CONFIG", None)
        except Exception:
            raw = None
    defaults = {
        "enabled": False,
        "agora_app_id": "",
        "agora_app_certificate": "",
        "presenter_link_ttl_seconds": 600,
        "session_max_seconds": 14400,
        "rtc_token_ttl_seconds": 3600,
        "default_quality": "1080p",
    }
    if isinstance(raw, dict):
        defaults.update(raw)
    return defaults


class ScreenShareService:
    def __init__(self) -> None:
        # 后台观看令牌只保存在进程内；Redis 仍只保存哈希。
        self._admin_viewer_tokens: dict[str, tuple[str, int]] = {}

    async def _redis(self) -> ScreenShareRedis:
        try:
            redis = await get_redis_client()
        except Exception as exc:
            raise ScreenShareError(
                "Redis 当前不可用，屏幕共享为保护会话权限已暂停",
                code="redis_required",
                status_code=503,
            ) from exc
        if is_degraded() or not hasattr(redis, "eval"):
            raise ScreenShareError(
                "Redis 当前不可用，屏幕共享为保护会话权限已暂停",
                code="redis_required",
                status_code=503,
            )
        return cast(ScreenShareRedis, redis)

    @staticmethod
    def _credentials() -> tuple[str, str]:
        cfg = _config()
        if not bool(cfg.get("enabled")):
            raise ScreenShareError("屏幕共享尚未启用", code="disabled", status_code=503)
        app_id = str(cfg.get("agora_app_id") or "").strip()
        certificate = str(cfg.get("agora_app_certificate") or "").strip()
        # 复用 TokenBuilder 的严格校验，但不生成/记录真实 Token。
        try:
            build_rtc_token(
                app_id=app_id,
                app_certificate=certificate,
                channel_name="credential-check",
                uid=1,
                expires_in=60,
                publish=False,
                now=1,
            )
        except ValueError as exc:
            raise ScreenShareError(str(exc), code="invalid_agora_config", status_code=503) from exc
        return app_id, certificate

    @staticmethod
    async def authorize(sender, *, user: str, area: str, is_bot_admin: bool = False) -> bool:
        if is_bot_admin:
            return True
        # area/v3/info 只描述“当前 Bot 是否为域主”，不能用于判断命令发起者。
        # 已加入域列表包含真实 owner UID，因此以它为域主判定来源。
        try:
            joined_areas = await sender.get_joined_areas(quiet=True)
        except Exception:
            joined_areas = []
        if isinstance(joined_areas, list):
            for joined in joined_areas:
                if not isinstance(joined, dict):
                    continue
                joined_id = str(joined.get("id") or joined.get("area") or "").strip()
                owner = str(joined.get("owner") or "").strip()
                if joined_id == str(area) and owner and secrets.compare_digest(owner, str(user)):
                    return True

        allowed = set(get_area_registry().get(area).screen_share_role_ids)
        if not allowed:
            return False
        try:
            detail = await sender.get_user_area_detail(str(user), area=area)
        except Exception:
            return False
        if not isinstance(detail, dict) or detail.get("error"):
            return False
        roles = detail.get("list")
        if not isinstance(roles, list):
            return False
        user_roles: set[int] = set()
        for role in roles:
            if not isinstance(role, dict):
                continue
            role_id = role.get("roleID")
            if isinstance(role_id, (str, int)) and str(role_id).isdigit():
                user_roles.add(int(role_id))
        return bool(allowed & user_roles)

    async def create_session(self, *, sender, user: str, area: str, channel: str, is_bot_admin: bool = False) -> ShareLinks:
        self._credentials()
        if not await self.authorize(sender, user=user, area=area, is_bot_admin=is_bot_admin):
            raise ScreenShareError("你的域角色没有发起屏幕共享的权限", code="forbidden", status_code=403)

        redis = await self._redis()
        cfg = _config()
        link_ttl = max(60, min(int(cfg.get("presenter_link_ttl_seconds") or 600), 3600))
        now = int(time.time())
        session_id = secrets.token_urlsafe(16)
        presenter_token = secrets.token_urlsafe(32)
        presenter_hash = _digest(presenter_token)
        publisher_uid = secrets.randbelow(0xFFFFFFFE) + 1
        session = {
            "id": session_id,
            "status": "pending",
            "area": str(area),
            "channel": str(channel),
            "presenter_uid": str(user),
            "presenter_token_hash": presenter_hash,
            "viewer_token_hash": "",
            "presenter_auth_hash": "",
            "viewer_message_id": "",
            "viewer_message_timestamp": "",
            "agora_channel": f"oopz-share-{session_id}",
            "publisher_uid": publisher_uid,
            "created_at": now,
            "claimed_at": 0,
            "ready_at": 0,
            "last_heartbeat": 0,
            "expires_at": 0,
        }
        try:
            result = await redis.eval(
                _CREATE_LUA,
                4,
                f"{_PREFIX}:user:{_digest(str(user))}",
                f"{_PREFIX}:channel:{_scope_key(area, channel)}:{session_id}",
                f"{_PREFIX}:presenter:{presenter_hash}",
                _session_key(session_id),
                session_id,
                json.dumps(session, ensure_ascii=False, separators=(",", ":")),
                link_ttl,
            )
        except Exception as exc:
            raise ScreenShareError(
                "Redis 当前不可用，无法创建屏幕共享",
                code="redis_required",
                status_code=503,
            ) from exc
        result_text = redis_optional_text(result, field="screen share create result") or ""
        if result_text == "USER_BUSY":
            raise ScreenShareError("你已经有一个屏幕共享会话", code="user_busy", status_code=409)
        if result_text != "OK":
            raise ScreenShareError("创建屏幕共享会话失败", status_code=500)

        from web.web_player_config import display_web_base_url
        base = display_web_base_url().rstrip("/")
        return ShareLinks(
            session_id=session_id,
            # 令牌放在 URL fragment 中，浏览器不会把它发送到 Web/代理访问日志。
            presenter_url=f"{base}/screen-share/p#{presenter_token}",
            viewer_url="",
            expires_at=now + link_ttl,
        )

    async def _session_from_token(self, kind: str, token: str) -> dict[str, Any]:
        redis = await self._redis()
        token_hash = _digest(str(token or ""))
        session_id = redis_optional_text(
            await redis.get(f"{_PREFIX}:{kind}:{token_hash}"),
            field="screen share token mapping",
        )
        if not session_id:
            raise ScreenShareError("屏幕共享链接无效或已失效", code="invalid_link", status_code=404)
        raw = await redis.get(_session_key(session_id))
        if raw is None:
            raise ScreenShareError("屏幕共享会话已结束", code="session_ended", status_code=410)
        return dict(redis_json_object(raw, field="screen share session"))

    @staticmethod
    def _session_payload(raw: Any, *, field: str, key: Any) -> dict[str, Any] | None:
        try:
            return dict(redis_json_object(raw, field=field))
        except Exception:
            logger.warning("忽略损坏的屏幕共享会话: key=%s", key, exc_info=True)
            return None

    def _rtc_payload(self, session: dict[str, Any], *, uid: int, publish: bool) -> dict[str, Any]:
        app_id, certificate = self._credentials()
        ttl = max(300, min(int(_config().get("rtc_token_ttl_seconds") or 3600), 86400))
        expires_at = redis_int(
            session.get("expires_at") or 0,
            field="screen share expiration",
        )
        if expires_at:
            ttl = min(ttl, expires_at - int(time.time()))
        if ttl <= 0:
            raise ScreenShareError(
                "屏幕共享已达到最长时长",
                code="session_expired",
                status_code=410,
            )
        token = build_rtc_token(
            app_id=app_id,
            app_certificate=certificate,
            channel_name=str(session["agora_channel"]),
            uid=int(uid),
            expires_in=ttl,
            publish=publish,
        )
        return {
            "app_id": app_id,
            "channel": session["agora_channel"],
            "uid": int(uid),
            "token": token,
            "expires_in": ttl,
        }

    async def claim(self, presenter_token: str) -> tuple[dict[str, Any], str]:
        redis = await self._redis()
        presenter_hash = _digest(str(presenter_token or ""))
        session_id = redis_optional_text(
            await redis.get(f"{_PREFIX}:presenter:{presenter_hash}"),
            field="presenter mapping",
        )
        if not session_id:
            raise ScreenShareError("发起链接无效、已领取或已过期", code="invalid_link", status_code=404)
        raw_session = await redis.get(_session_key(session_id))
        if raw_session is None:
            raise ScreenShareError("发起链接无效、已领取或已过期", code="invalid_link", status_code=404)
        pending = dict(redis_json_object(raw_session, field="screen share pending session"))
        auth_token = secrets.token_urlsafe(32)
        auth_hash = _digest(auth_token)
        ttl = max(300, min(int(_config().get("session_max_seconds") or 14400), 86400))
        storage_ttl = ttl + _SESSION_STORAGE_GRACE_SECONDS
        result = await redis.eval(
            _CLAIM_LUA,
            5,
            f"{_PREFIX}:presenter:{presenter_hash}",
            _session_key(session_id),
            f"{_PREFIX}:auth:{auth_hash}",
            (
                f"{_PREFIX}:channel:"
                f"{_scope_key(str(pending['area']), str(pending['channel']))}:"
                f"{session_id}"
            ),
            f"{_PREFIX}:user:{_digest(str(pending['presenter_uid']))}",
            auth_hash,
            int(time.time()),
            ttl,
            storage_ttl,
        )
        result_text = redis_optional_text(result, field="screen share claim result") or ""
        if result_text in {"INVALID", "CLAIMED"}:
            raise ScreenShareError("发起链接无效、已领取或已过期", code="invalid_link", status_code=404)
        session = dict(json.loads(result_text))
        payload = self._rtc_payload(session, uid=int(session["publisher_uid"]), publish=True)
        payload.update({"session_id": session_id, "default_quality": str(_config().get("default_quality") or "1080p")})
        return payload, auth_token

    async def _session_from_auth(self, auth_token: str) -> dict[str, Any]:
        redis = await self._redis()
        auth_hash = _digest(str(auth_token or ""))
        session_id = redis_optional_text(
            await redis.get(f"{_PREFIX}:auth:{auth_hash}"),
            field="presenter auth mapping",
        )
        if not session_id:
            raise ScreenShareError("共享者会话无效或已结束", code="invalid_session", status_code=401)
        raw = await redis.get(_session_key(session_id))
        if raw is None:
            raise ScreenShareError("屏幕共享会话已结束", code="session_ended", status_code=410)
        session = dict(redis_json_object(raw, field="screen share session"))
        if not secrets.compare_digest(str(session.get("presenter_auth_hash") or ""), auth_hash):
            raise ScreenShareError("共享者会话无效", code="invalid_session", status_code=401)
        return session

    async def mark_ready(self, auth_token: str) -> dict[str, Any]:
        session = await self._session_from_auth(auth_token)
        redis = await self._redis()
        now = int(time.time())
        ttl = redis_int(session.get("expires_at"), field="screen share expiration") - now
        if ttl <= 0:
            raise ScreenShareError("屏幕共享已达到最长时长", code="session_expired", status_code=410)
        viewer_token = secrets.token_urlsafe(32)
        viewer_hash = _digest(viewer_token)
        auth_hash = _digest(str(auth_token or ""))
        result = await redis.eval(
            _READY_LUA,
            3,
            _session_key(str(session["id"])),
            f"{_PREFIX}:viewer:{viewer_hash}",
            f"{_PREFIX}:auth:{auth_hash}",
            viewer_hash,
            now,
            ttl,
            auth_hash,
            str(session["id"]),
            ttl + _SESSION_STORAGE_GRACE_SECONDS,
        )
        result_text = redis_optional_text(result, field="screen share ready result") or ""
        if result_text == "INVALID":
            raise ScreenShareError("共享者会话无效或已结束", code="invalid_session", status_code=401)
        if result_text == "INVALID_STATE":
            raise ScreenShareError("当前会话不能开始推流", code="invalid_state", status_code=409)
        session = dict(json.loads(result_text))
        first_ready = bool(session.pop("_first_ready", False))
        if not first_ready:
            viewer_token = ""
        return {"session": session, "first_ready": first_ready, "viewer_token": viewer_token}

    async def record_viewer_message(
        self,
        session_id: str,
        *,
        message_id: str,
        timestamp: str = "",
    ) -> bool:
        """把频道观看链接的消息引用保存到会话，供结束时精准撤回。"""
        normalized_id = str(message_id or "").strip()
        if not normalized_id:
            raise ScreenShareError(
                "观看链接消息缺少可撤回标识",
                code="message_reference_missing",
                status_code=502,
            )
        redis = await self._redis()
        try:
            result = await redis.eval(
                _RECORD_VIEWER_MESSAGE_LUA,
                1,
                _session_key(str(session_id)),
                normalized_id,
                str(timestamp or ""),
                int(time.time()),
                _SESSION_STORAGE_GRACE_SECONDS,
            )
        except Exception as exc:
            raise ScreenShareError(
                "Redis 当前不可用，无法保存观看链接消息",
                code="redis_required",
                status_code=503,
            ) from exc
        result_text = redis_optional_text(
            result,
            field="screen share viewer message result",
        ) or ""
        if result_text == "EXPIRED":
            return False
        return result_text == "OK"

    async def heartbeat(self, auth_token: str) -> dict[str, Any]:
        session = await self._session_from_auth(auth_token)
        redis = await self._redis()
        auth_hash = _digest(str(auth_token or ""))
        result = await redis.eval(
            _HEARTBEAT_LUA,
            2,
            _session_key(str(session["id"])),
            f"{_PREFIX}:auth:{auth_hash}",
            int(time.time()),
            str(session["id"]),
            auth_hash,
            _SESSION_STORAGE_GRACE_SECONDS,
        )
        result_text = redis_optional_text(result, field="screen share heartbeat result") or ""
        if result_text == "EXPIRED":
            raise ScreenShareError("屏幕共享已达到最长时长", code="session_expired", status_code=410)
        if result_text in {"INVALID", "INVALID_STATE"}:
            raise ScreenShareError("屏幕共享会话已结束", code="session_ended", status_code=410)
        return dict(json.loads(result_text))

    async def renew_presenter(self, auth_token: str) -> dict[str, Any]:
        session = await self._session_from_auth(auth_token)
        return self._rtc_payload(session, uid=int(session["publisher_uid"]), publish=True)

    async def viewer_credentials(
        self,
        viewer_token: str,
        *,
        viewer_instance: str,
    ) -> dict[str, Any]:
        session = await self._session_from_token("viewer", viewer_token)
        if session.get("status") != "active":
            raise ScreenShareError("共享尚未开始或已经结束", code="not_active", status_code=409)
        uid = _viewer_uid(viewer_token, viewer_instance)
        payload = self._rtc_payload(session, uid=uid, publish=False)
        payload["session_id"] = session["id"]
        return payload

    async def admin_active_shares(self) -> list[dict[str, Any]]:
        """返回后台可展示的活动共享，并为每项签发等效观看链接。"""
        redis = await self._redis()
        now = int(time.time())
        self._admin_viewer_tokens = {
            session_id: cached
            for session_id, cached in self._admin_viewer_tokens.items()
            if cached[1] > now
        }
        cursor = 0
        shares: list[dict[str, Any]] = []
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"{_PREFIX}:session:*", count=100)
            for key in keys:
                raw = await redis.get(key)
                if raw is None:
                    continue
                session = self._session_payload(
                    raw,
                    field="screen share admin session",
                    key=key,
                )
                if session is None:
                    continue
                if session.get("status") != "active":
                    continue
                expires_at = redis_int(
                    session.get("expires_at"),
                    field="screen share expiration",
                )
                ttl = expires_at - now
                if ttl <= 0:
                    continue
                session_id = str(session["id"])
                cached = self._admin_viewer_tokens.get(session_id)
                viewer_token = cached[0] if cached else secrets.token_urlsafe(32)
                self._admin_viewer_tokens[session_id] = (viewer_token, expires_at)
                viewer_hash = _digest(viewer_token)
                await redis.set(
                    f"{_PREFIX}:viewer:{viewer_hash}",
                    session_id,
                    ex=ttl,
                )
                from web.web_player_config import display_web_base_url

                shares.append({
                    "id": str(session["id"]),
                    "area": str(session["area"]),
                    "channel": str(session["channel"]),
                    "presenter_uid": str(session["presenter_uid"]),
                    "ready_at": redis_int(
                        session.get("ready_at"),
                        field="screen share ready timestamp",
                    ),
                    "expires_at": expires_at,
                    "viewer_url": (
                        f"{display_web_base_url().rstrip('/')}/screen-share/w#"
                        f"{viewer_token}"
                    ),
                })
            if int(cursor) == 0:
                break
        shares.sort(key=lambda item: item["ready_at"], reverse=True)
        return shares

    async def stop(self, session: dict[str, Any], *, reason: str = "unspecified") -> dict[str, Any]:
        redis = await self._redis()
        session_id = str(session["id"])
        cached_admin_token = self._admin_viewer_tokens.get(session_id)
        admin_viewer_hash = _digest(cached_admin_token[0]) if cached_admin_token else "-"
        result = await redis.eval(
            _STOP_LUA,
            7,
            _session_key(session_id),
            (
                f"{_PREFIX}:channel:"
                f"{_scope_key(str(session['area']), str(session['channel']))}:"
                f"{session['id']}"
            ),
            f"{_PREFIX}:user:{_digest(str(session['presenter_uid']))}",
            f"{_PREFIX}:viewer:{session['viewer_token_hash']}",
            f"{_PREFIX}:auth:{session.get('presenter_auth_hash') or '-'}",
            f"{_PREFIX}:channel:{_scope_key(str(session['area']), str(session['channel']))}",
            f"{_PREFIX}:viewer:{admin_viewer_hash}",
        )
        result_text = redis_optional_text(result, field="screen share stop result") or ""
        stopped = dict(json.loads(result_text)) if result_text else session
        self._admin_viewer_tokens.pop(session_id, None)
        logger.info(
            "屏幕共享会话结束: session_id=%s area=%s channel=%s status=%s reason=%s",
            stopped.get("id", ""),
            stopped.get("area", ""),
            stopped.get("channel", ""),
            stopped.get("status", ""),
            reason,
        )
        return stopped

    async def stop_by_auth(self, auth_token: str, *, reason: str = "presenter_request") -> dict[str, Any]:
        return await self.stop(await self._session_from_auth(auth_token), reason=reason)

    async def get_by_id(self, session_id: str) -> dict[str, Any] | None:
        redis = await self._redis()
        raw = await redis.get(_session_key(str(session_id)))
        if raw is None:
            return None
        return dict(redis_json_object(raw, field="screen share session"))

    async def stop_by_id(
        self,
        session_id: str,
        *,
        reason: str = "session_request",
    ) -> dict[str, Any] | None:
        session = await self.get_by_id(session_id)
        return None if session is None else await self.stop(session, reason=reason)

    async def list_by_channel(self, *, area: str, channel: str) -> list[dict[str, Any]]:
        """列出文字频道内的全部共享。

        以会话为真实数据源，同时兼容旧版单频道锁创建的存量会话。
        """
        redis = await self._redis()
        scope = _scope_key(area, channel)
        channel_key = f"{_PREFIX}:channel:{scope}"
        cursor = 0
        session_ids: list[str] = []
        while True:
            cursor, keys = await redis.scan(
                cursor=cursor,
                match=f"{channel_key}:*",
                count=100,
            )
            for key in keys:
                session_id = redis_optional_text(
                    await redis.get(key),
                    field="screen share channel member",
                )
                if session_id:
                    session_ids.append(session_id)
            if int(cursor) == 0:
                break
        legacy_session_id = redis_optional_text(
            await redis.get(channel_key),
            field="legacy screen share channel member",
        )
        if legacy_session_id:
            session_ids.append(legacy_session_id)

        sessions: list[dict[str, Any]] = []
        for session_id in dict.fromkeys(session_ids):
            raw = await redis.get(_session_key(session_id))
            if raw is None:
                continue
            session = self._session_payload(
                raw,
                field="screen share channel session",
                key=_session_key(session_id),
            )
            if session is not None:
                sessions.append(session)
        sessions.sort(
            key=lambda item: redis_int(
                item.get("created_at") or 0,
                field="screen share creation timestamp",
            )
        )
        return sessions

    async def expire_stale(
        self,
        *,
        heartbeat_timeout: int = _HEARTBEAT_TIMEOUT_SECONDS,
    ) -> list[dict[str, Any]]:
        redis = await self._redis()
        cursor = 0
        expired: list[dict[str, Any]] = []
        now = int(time.time())
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"{_PREFIX}:session:*", count=100)
            for key in keys:
                raw = await redis.get(key)
                if raw is None:
                    continue
                session = self._session_payload(
                    raw,
                    field="screen share session",
                    key=key,
                )
                if session is None:
                    continue
                if session.get("status") != "active":
                    continue
                expires_at = redis_int(
                    session.get("expires_at") or 0,
                    field="screen share expiration",
                )
                if expires_at and now >= expires_at:
                    expired.append(await self.stop(session, reason="session_expired"))
                    continue
                last = redis_int(
                    session.get("last_heartbeat") or session.get("ready_at") or 0,
                    field="screen share heartbeat timestamp",
                )
                if last and now - last > heartbeat_timeout:
                    expired.append(await self.stop(session, reason="heartbeat_timeout"))
            if int(cursor) == 0:
                break
        return expired


_service: ScreenShareService | None = None


def get_screen_share_service() -> ScreenShareService:
    global _service
    if _service is None:
        _service = ScreenShareService()
    return _service
