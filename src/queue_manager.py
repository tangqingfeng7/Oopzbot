"""
Redis 播放队列管理模块
管理播放队列、当前播放状态、播放历史
"""

import json
from typing import Optional

import redis

from config import REDIS_CONFIG
from logger_config import get_logger

logger = get_logger("QueueManager")

# Redis 键名
KEY_QUEUE = "music:queue"
KEY_CURRENT = "music:current"
KEY_DEFAULT_CHANNEL = "music:default_channel"


class QueueManager:
    """基于 Redis 的播放队列管理器"""

    def __init__(self):
        try:
            self.redis = redis.Redis(**REDIS_CONFIG)
            self.redis.ping()
            logger.info("Redis 连接成功")
        except redis.ConnectionError as e:
            logger.error(f"Redis 连接失败: {e}")
            raise

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
        except redis.ResponseError:
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
        return self.redis.get(KEY_DEFAULT_CHANNEL)
