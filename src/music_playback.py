"""音乐播放执行逻辑 — IP 检测、Web 播放器链接、Agora 推流、自动播放监控。"""

from __future__ import annotations

import json
import time
import uuid
import threading
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from config import WEB_PLAYER_CONFIG
from logger_config import get_logger
from web_link_token import ensure_token
from database import SongCache, Statistics

if TYPE_CHECKING:
    pass

logger = get_logger("MusicPlayback")

_AUTO_PLAY_CHECK_INTERVAL = 10
_PLAY_FADE_DELAY = 5
_DEFAULT_PLAY_DURATION = 300

_resolved_web_url: str | None = None


def reset_web_player_url_cache() -> None:
    global _resolved_web_url
    _resolved_web_url = None


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
            with urllib.request.urlopen(req, timeout=3) as resp:
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
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logger.debug(f"内网 IPv4 探测失败: {e}")

    # 回退内网 IPv6
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.connect(("2001:4860:4860::8888", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception as e:
        logger.debug(f"内网 IPv6 探测失败: {e}")
    return ""


def _web_player_link(redis_client=None) -> str:
    """生成 Markdown 格式的 Web 播放器跳转链接"""
    url = _get_web_player_url()
    if not url:
        return ""
    try:
        token_ttl = int(WEB_PLAYER_CONFIG.get("token_ttl_seconds", 86400) or 0)
    except (TypeError, ValueError):
        token_ttl = 86400
        logger.warning("WEB_PLAYER_CONFIG.token_ttl_seconds 非法，已回退为 86400 秒")
    token = ensure_token(redis_client=redis_client, ttl_seconds=token_ttl)
    if token:
        return f"[▶ 网页播放器]({url}/w/{token})"
    return f"[▶ 网页播放器]({url})"


class PlaybackMixin:
    """播放相关逻辑的 Mixin，供 MusicHandler 等使用"""

    def auto_play_monitor(self):
        """定期检查播放状态，自动播放下一首（基于歌曲时长判断是否播完）"""
        while True:
            try:
                is_playing = self._is_playing()

                if not is_playing:
                    current = self.queue.get_current()

                    if current is not None:
                        logger.info("自动播放监控: 歌曲已播完，清理 current 状态")
                        self.queue.clear_current()
                        try:
                            self.queue.redis.delete("music:play_state")
                        except Exception as e:
                            logger.debug(f"自动播放监控清理 play_state 失败: {e}")
                        current = None

                    # 队列有歌 → 自动切下一首（仅当 Bot 在语音频道时才真正播放，否则只从队列移除）
                    queue_length = self.queue.get_queue_length()
                    if queue_length > 0 and current is None:
                        if not self._voice_channel_id:
                            # Bot 不在语音频道时不应丢歌，保留队列等待下一次可播放时机
                            time.sleep(2)
                            continue
                        next_song = self.queue.play_next()
                        if next_song:
                            ch = next_song.get("channel") or self._voice_channel_id
                            ar = next_song.get("area") or self._voice_channel_area
                            next_song["channel"] = ch
                            next_song["area"] = ar

                            if not ch:
                                logger.warning("自动播放: 未获取到语音频道，歌曲保留在队列")
                                try:
                                    self.queue.redis.lpush("music:queue", json.dumps(next_song, ensure_ascii=False))
                                except Exception as e:
                                    logger.error(f"自动播放回退入队失败，歌曲可能丢失: {e}")
                                time.sleep(2)
                                continue

                            play_uuid = str(uuid.uuid4())
                            next_song["play_uuid"] = play_uuid
                            self._start_playing(next_song.get("duration_ms", 0))
                            self.queue.set_current(next_song)

                            SongCache.record_play(
                                song_id=next_song.get("song_id"),
                                platform=next_song.get("platform"),
                                data=next_song,
                                channel_id=ch,
                                user_id=next_song.get("user", ""),
                            )
                            Statistics.update_today(next_song.get("platform", "netease"), cache_hit=False)
                            logger.info(f"自动播放: {next_song.get('name')}")

                            threading.Thread(
                                target=self._stream_to_voice_channel,
                                args=(next_song["url"], next_song.get("name", "music"), ch, ar,
                                      str(next_song.get("song_id", "")), next_song.get("duration_ms", 0)),
                                daemon=True,
                            ).start()
                            # 预加载队首下一首，减少切歌时的下载延迟与卡顿
                            self._preload_next_song_if_any()

                            text = self._build_now_playing_text("自动播放", next_song)
                            self.sender.send_message(
                                text=text,
                                attachments=next_song.get("attachments", []),
                                channel=ch,
                                area=ar,
                            )

                            time.sleep(_PLAY_FADE_DELAY)
                    elif queue_length == 0 and current is None and self._voice_channel_id:
                        grace = time.time() - self._voice_enter_time < 30
                        if not grace:
                            logger.info("队列已空，Bot 自动退出语音频道")
                            self._leave_current_voice_channel()

                self._release_web_link_if_needed()
                time.sleep(_AUTO_PLAY_CHECK_INTERVAL)

            except Exception as e:
                logger.error(f"自动播放监控出错: {e}")
                time.sleep(_PLAY_FADE_DELAY)

    def _preload_next_song_if_any(self):
        """若队列中还有下一首且带 URL，则后台预加载其音频，减少切歌卡顿。"""
        if not self.voice or not self.voice.available:
            return
        try:
            next_item = self.queue.peek_next()
            if next_item and next_item.get("url"):
                self.voice.preload_audio(next_item["url"])
        except Exception as e:
            logger.debug(f"预加载下一首失败（忽略）: {e}")

    def _stream_to_voice_channel(self, url: str, name: str, channel: str, area: str,
                                 song_id: str = None, duration_ms: int = 0):
        """后台线程：通过 Agora 推流到语音频道"""
        if not self.voice or not self.voice.available or not self._voice_channel_id:
            logger.warning("语音频道未连接，无法推流")
            self._play_start_time = 0
            self._play_duration = 0
            self.queue.clear_current()
            try:
                self.queue.redis.delete("music:play_state")
            except Exception as e:
                logger.debug(f"推流前清理 play_state 失败: {e}")
            return

        try:
            self.voice.play_audio(url)
            logger.info(f"开始 Agora 推流: {name}")
        except Exception as e:
            if song_id:
                logger.info(f"推流失败，尝试重新获取音频URL: {name}")
                try:
                    current = self.queue.get_current() or {}
                    platform_name = current.get("platform", "netease")
                    p = self.platforms.get(platform_name) if hasattr(self, "platforms") else None
                    refetch = p or self.netease
                    new_url = refetch.get_song_url(song_id)
                    if new_url:
                        self.voice.play_audio(new_url)
                        logger.info(f"重新获取URL后推流成功: {name}")
                        return
                except Exception as inner_e:
                    logger.debug(f"重新获取音频 URL 失败: {inner_e}")
            logger.warning(f"Agora 推流失败: {e}")

            self._play_start_time = 0
            self._play_duration = 0
            self.queue.clear_current()
            try:
                self.queue.redis.delete("music:play_state")
            except Exception as clear_e:
                logger.debug(f"推流失败后清理 play_state 失败: {clear_e}")

    def _start_playing(self, duration_ms: int):
        """记录播放开始时间和时长，同步到 Redis 供 Web 播放器读取"""
        self._play_start_time = time.time()
        self._play_duration = duration_ms / 1000 if duration_ms else _DEFAULT_PLAY_DURATION
        try:
            self.queue.redis.set("music:play_state", json.dumps({
                "start_time": self._play_start_time,
                "duration": self._play_duration,
            }))
        except Exception as e:
            logger.debug(f"写入 play_state 到 Redis 失败: {e}")

    def _is_playing(self) -> bool:
        """根据时间判断当前歌曲是否还在播放（暂停状态也算播放中）"""
        if self._play_start_time <= 0:
            return False
        try:
            ps_raw = self.queue.redis.get("music:play_state")
            if ps_raw:
                ps = json.loads(ps_raw)
                if ps.get("paused"):
                    return True
        except Exception as e:
            logger.debug(f"读取 play_state 失败，按时间判定播放状态: {e}")
        try:
            if self.voice and self.voice.available and self._voice_channel_id and not self.voice.is_playing:
                return False
        except Exception as e:
            logger.debug(f"读取语音推流状态失败，回退时间判定: {e}")
        elapsed = time.time() - self._play_start_time
        return elapsed < self._play_duration

    def _build_now_playing_text(self, prefix: str, song_data: dict) -> str:
        """构建"正在播放"消息文本"""
        platform_name = {
            "netease": "网易云",
            "qq": "QQ音乐",
            "bilibili": "B站",
        }.get(song_data.get("platform"), "未知")

        text = f"{prefix}:\n来自于{platform_name}:\n"
        text += f"歌曲: {song_data['name']}\n"
        text += f"歌手: {song_data.get('artists', '未知')}\n"

        if song_data.get("album"):
            text += f"专辑: {song_data['album']}\n"
        if song_data.get("duration"):
            text += f"时长: {song_data['duration']}\n"

        link = self._get_web_link()
        if link:
            text += link

        attachments = song_data.get("attachments", [])
        if attachments:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        return text.rstrip()
