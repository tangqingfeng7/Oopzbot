"""Steam 游戏价格查询与史低提醒插件 (IsThereAnyDeal 数据源)。"""

from __future__ import annotations

from typing import Optional

from logger_config import get_logger
from plugin_base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
    parse_int,
    validate_min,
    validate_range,
)

from ._steam_price_api import SteamPriceApiClient
from ._steam_price_monitor import SteamPriceMonitor
from ._steam_price_store import SteamPriceStore

logger = get_logger("SteamPricePlugin")


_HELP_TEXT = (
    "**Steam 游戏价格查询**\n"
    "\n"
    "**查询价格**\n"
    "  @bot steam <游戏名>  |  /steam <游戏名>\n"
    "\n"
    "**个人关注 (史低提醒)**\n"
    "  @bot steam 关注 <游戏名>  |  /steam watch <游戏名>\n"
    "  @bot steam 取关 <ID>      |  /steam unwatch <ID>\n"
    "  @bot steam 关注列表        |  /steam watchlist\n"
    "\n"
    "**频道推送 (管理员)**\n"
    "  @bot steam 开启推送  |  /steam push on\n"
    "  @bot steam 关闭推送  |  /steam push off\n"
    "\n"
    "  @bot steam 帮助  |  /steam help\n"
    "\n"
    "数据来源: IsThereAnyDeal.com | 支持中英文搜索"
)


def _fmt_price(amount: Optional[float], currency: str = "") -> str:
    if amount is None:
        return "暂无"
    label = currency or "USD"
    return f"{label} {amount:.2f}"


def _strip_prefix(text: str, prefix: str) -> str:
    """安全地移除前缀字符串（不像 lstrip 那样按字符剥离）。"""
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def _format_game_detail(detail: dict) -> str:
    """将组合查询结果格式化为展示文本。"""
    title = detail.get("title") or "Unknown"
    appid = detail.get("appid")
    itad_id = detail.get("itad_id") or ""
    currency = detail.get("currency") or "USD"

    lines = [f"**{title}**"]

    current = detail.get("current_price")
    regular = detail.get("regular_price")
    cut = detail.get("current_cut", 0)
    shop = detail.get("current_shop", "")

    if current is not None:
        price_line = f"当前最低: {_fmt_price(current, currency)}"
        if cut:
            price_line += f" (-{cut}%)"
        if regular and cut:
            price_line += f"  原价 {_fmt_price(regular, currency)}"
        if shop:
            price_line += f"  @ {shop}"
        lines.append(price_line)
    elif detail.get("steam_price_final") is not None:
        sp = detail["steam_price_final"]
        si = detail.get("steam_price_initial")
        price_line = f"Steam 当前: CNY {sp:.2f}"
        if si and si > sp:
            price_line += f" (原价 CNY {si:.2f})"
        lines.append(price_line)

    h_price = detail.get("history_low_price")
    h_cut = detail.get("history_low_cut", 0)
    h_shop = detail.get("history_low_shop", "")
    h_date = detail.get("history_low_date", "")

    lowest = detail.get("lowest_price")
    lowest_cut = detail.get("lowest_cut", 0)
    lowest_shop = detail.get("lowest_shop", "")
    lowest_date = detail.get("lowest_date", "")

    history_same_as_lowest = (
        h_price is not None
        and lowest is not None
        and abs(h_price - lowest) < 0.01
    )

    if h_price is not None:
        hl_line = f"史低: {_fmt_price(h_price, currency)}"
        if h_cut:
            hl_line += f" (-{h_cut}%)"
        if h_shop:
            hl_line += f"  @ {h_shop}"
        if h_date:
            hl_line += f"  [{h_date[:10]}]"
        lines.append(hl_line)

        if not history_same_as_lowest and lowest is not None:
            low_line = f"近期低价: {_fmt_price(lowest, currency)}"
            if lowest_cut:
                low_line += f" (-{lowest_cut}%)"
            if lowest_shop:
                low_line += f"  @ {lowest_shop}"
            if lowest_date:
                low_line += f"  [{lowest_date[:10]}]"
            lines.append(low_line)
    elif lowest is not None:
        low_line = f"史低: {_fmt_price(lowest, currency)}"
        if lowest_cut:
            low_line += f" (-{lowest_cut}%)"
        if lowest_shop:
            low_line += f"  @ {lowest_shop}"
        if lowest_date:
            low_line += f"  [{lowest_date[:10]}]"
        lines.append(low_line)

    if current is not None and h_price is not None and h_price > 0:
        if current <= h_price:
            lines.append("** 当前价格已达史低! **")

    link_parts = []
    if appid:
        link_parts.append(f"Steam: https://store.steampowered.com/app/{appid}")
    if itad_id:
        link_parts.append(f"ITAD: https://isthereanydeal.com/game/id:{itad_id}/")
    if link_parts:
        lines.append("  ".join(link_parts))

    return "\n".join(lines)


