import time
import uuid
from collections.abc import Mapping
from typing import cast

from core.database import SongCache, Statistics
from core.logger_config import get_logger
from core.queue_manager import get_redis_client
from core.redis_keys import VOLUME as KEY_VOLUME
from domain.playback import AreaWebCommand, GlobalWebCommand, WebCommand

logger = get_logger("MusicWebControl")


class WebControlExecutor:
    """执行来自 Web 面板的控制命令。"""

    def __init__(self, handler):
        self.h = handler

    async def execute(self, command: WebCommand, queue=None) -> bool:
        logger.info("Web 控制命令: scope=%s action=%s", command.scope, command.action)
        try:
            if isinstance(command, GlobalWebCommand):
                await self._handle_volume(cast(int, command.payload["value"]))
                return True
            if not isinstance(command, AreaWebCommand) or queue is None:
                return False
            async with self.h._playback_lock:
                session = self.h._playback_snapshot_locked()
                if session.area != command.area:
                    return False
                if command.action == "next":
                    await self._handle_next(queue, command.area.value, session)
                elif command.action == "stop":
                    await self._handle_stop(queue)
                elif command.action == "pause":
                    await self._handle_pause(queue)
                elif command.action == "resume":
                    await self._handle_resume(queue)
                elif command.action == "seek":
                    await self._handle_seek(queue, cast(float, command.payload["time"]))
                elif command.action == "notify":
                    await self._handle_notify(queue, command.payload, command.area.value)
                else:
                    return False
                return True
        except Exception as e:
            logger.warning("执行 Web 命令异常 (%s): %s", command.action, e)
            return False

    async def _stop_voice_audio(self, context: str):
        if not (self.h.voice and self.h.voice.available):
            return
        try:
            self.h.voice.set_playing(False)
            await self.h.voice.service.stop()
        except Exception as e:
            logger.debug(f"{context} 停止音频失败: {e}")

    async def _handle_next(self, queue, area: str, session):
        """Web 端用户主动切下一首：直接完成出队 + 切歌 + 推流。

        这里不能依赖 auto_play_monitor 的轮询触发：
        - 监控线程会把残留的 current 视作"自然播完"，传 natural_end=True
          + current_song=旧歌 给 _dequeue_next_song，导致单曲循环重播本首；
        - 监控线程的轮询周期最长 10s，会让 UI 卡在"上一首"几秒钟。

        改成这里直接走切歌流程：
        - 通过 _dequeue_next_song(natural_end=True, current_song=None)
          既跳过 SINGLE 自循环（SINGLE 分支需要 current_song 才生效），
          又保留空队列时 AUTOPLAY 模式自动续播的能力。
        """
        h = self.h
        channel = session.channel

        if not channel:
            h._advance_playback_generation_locked()
            h._play_start_time = 0
            h._play_duration = 0
            await self._stop_voice_audio("执行 next 时")
            try:
                await queue.clear_current()
                await queue.clear_play_state()
            except Exception as e:
                logger.debug(f"未在语音频道时清理 play_state 失败: {e}")
            return

        try:
            next_song, _source = await h._dequeue_next_song(
                natural_end=True,
                current_song=None,
                queue=queue,
            )
        except Exception as e:
            logger.warning(f"Web next 取下一首失败: {e}")
            next_song = None

        session = h._advance_playback_generation_locked()
        await self._stop_voice_audio("执行 next 时")
        h._play_start_time = 0
        h._play_duration = 0

        if not next_song:
            try:
                await queue.clear_current()
                await queue.clear_play_state()
            except Exception as e:
                logger.debug(f"队列空清理 play_state 失败: {e}")
            return

        next_song["channel"] = next_song.get("channel") or channel
        next_song["area"] = area
        next_song["play_uuid"] = str(uuid.uuid4())

        await h._mark_web_active_area(area, queue=queue)
        await h._start_playing(next_song.get("duration_ms", 0), area=area)
        await queue.set_current(next_song)

        try:
            await SongCache.record_play(
                song_id=str(next_song.get("song_id") or ""),
                platform=str(next_song.get("platform") or "netease"),
                data=next_song,
                channel_id=next_song["channel"],
                user_id=next_song.get("user", ""),
            )
            await Statistics.update_today(
                next_song.get("platform", "netease"), cache_hit=False,
            )
        except Exception as e:
            logger.debug(f"记录 Web 切歌播放历史失败: {e}")

        h._start_stream_task(next_song, session)
        await h._preload_next_song_if_any(queue=queue)

        try:
            text = await h._build_now_playing_text("切换到下一首", next_song)
            await h.sender.send_message(
                text=text,
                attachments=next_song.get("attachments", []),
                channel=next_song["channel"],
                area=next_song["area"],
            )
        except Exception as e:
            logger.warning(f"Web 切歌通知发送失败: {e}")

    async def _handle_stop(self, queue):
        self.h._advance_playback_generation_locked()
        self.h._play_start_time = 0
        self.h._play_duration = 0
        await queue.clear_current()
        await queue.clear_queue()
        try:
            await queue.clear_play_state()
        except Exception as e:
            logger.debug(f"执行 stop 时清理 play_state 失败: {e}")
        await self._stop_voice_audio("执行 stop 时")
        await self.h._leave_current_voice_channel()

    async def _handle_pause(self, queue):
        if self.h.voice and self.h.voice.available and await self.h.voice.service.pause():
            self.h.voice.set_playing(False)
            elapsed = time.time() - self.h._play_start_time
            await self.h._update_play_state_redis(
                queue=queue,
                paused=True,
                pause_elapsed=elapsed,
            )

    async def _handle_resume(self, queue):
        if not (self.h.voice and self.h.voice.available and await self.h.voice.service.resume()):
            return
        self.h.voice.set_playing(True)
        try:
            ps = await queue.get_play_state()
            if not ps:
                return
            elapsed = ps.get("pause_elapsed", 0)
            self.h._play_start_time = time.time() - elapsed
            await self.h._update_play_state_redis(
                queue=queue,
                start_time=self.h._play_start_time,
                paused=False,
                pause_elapsed=None,
            )
        except Exception as e:
            logger.debug(f"执行 resume 时读取 play_state 失败: {e}")

    async def _handle_seek(self, queue, seek_time: float):
        if not (self.h.voice and self.h.voice.available):
            return
        if not await self.h.voice.service.seek(seek_time):
            return
        was_paused = False
        try:
            ps = await queue.get_play_state()
            if ps:
                was_paused = bool(ps.get("paused"))
        except Exception:
            pass
        self.h._play_start_time = time.time() - seek_time
        await self.h._update_play_state_redis(
            queue=queue,
            start_time=self.h._play_start_time,
            paused=was_paused,
            pause_elapsed=seek_time if was_paused else None,
        )

    async def _handle_volume(self, vol: int):
        redis_client = await get_redis_client()
        try:
            await redis_client.set(KEY_VOLUME, str(vol))
        except Exception as e:
            logger.debug(f"持久化音量失败: {e}")
        if not (self.h.voice and self.h.voice.available):
            return
        if not await self.h.voice.service.set_volume(vol):
            return
        try:
            await redis_client.set(KEY_VOLUME, str(vol))
        except Exception as e:
            logger.debug(f"持久化音量失败: {e}")

    async def _handle_notify(self, queue, info: Mapping[str, object], area: str):
        ch = self.h._voice_channel_id
        if not ch:
            return

        name = info.get("name", "未知")
        artists = info.get("artists", "未知")
        pos = info.get("position", "?")
        pos_int = pos if isinstance(pos, int) and not isinstance(pos, bool) else 1
        has_current = False
        try:
            has_current = await queue.get_current() is not None
        except Exception as e:
            logger.debug(f"读取当前播放状态失败，按队列位置展示: {e}")
        if not has_current:
            try:
                has_current = bool(await self.h._is_playing(queue=queue))
            except Exception as e:
                logger.debug(f"读取播放状态失败，按队列位置展示: {e}")
        actual = max(1, pos_int + (1 if has_current else 0))
        text = f"[Web 点歌] {name} - {artists}\n已加入队列 (位置: {actual})"
        try:
            await self.h.sender.send_message(text, channel=ch, area=area)
        except Exception as e:
            logger.warning(f"Web 通知消息发送失败: {e}")
