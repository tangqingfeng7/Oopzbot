from __future__ import annotations

from datetime import datetime

from core.logger_config import get_logger
from plugins._shared.background import IntervalWorker

from .formatters import format_daily_keyword_text

logger = get_logger("DeltaForceDailyPush")


class DeltaForceDailyKeywordPushManager(IntervalWorker):
    _NAME = "DeltaForceDailyKeywordPush"

    def __init__(self, config: dict, api_client, store) -> None:
        self._config = config or {}
        self._api = api_client
        self._store = store
        self._handler = None
        super().__init__(int(self._config.get("daily_keyword_push_check_interval_sec", 60)))
        hour_text, minute_text = str(self._config.get("daily_keyword_push_time", "08:00")).split(":", 1)
        self._push_hour, self._push_minute = int(hour_text), int(minute_text)

    def ensure_started(self, handler) -> None:
        self._handler = handler
        self._start_task()

    async def stop(self, timeout: float = 2.0) -> None:
        await super().stop(timeout=timeout)

    async def subscribe(self, channel_id: str, area_id: str) -> None:
        await self._store.upsert_daily_keyword_push_subscription(channel_id, area_id)

    async def unsubscribe(self, channel_id: str, area_id: str) -> None:
        await self._store.remove_daily_keyword_push_subscription(channel_id, area_id)

    async def is_subscribed(self, channel_id: str, area_id: str) -> bool:
        return await self._store.has_daily_keyword_push_subscription(channel_id, area_id)

    async def _tick(self) -> None:
        if not self._handler:
            return
        now = datetime.now()
        if (now.hour, now.minute) < (self._push_hour, self._push_minute):
            return
        today = now.strftime("%Y-%m-%d")
        pending = [
            sub
            for sub in await self._store.list_daily_keyword_push_subscriptions()
            if str(sub.get("last_push_date") or "") != today and sub.get("channel_id") and sub.get("area_id")
        ]
        if not pending:
            return
        payload = await self._api.get_daily_keyword()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not data.get("list"):
            return
        text = format_daily_keyword_text(payload)
        for sub in pending:
            if self.stopping:
                return
            channel_id = str(sub["channel_id"])
            area_id = str(sub["area_id"])
            try:
                await self._handler.sender.send_message(text, channel=channel_id, area=area_id)
                await self._store.mark_daily_keyword_pushed(channel_id, area_id, today)
            except Exception as exc:
                logger.warning("DeltaForceDailyPush: send failed: %s", exc)
