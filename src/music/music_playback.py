"""音乐播放执行逻辑 — IP 检测、Web 播放器链接、Agora 推流、自动播放监控。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from config import WEB_PLAYER_CONFIG
from core.database import SongCache, Statistics
from core.http_constants import HTTP_TIMEOUT_PROBE
from core.logger_config import get_logger
from domain.playback import PlaybackSessionSnapshot
from web.web_link_token import ensure_token

if TYPE_CHECKING:
    from core.queue_manager import QueueManager
    from music.music_platform import PlatformRegistry

logger = get_logger("MusicPlayback")

_AUTO_PLAY_CHECK_INTERVAL = 10
_PLAY_FADE_DELAY = 5
_DEFAULT_PLAY_DURATION = 300

_resolved_web_url: str | None = None


def reset_web_player_url_cache() -> None:
    global _resolved_web_url
    _resolved_web_url = None


try:
    from web.web_player_config import on_config_refresh
    on_config_refresh(reset_web_player_url_cache)
except ImportError:
    pass


def _get_web_player_url() -> str:
    """获取 Web 播放器 URL，自动检测 IP（公网优先，回退内网）"""
    global _resolved_web_url
    if _resolved_web_url is not None:
        return _resolved_web_url

    url = WEB_PLAYER_CONFIG.get("url", "")
    if url:
        parsed = urlparse(str(url).strip())
        host = (parsed.hostname or "").strip().lower()
        if host in ("0.0.0.0", "::"):
            logger.warning("WEB_PLAYER_CONFIG.url 配置为监听地址 %s，已忽略并改为自动检测", host)
        else:
            _resolved_web_url = str(url).rstrip("/")
            return _resolved_web_url

    port = WEB_PLAYER_CONFIG.get("port", 8080)
    ip = _detect_ip()
    if ip:
        host_part = f"[{ip}]" if ":" in ip else ip
        _resolved_web_url = f"http://{host_part}:{port}"
        logger.info(f"Web 播放器地址自动检测: {_resolved_web_url}")
        return _resolved_web_url
    # 检测失败时不缓存空字符串，避免网络短暂不可用后永久拿不到链接
    return ""


def _detect_ip() -> str:
    """检测本机 IP：优先公网 IPv4（与 Web 仅监听 IPv4 一致），回退公网 IPv6、内网"""
    import socket
    import urllib.request

    def _query(url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_PROBE) as resp:
                return resp.read().decode().strip()
        except Exception as e:
            logger.debug(f"IP 探测服务请求失败 ({url}): {e}")
            return ""

    # 优先公网 IPv4（Web 仅用 IPv4，链接也优先给 IPv4 便于外网访问）
    for svc in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        ip = _query(svc)
        if ip and ":" not in ip:
            return ip

    # 回退公网 IPv6
    for svc in ("https://api6.ipify.org", "https://ipv6.icanhazip.com"):
        ip = _query(svc)
        if ip:
            return ip

    # 回退内网 IPv4
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip
        finally:
            s.close()
    except Exception as e:
        logger.debug(f"内网 IPv4 探测失败: {e}")

    # 回退内网 IPv6
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        try:
            s.connect(("2001:4860:4860::8888", 80))
            ip = s.getsockname()[0]
            return ip
        finally:
            s.close()
    except Exception as e:
        logger.debug(f"内网 IPv6 探测失败: {e}")
    return ""


async def _web_player_link(redis_client=None) -> str:
    """生成 Markdown 格式的 Web 播放器跳转链接"""
    url = _get_web_player_url()
    if not url:
        return ""
    try:
        token_ttl = int(WEB_PLAYER_CONFIG.get("token_ttl_seconds", 86400) or 0)
    except (TypeError, ValueError):
        token_ttl = 86400
        logger.warning("WEB_PLAYER_CONFIG.token_ttl_seconds 非法，已回退为 86400 秒")
    token = await ensure_token(redis_client=redis_client, ttl_seconds=token_ttl)
    if token:
        return f"[▶ 网页播放器]({url}/w/{token})"
    return f"[▶ 网页播放器]({url})"


class PlaybackMixin:
    """播放相关逻辑的 Mixin，供 MusicHandler 等使用"""

    if TYPE_CHECKING:
        voice: Any
        sender: Any
        platforms: PlatformRegistry
        netease: Any
        _playback_lock: asyncio.Lock
        _voice_channel_id: str | None
        _voice_channel_area: str | None
        _voice_enter_time: float
        _play_start_time: float
        _play_duration: float

        def _create_task(self, awaitable: Any, *, name: str) -> asyncio.Task[Any]: ...

        @property
        def queue(self) -> QueueManager: ...

        def _get_queue(self, area: str) -> QueueManager: ...

        def _resolve_background_area(self) -> str: ...

        async def _mark_web_active_area(
            self,
            area: str = "",
            queue: QueueManager | None = None,
        ) -> None: ...

        async def _get_web_link(self, area: str = "", *, mark_active: bool = True) -> str: ...

        async def _leave_current_voice_channel(self) -> None: ...

        async def _release_web_link_if_needed(self, queue: QueueManager | None = None) -> None: ...

        def _playback_snapshot_locked(self) -> PlaybackSessionSnapshot: ...

        def _playback_snapshot_is_current_locked(
            self,
            snapshot: PlaybackSessionSnapshot,
        ) -> bool: ...

        def _advance_playback_generation_locked(self) -> PlaybackSessionSnapshot: ...

        async def _dequeue_next_song(
            self,
            natural_end: bool,
            current_song: dict | None,
            queue: QueueManager,
        ) -> tuple[dict | None, str]: ...

    async def auto_play_monitor(self, stop_event: asyncio.Event | None = None) -> None:
        """定期检查播放状态，自动播放下一首（基于歌曲时长判断是否播完）"""
        if stop_event is None:
            candidate = getattr(self, "_service_stop_event", None)
            stop_event = candidate if isinstance(candidate, asyncio.Event) else asyncio.Event()
        while not stop_event.is_set():
            wait_seconds = _AUTO_PLAY_CHECK_INTERVAL
            # 本轮就要处理这次「播完」，先清掉标志；否则队列空时它一直置位，
            # 等待会立即返回，循环变成空转。
            ended = getattr(self.voice, "playback_ended", None)
            if isinstance(ended, asyncio.Event):
                ended.clear()
            try:
                area = self._resolve_background_area()
                if not area:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
                        return
                    except asyncio.TimeoutError:
                        continue
                    continue

                stream_song: dict | None = None
                stream_session: PlaybackSessionSnapshot | None = None
                record_song: dict | None = None
                record_channel = ""
                notify_song: dict | None = None
                notify_source = ""
                queue = None
                is_playing = False

                async with self._playback_lock:
                    session = self._playback_snapshot_locked()
                    if session.area is not None and session.area.value != area:
                        logger.debug(
                            "自动播放跳过已切换的域: resolved=%s current=%s generation=%d",
                            area[:8],
                            session.area.value[:8],
                            session.generation,
                        )
                        wait_seconds = _PLAY_FADE_DELAY
                    else:
                        queue = self._get_queue(area)
                        is_playing = await self._is_playing(queue=queue)

                    if queue is not None and not is_playing:
                        current = await queue.get_current()
                        finished_song = None

                        if current is not None:
                            logger.info("自动播放监控: 歌曲已播完，清理 current 状态")
                            finished_song = current
                            await queue.clear_current()
                            try:
                                await queue.clear_play_state()
                            except Exception as e:
                                logger.debug(f"自动播放监控清理 play_state 失败: {e}")
                            current = None
                            session = self._advance_playback_generation_locked()

                        queue_length = await queue.get_queue_length()
                        if (queue_length > 0 or finished_song is not None) and current is None:
                            if session.area is None or session.channel is None:
                                wait_seconds = 2
                            else:
                                next_song, source = await self._dequeue_next_song(
                                    natural_end=finished_song is not None,
                                    current_song=finished_song,
                                    queue=queue,
                                )
                                if next_song:
                                    if finished_song is None:
                                        session = self._advance_playback_generation_locked()
                                    ch = next_song.get("channel") or session.channel
                                    next_song["channel"] = ch
                                    next_song["area"] = area

                                    if not ch:
                                        logger.warning("自动播放: 未获取到消息频道，歌曲保留在队列")
                                        try:
                                            await (await queue.client()).lpush(
                                                queue._qkey(),
                                                json.dumps(next_song, ensure_ascii=False),
                                            )
                                        except Exception as e:
                                            logger.error(
                                                "自动播放回退入队失败，歌曲可能丢失: %s",
                                                e,
                                            )
                                        wait_seconds = 2
                                    else:
                                        next_song["play_uuid"] = str(uuid.uuid4())
                                        await self._mark_web_active_area(area, queue=queue)
                                        await self._start_playing(
                                            next_song.get("duration_ms", 0),
                                            area=area,
                                        )
                                        await queue.set_current(next_song)

                                        stream_song = next_song
                                        stream_session = session
                                        record_song = next_song
                                        record_channel = ch
                                        notify_song = next_song
                                        notify_source = source
                                        wait_seconds = _PLAY_FADE_DELAY
                                        logger.info("自动播放: %s", next_song.get("name"))

                        elif queue_length == 0 and current is None and session.channel:
                            grace = time.time() - self._voice_enter_time < 30
                            if not grace:
                                logger.info("队列已空，Bot 自动退出语音频道")
                                await self._leave_current_voice_channel()

                    if queue is not None:
                        await self._release_web_link_if_needed(queue=queue)

                if record_song is not None:
                    try:
                        await SongCache.record_play(
                            song_id=str(record_song.get("song_id") or ""),
                            platform=str(record_song.get("platform") or "netease"),
                            data=record_song,
                            channel_id=record_channel,
                            user_id=str(record_song.get("user") or ""),
                        )
                        await Statistics.update_today(
                            str(record_song.get("platform") or "netease"),
                            cache_hit=False,
                        )
                    except Exception:
                        logger.debug("记录自动播放历史失败", exc_info=True)
                if stream_song is not None and stream_session is not None:
                    self._start_stream_task(stream_song, stream_session)
                    await self._preload_next_song_if_any(queue=queue)
                if notify_song is not None and notify_source != "autoplay":
                    text = await self._build_now_playing_text("自动播放", notify_song)
                    await self.sender.send_message(
                        text=text,
                        attachments=notify_song.get("attachments", []),
                        channel=record_channel,
                        area=area,
                    )

            except Exception as e:
                logger.error(f"自动播放监控出错: {e}")
                wait_seconds = _PLAY_FADE_DELAY

            if await self._wait_next_check(stop_event, wait_seconds):
                return

    async def _wait_next_check(self, stop_event: asyncio.Event, timeout: float) -> bool:
        """等到下一轮检查，返回 True 表示收到停止信号。"""
        waiters = [asyncio.ensure_future(stop_event.wait())]
        ended = getattr(self.voice, "playback_ended", None)
        if isinstance(ended, asyncio.Event):
            waiters.append(asyncio.ensure_future(ended.wait()))
        try:
            await asyncio.wait(
                waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()
        return stop_event.is_set()

    async def _preload_next_song_if_any(self, queue=None):
        """若队列中还有下一首且带 URL，则后台预加载其音频，减少切歌卡顿。"""
        if not self.voice or not self.voice.available:
            return
        try:
            next_item = await (queue or self.queue).peek_next()
            if next_item and next_item.get("url"):
                self.voice.preload_audio(
                    next_item["url"],
                    headers=self._stream_request_headers(
                        str(next_item.get("platform") or "netease"),
                        str(next_item.get("song_id") or ""),
                    ),
                )
        except Exception as e:
            logger.debug(f"预加载下一首失败（忽略）: {e}")

    def _stream_request_headers(self, platform_name: str, song_id: str) -> dict[str, str] | None:
        """获取平台音频直链所需的非敏感请求头。"""
        platform = self.platforms.get(platform_name) if hasattr(self, "platforms") else None
        provider = getattr(platform, "get_stream_headers", None)
        if not callable(provider):
            return None
        headers = provider(song_id)
        if not isinstance(headers, dict):
            return None
        return {str(name): str(value) for name, value in headers.items() if value is not None}

    def _start_stream_task(
        self,
        song: dict,
        session: PlaybackSessionSnapshot,
    ) -> None:
        """只用不可变会话快照启动受监管的异步推流任务。"""
        self._create_task(
            self._stream_to_voice_channel(
                str(song["url"]),
                str(song.get("name") or "music"),
                session,
                str(song.get("song_id") or ""),
                str(song.get("platform") or "netease"),
            ),
            name=f"music-stream-{session.generation}",
        )

    async def _stream_to_voice_channel(
        self,
        url: str,
        name: str,
        session: PlaybackSessionSnapshot,
        song_id: str = "",
        platform_name: str = "netease",
    ) -> None:
        """后台任务：仅在捕获的播放会话仍有效时向 Agora 提交推流。"""
        if session.area is None:
            logger.warning("推流快照缺少播放域，已拒绝")
            return
        async with self._playback_lock:
            if not self._playback_snapshot_is_current_locked(session):
                logger.info(
                    "丢弃过期推流任务: area=%s generation=%d",
                    session.area.value[:8],
                    session.generation,
                )
                return
            q = self._get_queue(session.area.value)
            voice = self.voice
            if not voice or not voice.available or session.channel is None:
                logger.warning("语音频道未连接，无法推流")
                self._play_start_time = 0
                self._play_duration = 0
                await q.clear_current()
                try:
                    await q.clear_play_state()
                except Exception as e:
                    logger.debug(f"推流前清理 play_state 失败: {e}")
                return

        async def _on_audio_started():
            async with self._playback_lock:
                if not self._playback_snapshot_is_current_locked(session):
                    return
                self._play_start_time = time.time()
                try:
                    await q.set_play_state({
                        "start_time": self._play_start_time,
                        "duration": self._play_duration,
                        "loading": False,
                    })
                    logger.info(f"音频实际开始播放，已校准 start_time: {name}")
                except Exception as e:
                    logger.debug(f"校准 start_time 写入 Redis 失败: {e}")

        stream_headers = self._stream_request_headers(platform_name, song_id)
        try:
            async with self._playback_lock:
                if not self._playback_snapshot_is_current_locked(session):
                    return
            await voice.play_audio(
                url,
                on_started=_on_audio_started,
                headers=stream_headers,
                prefer_remote=platform_name == "netease",
            )
            logger.info(f"已提交 Agora 推流任务: {name}")
            return
        except Exception as e:
            if song_id:
                logger.info(f"推流失败，尝试重新获取音频URL: {name}")
                try:
                    p = (
                        self.platforms.get(platform_name)
                        if hasattr(self, "platforms")
                        else None
                    )
                    refetch = p or self.netease
                    new_url = await refetch.get_song_url(song_id)
                    if new_url:
                        async with self._playback_lock:
                            if not self._playback_snapshot_is_current_locked(session):
                                return
                        await voice.play_audio(
                            new_url,
                            on_started=_on_audio_started,
                            headers=stream_headers,
                            prefer_remote=platform_name == "netease",
                        )
                        logger.info(f"重新获取URL后推流成功: {name}")
                        return
                except Exception as inner_e:
                    logger.debug(f"重新获取音频 URL 失败: {inner_e}")
            logger.warning(f"Agora 推流失败: {e}")

            async with self._playback_lock:
                if not self._playback_snapshot_is_current_locked(session):
                    return
                self._play_start_time = 0
                self._play_duration = 0
                await q.clear_current()
                try:
                    await q.clear_play_state()
                except Exception as clear_e:
                    logger.debug(f"推流失败后清理 play_state 失败: {clear_e}")

    async def _start_playing(self, duration_ms: int, area: str | None = None):
        """记录播放开始时间和时长，同步到 Redis 供 Web 播放器读取"""
        self._play_start_time = time.time()
        self._play_duration = duration_ms / 1000 if duration_ms else _DEFAULT_PLAY_DURATION
        try:
            q = self._get_queue(area) if area is not None else self.queue
            await q.set_play_state({
                "start_time": self._play_start_time,
                "duration": self._play_duration,
                "loading": True,
            })
        except Exception as e:
            logger.debug(f"写入 play_state 到 Redis 失败: {e}")

    async def _is_playing(self, queue=None) -> bool:
        """根据时间判断当前歌曲是否还在播放（暂停状态也算播放中）"""
        if self._play_start_time <= 0:
            return False
        try:
            ps = await (queue or self.queue).get_play_state()
            if ps:
                if ps.get("paused"):
                    return True
                if ps.get("loading") is True:
                    elapsed = time.time() - self._play_start_time
                    return elapsed < self._play_duration
        except Exception as e:
            logger.debug(f"读取 play_state 失败，按时间判定播放状态: {e}")
        voice_state = None
        try:
            if self.voice and self.voice.available and self._voice_channel_id:
                voice_state = self.voice.is_playing
        except Exception as e:
            logger.debug(f"读取语音推流状态失败，回退时间判定: {e}")
        if voice_state is True:
            return True
        if voice_state is False:
            return False
        elapsed = time.time() - self._play_start_time
        return elapsed < self._play_duration

    async def _build_now_playing_text(self, prefix: str, song_data: dict) -> str:
        """构建"正在播放"消息文本"""
        platform_name = {
            "netease": "网易云",
            "qq": "QQ音乐",
            "bilibili": "B站",
        }.get(str(song_data.get("platform") or ""), "未知")

        text = f"{prefix}:\n来自于{platform_name}:\n"
        text += f"歌曲: {song_data['name']}\n"
        text += f"歌手: {song_data.get('artists', '未知')}\n"

        if song_data.get("album"):
            text += f"专辑: {song_data['album']}\n"
        if song_data.get("duration"):
            text += f"时长: {song_data['duration']}\n"

        # 播放提交时已经在锁内更新活跃域；通知可能在离锁后才生成。旧播放通知
        # 只能生成链接，不能把并发切换后的新活跃域覆盖回去。
        link = await self._get_web_link(
            area=str(song_data.get("area") or ""),
            mark_active=False,
        )
        if link:
            text += link

        attachments = song_data.get("attachments", [])
        if attachments:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        return text.rstrip()
