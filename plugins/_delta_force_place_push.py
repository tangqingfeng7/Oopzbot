"""
Background polling for Delta Force place completion notifications.
"""

from __future__ import annotations

import threading
from typing import Optional

from logger_config import get_logger

from ._delta_force_api import describe_common_failure

logger = get_logger("DeltaForcePlacePush")


class DeltaForcePlacePushManager:
    def __init__(self, config: dict, api_client, store) -> None:
        self._config = config or {}
        self._api = api_client
        self._store = store
        self._interval = max(15, int(self._config.get("place_push_interval_sec", 60) or 60))
        self._handler = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def ensure_started(self, handler) -> None:
        self._handler = handler
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="DeltaForcePlacePush", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        self._thread = None

    def subscribe(self, user_id: str, channel_id: str, area_id: str, initial_snapshot: Optional[list[dict]] = None) -> None:
        self._store.upsert_place_push_subscription(user_id, channel_id, area_id, initial_snapshot or [])

    def unsubscribe(self, user_id: str, channel_id: str, area_id: str) -> None:
        self._store.remove_place_push_subscription(user_id, channel_id, area_id)

    def is_subscribed(self, user_id: str, channel_id: str, area_id: str) -> bool:
        return self._store.has_place_push_subscription(user_id, channel_id, area_id)

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            if not self._handler:
                continue
            for sub in self._store.list_place_push_subscriptions():
                if self._stop_event.is_set():
                    return
                try:
                    self._process_subscription(sub)
                except Exception:
                    logger.exception("DeltaForcePlacePush: process subscription failed: %s", sub)

    def _process_subscription(self, sub: dict) -> None:
        user_id = str(sub.get("user_id") or "")
        channel_id = str(sub.get("channel_id") or "")
        area_id = str(sub.get("area_id") or "")
        if not user_id or not channel_id or not area_id:
            return
        token = self._store.get_active_token(user_id)
        if not token:
            return

        payload = self._api.get_place_status(token)
        if describe_common_failure(payload):
            return
        current_tasks = self.extract_active_tasks(payload)
        previous_tasks = sub.get("last_snapshot") if isinstance(sub.get("last_snapshot"), list) else []
        for text in self.find_completed_messages(previous_tasks, current_tasks):
            try:
                self._handler.sender.send_message(text, channel=channel_id, area=area_id)
            except Exception as exc:
                logger.warning("DeltaForcePlacePush: send completion failed: %s", exc)
        self._store.update_place_push_snapshot(user_id, channel_id, area_id, current_tasks)

    @staticmethod
    def extract_active_tasks(payload: dict) -> list[dict]:
        data = payload.get("data") if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else {}
        places = data.get("places") if isinstance(data.get("places"), list) else []
        tasks: list[dict] = []
        for place in places:
            if not isinstance(place, dict):
                continue
            detail = place.get("objectDetail")
            if not isinstance(detail, dict):
                continue
            object_name = str(detail.get("objectName") or detail.get("name") or "未知物品")
            place_name = str(place.get("placeName") or place.get("placeType") or "未知设施")
            level = int(place.get("level") or 0)
            try:
                left_time = max(0, int(float(place.get("leftTime") or 0)))
            except (TypeError, ValueError):
                left_time = 0
            tasks.append(
                {
                    "key": f"{place_name}|{level}|{object_name}",
                    "place_name": place_name,
                    "level": level,
                    "object_name": object_name,
                    "left_time": left_time,
                }
            )
        return tasks

    @staticmethod
    def find_completed_messages(previous_tasks: list[dict], current_tasks: list[dict]) -> list[str]:
        previous_map = {}
        for item in previous_tasks:
            if isinstance(item, dict) and item.get("key"):
                previous_map[str(item.get("key"))] = item
        current_map = {}
        for item in current_tasks:
            if isinstance(item, dict) and item.get("key"):
                current_map[str(item.get("key"))] = item

        messages: list[str] = []
        for key, prev in previous_map.items():
            curr = current_map.get(key)
            if curr is None:
                messages.append(
                    f"【三角洲特勤处】{prev.get('place_name') or '设施'} Lv.{prev.get('level') or 0} 的 "
                    f"{prev.get('object_name') or '物品'} 已制造完成。"
                )
                continue
            prev_left = int(prev.get("left_time") or 0)
            curr_left = int(curr.get("left_time") or 0)
            if prev_left > 0 and curr_left == 0:
                messages.append(
                    f"【三角洲特勤处】{curr.get('place_name') or '设施'} Lv.{curr.get('level') or 0} 的 "
                    f"{curr.get('object_name') or '物品'} 已制造完成。"
                )
        return messages
