"""按键分槽的 TTL 缓存
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class TtlCache:
    """最多保存 ``maxsize`` 个键的 TTL 缓存，超出时淘汰最久未使用的。"""

    def __init__(self, ttl: float, maxsize: int = 32) -> None:
        self._ttl = max(0.0, float(ttl))
        self._maxsize = max(1, int(maxsize))
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.time() - stored_at >= self._ttl:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (time.time(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._maxsize:
            self._entries.popitem(last=False)

    def invalidate(self, key: str | None = None) -> None:
        """清除指定键；不传键则清空整个缓存。"""
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["TtlCache"]
