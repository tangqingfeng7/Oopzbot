from __future__ import annotations

import asyncio
import contextlib
import copy
import random
import threading
import time
import uuid
from typing import Any, Protocol, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.playback import PlaybackAreaResolver
from config import OOPZ_CONFIG, WEB_PLAYER_CONFIG
from core.database import ImageCache, SongCache, Statistics
from core.logger_config import get_logger
from core.queue_manager import QueueManager, get_redis_client
from core.redis_keys import (
    VOLUME as KEY_VOLUME,
)
from core.redis_keys import (
    WEB_COMMANDS as KEY_WEB_COMMANDS,
)
from core.redis_keys import (
    decode_web_command,
)
from core.redis_protocol import redis_int
from domain.playback import (
    AreaId,
    AreaWebCommand,
    GlobalWebCommand,
    PlaybackSessionSnapshot,
    WebCommandDecodeError,
)
from music.music_platform import PlatformRegistry
from music.music_playback import (
    PlaybackMixin,
    _web_player_link,
    reset_web_player_url_cache,  # noqa: F401 — re-export
)
from music.music_web_control import WebControlExecutor
from music.netease import NeteaseCloud
from oopz.name_resolver import NameResolver
from oopz.sdk_gateway import AsyncOopzGateway
from web.web_link_token import (
    clear_token,
    get_active_area,
    get_token,
    seconds_since_access,
    set_active_area,
)

logger = get_logger("Music")

_LIKED_PER_PAGE = 20
_PLATFORM_NETEASE = "netease"
PLAY_MODE_LIST = "list"
PLAY_MODE_SINGLE = "single"
PLAY_MODE_SHUFFLE = "shuffle"
PLAY_MODE_STOP = "stop"
# autoplay 不再作为可选播放模式，仅作为「队列播完按配置自动续播」时的来源标识。
PLAY_MODE_AUTOPLAY = "autoplay"
_VALID_PLAY_MODES = {
    PLAY_MODE_LIST,
    PLAY_MODE_SINGLE,
    PLAY_MODE_SHUFFLE,
    PLAY_MODE_STOP,
}


class _NeteaseSongUrlProvider(Protocol):
    async def get_song_url(
        self,
        song_id: int,
        expected_duration_ms: int = 0,
        song_name: str = "",
    ) -> str | None: ...


_PLATFORM_PREFIX_MAP = {
    "qq:": "qq",
    "QQ:": "qq",
    "qq\uff1a": "qq",
    "QQ\uff1a": "qq",
    "b\u7ad9:": "bilibili",
    "B\u7ad9:": "bilibili",
    "bili:": "bilibili",
    "BILI:": "bilibili",
    "b\u7ad9\uff1a": "bilibili",
    "B\u7ad9\uff1a": "bilibili",
    "bili\uff1a": "bilibili",
    "\u7f51\u6613:": "netease",
    "\u7f51\u6613\uff1a": "netease",
    "netease:": "netease",
    "netease\uff1a": "netease",
}


def parse_platform_prefix(keyword: str) -> tuple[str, str]:
    """从关键词中解析平台前缀，返回 (platform, clean_keyword)。"""
    for prefix, platform in _PLATFORM_PREFIX_MAP.items():
        if keyword.startswith(prefix):
            return platform, keyword[len(prefix):].strip()
    return "", keyword


def _music_auto_play_enabled() -> bool:
    try:
        from web.web_player_config import MUSIC_CONFIG
        return bool(MUSIC_CONFIG.get("auto_play_enabled", True))
    except Exception:
        return True


