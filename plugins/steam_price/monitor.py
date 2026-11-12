"""Steam 价格后台异步监控，定期检测关注游戏的价格变动并推送通知。"""

from __future__ import annotations

import asyncio
from typing import Any

from core.logger_config import get_logger
from plugins._shared.background import IntervalWorker

from .api import SteamPriceApiClient
from .store import SteamPriceStore

logger = get_logger("SteamPriceMonitor")


class SteamPriceMonitor(IntervalWorker):
    """可取消任务：轮询关注列表中游戏的最新价格，触发史低/特惠推送。"""

    _NAME = "SteamPriceMonitor"

    def __init__(self, config: dict, api: SteamPriceApiClient, store: SteamPriceStore) -> None:
        self._config = config or {}
        self._api = api
        self._store = store
        super().__init__(int(self._config.get("check_interval_sec", 1800)))
        self._min_discount = int(self._config.get("min_discount_for_push", 50))
        self._handler: Any = None

    def ensure_started(self, handler) -> None:
        self._handler = handler
        if self._start_task():
            logger.info("SteamPriceMonitor: 后台监控已启动 (间隔 %ds)", self._interval)

    async def stop(self, timeout: float = 3.0) -> None:
        await super().stop(timeout=timeout)
        logger.info("SteamPriceMonitor: 已停止")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        if not self._handler:
            return
        personal_watches = await self._store.get_all_personal_watches()
        channel_subs = await self._store.get_channel_subscriptions()

        if not personal_watches and not channel_subs:
            return

        itad_ids: list[str] = []
        game_names: dict[str, str] = {}
        appid_map: dict[str, int | None] = {}
        for w in personal_watches:
            gid = w.get("itad_id") or ""
            if gid and gid not in game_names:
                itad_ids.append(gid)
                game_names[gid] = w.get("game_name") or "Unknown"
                appid_map[gid] = w.get("app_id")

        if not itad_ids:
            return

        overviews, history_lows = await asyncio.gather(
            self._api.itad_price_overview(itad_ids),
            self._api.itad_history_low(itad_ids),
        )

        await self._check_personal_alerts(personal_watches, overviews, history_lows)
        await self._check_channel_push(channel_subs, overviews, game_names, appid_map)
        await self._store.cleanup_old_logs(days=90)

    # ------------------------------------------------------------------
    # 个人关注提醒
    # ------------------------------------------------------------------

    async def _check_personal_alerts(
        self,
        watches: list[dict],
        overviews: dict[str, dict],
        history_lows: dict[str, dict],
    ) -> None:
        # 同一游戏同一价格只判定一次，本轮所有关注者都收到提醒后再统一落库。
        already_notified: dict[str, bool] = {}
        for watch in watches:
            if self.stopping:
                break
            itad_id = watch.get("itad_id") or ""
            if not itad_id:
                continue
            overview = overviews.get(itad_id, {})
            current_price = overview.get("current_price")
            if current_price is None:
                continue

            history = history_lows.get(itad_id, {})
            history_low = history.get("price")
            lowest = overview.get("lowest_price")

            await self._store.update_watch_price(int(watch["id"]), current_price, history_low or lowest)

            trigger_price = history_low if history_low is not None else lowest
            if trigger_price is None or current_price > trigger_price:
                continue
            if itad_id not in already_notified:
                already_notified[itad_id] = await self._store.has_notified(itad_id, current_price, "personal")
            if not already_notified[itad_id]:
                await self._send_personal_alert(watch, overview, history)

        for itad_id, notified in already_notified.items():
            if not notified:
                overview = overviews[itad_id]
                await self._store.mark_notified(
                    itad_id, overview["current_price"], overview.get("current_cut", 0), "personal"
                )

    async def _send_personal_alert(self, watch: dict, overview: dict, history: dict) -> None:
        channel = watch.get("channel") or ""
        area = watch.get("area") or ""
        user_id = watch.get("user_id") or ""
        if not channel or not area:
            return

        name = watch.get("game_name") or "Unknown"
        current = overview.get("current_price")
        cut = overview.get("current_cut", 0)
        currency = overview.get("currency", "USD")
        shop = overview.get("current_shop", "")
        appid = watch.get("app_id")
        itad_id = watch.get("itad_id") or ""

        lines = [f"** Steam 史低提醒 | {name} **"]
        price_text = f"{currency} {current:.2f}" if current is not None else "N/A"
        if cut:
            price_text += f" (-{cut}%)"
        if shop:
            price_text += f"  @ {shop}"
        lines.append(f"当前价格已达史低: {price_text}")

        h_low = history.get("price")
        if h_low is not None:
            h_shop = history.get("shop", "")
            h_cut = history.get("cut", 0)
            h_text = f"{currency} {h_low:.2f}"
            if h_cut:
                h_text += f" (-{h_cut}%)"
            if h_shop:
                h_text += f"  @ {h_shop}"
            lines.append(f"全网历史最低: {h_text}")

        link_parts = []
        if appid:
            link_parts.append(f"Steam: https://store.steampowered.com/app/{appid}")
        if itad_id:
            link_parts.append(f"ITAD: https://isthereanydeal.com/game/id:{itad_id}/")
        if link_parts:
            lines.append("  ".join(link_parts))

        if user_id:
            lines.append(f"@{user_id}")

        try:
            await self._handler.sender.send_message("\n".join(lines), channel=channel, area=area)
        except Exception as exc:
            logger.warning("SteamPriceMonitor: 个人提醒发送失败: %s", exc)

    # ------------------------------------------------------------------
    # 频道特惠推送
    # ------------------------------------------------------------------

    async def _check_channel_push(
        self,
        subs: list[dict],
        overviews: dict[str, dict],
        game_names: dict[str, str],
        appid_map: dict[str, int | None],
    ) -> None:
        if not subs or not overviews:
            return
        deals: list[dict] = []
        for itad_id, detail in overviews.items():
            cut = detail.get("current_cut", 0)
            current_price = detail.get("current_price")
            if (
                cut >= self._min_discount
                and current_price is not None
                and not await self._store.has_notified(itad_id, current_price, "channel")
            ):
                detail["_itad_id"] = itad_id
                detail["_game_name"] = game_names.get(itad_id, "")
                detail["_appid"] = appid_map.get(itad_id)
                deals.append(detail)

        if not deals:
            return

        deals.sort(key=lambda d: d.get("current_cut", 0), reverse=True)
        top_deals = deals[:10]

        for sub in subs:
            if self.stopping:
                return
            channel = sub.get("channel") or ""
            area = sub.get("area") or ""
            sub_min = sub.get("min_discount")
            if sub_min is None:
                sub_min = self._min_discount
            if not channel or not area:
                continue
            filtered = [d for d in top_deals if d.get("current_cut", 0) >= sub_min]
            if filtered:
                await self._send_channel_deals(filtered, channel, area)

        for deal in top_deals:
            await self._store.mark_notified(
                deal.get("_itad_id", ""),
                deal.get("current_price", 0),
                deal.get("current_cut", 0),
                "channel",
            )

    async def _send_channel_deals(self, deals: list[dict], channel: str, area: str) -> None:
        lines = ["**Steam 特惠推送**", ""]
        for d in deals:
            name = d.get("_game_name") or ""
            current = d.get("current_price")
            regular = d.get("regular_price")
            cut = d.get("current_cut", 0)
            shop = d.get("current_shop", "")
            currency = d.get("currency", "USD")
            appid = d.get("_appid")
            itad_id = d.get("_itad_id", "")

            title_line = f"**{name}**" if name else ""
            price_text = f"{currency} {current:.2f}" if current is not None else "免费"
            if regular:
                price_text += f" (原价 {regular:.2f})"
            info_line = f"-{cut}%  {price_text}"
            if shop:
                info_line += f"  @ {shop}"

            if title_line:
                lines.append(title_line)
            lines.append(info_line)

            link_parts = []
            if appid:
                link_parts.append(f"https://store.steampowered.com/app/{appid}")
            if itad_id:
                link_parts.append(f"https://isthereanydeal.com/game/id:{itad_id}/")
            if link_parts:
                lines.append("  ".join(link_parts))
            lines.append("")

        try:
            await self._handler.sender.send_message("\n".join(lines).rstrip(), channel=channel, area=area)
        except Exception as exc:
            logger.warning("SteamPriceMonitor: 频道推送发送失败: %s", exc)
