"""面向音乐业务的 Oopz-SDK 语音控制器。"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import OrderedDict
from collections.abc import Awaitable, Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from core.http_constants import HTTP_TIMEOUT_DOWNLOAD
from core.logger_config import get_logger
from oopz.remote_fetch import SafeRemoteFetcher

logger = get_logger("SdkVoiceController")
MAX_AUDIO_BYTES = 100 * 1024 * 1024
# 这个间隔直接决定一首歌放完后的空档下限，浏览器里查一次状态只是一次 JS 求值，
# 收紧到 0.5 秒的开销可以忽略
_PLAY_POLL_INTERVAL = 0.5
# 连续查不到状态就放弃轮询并当作已停止，让上层回退到按时长判定，
_PLAY_POLL_MAX_FAILURES = 3
# 播放页在曲目结束时只把状态短暂置为 finished，紧接着收尾流程就改成 joined，
# 轮询几乎必然错过那一瞬；而 play_bytes 成功返回前状态已同步置为 playing，
# 所以只要离开下面这两个状态，就说明这一首已经结束
_ACTIVE_PLAYBACK_STATES = frozenset({"playing", "paused"})
# 等预热的上限。宁可等，也好过在浏览器没起来时进频道导致 bot 不显示；
# 但不能无限等，超时后照常进，至少还能听到声音。
_WARMUP_WAIT_TIMEOUT = 60.0
_NETEASE_REMOTE_AUDIO_SUFFIXES = ("music.126.net", "music.163.com")


class SdkVoiceController:
    """以 SDK Voice 为后端，补充安全下载、预加载和播放状态。"""

    def __init__(self, voice_service, *, proxy_value=None, supervisor=None) -> None:
        self._voice = voice_service
        self._fetcher = SafeRemoteFetcher(proxy_value=proxy_value)
        self._supervisor = supervisor
        self._preloaded: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._preload_tasks: dict[str, asyncio.Task[None]] = {}
        self._playing = False
        self._playback_watch: asyncio.Task[None] | None = None
        # 播完立刻置位，供自动播放监控等待。没有它监控只能靠定时轮询发现，
        # 一首歌结束后要白等最多一整个轮询周期才切下一首。
        self.playback_ended = asyncio.Event()
        self._warmup_started = False
        self._warmup_done = asyncio.Event()
        self._closed = False

    @property
    def available(self) -> bool:
        return not self._closed

    async def warmup(self) -> None:
        if self._closed:
            return
        self._warmup_started = True
        started = time.monotonic()
        try:
            await self._voice.start()
        except Exception as exc:
            logger.warning("语音浏览器预热失败，首次进入语音频道可能变慢: %s", exc)
        else:
            logger.info("语音浏览器预热完成，耗时 %.1fs", time.monotonic() - started)
        finally:
            self._warmup_done.set()

    async def _await_warmup(self) -> None:
        if not self._warmup_started or self._warmup_done.is_set():
            return
        try:
            await asyncio.wait_for(self._warmup_done.wait(), timeout=_WARMUP_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("等待语音浏览器预热超时，仍继续进入语音频道")

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def agora_uid(self) -> str:
        sign = self._voice.current_sign
        return str(getattr(sign, "agora_sign_pid", "") or "")

    async def join(
        self,
        *,
        area: str,
        channel: str,
        from_area: str = "",
        from_channel: str = "",
        rtc_uid: str | int | None = None,
    ):
        await self._await_warmup()
        return await self._voice.join(
            area=area,
            channel=channel,
            from_area=from_area,
            from_channel=from_channel,
            rtc_uid=rtc_uid,
        )

    async def leave(self) -> None:
        self._playing = False
        self._cancel_playback_watch()
        await self._voice.leave()

    def preload_audio(self, url: str, *, headers: Mapping[str, str] | None = None) -> None:
        url = str(url or "").strip()
        if not url or url in self._preloaded or url in self._preload_tasks:
            return
        coroutine = self._preload(url, headers=headers)
        task = (
            self._supervisor.create(coroutine, name="voice-audio-preload")
            if self._supervisor is not None
            else asyncio.create_task(coroutine, name="voice-audio-preload")
        )
        self._preload_tasks[url] = task
        task.add_done_callback(lambda _task, key=url: self._preload_tasks.pop(key, None))

    async def _preload(self, url: str, *, headers: Mapping[str, str] | None = None) -> None:
        try:
            payload = await asyncio.to_thread(
                self._fetcher.fetch,
                url,
                max_bytes=MAX_AUDIO_BYTES,
                timeout=(10, HTTP_TIMEOUT_DOWNLOAD),
                headers=headers,
            )
        except Exception as exc:
            logger.debug("语音预加载失败: %s", exc)
            return
        self._preloaded[url] = payload
        self._preloaded.move_to_end(url)
        while len(self._preloaded) > 3:
            self._preloaded.popitem(last=False)

    async def play_audio(
        self,
        url: str,
        on_started=None,
        *,
        headers: Mapping[str, str] | None = None,
        prefer_remote: bool = False,
    ) -> dict[str, Any]:
        url = str(url or "").strip()
        if not url:
            raise ValueError("音频 URL 不能为空")
        pending = self._preload_tasks.get(url)
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        cached = self._preloaded.pop(url, None)
        if cached is None and prefer_remote and self._is_netease_remote_audio(url):
            play_url = getattr(self._voice, "play_url", None)
            if callable(play_url):
                started = time.monotonic()
                try:
                    pending_result = play_url(url)
                    if not inspect.isawaitable(pending_result):
                        raise TypeError("voice play_url() must return an awaitable")
                    result = await cast(Awaitable[dict[str, Any]], pending_result)
                except Exception as exc:
                    logger.debug("浏览器直载网易云音频失败，回退安全下载: %s", exc)
                else:
                    if result and result.get("ok", False):
                        logger.info(
                            "网易云音频由语音浏览器直接加载，耗时 %.1fs",
                            time.monotonic() - started,
                        )
                        if on_started is not None:
                            callback_result = on_started()
                            if inspect.isawaitable(callback_result):
                                await callback_result
                        self._playing = True
                        self.playback_ended.clear()
                        self._watch_playback_end()
                        return result
                    logger.debug(
                        "浏览器直载网易云音频未成功，回退安全下载: %s",
                        (result or {}).get("error") or "empty result",
                    )
        if cached is None:
            # 没命中预加载就得现下，这段时间正是切歌空档的主要来源，记下来便于定位
            started = time.monotonic()
            cached = await asyncio.to_thread(
                self._fetcher.fetch,
                url,
                max_bytes=MAX_AUDIO_BYTES,
                timeout=(10, HTTP_TIMEOUT_DOWNLOAD),
                headers=headers,
            )
            logger.debug("音频未命中预加载，现下载耗时 %.1fs", time.monotonic() - started)
        data, mime_type = cached
        publish_started = time.monotonic()
        result = await self._voice.play_bytes(data, mime_type=mime_type or "audio/mpeg")
        if not result or not result.get("ok", False):
            raise RuntimeError(str((result or {}).get("error") or "SDK 语音播放失败"))
        logger.debug("推流到语音频道耗时 %.1fs", time.monotonic() - publish_started)
        self._playing = True
        self.playback_ended.clear()
        self._watch_playback_end()
        if on_started is not None:
            callback_result = on_started()
            if inspect.isawaitable(callback_result):
                await callback_result
        return result

    @staticmethod
    def _is_netease_remote_audio(url: str) -> bool:
        """只允许网易云自有音频域名绕过 Python→Base64 的重复搬运。"""
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        if parsed.scheme not in {"http", "https"} or not host:
            return False
        return any(
            host == suffix or host.endswith("." + suffix)
            for suffix in _NETEASE_REMOTE_AUDIO_SUFFIXES
        )

    def _watch_playback_end(self) -> None:
        """轮询浏览器状态，曲目自然播完时把 _playing 复位。

        SDK 播完不会回调通知，而 _playing 只有 stop/pause/leave/destroy 会清。
        少了这个轮询，一首歌放完后 is_playing 会永远停在 True，自动播放监控
        据此认为「还在播」，于是不再切下一首，只能去 Web 播放器手动点。
        """
        self._cancel_playback_watch()
        coroutine = self._await_playback_end()
        self._playback_watch = (
            self._supervisor.create(coroutine, name="voice-playback-end")
            if self._supervisor is not None
            else asyncio.create_task(coroutine, name="voice-playback-end")
        )

    def _cancel_playback_watch(self) -> None:
        task = self._playback_watch
        self._playback_watch = None
        if task is not None and not task.done():
            task.cancel()

    async def _await_playback_end(self) -> None:
        failures = 0
        while self._playing and not self._closed:
            await asyncio.sleep(_PLAY_POLL_INTERVAL)
            if not self._playing or self._closed:
                return
            try:
                state = await self._voice.get_state()
            except Exception as exc:
                failures += 1
                if failures >= _PLAY_POLL_MAX_FAILURES:
                    logger.debug("连续查询播放状态失败，按已停止处理: %s", exc)
                    self._mark_playback_ended()
                    return
                continue
            failures = 0
            if state in _ACTIVE_PLAYBACK_STATES:
                continue
            logger.info("语音推流播放完成 (state=%s)", state)
            self._mark_playback_ended()
            return

    def _mark_playback_ended(self) -> None:
        self._playing = False
        self.playback_ended.set()

    async def stop_audio(self) -> None:
        self._playing = False
        self._cancel_playback_watch()
        await self._voice.stop()

    async def pause_audio(self) -> bool:
        result = await self._voice.pause()
        if result:
            self._playing = False
        return result

    async def resume_audio(self) -> bool:
        result = await self._voice.resume()
        if result:
            self._playing = True
            self._watch_playback_end()
        return result

    async def seek_audio(self, seconds: float) -> bool:
        return await self._voice.seek(seconds)

    async def set_volume(self, volume: int) -> bool:
        return await self._voice.set_volume(volume)

    async def destroy(self, timeout: float = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancel_playback_watch()
        for task in tuple(self._preload_tasks.values()):
            task.cancel()
        if self._preload_tasks:
            await asyncio.gather(*self._preload_tasks.values(), return_exceptions=True)
        self._preload_tasks.clear()
        self._preloaded.clear()
        # 关停必须先退出语音频道：SDK 的 close() 只停身份心跳并关掉浏览器，
        # 不会调用 leave_voice_channel，服务端会继续把 bot 挂在频道里。
        # 残留的成员身份会让下一次 enter_channel 被当作「重复进入」——服务端
        # 不再广播成员加入事件，于是其他客户端听得到 bot 推流却看不到它在频道里。
        try:
            await asyncio.wait_for(self._voice.leave(), timeout=max(0.1, timeout))
        except Exception as exc:
            logger.warning("关停时退出语音频道失败，服务端可能残留成员状态: %s", exc)
        await asyncio.wait_for(self._voice.close(), timeout=max(0.1, timeout))


__all__ = ["MAX_AUDIO_BYTES", "SdkVoiceController"]
