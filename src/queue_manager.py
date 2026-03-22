import json
import time
from typing import Optional
import threading

import redis

from config import REDIS_CONFIG
from logger_config import get_logger

logger = get_logger("QueueManager")

# Redis 键名（全局，用于向后兼容无 area 场景）
KEY_QUEUE = "music:queue"
KEY_CURRENT = "music:current"
KEY_DEFAULT_CHANNEL = "music:default_channel"
KEY_PLAY_STATE = "music:play_state"


def _area_key(base: str, area: str) -> str:
    """生成域隔离的 Redis 键。area 为空时回退到全局键。"""
    if not area:
        return base
    return f"music:{area}:{base.split(':', 1)[1]}"

_redis_client = None
_redis_lock = threading.Lock()


class _InMemoryRedis:
    """
    简易的内存版 Redis，用于 Redis 无法连接时的降级。
    只实现当前项目用到的最小方法集合。
    """

    def __init__(self):
        self._kv: dict[str, object] = {}
        self._lists: dict[str, list] = {}
        self._expires_at: dict[str, float] = {}
        self._condition = threading.Condition()

    # --- 兼容性方法 ---
    def ping(self):
        return True

    def _get_list(self, key: str) -> list:
        return self._lists.setdefault(key, [])

    def _is_expired(self, key: str) -> bool:
        expires_at = self._expires_at.get(key)
        if expires_at is None:
            return False
        if time.time() < expires_at:
            return False
        self._kv.pop(key, None)
        self._lists.pop(key, None)
        self._expires_at.pop(key, None)
        return True

    # 列表操作
    def rpush(self, key: str, value):
        with self._condition:
            self._get_list(key).append(value)
            self._condition.notify_all()

    def lpush(self, key: str, value):
        with self._condition:
            self._get_list(key).insert(0, value)
            self._condition.notify_all()

    def lrange(self, key: str, start: int, end: int):
        with self._condition:
            lst = self._lists.get(key, [])
            if end == -1:
                end = len(lst) - 1
            return list(lst[start : end + 1]) if lst else []

    def llen(self, key: str) -> int:
        with self._condition:
            return len(self._lists.get(key, []))

    def lpop(self, key: str):
        with self._condition:
            lst = self._lists.get(key, [])
            if not lst:
                return None
            return lst.pop(0)

    def lindex(self, key: str, index: int):
        with self._condition:
            lst = self._lists.get(key, [])
            try:
                return lst[index]
            except IndexError:
                return None

    def lset(self, key: str, index: int, value):
        with self._condition:
            lst = self._get_list(key)
            if index < 0 or index >= len(lst):
                raise IndexError("list index out of range")
            lst[index] = value

    def lrem(self, key: str, count: int, value):
        with self._condition:
            lst = self._lists.get(key, [])
            if not lst:
                return 0
            removed = 0
            if count > 0:
                new = []
                for item in lst:
                    if removed < count and item == value:
                        removed += 1
                        continue
                    new.append(item)
                self._lists[key] = new
            elif count < 0:
                new = []
                for item in reversed(lst):
                    if removed < -count and item == value:
                        removed += 1
                        continue
                    new.append(item)
                self._lists[key] = list(reversed(new))
            else:
                new = [item for item in lst if item != value]
                removed = len(lst) - len(new)
                self._lists[key] = new
            return removed

    # 字符串 / 通用键
    def set(self, key: str, value, ex: Optional[int] = None, px: Optional[int] = None, **kwargs):
        with self._condition:
            self._kv[key] = value
            if px is not None:
                self._expires_at[key] = time.time() + (float(px) / 1000.0)
            elif ex is not None:
                self._expires_at[key] = time.time() + float(ex)
            else:
                self._expires_at.pop(key, None)

    def get(self, key: str):
        with self._condition:
            if self._is_expired(key):
                return None
            return self._kv.get(key)

    def delete(self, key: str):
        with self._condition:
            self._kv.pop(key, None)
            self._lists.pop(key, None)
            self._expires_at.pop(key, None)

    def blpop(self, key: str, timeout: int = 0):
        """阻塞弹出：使用 Condition 等待，避免 CPU 空转。"""
        deadline = time.monotonic() + max(timeout, 0)
        with self._condition:
            while True:
                lst = self._lists.get(key, [])
                if lst:
                    return key, lst.pop(0)
                if timeout <= 0:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)


