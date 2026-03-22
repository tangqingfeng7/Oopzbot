import re
import time
from typing import Optional

from config import PROFANITY_CONFIG
from domain.safety.profanity_rules import (
    actual_mute_duration as resolve_mute_duration,
    format_duration as format_mute_duration,
    match_context_keyword,
    match_keyword,
)
from logger_config import get_logger
from app.services.runtime import CommandRuntimeView, sender_of

logger = get_logger("ProfanityGuardService")


class ProfanityGuardService:
    """负责脏话检测、上下文缓冲和自动禁言。"""

    _CHAR_NORMALIZE = str.maketrans({
        "艹": "草", "屄": "逼", "馬": "马", "嗎": "吗",
        "媽": "妈", "罵": "骂", "幹": "干", "機": "鸡",
        "雞": "鸡", "賤": "贱", "個": "个", "殺": "杀",
        "腦": "脑", "殘": "残", "滾": "滚",
        "糙": "草", "槽": "草",
        "批": "逼",
        "肏": "操",
        "*": "", "#": "", "@": "", "×": "",
    })
    _MAX_TRACKED_USERS = 500

    _WARN_EXPIRE_SECONDS = 300

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)
        self._user_msg_buffer: dict[str, list[dict]] = {}
        self._warnings: dict[str, tuple[int, float]] = {}
        self._last_cleanup: float = 0.0

    @property
    def _keywords(self) -> list[str]:
        return [kw.lower() for kw in PROFANITY_CONFIG.get("keywords", [])]

    @classmethod
    def clean_text(cls, content: str) -> str:
        """清理文本，用于脏话匹配。"""
        text = re.sub(r"\(met\)[A-Za-z0-9_\-]+\(met\)", "", content)
        text = re.sub(r"[\s\u200b\u200c\u200d\ufeff.,!?，。！？~·、\-_+=]+", "", text)
        text = text.translate(cls._CHAR_NORMALIZE)
        return text.lower()

    def check_profanity(self, content: str) -> Optional[str]:
        """检测单条消息是否命中违禁词。"""
        text = self.clean_text(content)
        return match_keyword(text, self._keywords)

    def push_user_buffer(
        self,
        user: str,
        content: str,
        message_id: str,
        channel: str,
        area: str,
        timestamp: str,
    ) -> None:
        """将消息加入用户上下文缓冲区，并清理过期条目。"""
        now = time.time()
        window = PROFANITY_CONFIG.get("context_window", 30)
        max_messages = PROFANITY_CONFIG.get("context_max_messages", 10)

        buffer = self._user_msg_buffer.setdefault(user, [])
        buffer.append({
            "content": content,
            "message_id": message_id,
            "channel": channel,
            "area": area,
            "timestamp": timestamp,
            "time": now,
        })
        cutoff = now - window
        self._user_msg_buffer[user] = [item for item in buffer if item["time"] >= cutoff][-max_messages:]

        if now - self._last_cleanup > 60:
            self._evict_stale_users(cutoff)
            self._last_cleanup = now

    def _evict_stale_users(self, cutoff: float) -> None:
        """清理长时间不活跃的用户缓冲，防止内存无限增长。"""
        now = time.time()
        stale = [u for u, buf in self._user_msg_buffer.items()
                 if not buf or buf[-1]["time"] < cutoff]
        for u in stale:
            self._user_msg_buffer.pop(u, None)
        if len(self._user_msg_buffer) > self._MAX_TRACKED_USERS:
            by_time = sorted(self._user_msg_buffer.items(), key=lambda x: x[1][-1]["time"] if x[1] else 0)
            for u, _ in by_time[:len(by_time) - self._MAX_TRACKED_USERS]:
                self._user_msg_buffer.pop(u, None)
        warn_stale = [u for u, (_, ts) in self._warnings.items()
                      if now - ts > self._WARN_EXPIRE_SECONDS]
        for u in warn_stale:
            self._warnings.pop(u, None)

    def check_context_profanity(self, user: str) -> Optional[tuple[str, list[dict]]]:
        """检测用户上下文拼接后是否命中违禁词。"""
        buffer = self._user_msg_buffer.get(user, [])
        cleaned_messages = [self.clean_text(item["content"]) for item in buffer]
        context_match = match_context_keyword(cleaned_messages, self._keywords)
        if not context_match:
            return None

        keyword, start = context_match
        return keyword, buffer[start:]

    def get_user_buffer(self, user: str) -> list[dict]:
        """返回用户当前的上下文缓冲。"""
        return list(self._user_msg_buffer.get(user, []))

    @classmethod
    def actual_mute_duration(cls, minutes: int) -> int:
        """返回 API 实际生效的禁言时长。"""
        return resolve_mute_duration(minutes)

    @staticmethod
    def format_duration(minutes: int) -> str:
        """将分钟数格式化为更易读的时长。"""
        return format_mute_duration(minutes)

    def handle_profanity(
        self,
        user: str,
        channel: str,
        area: str,
        matched: str,
        messages: list[dict],
    ) -> None:
        """处理违禁消息，包括撤回、警告和自动禁言。"""
        from name_resolver import NameResolver

        name = NameResolver().user(user) or user[:8]
        duration = PROFANITY_CONFIG.get("mute_duration", 5)
        actual_duration = self.actual_mute_duration(duration)
        display = self.format_duration(actual_duration)

        if PROFANITY_CONFIG.get("recall_message"):
            for message in messages:
                message_id = message.get("message_id")
                if not message_id:
                    continue
                self._sender.recall_message(
                    message_id,
                    area=message.get("area", area),
                    channel=message.get("channel", channel),
                    timestamp=message.get("timestamp", ""),
                )

        if PROFANITY_CONFIG.get("warn_before_mute"):
            now = time.time()
            prev_count, _ = self._warnings.get(user, (0, 0.0))
            count = prev_count + 1
            self._warnings[user] = (count, now)
            if count < 2:
                self._sender.send_message(
                    f"[!] {name} 请文明发言，再犯将被禁言 {display}",
                    channel=channel,
                    area=area,
                )
                return
            self._warnings[user] = (0, now)

        result = self._sender.mute_user(user, area=area, duration=duration)
        if "error" in result:
            logger.warning("自动禁言 %s 失败: %s", name, result["error"])
            self._sender.send_message(
                f"[!] {name} 发送违规内容，自动禁言失败",
                channel=channel,
                area=area,
            )
        else:
            logger.info("自动禁言: %s 触发关键词 [%s]（%s条消息），禁言 %s", name, matched, len(messages), display)
            self._sender.send_message(
                f"[!] {name} 因发送违规内容被自动禁言 {display}",
                channel=channel,
                area=area,
            )

        self._user_msg_buffer.pop(user, None)
