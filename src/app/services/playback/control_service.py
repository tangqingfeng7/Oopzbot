from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from core.queue_manager import (
    atomic_enqueue_song_and_notify,
    atomic_queue_move_to_front,
    atomic_queue_remove_at,
)
from core.redis_keys import (
    PLAY_MODE,
    QUEUE,
    VOLUME,
    WEB_COMMANDS,
    area_key,
)
from core.redis_protocol import PlaybackCommandStore
from domain.playback import (
    AreaAction,
    AreaId,
    AreaWebCommand,
    GlobalWebCommand,
    encode_web_command,
)

from .area_resolution import PlaybackAreaUnavailable

_AREA_COMMAND_ACTIONS = frozenset({"next", "stop", "pause", "resume", "seek"})
_AREA_DIRECT_ACTIONS = frozenset({"clear", "mode"})
_VALID_PLAY_MODES = frozenset({"list", "single", "shuffle", "stop"})


def _sanitize_cover_url(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return text


def playback_area_unavailable_result() -> dict[str, object]:
    return {
        "ok": False,
        "code": PlaybackAreaUnavailable.code,
        "error": PlaybackAreaUnavailable.message,
    }


class PlaybackControlService:
    """统一承载播放控制、队列原子变更和 Web 点歌。"""

    def __init__(
        self,
        redis_client: PlaybackCommandStore,
        *,
        redis_provider: Callable[[], Awaitable[PlaybackCommandStore]] | None = None,
        platform_resolver: Callable[[str], Any] | None = None,
        default_volume: int = 50,
    ) -> None:
        async def _fixed_client() -> PlaybackCommandStore:
            return redis_client

        # provider 统一为异步：未显式提供时退化为返回构造时传入的客户端。
        self._redis_provider = redis_provider or _fixed_client
        self._platform_resolver = platform_resolver
        self._default_volume = max(0, min(100, int(default_volume)))

    @staticmethod
    def _area(value: str) -> AreaId | None:
        normalized = str(value or "").strip()
        return AreaId(normalized) if normalized else None

    async def control(
        self,
        *,
        action: str,
        payload: Mapping[str, object],
        area: str = "",
    ) -> dict[str, object]:
        """提交一项播放控制；只有音量允许不带域。"""
        normalized_action = str(action or "").strip()
        redis_client = await self._redis_provider()
        if normalized_action == "volume":
            volume = self._normalize_volume(payload.get("value"))
            await redis_client.set(VOLUME, str(volume))
            await self._push(
                GlobalWebCommand("volume", {"value": volume}),
                redis_client=redis_client,
            )
            return {"ok": True, "volume": volume}

        if normalized_action not in _AREA_COMMAND_ACTIONS | _AREA_DIRECT_ACTIONS:
            return {"ok": False, "error": f"未知操作: {normalized_action}"}

        area_id = self._area(area)
        if area_id is None:
            return playback_area_unavailable_result()

        if normalized_action == "clear":
            await redis_client.delete(area_key(QUEUE, area_id.value))
            return {"ok": True}
        if normalized_action == "mode":
            mode = payload.get("value") or payload.get("mode")
            if not isinstance(mode, str) or mode not in _VALID_PLAY_MODES:
                return {"ok": False, "error": f"未知播放模式: {mode}"}
            await redis_client.set(area_key(PLAY_MODE, area_id.value), mode)
            return {"ok": True, "mode": mode}

        command_payload: dict[str, object] = {}
        if normalized_action == "seek":
            command_payload = {"time": payload.get("time", 0)}
        try:
            command = AreaWebCommand(
                area_id,
                cast(AreaAction, normalized_action),
                command_payload,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        await self._push(command, redis_client=redis_client)
        return {"ok": True}

    async def mutate_queue(
        self,
        *,
        action: str,
        index: object,
        area: str,
    ) -> dict[str, object]:
        """原子删除队列项或将队列项置顶。"""
        if action not in {"remove", "top"}:
            return {"ok": False, "error": f"未知操作: {action}"}
        if isinstance(index, bool) or not isinstance(index, int):
            return {"ok": False, "error": "索引无效"}
        parsed_index = index

        area_id = self._area(area)
        if area_id is None:
            return playback_area_unavailable_result()
        key = area_key(QUEUE, area_id.value)
        mutation = atomic_queue_remove_at if action == "remove" else atomic_queue_move_to_front
        if not await mutation(await self._redis_provider(), key, parsed_index):
            return {"ok": False, "error": "索引无效"}
        return {"ok": True}

    async def add_song(
        self,
        *,
        body: Mapping[str, object],
        area: str,
    ) -> dict[str, object]:
        """解析歌曲、写入域队列并提交类型化通知命令。"""
        area_id = self._area(area)
        if area_id is None:
            return playback_area_unavailable_result()
        if self._platform_resolver is None:
            raise RuntimeError("播放控制服务未配置音乐平台解析器")

        song_id = body.get("id")
        if not song_id:
            return {"ok": False, "error": "缺少歌曲 ID"}
        platform_name = str(body.get("platform") or "netease")
        platform = self._platform_resolver(platform_name)
        name = str(body.get("name") or "")
        artists = str(body.get("artists") or "")
        album = str(body.get("album") or "")
        cover = _sanitize_cover_url(body.get("cover"))
        duration_ms = body.get("duration", 0)
        duration_text = str(body.get("durationText") or "")
        try:
            url = await platform.get_song_url(
                song_id,
                expected_duration_ms=duration_ms or 0,
                song_name=name,
            )
        except TypeError:
            url = await platform.get_song_url(song_id)
        if not url:
            detail = (
                getattr(platform, "last_song_url_error", "")
                or "无法获取播放链接，可能需要 VIP"
            )
            return {"ok": False, "error": detail}

        song_data = {
            "platform": platform_name,
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
            "area": area_id.value,
            "user": "web",
        }
        # 平台解析可能包含数秒网络请求；期间全局 Redis 可能已从内存降级恢复。
        # 真正提交前再取一次客户端，并让队列与通知使用同一实例，避免把成功
        # 响应对应的数据写进已经退役的 fallback。
        redis_client = await self._redis_provider()
        queue_key = area_key(QUEUE, area_id.value)
        # 队列顺序、1-based 位置与通知顺序必须来自同一个原子提交：
        # 真实 Redis 走 Lua，内存 fallback 走单一 Condition 临界区。
        notification_template = encode_web_command(
            AreaWebCommand(
                area_id,
                "notify",
                {
                    "name": name,
                    "artists": artists,
                    "position": 0,
                },
            )
        )
        queue_length = await atomic_enqueue_song_and_notify(
            redis_client,
            queue_key,
            json.dumps(song_data, ensure_ascii=False),
            WEB_COMMANDS,
            notification_template,
        )
        return {"ok": True, "position": queue_length, "name": name}

    @staticmethod
    async def _push(
        command: AreaWebCommand | GlobalWebCommand,
        *,
        redis_client: PlaybackCommandStore,
    ) -> None:
        await redis_client.rpush(WEB_COMMANDS, encode_web_command(command))

    def _normalize_volume(self, raw: object) -> int:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            return self._default_volume
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = self._default_volume
        return max(0, min(100, value))


__all__ = [
    "PlaybackControlService",
    "playback_area_unavailable_result",
]
