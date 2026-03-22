"""AI 对话上下文记忆 -- 按 user+channel 粒度存储在 Redis 中。"""

from __future__ import annotations

import json
from typing import Optional

from logger_config import get_logger

logger = get_logger("ConversationMemory")


class ConversationMemory:
    """按 user+channel 粒度管理 AI 对话历史，Redis 后端。

    每个 key 存储一个 JSON 数组，元素为 {"role": "user"|"assistant", "content": str}。
    每次 add_round 后重设 TTL。
    """

    REDIS_KEY_PREFIX = "ai:history"

    def __init__(self, redis_client, max_rounds: int = 10, ttl_seconds: int = 1800):
        self._redis = redis_client
        self._max_rounds = max(0, int(max_rounds))
        self._ttl = max(0, int(ttl_seconds))

    def _key(self, user: str, channel: str) -> str:
        return f"{self.REDIS_KEY_PREFIX}:{user}:{channel}"

    def get_history(self, user: str, channel: str) -> list[dict]:
        """返回对话历史列表 [{"role": "user", "content": ...}, ...]，按时间正序。"""
        if not self._max_rounds:
            return []
        try:
            raw = self._redis.get(self._key(user, channel))
            if not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception as e:
            logger.debug("读取对话历史失败 (user=%s, ch=%s): %s", user[:8], channel[:8], e)
        return []

    def add_round(self, user: str, channel: str, user_msg: str, assistant_msg: str) -> None:
        """追加一轮对话（user + assistant），超过 max_rounds 时裁剪最旧的轮次。"""
        if not self._max_rounds:
            return
        key = self._key(user, channel)
        history = self.get_history(user, channel)
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})

        max_messages = self._max_rounds * 2
        if len(history) > max_messages:
            history = history[-max_messages:]

        try:
            payload = json.dumps(history, ensure_ascii=False)
            if self._ttl > 0:
                self._redis.set(key, payload, ex=self._ttl)
            else:
                self._redis.set(key, payload)
        except Exception as e:
            logger.debug("保存对话历史失败 (user=%s, ch=%s): %s", user[:8], channel[:8], e)

    def clear(self, user: str, channel: str) -> bool:
        """清空指定用户+频道的对话历史。"""
        try:
            return bool(self._redis.delete(self._key(user, channel)))
        except Exception as e:
            logger.debug("清除对话历史失败: %s", e)
            return False

    def clear_user(self, user: str) -> int:
        """清空指定用户在所有频道的历史（使用 SCAN 匹配）。"""
        pattern = f"{self.REDIS_KEY_PREFIX}:{user}:*"
        count = 0
        try:
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    count += self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug("批量清除用户对话历史失败 (user=%s): %s", user[:8], e)
        return count


def create_conversation_memory(redis_client) -> Optional[ConversationMemory]:
    """工厂函数：从 DOUBAO_CONFIG 读取参数创建 ConversationMemory 实例。"""
    try:
        from config import DOUBAO_CONFIG
    except Exception:
        DOUBAO_CONFIG = {}

    if not DOUBAO_CONFIG.get("enabled"):
        return None

    max_rounds = int(DOUBAO_CONFIG.get("context_max_rounds", 10) or 0)
    ttl = int(DOUBAO_CONFIG.get("context_ttl_seconds", 1800) or 0)

    if max_rounds <= 0:
        logger.info("AI 对话上下文记忆已禁用 (context_max_rounds=%d)", max_rounds)
        return None

    logger.info("AI 对话上下文记忆已启用: max_rounds=%d, ttl=%ds", max_rounds, ttl)
    return ConversationMemory(redis_client, max_rounds=max_rounds, ttl_seconds=ttl)