class MusicHandler(PlaybackMixin):
    """音乐功能处理器。
    队列按域隔离，每个域拥有独立的 QueueManager。
    语音连接同一时刻只有一个（Agora 限制），通过 _voice_channel_area 标识当前所在域。"""

    def __init__(
        self,
        sender: AsyncOopzGateway,
        voice: Any | None = None,
        supervisor=None,
    ):
        self.supports_interactive_selection = True
        self.sender = sender
        self.voice = voice
        self._supervisor = supervisor
        self.netease = NeteaseCloud()
        self._queue_cache: dict[str, QueueManager] = {}
        self.names = NameResolver()
        self._playback_lock = asyncio.Lock()
        self._voice_lock = asyncio.Lock()
        self._playback_generation = 0
        self._service_stop_event = asyncio.Event()
        self._auto_play_task: asyncio.Task[None] | None = None
        self._web_command_task: asyncio.Task[None] | None = None
        self._background_area_cache: tuple[str, float] = ("", 0.0)
        self._liked_cache: list = []
        self._liked_ids_cache: list = []
        self._play_start_time: float = 0
        self._play_duration: float = 0
        self._voice_channel_id: str | None = None
        self._voice_channel_area: str | None = None
        self._voice_enter_time: float = 0
        self._playlist_idle_since: float = 0
        self._web_link_released_due_to_idle: bool = False
        self._web_control = WebControlExecutor(self)
        self.platforms = PlatformRegistry()
        self.platforms.register(self.netease)
        self._init_extra_platforms()

        # 登录账号"我喜欢的音乐"本地搜索索引：/bf 时优先在这里命中，
        # 命中可省一次 cloudsearch 且更贴近用户口味。索引在后台懒加载，
        # 不阻塞启动；30 分钟过期后下一次 /bf 会触发后台刷新。
        self._liked_search_index: list[dict] = []
        self._liked_search_loaded_at: float = 0.0
        self._liked_search_loading: bool = False
        self._liked_search_lock = threading.Lock()
        self._liked_refresh_task: asyncio.Task[None] | None = self._create_task(
            self._refresh_liked_search_index(),
            name="music-liked-index-refresh",
        )

        # 封面下载+上传 side channel：首次播放某首歌时，封面没缓存
        # 需要 1-3s 的"下载封面 + 申请 OSS 签名 + 上传"同步阻塞；
        # 通过在搜索成功后立即后台预热，使其与 voice 加入/队列写入并行，
        # 真正发消息时直接取结果，能省掉这段串行延迟。
        # song_data 要进 Redis 不能塞 Event，故用 (platform, song_id)
        # 作 key 的进程内注册表承载 future。
        self._cover_prefetch: dict[str, asyncio.Task[tuple[list, int | None, bool]]] = {}
        # 活跃域由异步侧刷新，供同步的 queue 属性读取。
        self._active_area_cache: str = ""

    def _create_task(self, awaitable, *, name: str):
        if self._supervisor is not None:
            return self._supervisor.create(awaitable, name=name)
        return asyncio.create_task(awaitable, name=name)

    def _get_queue(self, area: str) -> QueueManager:
        """获取域隔离的 QueueManager（带缓存）。"""
        area = (area or "").strip()
        if not area:
            raise ValueError("播放域不能为空")
        if area not in self._queue_cache:
            self._queue_cache[area] = QueueManager(area=area)
        return self._queue_cache[area]

    def _resolve_background_area(self) -> str:
        """同步解析后台播放域：只读缓存与配置，不做任何 I/O。

        ``queue`` 是属性，无法 await，所以活跃域和已加入域都取异步侧刷新的缓存；
        需要真正探测时用 ``_resolve_background_area_async``。
        """
        cached_joined, cached_at = self._background_area_cache
        joined = cached_joined if cached_joined and time.monotonic() - cached_at < 300 else ""
        return PlaybackAreaResolver(
            active_area_reader=lambda: self._active_area_cache,
            default_area_reader=lambda: str(OOPZ_CONFIG.get("default_area") or ""),
            joined_area_reader=lambda: joined,
        ).admin().value

    async def _resolve_background_area_async(self) -> str:
        """解析后台播放域，并刷新供同步侧使用的缓存。"""
        try:
            self._active_area_cache = await get_active_area(
                redis_client=await get_redis_client()
            )
        except Exception:
            logger.debug("读取 Web 活跃域失败", exc_info=True)

        cached, cached_at = self._background_area_cache
        now = time.monotonic()
        if not cached or now - cached_at >= 300:
            try:
                areas = await self.sender.get_joined_areas(quiet=True)
                area = str((areas[0] if areas else {}).get("id") or "").strip()
                if area:
                    self._background_area_cache = (area, now)
            except Exception:
                logger.debug("后台播放域自动探测失败", exc_info=True)

        return self._resolve_background_area()

    @property
    def queue(self) -> QueueManager:
        """返回当前播放域队列；无域时明确拒绝，绝不落到全局播放键。"""
        area = self._voice_channel_area or self._resolve_background_area()
        if not area:
            from app.services.playback import PlaybackAreaUnavailable

            raise PlaybackAreaUnavailable(PlaybackAreaUnavailable.message)
        return self._get_queue(area)

    async def _mark_web_active_area(self, area: str = "", queue: QueueManager | None = None) -> None:
        """让 Web 播放器跟随当前真正播放的域。"""
        area = (area or "").strip()
        try:
            q = queue or self._get_queue(area)
            await set_active_area(area, redis_client=await q.client())
            self._active_area_cache = area
            self._web_link_released_due_to_idle = False
        except Exception as e:
            logger.debug(f"写入 Web 播放器活跃域失败: {e}")

    def _init_extra_platforms(self) -> None:
        """初始化并注册 QQ 音乐和 B 站平台（仅在配置启用时）。"""
        try:
            from music.qq_music import QQMusic
            qq = QQMusic()
            if qq.enabled:
                self.platforms.register(qq)
                logger.info("QQ 音乐平台已注册")
        except Exception as e:
            logger.debug("QQ 音乐平台初始化跳过: %s", e)
        try:
            from music.bilibili_music import BilibiliMusic
            bili = BilibiliMusic()
            if bili.enabled:
                self.platforms.register(bili)
                logger.info("B 站音乐平台已注册")
        except Exception as e:
            logger.debug("B 站音乐平台初始化跳过: %s", e)

    def refresh_platforms(self) -> dict:
        """后台配置变更后刷新平台实例，让新 Cookie 立即用于当前进程。"""
        self.netease = NeteaseCloud()
        self.platforms = PlatformRegistry()
        self.platforms.register(self.netease)
        self._init_extra_platforms()
        return {
            "available": True,
            "refreshed": True,
            "platforms": list(self.platforms.available.keys()),
        }

    async def _get_web_link(self, area: str = "", *, mark_active: bool = True) -> str:
        """获取 Web 播放器链接（按需生成随机访问令牌）。"""
        q = self._get_queue(area)
        # QueueManager 的取客户端入口是 async client()，旧的 `redis` 属性已不存在；
        # 用 getattr 兜底会恒得 None，令牌就退化成不带 Redis 的进程内版本。
        redis_client = await q.client()
        if mark_active:
            await self._mark_web_active_area(area, queue=q)
        link = await _web_player_link(redis_client=redis_client)
        if link:
            self._web_link_released_due_to_idle = False
        return link

    async def _release_web_link_if_needed(self, queue=None):
        """播放列表长时间空闲后，释放随机 Web 访问链接。"""
        timeout = int(WEB_PLAYER_CONFIG.get("link_idle_release_seconds", 1800) or 0)
        if timeout <= 0:
            self._playlist_idle_since = 0
            self._web_link_released_due_to_idle = False
            return

        q = queue
        if q is None:
            area = self._resolve_background_area()
            if not area:
                return
            q = self._get_queue(area)
        try:
            current = await q.get_current()
            queue_length = await q.get_queue_length()
        except Exception as e:
            logger.debug(f"读取播放队列状态失败，跳过链接释放检查: {e}")
            return

        if current is None and queue_length == 0 and not await self._is_playing(queue=q):
            if self._playlist_idle_since <= 0:
                self._playlist_idle_since = time.time()
                return
            if getattr(self, "_web_link_released_due_to_idle", False):
                return
            idle_for = time.time() - self._playlist_idle_since
            if idle_for >= timeout:
                try:
                    # 队列空不等于没人用：用户可能正开着页面搜歌、翻喜欢列表。
                    # 两个条件都满足才释放，否则会把活跃用户踢下线。
                    client = await q.client()
                    since_access = await seconds_since_access(redis_client=client)
                    if since_access < timeout:
                        logger.debug(
                            "播放列表空闲但播放器 %.0fs 前仍在使用，暂不释放链接", since_access
                        )
                        return
                    token = await get_token(redis_client=client)
                    if token:
                        await clear_token(redis_client=client)
                        logger.info("播放列表空闲超时且播放器无人使用，已释放 Web 访问链接令牌")
                except Exception as e:
                    logger.debug(f"释放 Web 播放器链接令牌失败: {e}")
                self._web_link_released_due_to_idle = True
        else:
            self._playlist_idle_since = 0
            self._web_link_released_due_to_idle = False

    # ------------------------------------------------------------------
    # 公共命令
    # ------------------------------------------------------------------

    async def _do_enter_voice(self, voice_channel_id: str, area: str) -> dict:
        """由 SDK Voice 完成 Oopz 进入、Agora 连接及失败回滚。"""
        if not self.voice or not self.voice.available:
            return {"error": "voice_unavailable"}
        async with self._voice_lock:
            from_channel = self._voice_channel_id or ""
            from_area = self._voice_channel_area or ""
            if self._voice_channel_id and (
                self._voice_channel_id != voice_channel_id
                or self._voice_channel_area != area
            ):
                await self._leave_current_voice_channel()
            if not self._voice_channel_id:
                await self._cleanup_stale_voice_membership(area)
            try:
                sign = await self.voice.join(
                    area=area,
                    channel=voice_channel_id,
                    from_area=from_area,
                    from_channel=from_channel,
                )
            except Exception as exc:
                logger.warning("Bot 进入语音频道失败: %s", exc)
                return {"error": str(exc)}
            self._voice_channel_id = voice_channel_id
            self._voice_channel_area = area
            self._playback_generation += 1
            self._voice_enter_time = time.time()
            await self._restore_volume_from_redis()
            logger.info("Bot 已进入语音频道: %s", self.names.channel(voice_channel_id))
            return {"status": True, "sign": sign}

    async def _check_and_enter_voice_channel(self, user: str, channel: str, area: str) -> bool:
        """
        检查用户是否在语音频道，若在则 Bot 进入该频道。
        若用户不在任何语音频道，发送提示并返回 False。
        若 Bot 正在其他频道播放，拒绝切换并提示。
        """
        if not self.voice or not self.voice.available:
            await self.sender.send_message(
                "语音推流功能未启用或初始化失败，无法播放音乐。",
                channel=channel, area=area,
            )
            return False

        voice_ch_id = await self.sender.get_voice_channel_for_user(user, area=area)
        if not voice_ch_id:
            await self.sender.send_message(
                "请先加入一个语音频道，Bot 会跟随你进入并放歌。",
                channel=channel, area=area,
            )
            return False

        if self._voice_channel_id == voice_ch_id and self._voice_channel_area == area:
            if await self._still_registered_in_voice(voice_ch_id, area):
                return True
            logger.info("服务端已不再把 bot 记为语音频道成员，重新进入")
            await self._leave_current_voice_channel()
        current_channel = self._voice_channel_id
        current_area = str(self._voice_channel_area or "").strip()
        if current_channel and (
            current_channel != voice_ch_id or current_area != area
        ):
            current_queue = self._get_queue(current_area) if current_area else None
            if current_queue is None or await self._is_playing(queue=current_queue):
                await self.sender.send_message(
                    f"Bot 正在 {self.names.channel(current_channel)} 播放中，请等播完或到该频道使用 /st 停止。",
                    channel=channel,
                    area=area,
                )
                return False
        data = await self._do_enter_voice(voice_ch_id, area)
        if "error" in data:
            await self.sender.send_message(
                f"进入语音频道失败: {data['error']}，请稍后再试。",
                channel=channel, area=area,
            )
            return False
        return True

    async def enter_voice_channel(self, voice_channel_id: str, area: str) -> dict:
        if not self.voice or not self.voice.available:
            return {"error": "voice_unavailable"}

        voice_channel_id = (voice_channel_id or "").strip()
        if not voice_channel_id:
            return {"error": "missing_channel"}

        return await self._do_enter_voice(voice_channel_id, area)

    async def _restore_volume_from_redis(self) -> None:
        """从 Redis 恢复用户上次设置的播放音量。

        浏览器进程重启或重新加入 Agora 房间后，agora_player.html 内的
        `_currentVolume` 会回到默认值。这里把 Redis 持久化的音量回灌到浏览器，
        避免用户每次重连后都得手动重新拉一遍音量条。
        """
        if not self.voice or not self.voice.available:
            return
        try:
            raw = await (await get_redis_client()).get(KEY_VOLUME)
        except Exception as e:
            logger.debug(f"读取 {KEY_VOLUME} 失败，跳过音量恢复: {e}")
            return
        if raw is None:
            return
        try:
            vol = redis_int(raw, field="播放音量")
        except (TypeError, ValueError):
            return
        vol = max(0, min(100, vol))
        try:
            await self.voice.set_volume(vol)
            logger.debug(f"已从 Redis 恢复播放音量: {vol}")
        except Exception as e:
            logger.debug(f"恢复音量失败: {e}")

    async def _cleanup_stale_voice_membership(self, area: str) -> None:
        """清理服务端残留的 bot 语音频道成员状态。

        bot 进程上次未正常退出时，服务端可能仍把 bot 挂在某个语音频道里。
        新一次 enter_channel 会被当作重复进入，不会广播"成员加入"事件，
        其他客户端因此看不到 bot。这里在进入前主动 leave 一次。
        """
        bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
        if not bot_uid:
            return
        try:
            stale_ch = await self.sender.get_voice_channel_for_user(bot_uid, area=area)
        except Exception as e:
            logger.debug(f"查询服务端残留语音状态失败，跳过清理: {e}")
            return
        if not stale_ch:
            return
        logger.info(f"检测到服务端残留: bot 仍登记在语音频道 {stale_ch}，先 leave 清理")
        try:
            await self.sender.leave_voice_channel(channel=stale_ch, area=area)
        except Exception as e:
            logger.warning(f"清理残留语音状态失败: {e}")

    async def _still_registered_in_voice(self, channel: str, area: str) -> bool:
        """确认服务端仍把 bot 记在这个语音频道里。

        Agora 只负责音频，Oopz 的频道成员身份是另一套，身份心跳走 Agora 信令
        并不维持它。成员身份掉了之后本地仍以为在频道里，就不会重新进入——
        表现就是听得到歌声、看不到 bot。查询失败按「仍在」处理，免得一次网络
        抖动引发无谓的退出重进。
        """
        bot_uid = (OOPZ_CONFIG.get("person_uid") or "").strip()
        if not bot_uid:
            return True
        try:
            actual = await self.sender.get_voice_channel_for_user_strict(bot_uid, area=area)
        except Exception as e:
            logger.debug("校验语音成员身份失败，按仍在频道处理: %s", e)
            return True
        return str(actual or "") == channel

    async def _leave_current_voice_channel(self) -> None:
        """退出 Bot 当前所在的语音频道。"""
        if not self._voice_channel_id:
            return

        # 在任何外部停止/退出动作前先使旧推流快照失效，避免回调在
        # leave 期间重新写回上一会话的状态。
        self._playback_generation = getattr(self, "_playback_generation", 0) + 1

        # 先断开 Agora RTC 连接
        if self.voice and self.voice.available:
            await self.voice.leave()

        logger.info("Bot 已退出语音频道: %s", self.names.channel(self._voice_channel_id))
        self._voice_channel_id = None
        self._voice_channel_area = None

    async def play_netease(self, keyword: str, channel: str, area: str, user: str) -> None:
        """搜索网易云并播放或加入队列"""
        await self.play_song(keyword, "netease", channel, area, user)

    async def search_candidates(self, keyword: str, platform: str = _PLATFORM_NETEASE, limit: int = 5) -> list[dict]:
        """返回歌曲候选列表，用于交互式选择。"""
        resolved_platform = platform or _PLATFORM_NETEASE
        p = self.platforms.get(resolved_platform)
        if not p:
            return []
        return await p.search_many(keyword, limit=max(1, min(limit, 10)))

    async def search_best_candidate(self, keyword: str, platform: str = _PLATFORM_NETEASE) -> dict | None:
        """快速搜索首条候选，用于 /bf 直播放歌的快速命中。

        netease 平台优先在登录账号"我喜欢的音乐"里搜，命中就用喜欢列表的那一首；
        没命中再退回到全网 cloudsearch。
        """
        resolved_platform = platform or _PLATFORM_NETEASE
        p = self.platforms.get(resolved_platform)
        if not p:
            return None
        if resolved_platform == _PLATFORM_NETEASE:
            try:
                liked_hit = await self._lookup_liked_song(keyword)
            except Exception as e:
                logger.debug("喜欢列表搜索异常 (%r): %s", keyword, e)
                liked_hit = None
            if liked_hit:
                logger.info(
                    "/bf 命中喜欢列表: keyword=%r → %s - %s (id=%s)",
                    keyword,
                    liked_hit.get("name"),
                    liked_hit.get("artists"),
                    liked_hit.get("id"),
                )
                return liked_hit
        try:
            return await p.search(keyword, limit=1)
        except Exception as e:
            logger.debug("快速搜索候选失败 (%s): %s", resolved_platform, e)
            return None

    @staticmethod
    def _build_song_data_from_platform_data(
        data: dict,
        platform: str,
        song_id,
        channel: str,
        area: str,
        user: str,
    ) -> dict:
        """把平台返回的歌曲信息统一转换为内部 song_data。"""
        duration_ms = data.get("duration", 0) or data.get("duration_ms", 0) or 0
        duration_text = data.get("durationText", "") or data.get("duration", "")
        return {
            "platform": platform,
            "song_id": str(data.get("id") or data.get("mid") or song_id),
            "name": data["name"],
            "artists": data["artists"],
            "album": data.get("album", ""),
            "url": data["url"],
            "cover": data.get("cover"),
            "duration": duration_text,
            "duration_ms": duration_ms,
            "attachments": [],
            "channel": channel,
            "area": area,
            "user": user,
        }

    async def play_song_choice(self, song: dict, channel: str, area: str, user: str) -> None:
        """播放用户从候选列表中选中的歌曲。"""
        platform = song.get("platform") or _PLATFORM_NETEASE
        p = self.platforms.get(platform)
        if not p:
            await self.sender.send_message(f"错误: 未知或未启用的音乐平台: {platform}", channel=channel, area=area)
            return
        song_id = song.get("id") or song.get("song_id") or song.get("mid")
        if not song_id:
            await self.sender.send_message("错误: 无法识别歌曲 ID", channel=channel, area=area)
            return

        data = None
        if song.get("url"):
            data = dict(song)
        elif song.get("name") and song.get("artists"):
            if platform == _PLATFORM_NETEASE:
                if isinstance(song_id, bool):
                    await self.sender.send_message(
                        "错误: 网易云歌曲 ID 无效",
                        channel=channel,
                        area=area,
                    )
                    return
                try:
                    netease_song_id = int(str(song_id))
                except ValueError:
                    await self.sender.send_message(
                        "错误: 网易云歌曲 ID 无效",
                        channel=channel,
                        area=area,
                    )
                    return
                raw_duration = song.get("duration_ms") or song.get("duration", 0)
                duration_ms = (
                    raw_duration
                    if isinstance(raw_duration, int) and not isinstance(raw_duration, bool)
                    else 0
                )
                url = await cast(_NeteaseSongUrlProvider, p).get_song_url(
                    netease_song_id,
                    expected_duration_ms=duration_ms,
                    song_name=str(song.get("name") or ""),
                )
            else:
                url = await p.get_song_url(song_id)
            if not url:
                detail = getattr(p, "last_song_url_error", "") or "无法获取播放链接"
                await self.sender.send_message(f"错误: {detail}", channel=channel, area=area)
                return
            data = dict(song)
            data["url"] = url
        else:
            result = await p.summarize_by_id(song_id)
            if result["code"] != "success":
                await self.sender.send_message(f"错误: {result['message']}", channel=channel, area=area)
                return
            data = result["data"]

        song_data = self._build_song_data_from_platform_data(data, platform, song_id, channel, area, user)
        self._kickoff_cover_prefetch(song_data)
        if not await self._check_and_enter_voice_channel(user, channel, area):
            return
        user_name = self.names.user(user) if user else "未知用户"
        result = await self._commit_song_request(song_data, prefix=f"{user_name} 从搜歌结果中选择了")
        await self.sender.send_message(text=result["message"], attachments=result.get("attachments", []), channel=channel, area=area)

    async def play_song(self, keyword: str, platform: str, channel: str, area: str, user: str) -> None:
        """通用的多平台点歌入口。"""
        voice_ok, result = await asyncio.gather(
            self._check_and_enter_voice_channel(user, channel, area),
            self._prepare_song_request(keyword, channel, area, user, platform=platform),
        )
        if result["code"] != "success":
            await self.sender.send_message(f"错误: {result['message']}", channel=channel, area=area)
            return

        if not voice_ok:
            return

        result = await self._commit_song_request(result["song_data"])

        text = result["message"]
        attachments = result.get("attachments", [])
        await self.sender.send_message(text=text, attachments=attachments, channel=channel, area=area)

    async def play_next(self, channel: str, area: str, user: str) -> None:
        """播放队列中的下一首"""
        async with self._playback_lock:
            session = self._playback_snapshot_locked()
            if session.area is None or session.channel is None:
                error = "Bot 当前不在语音频道，请先用 /bf 点歌或让 Bot 跟随进入语音频道。"
            elif session.area.value != str(area or "").strip():
                error = "Bot 当前正在其他域播放，已拒绝跨域切歌。"
            else:
                error = ""
            if error:
                await self.sender.send_message(error, channel=channel, area=area)
                return

            q = self._get_queue(area)
            next_song = await q.play_next()
            if not next_song:
                await self.sender.send_message("队列为空，没有下一首了", channel=channel, area=area)
                return

            next_song["channel"] = channel
            next_song["area"] = area

            session = self._advance_playback_generation_locked()
            if self.voice and self.voice.available:
                await self.voice.stop_audio()
            self._play_start_time = 0
            self._play_duration = 0

            play_uuid = str(uuid.uuid4())
            next_song["play_uuid"] = play_uuid
            await self._mark_web_active_area(area, queue=q)
            await self._start_playing(next_song.get("duration_ms", 0), area=area)
            await q.set_current(next_song)

            await SongCache.record_play(
                song_id=str(next_song.get("song_id") or ""),
                platform=str(next_song.get("platform") or _PLATFORM_NETEASE),
                data=next_song,
                channel_id=channel,
                user_id=user,
            )
            await Statistics.update_today(
                str(next_song.get("platform") or _PLATFORM_NETEASE),
                cache_hit=False,
            )

            self._start_stream_task(next_song, session)
            await self._preload_next_song_if_any(queue=q)

        text = await self._build_now_playing_text("切换到下一首", next_song)
        attachments = next_song.get("attachments", [])
        await self.sender.send_message(text=text, attachments=attachments, channel=channel, area=area)

    async def show_queue(self, channel: str, area: str) -> None:
        """显示当前队列"""
        q = self._get_queue(area)
        queue_list = await q.get_queue(0, 9)
        if queue_list:
            total = await q.get_queue_length()
            lines = [f"{i}. {s['name']} - {s.get('artists', '未知')}" for i, s in enumerate(queue_list, 1)]
            msg = "当前队列（前10首）:\n" + "\n".join(lines) + f"\n\n总计: {total} 首"
            await self.sender.send_message(msg, channel=channel, area=area)
        else:
            await self.sender.send_message("队列为空", channel=channel, area=area)

    async def show_liked_list(self, channel: str, area: str, page: int = 1) -> None:
        """显示喜欢的音乐列表（每页 20 首）"""
        uid = await self.netease.get_user_id()
        if not uid:
            await self.sender.send_message("无法获取网易云账号信息，请检查 Cookie 是否过期", channel=channel, area=area)
            return

        # 刷新缓存
        if not self._liked_ids_cache:
            self._liked_ids_cache = await self.netease.get_liked_ids(uid)

        if not self._liked_ids_cache:
            await self.sender.send_message("你的喜欢列表为空", channel=channel, area=area)
            return

        total = len(self._liked_ids_cache)
        per_page = _LIKED_PER_PAGE
        total_pages = (total + per_page - 1) // per_page
        page = max(1, min(page, total_pages))

        start = (page - 1) * per_page
        end = min(start + per_page, total)
        page_ids = self._liked_ids_cache[start:end]

        # 批量获取歌曲详情
        details = await self.netease.get_song_details_batch(page_ids)
        if not details:
            await self.sender.send_message("获取歌曲信息失败，请稍后再试", channel=channel, area=area)
            return

        # 缓存当前页供 play_liked_by_index 使用
        self._liked_cache = details

        lines = [f"喜欢的音乐 (第 {page}/{total_pages} 页，共 {total} 首):"]
        for i, song in enumerate(details, start + 1):
            lines.append(f"  {i}. {song['name']} - {song['artists']}  [{song['durationText']}]")

        lines.append("\n用法: /like play <编号> 播放指定歌曲")
        lines.append("      /like list <页码> 翻页")

        await self.sender.send_message("\n".join(lines), channel=channel, area=area)

    async def play_liked_by_index(self, index: int, channel: str, area: str, user: str) -> None:
        """通过列表编号播放喜欢的歌曲"""
        if not await self._check_and_enter_voice_channel(user, channel, area):
            return
        if not self._liked_ids_cache:
            await self.sender.send_message("请先使用 /like list 查看列表", channel=channel, area=area)
            return

        total = len(self._liked_ids_cache)
        if index < 1 or index > total:
            await self.sender.send_message(f"编号超出范围，请输入 1-{total}", channel=channel, area=area)
            return

        song_id = self._liked_ids_cache[index - 1]
        song_data = await self._fetch_netease_song_data(song_id, channel, area, user)
        if not song_data:
            await self.sender.send_message("获取歌曲失败，请稍后再试", channel=channel, area=area)
            return
        self._kickoff_cover_prefetch(song_data)

        user_name = self.names.user(user) if user else "未知用户"
        result = await self._commit_song_request(song_data, prefix=f"{user_name} 从喜欢列表点播了")
        await self.sender.send_message(
            text=result["message"],
            attachments=result.get("attachments", []),
            channel=channel,
            area=area,
        )

    async def play_liked(self, channel: str, area: str, user: str, count: int = 1) -> None:
        """从登录账号的喜欢列表中随机选歌播放"""
        if not await self._check_and_enter_voice_channel(user, channel, area):
            return
        uid = await self.netease.get_user_id()
        if not uid:
            await self.sender.send_message("无法获取网易云账号信息，请检查 Cookie 是否过期", channel=channel, area=area)
            return

        liked_ids = await self.netease.get_liked_ids(uid)
        if not liked_ids:
            await self.sender.send_message("你的喜欢列表为空", channel=channel, area=area)
            return

        count = min(count, 20, len(liked_ids))
        selected = random.sample(liked_ids, count)

        success_count = 0
        first_text = None
        first_attachments = []

        user_name = self.names.user(user) if user else "未知用户"
        prefix = f"{user_name} 随机播放了喜欢的音乐"

        for song_id in selected:
            song_data = await self._fetch_netease_song_data(song_id, channel, area, user)
            if not song_data:
                logger.warning(f"喜欢列表歌曲获取失败 (ID: {song_id})")
                continue

            if success_count == 0:
                self._kickoff_cover_prefetch(song_data)
                result = await self._commit_song_request(song_data, prefix=prefix)
                first_text = result["message"]
                first_attachments = result.get("attachments", [])
            else:
                await self._get_queue(area).add_to_queue(song_data)

            success_count += 1

        if success_count == 0:
            await self.sender.send_message("随机选歌失败，请稍后再试", channel=channel, area=area)
            return

        if first_text is None:
            raise RuntimeError("喜欢列表首首歌曲提交成功但未生成通知文本")
        if count > 1 and success_count > 1:
            first_text += f"\n(共 {success_count} 首已加入队列)"

        await self.sender.send_message(text=first_text, attachments=first_attachments, channel=channel, area=area)

    async def stop_play(self, channel: str, area: str) -> None:
        """停止播放并退出语音频道"""
        async with self._playback_lock:
            session = self._playback_snapshot_locked()
            if session.area is None or session.area.value != str(area or "").strip():
                await self.sender.send_message(
                    "Bot 当前未在该域播放，已拒绝跨域停止。",
                    channel=channel,
                    area=area,
                )
                return
            self._advance_playback_generation_locked()
            self._play_start_time = 0
            self._play_duration = 0
            q = self._get_queue(area)
            await q.clear_current()
            try:
                await q.clear_play_state()
            except Exception as e:
                logger.debug(f"停止播放时清理 play_state 失败: {e}")
            if self.voice and self.voice.available:
                await self.voice.stop_audio()
            await self._leave_current_voice_channel()
        await self.sender.send_message("已停止播放，Bot 已退出语音频道", channel=channel, area=area)

    async def get_play_mode(self, queue=None) -> str:
        """读取当前播放模式；未配置时默认列表循环。"""
        q = queue or self.queue
        mode = await q.get_play_mode() if hasattr(q, "get_play_mode") else None
        if mode not in _VALID_PLAY_MODES:
            mode = PLAY_MODE_LIST
            if hasattr(q, "set_play_mode"):
                await q.set_play_mode(mode)
        return mode

    async def set_play_mode(self, mode: str, queue=None) -> None:
        """设置播放模式。"""
        if mode not in _VALID_PLAY_MODES:
            raise ValueError(f"无效播放模式: {mode}")
        q = queue or self.queue
        if hasattr(q, "set_play_mode"):
            await q.set_play_mode(mode)

    async def _build_autoplay_song(self, current_song: dict | None) -> dict | None:
        uid = await self.netease.get_user_id()
        if not uid:
            return None
        if not self._liked_ids_cache:
            self._liked_ids_cache = await self.netease.get_liked_ids(uid)
        if not self._liked_ids_cache:
            return None
        song_id = random.choice(self._liked_ids_cache)
        result = await self.netease.summarize_by_id(song_id)
        if result["code"] != "success":
            return None
        data = result["data"]
        inherited = current_song or {}
        return {
            "platform": _PLATFORM_NETEASE,
            "song_id": str(song_id),
            "name": data["name"],
            "artists": data["artists"],
            "album": data.get("album", ""),
            "url": data["url"],
            "cover": data.get("cover"),
            "duration": data.get("durationText", ""),
            "duration_ms": data.get("duration", 0),
            "attachments": [],
            "channel": inherited.get("channel", ""),
            "area": inherited.get("area", ""),
            "user": inherited.get("user", ""),
        }

    _LIKED_SEARCH_TTL = 1800  # 30 分钟

    async def _refresh_liked_search_index(self) -> None:
        """后台刷新喜欢列表索引；失败静默回退到原有全网搜索。"""
        if self._liked_search_loading:
            return
        self._liked_search_loading = True
        try:
            uid = await self.netease.get_user_id()
            if not uid:
                logger.debug("未登录或获取 uid 失败，跳过喜欢列表索引加载")
                return
            details = await self.netease.get_all_liked_song_details(uid)
            if not details:
                logger.debug("喜欢列表为空或拉取失败，跳过索引加载")
                return
            with self._liked_search_lock:
                self._liked_search_index = details
                self._liked_search_loaded_at = time.time()
            logger.info(f"喜欢列表索引已加载: {len(details)} 首")
        except Exception as e:
            logger.warning(f"加载喜欢列表索引失败: {e}")
        finally:
            self._liked_search_loading = False

    @staticmethod
    def _match_liked_in(songs: list[dict], keyword: str) -> dict | None:
        """在给定歌曲列表里按 keyword 找最匹配的一首。

        匹配策略（按优先级降序）：
          1. 歌名完全相等（大小写/空白不敏感）
          2. 关键字是 "歌名" 的子串
          3. 关键字是 "歌名 - 歌手" 的子串
          4. 关键字按空格分词后全部命中 "歌名 + 歌手 + 专辑"
        多个候选优先取歌名长度更短的（更精确）。
        """
        if not keyword or not keyword.strip() or not songs:
            return None
        kw = keyword.strip().lower()
        kw_tokens = [t for t in kw.split() if t]

        exact: list[dict] = []
        prefix_name: list[dict] = []
        contains_full: list[dict] = []
        token_match: list[dict] = []
        for song in songs:
            name = (song.get("name") or "").strip().lower()
            artists = (song.get("artists") or "").strip().lower()
            album = (song.get("album") or "").strip().lower()
            if not name:
                continue
            if name == kw:
                exact.append(song)
                continue
            if kw in name:
                prefix_name.append(song)
                continue
            full = f"{name} - {artists}"
            if kw in full:
                contains_full.append(song)
                continue
            haystack = f"{name} {artists} {album}"
            if len(kw_tokens) > 1 and all(tok in haystack for tok in kw_tokens):
                token_match.append(song)

        for bucket in (exact, prefix_name, contains_full, token_match):
            if bucket:
                bucket.sort(key=lambda s: len(s.get("name") or ""))
                return bucket[0]
        return None

    async def _lookup_liked_song(self, keyword: str) -> dict | None:
        """在喜欢列表里找最匹配的一首；返回 None 表示未命中（外层走全网搜索）。

        - 先在本地 cache 里搜
        - 如果 miss，做一次"增量补漏"：拉最新 likelist 找出 cache 里没有的
          新增 ID，只对增量拉详情，再搜一次。这能覆盖用户启动 bot 后才
          点心的歌（cache 拍的是启动那一刻的快照）。
        """
        if not keyword or not keyword.strip():
            return None

        with self._liked_search_lock:
            index = list(self._liked_search_index)
            loaded_at = self._liked_search_loaded_at

        # 索引过期就后台补一次，但同一时刻只允许有一个刷新任务在跑
        index_is_stale = bool(loaded_at) and time.time() - loaded_at > self._LIKED_SEARCH_TTL
        refresh_idle = self._liked_refresh_task is None or self._liked_refresh_task.done()
        if index_is_stale and refresh_idle:
            self._liked_refresh_task = self._create_task(
                self._refresh_liked_search_index(),
                name="music-liked-index-refresh",
            )

        hit = self._match_liked_in(index, keyword)
        if hit:
            return hit

        if not index:
            logger.debug("/bf 喜欢列表索引尚未就绪，跳过喜欢列表搜索")
            return None

        # 增量补漏：cache miss 时检查是否有新增 ID 可补
        return await self._lookup_in_new_liked(keyword, {s.get("id") for s in index if s.get("id")})

    _NEW_LIKED_PROBE_LIMIT = 200

    async def _lookup_in_new_liked(self, keyword: str, existing_ids: set) -> dict | None:
        """从 likelist 里找 cache 还没收录的新增 ID，按需拉详情匹配。"""
        try:
            uid = await self.netease.get_user_id()
            if not uid:
                return None
            all_ids = await self.netease.get_liked_ids(uid)
            new_ids = [i for i in all_ids if i not in existing_ids]
            if not new_ids:
                logger.debug(
                    "/bf 喜欢列表 miss 且无新增 ID，回退全网搜索: keyword=%r 索引大小=%d",
                    keyword, len(existing_ids),
                )
                return None
            # 仅拉前 N 条，避免一次 /bf 触发数百次 API
            probe = new_ids[: self._NEW_LIKED_PROBE_LIMIT]
            details: list[dict] = []
            for i in range(0, len(probe), 50):
                chunk = probe[i:i + 50]
                got = await self.netease.get_song_details_batch(chunk)
                if got:
                    details.extend(got)
            if not details:
                return None

            hit = self._match_liked_in(details, keyword)
            with self._liked_search_lock:
                self._liked_search_index.extend(details)
                if not self._liked_search_loaded_at:
                    self._liked_search_loaded_at = time.time()
            if hit:
                logger.info(
                    "/bf 喜欢列表增量补漏命中: 新增 %d 首 → %s - %s",
                    len(details), hit.get("name"), hit.get("artists"),
                )
            else:
                logger.debug(
                    "/bf 增量补漏后仍未命中: keyword=%r 新增 %d 首",
                    keyword, len(details),
                )
            return hit
        except Exception as e:
            logger.debug(f"增量喜欢列表查询失败: {e}")
            return None

    async def _dequeue_next_song(
        self,
        natural_end: bool,
        current_song: dict | None,
        queue=None,
    ) -> tuple[dict | None, str]:
        """根据播放模式决定下一首歌。"""
        q = queue or self.queue
        mode = await self.get_play_mode(queue=q)
        if natural_end and mode == PLAY_MODE_STOP and current_song is not None:
            await q.clear_queue()
            return None, PLAY_MODE_STOP
        if natural_end and mode == PLAY_MODE_SINGLE and current_song:
            return copy.deepcopy(current_song), PLAY_MODE_SINGLE
        if mode == PLAY_MODE_SHUFFLE and hasattr(q, "pop_random"):
            return await q.pop_random(), "queue"
        next_song = await q.play_next()
        if next_song:
            return next_song, "queue"
        if natural_end and mode == PLAY_MODE_LIST and _music_auto_play_enabled():
            return await self._build_autoplay_song(current_song), PLAY_MODE_AUTOPLAY
        return None, mode

    # ------------------------------------------------------------------
    # 自动播放监控（在 main.py 中作为后台线程启动）
    # ------------------------------------------------------------------

    async def start_auto_play_monitor(self) -> None:
        """幂等启动自动播放监控。"""
        if self._auto_play_task and not self._auto_play_task.done():
            return
        self._service_stop_event.clear()
        self._auto_play_task = self._create_task(
            self.auto_play_monitor(stop_event=self._service_stop_event),
            name="music-auto-play",
        )

    async def _update_play_state_redis(self, queue=None, **overrides):
        """更新 Redis 中的 play_state，支持暂停/恢复/跳转时的状态同步"""
        try:
            ps = {"start_time": self._play_start_time, "duration": self._play_duration}
            ps.update(overrides)
            await (queue or self.queue).set_play_state(ps)
        except Exception as e:
            logger.debug(f"更新 play_state 失败: {e}")

    async def start_web_command_listener(self) -> None:
        """启动可取消异步任务，通过 BLPOP 实时监听 Web 控制命令。"""
        if self._web_command_task and not self._web_command_task.done():
            return
        self._service_stop_event.clear()

        async def _listener() -> None:
            logger.info("Web 命令异步监听已启动 (BLPOP)")
            last_warn_at = 0.0
            while not self._service_stop_event.is_set():
                try:
                    result = await (await get_redis_client()).blpop(
                        KEY_WEB_COMMANDS,
                        timeout=1,
                    )
                    if result:
                        _, cmd_raw = result
                        await self._consume_web_command(cmd_raw)
                except Exception as e:
                    now = time.time()
                    if now - last_warn_at >= 30:
                        logger.warning(f"Web 命令监听异常（30s 节流）: {e}")
                        last_warn_at = now
                    else:
                        logger.debug(f"Web 命令监听异常（抑制告警）: {e}")
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._service_stop_event.wait(), timeout=1)

        self._web_command_task = self._create_task(
            _listener(),
            name="music-web-command",
        )

    async def stop(self, timeout: float = 5.0) -> None:
        """停止音乐后台服务；可重复调用。"""
        self._service_stop_event.set()
        tasks = [
            task
            for task in (self._auto_play_task, self._web_command_task, self._liked_refresh_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=max(0.0, timeout),
                )
            except asyncio.TimeoutError:
                logger.warning("音乐后台任务停止超时")
        self._auto_play_task = None
        self._web_command_task = None
        self._liked_refresh_task = None
        for task in tuple(self._cover_prefetch.values()):
            task.cancel()
        if self._cover_prefetch:
            await asyncio.gather(*self._cover_prefetch.values(), return_exceptions=True)
        self._cover_prefetch.clear()
        await self.platforms.close()
        if self.voice is not None:
            await self.voice.destroy(timeout=max(0.1, timeout))

    async def _consume_web_command(self, cmd_raw) -> bool:
        """解码一条 Web 控制命令并按域决定是否执行。返回是否执行了。

        从监听线程的循环体里抽出来，好让「跨域命令会被跳过」这件事能被直接测到 ——
        埋在 while 循环 + BLPOP 里的话，把域校验整段删掉测试也照样绿。
        """
        try:
            command = decode_web_command(cmd_raw)
        except WebCommandDecodeError as exc:
            raw = cmd_raw.decode(errors="replace") if isinstance(cmd_raw, bytes) else str(cmd_raw)
            logger.warning("丢弃无效 Web 控制命令 (%s): %s", exc, raw[:80])
            return False
        lock = getattr(self, "_playback_lock", None)
        if lock is None:
            lock = self._playback_lock = asyncio.Lock()
        async with lock:
            snapshot = self._playback_snapshot_locked()
            if not self._web_command_applies_here(command, snapshot=snapshot):
                area = command.area.value if isinstance(command, AreaWebCommand) else ""
                logger.info(
                    "跳过不适用于当前播放会话的 Web 控制命令: area=%s action=%s",
                    area[:8],
                    command.action,
                )
                return False
            queue = (
                self._get_queue(snapshot.area.value)
                if isinstance(command, AreaWebCommand) and snapshot.area is not None
                else None
            )
        return await self._execute_web_command(command, queue=queue)

    def _playback_snapshot_locked(self) -> PlaybackSessionSnapshot:
        """在持有 ``_playback_lock`` 时捕获完整播放会话。"""
        current = str(getattr(self, "_voice_channel_area", "") or "").strip()
        return PlaybackSessionSnapshot(
            area=AreaId(current) if current else None,
            channel=getattr(self, "_voice_channel_id", None),
            generation=int(getattr(self, "_playback_generation", 0)),
        )

    def _advance_playback_generation_locked(self) -> PlaybackSessionSnapshot:
        """使旧异步播放任务失效，并返回新播放意图的不可变快照。"""
        self._playback_generation = (
            int(getattr(self, "_playback_generation", 0)) + 1
        )
        return self._playback_snapshot_locked()

    def _playback_snapshot_is_current_locked(
        self,
        snapshot: PlaybackSessionSnapshot,
    ) -> bool:
        """调用方持有播放锁时，验证异步任务是否仍属于当前会话。"""
        return self._playback_snapshot_locked() == snapshot

    def _web_command_applies_here(
        self,
        command,
        snapshot: PlaybackSessionSnapshot | None = None,
    ) -> bool:
        """命令是否该由当前正在播放的域执行。

        命令队列是全局单键，Web 端按自己看到的那个域下发 —— 不校验的话，B 域
        视图上按「切歌」会把 A 域正在播的歌切掉。
        空域只允许全局音量命令；播放控制必须显式带域，且当前正在播放的域必须
        与之完全一致。
        """
        if isinstance(command, GlobalWebCommand):
            return command.action == "volume"
        if not isinstance(command, AreaWebCommand):
            return False
        if snapshot is None:
            current = str(getattr(self, "_voice_channel_area", "") or "").strip()
            snapshot = PlaybackSessionSnapshot(
                area=AreaId(current) if current else None,
                channel=getattr(self, "_voice_channel_id", None),
                generation=int(getattr(self, "_playback_generation", 0)),
            )
        if snapshot.area is None:
            return False
        return command.area == snapshot.area

    async def _execute_web_command(self, command, queue=None) -> bool:
        """执行单条 Web 控制命令"""
        # 兼容测试中 __new__ 构造未执行 __init__ 的场景
        if not hasattr(self, "_web_control") or self._web_control is None:
            self._web_control = WebControlExecutor(self)
        return await self._web_control.execute(command, queue=queue)


    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _fetch_netease_song_data(self, song_id: int, channel: str, area: str, user: str) -> dict | None:
        """通过歌曲 ID 获取详情并构建统一的 song_data 字典，失败返回 None。"""
        result = await self.netease.summarize_by_id(song_id)
        if result["code"] != "success":
            return None
        data = result["data"]
        return {
            "platform": _PLATFORM_NETEASE,
            "song_id": str(song_id),
            "name": data["name"],
            "artists": data["artists"],
            "album": data["album"],
            "url": data["url"],
            "cover": data.get("cover"),
            "duration": data["durationText"],
            "duration_ms": data.get("duration", 0),
            "attachments": [],
            "channel": channel,
            "area": area,
            "user": user,
        }

    async def _prepare_song_request(self, keyword: str, channel: str, area: str, user: str, platform: str = "") -> dict:
        """搜索歌曲并准备播放数据，但不提前进入语音频道。"""
        resolved_platform = platform or _PLATFORM_NETEASE
        p = self.platforms.get(resolved_platform)
        if not p:
            return {"code": "error", "message": f"未知或未启用的音乐平台: {resolved_platform}"}

        if resolved_platform == _PLATFORM_NETEASE:
            liked_hit = await self._lookup_liked_song(keyword)
            if liked_hit:
                summarized = await p.summarize_by_id(liked_hit["id"])
                if summarized["code"] == "success":
                    logger.info(
                        "/bf 命中喜欢列表: keyword=%r → %s - %s (id=%s)",
                        keyword,
                        summarized["data"].get("name"),
                        summarized["data"].get("artists"),
                        liked_hit["id"],
                    )
                    song_data = self._build_song_data_from_platform_data(
                        summarized["data"], resolved_platform, liked_hit["id"],
                        channel, area, user,
                    )
                    self._kickoff_cover_prefetch(song_data)
                    return {"code": "success", "song_data": song_data}
                logger.debug(
                    "喜欢列表命中但取详情失败，回退全网搜索: id=%s err=%s",
                    liked_hit["id"], summarized.get("message"),
                )

        search_result = await p.summarize(keyword)
        if search_result["code"] != "success":
            return search_result

        data = search_result["data"]
        song_data = self._build_song_data_from_platform_data(
            data,
            resolved_platform,
            keyword,
            channel,
            area,
            user,
        )
        self._kickoff_cover_prefetch(song_data)

        return {"code": "success", "song_data": song_data}

    _COVER_PREFETCH_TIMEOUT = 3.0
    _COVER_PREFETCH_TTL = 60.0
    _NETEASE_COVER_SIZE = "300y300"

    def _cover_prefetch_key(self, song_data: dict) -> str | None:
        cover = song_data.get("cover")
        song_id = song_data.get("song_id")
        if not cover or not song_id:
            return None
        platform = song_data.get("platform", _PLATFORM_NETEASE)
        return f"{platform}:{song_id}"

    def _kickoff_cover_prefetch(self, song_data: dict) -> None:
        """后台预热封面下载+上传。可重复调用，相同歌曲只会发起一次。"""
        key = self._cover_prefetch_key(song_data)
        if not key:
            return
        if not hasattr(self, "_cover_prefetch"):
            return
        snapshot = dict(song_data)
        if key in self._cover_prefetch:
            return

        async def _task():
            try:
                return await self._resolve_song_attachments(snapshot)
            except Exception as e:
                logger.debug("封面预热失败 (%s): %s", key, e)
                return ([], None, False)

        task = self._create_task(_task(), name=f"music-cover-{key}")
        self._cover_prefetch[key] = task
        self._create_task(
            self._purge_cover_prefetch_later(key, task),
            name=f"music-cover-purge-{key}",
        )

    async def _consume_cover_prefetch(self, song_data: dict):
        """若该歌曲有正在进行/已完成的封面预热，等结果并取走；否则返回 None。"""
        key = self._cover_prefetch_key(song_data)
        if not key:
            return None
        if not hasattr(self, "_cover_prefetch"):
            return None
        task = self._cover_prefetch.pop(key, None)
        if task is None:
            return None
        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self._COVER_PREFETCH_TIMEOUT,
            )
        except asyncio.TimeoutError:
            # wait_for 外面包了 shield，超时不会自动停掉原任务。
            # 如果返回 None，_commit_song_request 还会同步再上传一次，
            # 导致两个大图上传并行超时，点歌通知被阻塞一分钟以上。
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.debug("封面预热超时，已取消且不重复上传: %s", key)
            return ([], None, False)

    async def _purge_cover_prefetch_later(self, key: str, task: asyncio.Task) -> None:
        await asyncio.sleep(self._COVER_PREFETCH_TTL)
        if self._cover_prefetch.get(key) is task:
            self._cover_prefetch.pop(key, None)

    async def _resolve_song_attachments(self, song_data: dict) -> tuple[list, int | None, bool]:
        """在真正提交播放前再处理封面，避免失败请求也触发上传和写库。"""
        attachments = list(song_data.get("attachments", []))
        image_cache_id = None
        cache_hit = False
        song_id = song_data.get("song_id")
        cover = song_data.get("cover")
        platform = song_data.get("platform", _PLATFORM_NETEASE)

        if not cover or not song_id:
            return attachments, image_cache_id, cache_hit

        cached = await ImageCache.get_by_source(song_id, platform)
        if cached:
            attachments = [cached["attachment_data"]]
            image_cache_id = cached["id"]
            cache_hit = True
            await ImageCache.increment_use(song_id, platform)
            return attachments, image_cache_id, cache_hit

        upload_url = self._cover_upload_url(str(cover), str(platform))
        up = await self.sender.upload_file_from_url(upload_url)
        if up.get("code") == "success":
            att = up["data"]
            attachments = [att]
            image_cache_id = await ImageCache.save(song_id, platform, cover, att)
        return attachments, image_cache_id, cache_hit

    @classmethod
    def _cover_upload_url(cls, cover: str, platform: str) -> str:
        """网易云封面上传使用 CDN 缩略图，避免下载并上传数 MB 原图。"""
        if platform != _PLATFORM_NETEASE:
            return cover
        try:
            parsed = urlsplit(cover)
        except ValueError:
            return cover
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not (
            host == "music.126.net"
            or host.endswith(".music.126.net")
            or host == "music.163.com"
            or host.endswith(".music.163.com")
        ):
            return cover
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["param"] = cls._NETEASE_COVER_SIZE
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    async def _build_song_request_text(self, song_data: dict, prefix: str = "") -> str:
        """统一构建点歌通知文本。prefix 为空时使用默认的 'XXX 点播了' 格式。"""
        if not prefix:
            user_name = self.names.user(song_data.get("user", "")) if song_data.get("user") else "未知用户"
            prefix = f"{user_name} 点播了"

        platform_name = {
            "netease": "网易云",
            "qq": "QQ音乐",
            "bilibili": "B站",
        }.get(str(song_data.get("platform") or ""), "网易云")

        text = (
            f"{prefix}:\n"
            f"来自于{platform_name}:\n"
            f"歌曲: {song_data['name']}\n"
            f"歌手: {song_data['artists']}\n"
            f"专辑: {song_data['album']}\n"
            f"时长: {song_data['duration']}"
        )

        if bool(WEB_PLAYER_CONFIG.get("send_link_enabled", True)):
            # 提交阶段已经在播放锁内设置过 active area。封面处理可能耗时，
            # 此时旧请求生成通知链接绝不能在新会话开始后把 active area 写回旧域。
            link = await self._get_web_link(
                area=str(song_data.get("area") or ""),
                mark_active=False,
            )
            if link:
                text += f"\n{link}"

        attachments = song_data.get("attachments", [])
        if attachments:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text
        return text

    async def _commit_song_request(self, song_data: dict, prefix: str = "") -> dict:
        """将已准备好的歌曲请求正式提交为播放或排队。prefix 用于自定义通知前缀。"""
        song_data = dict(song_data)

        area = str(song_data.get("area") or "").strip()
        direct_play = False
        queue_position: int | None = None

        async with self._playback_lock:
            session = self._playback_snapshot_locked()
            if session.area is None or session.area.value != area:
                return {
                    "code": "playback_session_changed",
                    "message": "播放域已发生变化，本次点歌未提交，请重试。",
                    "attachments": [],
                }
            q = self._get_queue(area)
            await self._mark_web_active_area(area, queue=q)
            is_playing = await self._is_playing(queue=q)
            current_song = await q.get_current()
            queue_length = await q.get_queue_length()

            if not is_playing and current_song is not None:
                logger.info("检测到残留状态: 歌曲已播完但 current 存在, 自动清理")
                await q.clear_current()
                current_song = None
                session = self._advance_playback_generation_locked()

            if not is_playing and current_song is None and queue_length == 0:
                song_data = dict(song_data)
                play_uuid = str(uuid.uuid4())
                song_data["play_uuid"] = play_uuid
                session = self._advance_playback_generation_locked()
                await self._start_playing(song_data.get("duration_ms", 0), area=area)
                await q.set_current(song_data)

                self._start_stream_task(song_data, session)
                await self._preload_next_song_if_any(queue=q)
                direct_play = True
            else:
                queue_position = await q.add_to_queue(song_data)
                # 入队歌曲提前下载进 voice cache；/next 命中后会直接落临时文件，
                # 再由 agoraPlayAudio(file://...) 播放，省掉远程尝试和再次下载。
                await self._preload_next_song_if_any(queue=q)

        prefetched = await self._consume_cover_prefetch(song_data)
        if prefetched is not None:
            attachments, image_cache_id, cache_hit = prefetched
        else:
            attachments, image_cache_id, cache_hit = await self._resolve_song_attachments(song_data)
        song_data["attachments"] = attachments

        if direct_play:
            try:
                async with self._playback_lock:
                    if self._playback_snapshot_is_current_locked(session):
                        current = await q.get_current() or {}
                        if current.get("play_uuid") == song_data.get("play_uuid"):
                            await q.set_current(song_data)
            except Exception:
                pass
            await SongCache.record_play(
                str(song_data.get("song_id") or ""),
                str(song_data.get("platform") or _PLATFORM_NETEASE),
                song_data,
                image_cache_id,
                str(song_data.get("channel") or ""),
                str(song_data.get("user") or ""),
            )
            await Statistics.update_today(
                str(song_data.get("platform") or _PLATFORM_NETEASE),
                cache_hit,
            )
            text = await self._build_song_request_text(song_data, prefix=prefix)
        else:
            if queue_position is None:
                raise RuntimeError("歌曲未直接播放且未写入队列")
            actual = queue_position + 1 + (1 if current_song or is_playing else 0)
            text = await self._build_song_request_text(song_data, prefix=prefix) + f"\n已加入队列 (位置: {actual})"

        return {"code": "success", "message": text, "attachments": attachments}
