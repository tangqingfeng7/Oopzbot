"""
Music Web 控制命令执行器

将 MusicHandler 中的 Web 命令处理逻辑拆分出来，降低主模块复杂度。
"""

import json
import time

from logger_config import get_logger

logger = get_logger("MusicWebControl")


class WebControlExecutor:
    """执行来自 Web 面板的控制命令。"""

    def __init__(self, handler):
        self.h = handler

    def execute(self, cmd: str):
        logger.info(f"Web 控制命令: {cmd}")
        try:
            if cmd == "next":
                self._handle_next()
                return
            if cmd == "stop":
                self._handle_stop()
                return
            if cmd == "pause":
                self._handle_pause()
                return
            if cmd == "resume":
                self._handle_resume()
                return
            if cmd.startswith("seek:"):
                self._handle_seek(cmd)
                return
            if cmd.startswith("volume:"):
                self._handle_volume(cmd)
                return
            if cmd.startswith("notify:"):
                self._handle_notify(cmd)
                return
        except Exception as e:
            logger.warning(f"执行 Web 命令异常 ({cmd}): {e}")

    def _stop_voice_audio(self, context: str):
        if not (self.h.voice and self.h.voice.available):
            return
        try:
            self.h.voice.stop_audio()
        except Exception as e:
            logger.debug(f"{context} 停止音频失败: {e}")

    def _handle_next(self):
        self.h._play_start_time = 0
        self.h._play_duration = 0
        self._stop_voice_audio("执行 next 时")

    def _handle_stop(self):
        self.h._play_start_time = 0
        self.h._play_duration = 0
        self.h.queue.clear_current()
        self.h.queue.clear_queue()
        try:
            self.h.queue.redis.delete("music:play_state")
        except Exception as e:
            logger.debug(f"执行 stop 时清理 play_state 失败: {e}")
        self._stop_voice_audio("执行 stop 时")
        self.h._leave_current_voice_channel()

    def _handle_pause(self):
        if self.h.voice and self.h.voice.available and self.h.voice.pause_audio():
            elapsed = time.time() - self.h._play_start_time
            self.h._update_play_state_redis(paused=True, pause_elapsed=elapsed)

    def _handle_resume(self):
        if not (self.h.voice and self.h.voice.available and self.h.voice.resume_audio()):
            return
        try:
            ps_raw = self.h.queue.redis.get("music:play_state")
            if not ps_raw:
                return
            ps = json.loads(ps_raw)
            elapsed = ps.get("pause_elapsed", 0)
            self.h._play_start_time = time.time() - elapsed
            self.h._update_play_state_redis(
                start_time=self.h._play_start_time,
                paused=False,
                pause_elapsed=None,
            )
        except Exception as e:
            logger.debug(f"执行 resume 时读取 play_state 失败: {e}")

    def _handle_seek(self, cmd: str):
        try:
            seek_time = float(cmd.split(":", 1)[1])
        except (ValueError, IndexError) as e:
            logger.debug(f"解析 seek 命令失败 ({cmd}): {e}")
            return
        if not (self.h.voice and self.h.voice.available):
            return
        self.h.voice.seek_audio(seek_time)
        self.h._play_start_time = time.time() - seek_time
        self.h._update_play_state_redis(
            start_time=self.h._play_start_time,
            paused=False,
            pause_elapsed=None,
        )

    def _handle_volume(self, cmd: str):
        try:
            vol = int(cmd.split(":", 1)[1])
        except (ValueError, IndexError) as e:
            logger.debug(f"解析 volume 命令失败 ({cmd}): {e}")
            return
        if not (self.h.voice and self.h.voice.available):
            return
        self.h.voice.set_volume(vol)
        try:
            self.h.queue.redis.set("music:volume", str(vol))
        except Exception as e:
            logger.debug(f"持久化音量失败: {e}")

    def _handle_notify(self, cmd: str):
        try:
            info = json.loads(cmd.split(":", 1)[1])
        except (ValueError, TypeError, IndexError, json.JSONDecodeError) as e:
            logger.debug(f"解析 notify 命令失败 ({cmd}): {e}")
            return

        ch = self.h._voice_channel_id
        ar = self.h._voice_channel_area
        if not ch:
            return

        name = info.get("name", "未知")
        artists = info.get("artists", "未知")
        pos = info.get("position", "?")
        try:
            pos_int = int(pos)
        except (ValueError, TypeError):
            pos_int = 1
        has_current = False
        try:
            has_current = self.h.queue.get_current() is not None
        except Exception as e:
            logger.debug(f"读取当前播放状态失败，按队列位置展示: {e}")
        if not has_current and hasattr(self.h, "_is_playing"):
            try:
                has_current = bool(self.h._is_playing())
            except Exception as e:
                logger.debug(f"读取播放状态失败，按队列位置展示: {e}")
        actual = max(1, pos_int + (1 if has_current else 0))
        text = f"[Web 点歌] {name} - {artists}\n已加入队列 (位置: {actual})"
        try:
            self.h.sender.send_message(text, channel=ch, area=ar)
        except Exception as e:
            logger.warning(f"Web 通知消息发送失败: {e}")
