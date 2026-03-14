from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

from logger_config import get_logger

logger = get_logger("DeltaForceDailyPush")


class DeltaForceDailyKeywordPushManager:
    def __init__(self, config: dict, api_client, store) -> None:
        self._config = config or {}
        self._api = api_client
        self._store = store
        self._handler = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._interval = max(30, int(self._config.get("daily_keyword_push_check_interval_sec", 60) or 60))
        self._push_hour, self._push_minute = self._parse_push_time(
            str(self._config.get("daily_keyword_push_time") or "08:00")
        )

    @staticmethod
    def _parse_push_time(value: str) -> tuple[int, int]:
        try:
            hour_text, minute_text = (value or "08:00").split(":", 1)
            hour = min(23, max(0, int(hour_text)))
            minute = min(59, max(0, int(minute_text)))
            return hour, minute
        except Exception:
            return 8, 0

    def ensure_started(self, handler) -> None:
        self._handler = handler
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="DeltaForceDailyKeywordPush", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None

    def subscribe(self, channel_id: str, area_id: str) -> None:
        self._store.upsert_daily_keyword_push_subscription(channel_id, area_id)

    def unsubscribe(self, channel_id: str, area_id: str) -> None:
        self._store.remove_daily_keyword_push_subscription(channel_id, area_id)

    def is_subscribed(self, channel_id: str, area_id: str) -> bool:
        return self._store.has_daily_keyword_push_subscription(channel_id, area_id)

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            if not self._handler:
                continue
            now = datetime.now()
            if (now.hour, now.minute) < (self._push_hour, self._push_minute):
                continue
            today = now.strftime("%Y-%m-%d")
            for sub in self._store.list_daily_keyword_push_subscriptions():
                if self._stop_event.is_set():
                    return
                last_push_date = str(sub.get("last_push_date") or "")
                if last_push_date == today:
                    continue
                self._push_to_subscription(sub, today)

    def _push_to_subscription(self, sub: dict, today: str) -> None:
        payload = self._api.get_daily_keyword()
        if not isinstance(payload, dict):
            return
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = data.get("list") if isinstance(data.get("list"), list) else []
        if not items:
            return
        lines = ["【每日密码】"]
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(f"【{item.get('mapName') or '未知地图'}】: {item.get('secret') or '-'}")
        text = "\n".join(lines)
        channel_id = str(sub.get("channel_id") or "")
        area_id = str(sub.get("area_id") or "")
        if not channel_id or not area_id:
            return
        try:
            self._handler.sender.send_message(text, channel=channel_id, area=area_id)
            self._store.mark_daily_keyword_pushed(channel_id, area_id, today)
        except Exception as exc:
            logger.warning("DeltaForceDailyPush: send failed: %s", exc)