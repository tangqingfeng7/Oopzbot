"""
Redis 播放队列管理模块
管理播放队列、当前播放状态、播放历史
"""

import json
import time
from typing import Optional

import redis

from config import REDIS_CONFIG
from logger_config import get_logger

logger = get_logger("QueueManager")

# Redis 键名
KEY_QUEUE = "music:queue"
KEY_CURRENT = "music:current"
KEY_DEFAULT_CHANNEL = "music:default_channel"


class _InMemoryRedis:
    """
    简易的内存版 Redis，用于 Redis 无法连接时的降级。
    只实现当前项目用到的最小方法集合。
    """

    def __init__(self):
        self._kv: dict[str, object] = {}
        self._lists: dict[str, list] = {}

    # --- 兼容性方法 ---
    def ping(self):
        return True

    def _get_list(self, key: str) -> list:
        return self._lists.setdefault(key, [])

    # 列表操作
    def rpush(self, key: str, value):
        self._get_list(key).append(value)

    def lrange(self, key: str, start: int, end: int):
        lst = self._lists.get(key, [])
        if end == -1:
            end = len(lst) - 1
        # redis lrange 是包含 end 的切片
        return lst[start : end + 1] if lst else []

    def llen(self, key: str) -> int:
        return len(self._lists.get(key, []))

    def lpop(self, key: str):
        lst = self._lists.get(key, [])
        if not lst:
            return None
        return lst.pop(0)

    def lindex(self, key: str, index: int):
        lst = self._lists.get(key, [])
        try:
            return lst[index]
        except IndexError:
            return None

    def lset(self, key: str, index: int, value):
        lst = self._get_list(key)
        if index < 0 or index >= len(lst):
            # 与 redis 行为保持一致，抛出错误，由上层捕获
            raise IndexError("list index out of range")
        lst[index] = value

    def lrem(self, key: str, count: int, value):
        lst = self._lists.get(key, [])
        if not lst:
            return 0
        removed = 0
        if count >= 0:
            new = []
            for item in lst:
                if removed < count and item == value:
                    removed += 1
                    continue
                new.append(item)
            self._lists[key] = new
        else:
            new = []
            for item in reversed(lst):
                if removed < -count and item == value:
                    removed += 1
                    continue
                new.append(item)
            self._lists[key] = list(reversed(new))
        return removed

    # 字符串 / 通用键
    def set(self, key: str, value):
        self._kv[key] = value

    def get(self, key: str):
        return self._kv.get(key)

    def delete(self, key: str):
        self._kv.pop(key, None)
        self._lists.pop(key, None)

    def blpop(self, key: str, timeout: int = 0):
        """
        简化版阻塞弹出：
        - timeout <= 0 时立即返回
        - timeout > 0 时在超时时间内轮询，避免忙等
        """
        end_time = time.monotonic() + max(timeout, 0)
        while True:
            lst = self._lists.get(key, [])
            if lst:
                return key, lst.pop(0)
            if timeout <= 0 or time.monotonic() >= end_time:
                return None
            # 轻量 sleep，避免 CPU 空转
            time.sleep(0.1)


class QueueManager:
    """基于 Redis 的播放队列管理器（Redis 不可用时自动回退到内存队列）"""

    def __init__(self):
        try:
            self.redis = redis.Redis(**REDIS_CONFIG)
            self.redis.ping()
            logger.info("Redis 连接成功")
        except Exception as e:
            logger.error(f"Redis 连接失败，将使用内存队列: {e}")
            self.redis = _InMemoryRedis()

    # ------------------------------------------------------------------
    # 队列操作
    # ------------------------------------------------------------------

    def add_to_queue(self, song_data: dict) -> int:
        """添加歌曲到队列尾部，返回队列中的位置（0-based）"""
        self.redis.rpush(KEY_QUEUE, json.dumps(song_data, ensure_ascii=False))
        pos = self.redis.llen(KEY_QUEUE) - 1
        logger.info(f"添加到队列: {song_data.get('name')} (位置 {pos})")
        return pos

    def play_next(self) -> Optional[dict]:
        """从队列头取出下一首"""
        data = self.redis.lpop(KEY_QUEUE)
        if data:
            song = json.loads(data)
            logger.info(f"队列弹出: {song.get('name')}")
            return song
        return None

    def peek_next(self) -> Optional[dict]:
        """查看队首下一首（不弹出），用于预加载"""
        data = self.redis.lindex(KEY_QUEUE, 0)
        if data:
            return json.loads(data)
        return None

    def get_queue(self, start: int = 0, end: int = -1) -> list:
        """获取队列列表"""
        items = self.redis.lrange(KEY_QUEUE, start, end)
        return [json.loads(item) for item in items]

    def get_queue_length(self) -> int:
        return self.redis.llen(KEY_QUEUE)

    def clear_queue(self):
        """清空队列"""
        self.redis.delete(KEY_QUEUE)
        logger.info("队列已清空")

    def remove_from_queue(self, index: int) -> bool:
        """移除队列中指定位置的歌曲"""
        try:
            placeholder = "__REMOVED__"
            self.redis.lset(KEY_QUEUE, index, placeholder)
            self.redis.lrem(KEY_QUEUE, 1, placeholder)
            logger.info(f"移除队列位置 {index}")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 当前播放
    # ------------------------------------------------------------------

    def set_current(self, song_data: dict):
        """设置当前播放歌曲"""
        self.redis.set(KEY_CURRENT, json.dumps(song_data, ensure_ascii=False))

    def get_current(self) -> Optional[dict]:
        """获取当前播放歌曲"""
        data = self.redis.get(KEY_CURRENT)
        if data:
            return json.loads(data)
        return None

    def clear_current(self):
        """清除当前播放"""
        self.redis.delete(KEY_CURRENT)

    # ------------------------------------------------------------------
    # 默认频道
    # ------------------------------------------------------------------

    def set_default_channel(self, channel: str):
        self.redis.set(KEY_DEFAULT_CHANNEL, channel)

    def get_default_channel(self) -> Optional[str]:
        val = self.redis.get(KEY_DEFAULT_CHANNEL)
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="ignore")
        return val
