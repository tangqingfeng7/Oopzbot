from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass
class PendingSelection:
    kind: str
    items: list[dict[str, Any]]
    query: str
    created_at: float
    expires_at: float


class SelectionService:
    """保存最近一次候选结果，供用户用编号继续操作。"""

    def __init__(self, ttl_seconds: int = 300):
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()
        self._pending: dict[tuple[str, str, str], PendingSelection] = {}

    def store(self, user: str, channel: str, area: str, kind: str, query: str, items: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock:
            self._cleanup_no_lock(now)
            self._pending[(user, channel, area)] = PendingSelection(
                kind=kind,
                items=list(items),
                query=query,
                created_at=now,
                expires_at=now + self._ttl_seconds,
            )

    def get(self, user: str, channel: str, area: str) -> PendingSelection | None:
        now = time.time()
        with self._lock:
            self._cleanup_no_lock(now)
            return self._pending.get((user, channel, area))

    def pick(self, user: str, channel: str, area: str, index: int) -> tuple[PendingSelection | None, dict[str, Any] | None]:
        selection = self.get(user, channel, area)
        if not selection:
            return None, None
        zero_index = index - 1
        if zero_index < 0 or zero_index >= len(selection.items):
            return selection, None
        return selection, selection.items[zero_index]

    def clear(self, user: str, channel: str, area: str) -> None:
        with self._lock:
            self._pending.pop((user, channel, area), None)

    def _cleanup_no_lock(self, now: float) -> None:
        expired = [key for key, value in self._pending.items() if value.expires_at <= now]
        for key in expired:
            self._pending.pop(key, None)
