"""
音乐点歌模块
集成搜索、播放、队列管理、封面缓存、语音频道推流
"""

import json
import time
import uuid
import random
import threading
from typing import Optional
from urllib.parse import urlparse

from oopz_sender import OopzSender
from netease import NeteaseCloud
from queue_manager import QueueManager
from database import ImageCache, SongCache, Statistics
from name_resolver import NameResolver
from voice_client import VoiceClient
from config import WEB_PLAYER_CONFIG
from logger_config import get_logger
from web_link_token import ensure_token, clear_token, get_token
from music_web_control import WebControlExecutor

logger = get_logger("Music")

_resolved_web_url: str | None = None


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


class MusicHandler:
    """音乐功能处理器"""

    def __init__(self, sender: OopzSender, voice: Optional[VoiceClient] = None):
        self.sender = sender
        self.voice = voice
        self.netease = NeteaseCloud()
        self.queue = QueueManager()
        self.names = NameResolver()
        self._liked_cache: list = []       # 缓存最近显示的喜欢列表
        self._liked_ids_cache: list = []   # 缓存完整的喜欢歌曲 ID 列表
        self._play_start_time: float = 0   # 当前歌曲开始播放时间戳
        self._play_duration: float = 0     # 当前歌曲时长（秒）
        self._voice_channel_id: Optional[str] = None  # Bot 当前所在语音频道 ID
        self._voice_channel_area: Optional[str] = None  # Bot 当前所在语音频道的域 ID
        self._voice_enter_time: float = 0  # 进入语音频道的时间戳（宽限期用）
        self._playlist_idle_since: float = 0  # 播放列表空闲起始时间（用于释放 Web 链接）
        self._web_link_released_due_to_idle: bool = False
        self._web_control = WebControlExecutor(self)

    def _get_web_link(self) -> str:
        """获取 Web 播放器链接（按需生成随机访问令牌）。"""
        link = _web_player_link(redis_client=getattr(self.queue, "redis", None))
        if link:
            self._web_link_released_due_to_idle = False
        return link

    def _release_web_link_if_needed(self):
        """播放列表长时间空闲后，释放随机 Web 访问链接。"""
        timeout = int(WEB_PLAYER_CONFIG.get("link_idle_release_seconds", 1800) or 0)
        if timeout <= 0:
            self._playlist_idle_since = 0
            self._web_link_released_due_to_idle = False
            return

        try:
            current = self.queue.get_current()
            queue_length = self.queue.get_queue_length()
        except Exception as e:
            logger.debug(f"读取播放队列状态失败，跳过链接释放检查: {e}")
            return

        if current is None and queue_length == 0 and not self._is_playing():
            if self._playlist_idle_since <= 0:
                self._playlist_idle_since = time.time()
                return
            if getattr(self, "_web_link_released_due_to_idle", False):
                return
            idle_for = time.time() - self._playlist_idle_since
            if idle_for >= timeout:
                try:
                    token = get_token(redis_client=self.queue.redis)
                    if token:
                        clear_token(redis_client=self.queue.redis)
                        logger.info("播放列表空闲超时，已释放 Web 播放器访问链接令牌")
                except Exception as e:
                    logger.debug(f"释放 Web 播放器链接令牌失败: {e}")
                self._web_link_released_due_to_idle = True
        else:
            self._playlist_idle_since = 0
            self._web_link_released_due_to_idle = False

    # ------------------------------------------------------------------
    # 公共命令
    # ------------------------------------------------------------------

    def _check_and_enter_voice_channel(self, user: str, channel: str, area: str) -> bool:
        """
        检查用户是否在语音频道，若在则 Bot 进入该频道。
        若用户不在任何语音频道，发送提示并返回 False。
        若 Bot 正在其他频道播放，拒绝切换并提示。
        """
        if not self.voice or not self.voice.available:
            self.sender.send_message(
                "语音推流功能未启用或初始化失败，无法播放音乐。",
                channel=channel, area=area,
            )
            return False

        voice_ch_id = self.sender.get_voice_channel_for_user(user, area=area)
        if not voice_ch_id:
            self.sender.send_message(
                "请先加入一个语音频道，Bot 会跟随你进入并放歌。",
                channel=channel, area=area,
            )
            return False

        if (self._voice_channel_id and self._voice_channel_id != voice_ch_id
                and self._is_playing()):
            from name_resolver import NameResolver
            names = NameResolver()
            cur_ch_name = names.channel(self._voice_channel_id)
            self.sender.send_message(
                f"Bot 正在 {cur_ch_name} 播放中，请等播完或到该频道使用 /st 停止。",
                channel=channel, area=area,
            )
            return False

        # 记录切换前的频道（用于 fromChannel/fromArea）
        from_channel = self._voice_channel_id or ""
        from_area = self._voice_channel_area or ""

        # 如果 Bot 已在另一个语音频道，先退出
        if self._voice_channel_id and self._voice_channel_id != voice_ch_id:
            self._leave_current_voice_channel()

        # 进入域和目标语音频道（获取 Agora 凭证）
        agora_pid = self.voice.agora_uid if self.voice and self.voice.available else ""
        self.sender.enter_area(area=area)
        data = self.sender.enter_channel(
            channel=voice_ch_id, area=area,
            channel_type="VOICE",
            from_channel=from_channel,
            from_area=from_area,
            pid=agora_pid,
        )
        if "error" in data:
            logger.warning(f"Bot 进入语音频道失败: {data['error']}")
            self.sender.send_message(
                f"进入语音频道失败: {data['error']}，请稍后再试。",
                channel=channel, area=area,
            )
            return False

        logger.info(f"Bot 已进入语音频道: {self.names.channel(voice_ch_id)}")
        self._join_agora_room(data)
        self._voice_channel_id = voice_ch_id
        self._voice_channel_area = area
        self._voice_enter_time = time.time()
        return True

    def _join_agora_room(self, channel_data: dict):
        """使用 enter_channel 返回的凭证连接 Agora RTC。"""
        if not self.voice or not self.voice.available:
            return

        token = channel_data.get("supplierSign", "")
        room_id = channel_data.get("roomId", "")
        supplier = channel_data.get("supplier", "")
        logger.debug(f"enter_channel 返回: supplier={supplier}, "
                     f"roomId={room_id}, supplierSign={'有' if token else '空'}")
        if not token or not room_id:
            logger.warning("enter_channel 未返回 Agora 凭证，跳过 RTC 连接")
            return

        uid = int(self.voice.agora_uid)
        ok = self.voice.join(token=token, room_id=room_id, uid=uid)
        if ok:
            logger.info(f"Agora RTC 已连接: room={room_id}, uid={uid}")
        else:
            logger.warning("Agora RTC 连接失败")

    def _leave_current_voice_channel(self):
        """退出 Bot 当前所在的语音频道。"""
        if not self._voice_channel_id:
            return

        # 先断开 Agora RTC 连接
        if self.voice and self.voice.available:
            self.voice.leave()

        result = self.sender.leave_voice_channel(
            channel=self._voice_channel_id,
            area=self._voice_channel_area,
        )
        if "error" in result:
            logger.warning(f"退出语音频道失败: {result['error']}")
        else:
            logger.info(f"Bot 已退出语音频道: {self.names.channel(self._voice_channel_id)}")
        self._voice_channel_id = None
        self._voice_channel_area = None

    def play_netease(self, keyword: str, channel: str, area: str, user: str):
        """搜索网易云并播放或加入队列"""
        if not self._check_and_enter_voice_channel(user, channel, area):
            return
        result = self._search_and_prepare(keyword, channel, area, user)
        if result["code"] != "success":
            self.sender.send_message(f"错误: {result['message']}", channel=channel, area=area)
            return

        text = result["message"]
        attachments = result.get("attachments", [])
        self.sender.send_message(text=text, attachments=attachments, channel=channel, area=area)

    def play_next(self, channel: str, area: str, user: str):
        """播放队列中的下一首"""
        if not self._voice_channel_id:
            self.sender.send_message(
                "Bot 当前不在语音频道，请先用 /bf 点歌或让 Bot 跟随进入语音频道。",
                channel=channel,
                area=area,
            )
            return
        next_song = self.queue.play_next()
        if not next_song:
            self.sender.send_message("队列为空，没有下一首了", channel=channel, area=area)
            return

        # 更新频道和区域
        next_song["channel"] = channel
        next_song["area"] = area

        # 生成 UUID 追踪
        play_uuid = str(uuid.uuid4())
        next_song["play_uuid"] = play_uuid
        self._start_playing(next_song.get("duration_ms", 0))
        self.queue.set_current(next_song)

        SongCache.update_play_stats(
            song_id=next_song.get("song_id"),
            platform=next_song.get("platform"),
            channel_id=channel,
            user_id=user,
        )
        Statistics.update_today(next_song.get("platform", "netease"), cache_hit=False)

        # 上传音频到频道
        threading.Thread(
            target=self._stream_to_voice_channel,
            args=(next_song["url"], next_song.get("name", "music"), channel, area,
                  str(next_song.get("song_id", "")), next_song.get("duration_ms", 0)),
            daemon=True,
        ).start()
        self._preload_next_song_if_any()

        # 发送通知
        text = self._build_now_playing_text("切换到下一首", next_song)
        attachments = next_song.get("attachments", [])
        self.sender.send_message(text=text, attachments=attachments, channel=channel, area=area)

    def show_queue(self, channel: str, area: str):
        """显示当前队列"""
        queue_list = self.queue.get_queue(0, 9)
        if queue_list:
            total = self.queue.get_queue_length()
            lines = [f"{i}. {s['name']} - {s.get('artists', '未知')}" for i, s in enumerate(queue_list, 1)]
            msg = "当前队列（前10首）:\n" + "\n".join(lines) + f"\n\n总计: {total} 首"
            self.sender.send_message(msg, channel=channel, area=area)
        else:
            self.sender.send_message("队列为空", channel=channel, area=area)

    def show_liked_list(self, channel: str, area: str, page: int = 1):
        """显示喜欢的音乐列表（每页 20 首）"""
        uid = self.netease.get_user_id()
        if not uid:
            self.sender.send_message("无法获取网易云账号信息，请检查 Cookie 是否过期", channel=channel, area=area)
            return

        # 刷新缓存
        if not self._liked_ids_cache:
            self._liked_ids_cache = self.netease.get_liked_ids(uid)

        if not self._liked_ids_cache:
            self.sender.send_message("你的喜欢列表为空", channel=channel, area=area)
            return

        total = len(self._liked_ids_cache)
        per_page = 20
        total_pages = (total + per_page - 1) // per_page
        page = max(1, min(page, total_pages))

        start = (page - 1) * per_page
        end = min(start + per_page, total)
        page_ids = self._liked_ids_cache[start:end]

        # 批量获取歌曲详情
        details = self.netease.get_song_details_batch(page_ids)
        if not details:
            self.sender.send_message("获取歌曲信息失败，请稍后再试", channel=channel, area=area)
            return

        # 缓存当前页供 play_liked_by_index 使用
        self._liked_cache = details

        lines = [f"喜欢的音乐 (第 {page}/{total_pages} 页，共 {total} 首):"]
        for i, song in enumerate(details, start + 1):
            lines.append(f"  {i}. {song['name']} - {song['artists']}  [{song['durationText']}]")

        lines.append(f"\n用法: /like play <编号> 播放指定歌曲")
        lines.append(f"      /like list <页码> 翻页")

        self.sender.send_message("\n".join(lines), channel=channel, area=area)

    def play_liked_by_index(self, index: int, channel: str, area: str, user: str):
        """通过列表编号播放喜欢的歌曲"""
        if not self._check_and_enter_voice_channel(user, channel, area):
            return
        if not self._liked_ids_cache:
            self.sender.send_message("请先使用 /like list 查看列表", channel=channel, area=area)
            return

        total = len(self._liked_ids_cache)
        if index < 1 or index > total:
            self.sender.send_message(f"编号超出范围，请输入 1-{total}", channel=channel, area=area)
            return

        song_id = self._liked_ids_cache[index - 1]
        result = self.netease.summarize_by_id(song_id)
        if result["code"] != "success":
            self.sender.send_message(f"获取歌曲失败: {result['message']}", channel=channel, area=area)
            return

        data = result["data"]

        # 封面处理
        attachments = []
        image_cache_id = None
        cache_hit = False

        if data.get("cover"):
            cached = ImageCache.get_by_source(song_id, "netease")
            if cached:
                attachments = [cached["attachment_data"]]
                image_cache_id = cached["id"]
                cache_hit = True
                ImageCache.increment_use(song_id, "netease")
            else:
                up = self.sender.upload_file_from_url(data["cover"])
                if up.get("code") == "success":
                    att = up["data"]
                    attachments = [att]
                    image_cache_id = ImageCache.save(song_id, "netease", data["cover"], att)

        # 歌曲缓存 & 统计
        song_cache_id = SongCache.get_or_create(song_id, "netease", data, image_cache_id)
        SongCache.add_play_history(song_cache_id, "netease", channel, user)
        Statistics.update_today("netease", cache_hit)

        # 消息
        user_name = self.names.user(user) if user else "未知用户"
        text = (
            f"{user_name} 从喜欢列表点播了:\n"
            "来自于网易云:\n"
            f"歌曲: {data['name']}\n"
            f"歌手: {data['artists']}\n"
            f"专辑: {data['album']}\n"
            f"时长: {data['durationText']}"
        )

        link = self._get_web_link()
        if link:
            text += f"\n{link}"

        if attachments:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        # 判断立即播放还是排队
        is_playing = self._is_playing()
        current_song = self.queue.get_current()
        queue_length = self.queue.get_queue_length()

        if not is_playing and current_song is not None:
            self.queue.clear_current()
            current_song = None

        song_data = {
            "platform": "netease",
            "song_id": str(song_id),
            "name": data["name"],
            "artists": data["artists"],
            "album": data["album"],
            "url": data["url"],
            "cover": data.get("cover"),
            "duration": data["durationText"],
            "duration_ms": data.get("duration", 0),
            "attachments": attachments,
            "channel": channel,
            "area": area,
            "user": user,
        }

        if not is_playing and current_song is None and queue_length == 0:
            play_uuid = str(uuid.uuid4())
            song_data["play_uuid"] = play_uuid
            self._start_playing(data.get("duration", 0))
            self.queue.set_current(song_data)
            threading.Thread(
                target=self._stream_to_voice_channel,
                args=(data["url"], data["name"], channel, area,
                      str(data.get("id", "")), data.get("duration", 0)),
                daemon=True,
            ).start()
            self._preload_next_song_if_any()
        else:
            pos = self.queue.add_to_queue(song_data)
            actual = pos + 1 + (1 if current_song or is_playing else 0)
            text += f"\n已加入队列 (位置: {actual})"

        self.sender.send_message(text=text, attachments=attachments, channel=channel, area=area)

    def play_liked(self, channel: str, area: str, user: str, count: int = 1):
        """从登录账号的喜欢列表中随机选歌播放"""
        if not self._check_and_enter_voice_channel(user, channel, area):
            return
        uid = self.netease.get_user_id()
        if not uid:
            self.sender.send_message("无法获取网易云账号信息，请检查 Cookie 是否过期", channel=channel, area=area)
            return

        liked_ids = self.netease.get_liked_ids(uid)
        if not liked_ids:
            self.sender.send_message("你的喜欢列表为空", channel=channel, area=area)
            return

        count = min(count, 20, len(liked_ids))
        selected = random.sample(liked_ids, count)

        success_count = 0
        first_text = None
        first_attachments = []

        for i, song_id in enumerate(selected):
            result = self.netease.summarize_by_id(song_id)
            if result["code"] != "success":
                logger.warning(f"喜欢列表歌曲获取失败 (ID: {song_id}): {result['message']}")
                continue

            data = result["data"]

            # 封面处理
            attachments = []
            image_cache_id = None
            cache_hit = False

            if data.get("cover"):
                cached = ImageCache.get_by_source(song_id, "netease")
                if cached:
                    attachments = [cached["attachment_data"]]
                    image_cache_id = cached["id"]
                    cache_hit = True
                    ImageCache.increment_use(song_id, "netease")
                else:
                    up = self.sender.upload_file_from_url(data["cover"])
                    if up.get("code") == "success":
                        att = up["data"]
                        attachments = [att]
                        image_cache_id = ImageCache.save(song_id, "netease", data["cover"], att)

            # 歌曲缓存
            song_cache_id = SongCache.get_or_create(song_id, "netease", data, image_cache_id)
            SongCache.add_play_history(song_cache_id, "netease", channel, user)
            Statistics.update_today("netease", cache_hit)

            song_data = {
                "platform": "netease",
                "song_id": str(song_id),
                "name": data["name"],
                "artists": data["artists"],
                "album": data["album"],
                "url": data["url"],
                "cover": data.get("cover"),
                "duration": data["durationText"],
                "duration_ms": data.get("duration", 0),
                "attachments": attachments,
                "channel": channel,
                "area": area,
                "user": user,
            }

            # 第一首尝试立即播放，其余加队列
            if success_count == 0:
                is_playing = self._is_playing()
                current_song = self.queue.get_current()

                if not is_playing and current_song is not None:
                    self.queue.clear_current()
                    current_song = None

                queue_length = self.queue.get_queue_length()

                if not is_playing and current_song is None and queue_length == 0:
                    play_uuid = str(uuid.uuid4())
                    song_data["play_uuid"] = play_uuid
                    self._start_playing(data.get("duration", 0))
                    self.queue.set_current(song_data)
                    threading.Thread(
                        target=self._stream_to_voice_channel,
                        args=(data["url"], data["name"], channel, area,
                              str(data.get("id", "")), data.get("duration", 0)),
                        daemon=True,
                    ).start()
                    self._preload_next_song_if_any()

                    user_name = self.names.user(user) if user else "未知用户"
                    text = (
                        f"{user_name} 随机播放了喜欢的音乐:\n"
                        "来自于网易云:\n"
                        f"歌曲: {data['name']}\n"
                        f"歌手: {data['artists']}\n"
                        f"专辑: {data['album']}\n"
                        f"时长: {data['durationText']}"
                    )
                    link = self._get_web_link()
                    if link:
                        text += f"\n{link}"
                    if attachments:
                        att = attachments[0]
                        text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

                    first_text = text
                    first_attachments = attachments
                else:
                    pos = self.queue.add_to_queue(song_data)
                    user_name = self.names.user(user) if user else "未知用户"
                    first_text = (
                        f"{user_name} 随机播放了喜欢的音乐:\n"
                        f"歌曲: {data['name']} - {data['artists']}\n"
                        f"已加入队列"
                    )
                    first_attachments = attachments
            else:
                self.queue.add_to_queue(song_data)

            success_count += 1

        if success_count == 0:
            self.sender.send_message("随机选歌失败，请稍后再试", channel=channel, area=area)
            return

        if count > 1 and success_count > 1:
            first_text += f"\n(共 {success_count} 首已加入队列)"

        self.sender.send_message(text=first_text, attachments=first_attachments, channel=channel, area=area)

    def stop_play(self, channel: str, area: str):
        """停止播放并退出语音频道"""
        self._play_start_time = 0
        self._play_duration = 0
        self.queue.clear_current()
        try:
            self.queue.redis.delete("music:play_state")
        except Exception as e:
            logger.debug(f"停止播放时清理 play_state 失败: {e}")
        if self.voice and self.voice.available:
            self.voice.stop_audio()
        self._leave_current_voice_channel()
        self.sender.send_message("已停止播放，Bot 已退出语音频道", channel=channel, area=area)

    # ------------------------------------------------------------------
    # 自动播放监控（在 main.py 中作为后台线程启动）
    # ------------------------------------------------------------------

    def _update_play_state_redis(self, **overrides):
        """更新 Redis 中的 play_state，支持暂停/恢复/跳转时的状态同步"""
        try:
            ps = {"start_time": self._play_start_time, "duration": self._play_duration}
            ps.update(overrides)
            self.queue.redis.set("music:play_state", json.dumps(ps))
        except Exception as e:
            logger.debug(f"更新 play_state 失败: {e}")

    def start_web_command_listener(self):
        """启动独立线程，通过 BLPOP 实时监听 Web 控制命令（无延迟）"""
        def _listener():
            logger.info("Web 命令监听线程已启动 (BLPOP)")
            last_warn_at = 0.0
            while True:
                try:
                    result = self.queue.redis.blpop("music:web_commands", timeout=2)
                    if result:
                        _, cmd_raw = result
                        cmd = cmd_raw.decode() if isinstance(cmd_raw, bytes) else str(cmd_raw)
                        self._execute_web_command(cmd)
                except Exception as e:
                    now = time.time()
                    if now - last_warn_at >= 30:
                        logger.warning(f"Web 命令监听异常（30s 节流）: {e}")
                        last_warn_at = now
                    else:
                        logger.debug(f"Web 命令监听异常（抑制告警）: {e}")
                    time.sleep(1)

        t = threading.Thread(target=_listener, daemon=True)
        t.start()

    def _execute_web_command(self, cmd: str):
        """执行单条 Web 控制命令"""
        # 兼容测试中 __new__ 构造未执行 __init__ 的场景
        if not hasattr(self, "_web_control") or self._web_control is None:
            self._web_control = WebControlExecutor(self)
        self._web_control.execute(cmd)

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

                            SongCache.update_play_stats(
                                song_id=next_song.get("song_id"),
                                platform=next_song.get("platform"),
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

                            time.sleep(5)
                    elif queue_length == 0 and current is None and self._voice_channel_id:
                        grace = time.time() - self._voice_enter_time < 30
                        if not grace:
                            logger.info("队列已空，Bot 自动退出语音频道")
                            self._leave_current_voice_channel()

                self._release_web_link_if_needed()
                time.sleep(10)

            except Exception as e:
                logger.error(f"自动播放监控出错: {e}")
                time.sleep(5)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

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
            # URL 可能过期，尝试重新获取
            if song_id:
                logger.info(f"推流失败，尝试重新获取音频URL: {name}")
                try:
                    new_url = self.netease.get_song_url(int(song_id))
                    if new_url:
                        self.voice.play_audio(new_url)
                        logger.info(f"重新获取URL后推流成功: {name}")
                        return
                except Exception as inner_e:
                    logger.debug(f"重新获取音频 URL 失败: {inner_e}")
            logger.warning(f"Agora 推流失败: {e}")

    def _search_and_prepare(self, keyword: str, channel: str, area: str, user: str) -> dict:
        """搜索歌曲 → 缓存封面 → 决定立即播放或加队列"""
        search_result = self.netease.summarize(keyword)
        if search_result["code"] != "success":
            return search_result

        data = search_result["data"]
        song_id = data.get("id", keyword)

        # 图片缓存
        cache_hit = False
        attachments = []
        image_cache_id = None

        if data.get("cover"):
            cached = ImageCache.get_by_source(song_id, "netease")
            if cached:
                attachments = [cached["attachment_data"]]
                image_cache_id = cached["id"]
                cache_hit = True
                ImageCache.increment_use(song_id, "netease")
            else:
                up = self.sender.upload_file_from_url(data["cover"])
                if up.get("code") == "success":
                    att = up["data"]
                    attachments = [att]
                    image_cache_id = ImageCache.save(song_id, "netease", data["cover"], att)

        # 歌曲缓存
        song_cache_id = SongCache.get_or_create(song_id, "netease", data, image_cache_id)
        SongCache.add_play_history(song_cache_id, "netease", channel, user)
        Statistics.update_today("netease", cache_hit)

        # 消息文本
        user_name = self.names.user(user) if user else "未知用户"
        text = (
            f"{user_name} 点播了:\n"
            "来自于网易云:\n"
            f"歌曲: {data['name']}\n"
            f"歌手: {data['artists']}\n"
            f"专辑: {data['album']}\n"
            f"时长: {data['durationText']}"
        )

        link = self._get_web_link()
        if link:
            text += f"\n{link}"

        if attachments:
            att = attachments[0]
            text = f"![IMAGEw{att['width']}h{att['height']}]({att['fileKey']})\n" + text

        # 决定立即播放还是排队
        is_playing = self._is_playing()
        current_song = self.queue.get_current()
        queue_length = self.queue.get_queue_length()

        # 清理残留状态
        if not is_playing and current_song is not None:
            logger.info("检测到残留状态: 歌曲已播完但 current 存在, 自动清理")
            self.queue.clear_current()
            current_song = None

        song_data = {
            "platform": "netease",
            "song_id": str(song_id),
            "name": data["name"],
            "artists": data["artists"],
            "album": data["album"],
            "url": data["url"],
            "cover": data.get("cover"),
            "duration": data["durationText"],
            "duration_ms": data.get("duration", 0),
            "attachments": attachments,
            "channel": channel,
            "area": area,
            "user": user,
        }

        if not is_playing and current_song is None and queue_length == 0:
            # 立即播放
            play_uuid = str(uuid.uuid4())
            song_data["play_uuid"] = play_uuid
            self._start_playing(data.get("duration", 0))
            self.queue.set_current(song_data)

            threading.Thread(
                target=self._stream_to_voice_channel,
                args=(data["url"], data["name"], channel, area,
                      str(data.get("id", "")), data.get("duration", 0)),
                daemon=True,
            ).start()
            self._preload_next_song_if_any()
        else:
            pos = self.queue.add_to_queue(song_data)
            actual = pos + 1 + (1 if current_song or is_playing else 0)
            text += f"\n已加入队列 (位置: {actual})"

        return {"code": "success", "message": text, "attachments": attachments}

    def _start_playing(self, duration_ms: int):
        """记录播放开始时间和时长，同步到 Redis 供 Web 播放器读取"""
        self._play_start_time = time.time()
        self._play_duration = duration_ms / 1000 if duration_ms else 300
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