class QueueManager:
    """基于 Redis 的播放队列管理器（Redis 不可用时自动回退到内存队列）。
    支持域隔离：传入 area 后 Redis 键自动加域前缀。"""

    def __init__(self, area: str = ""):
        self._redis = get_redis_client()
        self._area = area

    @property
    def area(self) -> str:
        return self._area

    @property
    def redis(self):
        if self._redis is None:
            self._redis = get_redis_client()
        return self._redis

    def _qkey(self) -> str:
        return _area_key(KEY_QUEUE, self._area)

    def _ckey(self) -> str:
        return _area_key(KEY_CURRENT, self._area)

    def _dkey(self) -> str:
        return _area_key(KEY_DEFAULT_CHANNEL, self._area)

    def _pskey(self) -> str:
        return _area_key(KEY_PLAY_STATE, self._area)

    # ------------------------------------------------------------------
    # 队列操作
    # ------------------------------------------------------------------

    def add_to_queue(self, song_data: dict) -> int:
        """添加歌曲到队列尾部，返回队列中的位置（0-based）"""
        r = self.redis
        key = self._qkey()
        if hasattr(r, "pipeline"):
            pipe = r.pipeline(transaction=False)
            pipe.rpush(key, json.dumps(song_data, ensure_ascii=False))
            pipe.llen(key)
            _, length = pipe.execute()
            pos = int(length) - 1
        else:
            r.rpush(key, json.dumps(song_data, ensure_ascii=False))
            pos = r.llen(key) - 1
        logger.info(f"添加到队列: {song_data.get('name')} (位置 {pos})")
        return pos

    def play_next(self) -> Optional[dict]:
        """从队列头取出下一首"""
        data = self.redis.lpop(self._qkey())
        if data:
            song = json.loads(data)
            logger.info(f"队列弹出: {song.get('name')}")
            return song
        return None

    def peek_next(self) -> Optional[dict]:
        """查看队首下一首（不弹出），用于预加载"""
        data = self.redis.lindex(self._qkey(), 0)
        if data:
            return json.loads(data)
        return None

    def get_queue(self, start: int = 0, end: int = -1) -> list:
        """获取队列列表"""
        items = self.redis.lrange(self._qkey(), start, end)
        return [json.loads(item) for item in items]

    def get_queue_length(self) -> int:
        return self.redis.llen(self._qkey())

    def clear_queue(self):
        """清空队列"""
        self.redis.delete(self._qkey())
        logger.info("队列已清空")

    def remove_from_queue(self, index: int) -> bool:
        """移除队列中指定位置的歌曲"""
        try:
            placeholder = "__REMOVED__"
            self.redis.lset(self._qkey(), index, placeholder)
            self.redis.lrem(self._qkey(), 1, placeholder)
            logger.info(f"移除队列位置 {index}")
            return True
        except Exception as e:
            logger.warning("移除队列位置 %d 失败: %s", index, e)
            return False

    # ------------------------------------------------------------------
    # 当前播放
    # ------------------------------------------------------------------

    def set_current(self, song_data: dict):
        """设置当前播放歌曲"""
        self.redis.set(self._ckey(), json.dumps(song_data, ensure_ascii=False))

    def get_current(self) -> Optional[dict]:
        """获取当前播放歌曲"""
        data = self.redis.get(self._ckey())
        if data:
            return json.loads(data)
        return None

    def clear_current(self):
        """清除当前播放"""
        self.redis.delete(self._ckey())

    # ------------------------------------------------------------------
    # 默认频道
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 播放状态（域隔离）
    # ------------------------------------------------------------------

    def set_play_state(self, state: dict):
        self.redis.set(self._pskey(), json.dumps(state))

    def get_play_state(self) -> Optional[dict]:
        raw = self.redis.get(self._pskey())
        return json.loads(raw) if raw else None

    def clear_play_state(self):
        self.redis.delete(self._pskey())

    # ------------------------------------------------------------------
    # 默认频道
    # ------------------------------------------------------------------

    def set_default_channel(self, channel: str):
        self.redis.set(self._dkey(), channel)

    def get_default_channel(self) -> Optional[str]:
        val = self.redis.get(self._dkey())
        if isinstance(val, bytes):
            return val.decode("utf-8", errors="ignore")
        return val


def get_redis_client(force_reset: bool = False):
    """返回全局共享 Redis 客户端；连接失败时统一回退到内存实现。"""
    global _redis_client
    with _redis_lock:
        if force_reset:
            _redis_client = None
        if _redis_client is None:
            try:
                client = redis.Redis(**REDIS_CONFIG)
                client.ping()
                logger.info("Redis 连接成功")
                _redis_client = client
            except Exception as e:
                logger.error(f"Redis 连接失败，将使用内存队列: {e}")
                _redis_client = _InMemoryRedis()
        return _redis_client