class SteamPricePlugin(BotModule):
    def __init__(self) -> None:
        self._config: dict = {}
        self._api: Optional[SteamPriceApiClient] = None
        self._store: Optional[SteamPriceStore] = None
        self._monitor: Optional[SteamPriceMonitor] = None
        self._handler = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="steam_price",
            description="Steam 游戏价格查询与史低提醒 (ITAD)",
            version="2.1.0",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("steam", "Steam", "STEAM", "查价", "游戏价格"),
            slash_commands=("/steam",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (
            "plugins._steam_price_api",
            "plugins._steam_price_store",
            "plugins._steam_price_monitor",
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False, description="是否启用插件", example=False),
                PluginConfigField(
                    "api_key", default="",
                    description="IsThereAnyDeal API Key (在 https://isthereanydeal.com/apps/my/ 免费申请)",
                ),
                PluginConfigField("proxy", default="", description="HTTP 代理地址"),
                PluginConfigField(
                    "country", default="CN",
                    description="价格地区代码 (ISO 3166-1 alpha-2)，如 CN/US/EU",
                ),
                PluginConfigField(
                    "request_timeout_sec",
                    default=15, cast=parse_int, validator=validate_min(1),
                    description="API 请求超时秒数", constraint=">= 1",
                ),
                PluginConfigField(
                    "request_retries",
                    default=2, cast=parse_int, validator=validate_range(1, 5),
                    description="API 请求重试次数", constraint="1 - 5",
                ),
                PluginConfigField(
                    "check_interval_sec",
                    default=1800, cast=parse_int, validator=validate_min(300),
                    description="后台价格检查间隔秒数", constraint=">= 300",
                ),
                PluginConfigField(
                    "max_watches_per_user",
                    default=20, cast=parse_int, validator=validate_range(1, 100),
                    description="每用户最大关注数", constraint="1 - 100",
                ),
                PluginConfigField(
                    "min_discount_for_push",
                    default=50, cast=parse_int, validator=validate_range(0, 100),
                    description="频道推送最低折扣百分比", constraint="0 - 100",
                ),
            )
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def on_load(self, handler, config=None) -> None:
        self._handler = handler
        self._config = (config or {}).copy()
        self._api = SteamPriceApiClient(self._config)
        self._store = SteamPriceStore()
        self._monitor = SteamPriceMonitor(self._config, self._api, self._store)
        if self._store.any_subscriptions() and self._api.configured:
            try:
                self._monitor.ensure_started(handler)
            except Exception as exc:
                logger.warning("SteamPricePlugin: monitor preload skipped: %s", exc)

    def on_unload(self) -> None:
        if self._monitor:
            self._monitor.stop()

    # ------------------------------------------------------------------
    # 命令入口
    # ------------------------------------------------------------------

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        for prefix in self.command_capabilities.mention_prefixes:
            if text.startswith(prefix):
                command = text[len(prefix):].strip()
                self._dispatch(command, channel, area, user, handler)
                return True
        return False

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        if (command or "").strip().lower() != "/steam":
            return False
        parts = []
        if subcommand:
            parts.append(subcommand)
        if arg:
            parts.append(arg)
        self._dispatch(" ".join(parts).strip(), channel, area, user, handler)
        return True

    # ------------------------------------------------------------------
    # 命令分发
    # ------------------------------------------------------------------

    def _dispatch(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        try:
            self._dispatch_inner(command_text, channel, area, user, handler)
        except Exception as exc:
            logger.exception("SteamPricePlugin: command failed: %s", command_text)
            self._send(handler, f"Steam 查询出错: {exc}", channel, area)

    def _dispatch_inner(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        text = command_text.strip()
        lower = text.lower()

        if not text or lower in {"help", "帮助"}:
            self._send(handler, _HELP_TEXT, channel, area)
            return

        if lower in {"watchlist", "关注列表", "我的关注", "列表"}:
            self._show_watchlist(user, handler, channel, area)
            return

        if lower.startswith("watch "):
            game_name = text.split(None, 1)[1].strip()
            self._add_watch(game_name, user, handler, channel, area)
            return
        if text.startswith("关注"):
            game_name = _strip_prefix(text, "关注").strip()
            if not game_name:
                self._send(handler, "请提供游戏名称，例如: @bot steam 关注 Cyberpunk 2077", channel, area)
                return
            self._add_watch(game_name, user, handler, channel, area)
            return

        if lower.startswith("unwatch "):
            id_text = text.split(None, 1)[1].strip()
            if not id_text.isdigit():
                self._send(handler, "请提供关注 ID，例如: @bot steam 取关 1\n先用 \"关注列表\" 查看 ID", channel, area)
                return
            self._remove_watch(int(id_text), user, handler, channel, area)
            return
        if text.startswith("取关"):
            id_text = _strip_prefix(text, "取关").strip()
            if not id_text or not id_text.isdigit():
                self._send(handler, "请提供关注 ID，例如: @bot steam 取关 1\n先用 \"关注列表\" 查看 ID", channel, area)
                return
            self._remove_watch(int(id_text), user, handler, channel, area)
            return

        if lower in {"push on", "开启推送"}:
            self._toggle_channel_push(True, handler, channel, area)
            return

        if lower in {"push off", "关闭推送"}:
            self._toggle_channel_push(False, handler, channel, area)
            return

        self._query_price(text, handler, channel, area)

    # ------------------------------------------------------------------
    # 价格查询
    # ------------------------------------------------------------------

    def _query_price(self, keyword: str, handler, channel: str, area: str) -> None:
        if not self._api:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key，请先在配置中填写 IsThereAnyDeal API Key。", channel, area)
            return

        self._send(handler, f"正在搜索 \"{keyword}\" ...", channel, area)

        detail = self._api.search_and_price(keyword)
        if not detail:
            self._send(handler, f"未找到与 \"{keyword}\" 相关的游戏。", channel, area)
            return

        text = _format_game_detail(detail)

        others = detail.get("others") or []
        if others:
            other_lines = []
            for o in others[:4]:
                t = o.get("title") or o.get("name") or ""
                aid = o.get("appid")
                extra = f" (appid: {aid})" if aid else ""
                other_lines.append(f"  - {t}{extra}")
            if other_lines:
                text += "\n\n其他匹配:\n" + "\n".join(other_lines)

        self._send(handler, text, channel, area)

    # ------------------------------------------------------------------
    # 个人关注
    # ------------------------------------------------------------------

    def _add_watch(self, game_name: str, user: str, handler, channel: str, area: str) -> None:
        if not self._api or not self._store:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key。", channel, area)
            return

        max_watches = int(self._config.get("max_watches_per_user", 20) or 20)
        if self._store.count_personal_watches(user) >= max_watches:
            self._send(handler, f"关注数已达上限 ({max_watches})，请先取消部分关注。", channel, area)
            return

        detail = self._api.search_and_price(game_name)
        if not detail:
            self._send(handler, f"未找到与 \"{game_name}\" 相关的游戏。", channel, area)
            return

        itad_id = detail.get("itad_id") or ""
        if not itad_id:
            self._send(handler, "无法获取该游戏的 ITAD 标识，关注失败。", channel, area)
            return

        if self._store.is_watching(user, itad_id):
            self._send(handler, f"你已经关注了 {detail.get('title', game_name)}。", channel, area)
            return

        current_price = detail.get("current_price")
        history_low = detail.get("history_low_price")
        currency = detail.get("currency") or "USD"
        title = detail.get("title") or game_name

        watch_id = self._store.add_personal_watch(
            user_id=user,
            itad_id=itad_id,
            app_id=detail.get("appid"),
            game_name=title,
            current_price=current_price,
            lowest_price=history_low,
            channel=channel,
            area=area,
        )

        if self._monitor:
            self._monitor.ensure_started(self._handler or handler)

        lines = [
            f"已关注 **{title}** (ID: {watch_id})",
            f"当前最低: {_fmt_price(current_price, currency)}",
            f"史低: {_fmt_price(history_low, currency)}",
            "价格达到史低时将自动提醒你。",
        ]
        self._send(handler, "\n".join(lines), channel, area)

    def _remove_watch(self, watch_id: int, user: str, handler, channel: str, area: str) -> None:
        if not self._store:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if self._store.remove_personal_watch(watch_id, user):
            self._send(handler, f"已取消关注 (ID: {watch_id})", channel, area)
        else:
            self._send(handler, f"未找到关注 {watch_id}（可能不存在或不属于你）", channel, area)

    def _show_watchlist(self, user: str, handler, channel: str, area: str) -> None:
        if not self._store:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        watches = self._store.get_personal_watches(user)
        if not watches:
            self._send(handler, "你还没有关注任何游戏。\n使用 \"@bot steam 关注 <游戏名>\" 添加关注。", channel, area)
            return

        lines = ["**我的 Steam 关注列表**", ""]
        for w in watches:
            current = w.get("current_price")
            lowest = w.get("lowest_price")
            current_text = f"{current:.2f}" if current is not None else "N/A"
            lowest_text = f"{lowest:.2f}" if lowest is not None else "N/A"
            lines.append(
                f"[{w['id']}] {w['game_name']}  |  当前 {current_text}  |  史低 {lowest_text}"
            )
        lines.append(f"\n共 {len(watches)} 个关注  |  取消: @bot steam 取关 <ID>")
        self._send(handler, "\n".join(lines), channel, area)

    # ------------------------------------------------------------------
    # 频道推送
    # ------------------------------------------------------------------

    def _toggle_channel_push(self, enable: bool, handler, channel: str, area: str) -> None:
        if not self._store:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if enable:
            min_discount = int(self._config.get("min_discount_for_push", 50) or 50)
            self._store.subscribe_channel(channel, area, min_discount)
            if self._monitor and self._api and self._api.configured:
                self._monitor.ensure_started(self._handler or handler)
            self._send(
                handler,
                f"已开启当前频道的 Steam 特惠推送 (折扣 >= {min_discount}% 时推送)。",
                channel, area,
            )
        else:
            if not self._store.is_channel_subscribed(channel, area):
                self._send(handler, "当前频道尚未开启 Steam 特惠推送。", channel, area)
                return
            self._store.unsubscribe_channel(channel, area)
            self._send(handler, "已关闭当前频道的 Steam 特惠推送。", channel, area)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @staticmethod
    def _send(handler, text: str, channel: str, area: str) -> None:
        handler.sender.send_message(text, channel=channel, area=area)
