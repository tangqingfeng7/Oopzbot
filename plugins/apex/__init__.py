"""Apex Legends 玩家战绩与游戏信息查询插件。"""

from __future__ import annotations

from domain.plugins.base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
    parse_int,
    validate_min,
    validate_range,
)
from plugins._shared.command_mixin import PluginCommandMixin

from .api import ApexApiClient
from .formatters import (
    build_help_text,
    format_crafting_rotation,
    format_map_rotation,
    format_player_stats,
    format_predator,
)


class ApexPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "Apex 查询出错"
    command_log_name = "ApexPlugin"

    def __init__(self) -> None:
        self._config: dict = {}
        self._api: ApexApiClient | None = None
        self._handler = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="apex",
            description="Apex Legends 玩家战绩与游戏信息查询",
            version="1.0.0",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("apex", "Apex", "APEX", "apex查询"),
            slash_commands=("/apex",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (
            "plugins.apex.api",
            "plugins.apex.formatters",
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False, description="是否启用插件", example=False),
                PluginConfigField(
                    "api_key",
                    default="",
                    description="Apex Legends API Key (在 https://portal.apexlegendsapi.com/ 免费申请)",
                ),
                PluginConfigField("proxy", default="", description="HTTP 代理地址"),
                PluginConfigField(
                    "default_platform",
                    default="PC",
                    choices=("PC", "PS4", "X1", "SWITCH"),
                    description="默认查询平台",
                    constraint="PC | PS4 | X1 | SWITCH",
                ),
                PluginConfigField(
                    "request_timeout_sec",
                    default=15,
                    cast=parse_int,
                    validator=validate_min(1),
                    description="API 请求超时秒数",
                    constraint=">= 1",
                ),
                PluginConfigField(
                    "request_retries",
                    default=2,
                    cast=parse_int,
                    validator=validate_range(1, 5),
                    description="API 请求重试次数",
                    constraint="1 - 5",
                ),
            )
        )

    async def on_load(self, handler, config=None) -> None:
        await self.on_unload()
        self._handler = handler
        self._config = (config or {}).copy()
        if not self._config.get("enabled", False):
            return
        self._api = ApexApiClient(self._config)

    async def on_unload(self) -> None:
        api, self._api = self._api, None
        if api is not None:
            await api.close()

    async def dispatch_command(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        if not self._config.get("enabled", False):
            await self._send(
                handler,
                "apex 插件当前未启用，请在 config/plugins/apex/config.json 中设置 enabled=true 后重载插件配置。",
                channel,
                area,
            )
            return
        text = command_text.strip()
        lower = text.lower()

        if not text or lower in {"help", "帮助"}:
            await self._send(handler, build_help_text(), channel, area)
            return

        if lower in {"map", "地图", "地图轮换", "轮换"}:
            await self._send_map_rotation(handler, channel, area)
            return

        if lower in {"crafting", "合成", "复制器", "制造"}:
            await self._send_crafting(handler, channel, area)
            return

        if lower in {"predator", "猎杀者", "猎杀", "pred", "大师"}:
            await self._send_predator(handler, channel, area)
            return

        if lower.startswith("player "):
            args = text.split(None, 2)
            player_name = args[1] if len(args) > 1 else ""
            platform = args[2] if len(args) > 2 else ""
            if player_name:
                await self._send_player(player_name, platform, handler, channel, area)
                return
            await self._send(handler, "请提供玩家名称，例如: /apex player Shroud PC", channel, area)
            return

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].lower() in (
            "pc", "origin", "steam", "ps", "ps4", "ps5",
            "playstation", "xbox", "x1", "xb", "switch", "ns",
        ):
            await self._send_player(parts[0], parts[1], handler, channel, area)
            return

        await self._send_player(text, "", handler, channel, area)

    async def _send_player(self, player_name: str, platform: str, handler, channel: str, area: str) -> None:
        if not self._api:
            await self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            await self._send(handler, "插件未配置 api_key，请先在配置中填写 Apex Legends API Key。", channel, area)
            return

        if not platform:
            platform = str(self._config.get("default_platform", "PC") or "PC")

        await self._send(handler, f"正在查询 \"{player_name}\" ({platform}) ...", channel, area)

        data = await self._api.get_player(player_name, platform)
        result = format_player_stats(data)
        await self._send(handler, result, channel, area)

    async def _send_map_rotation(self, handler, channel: str, area: str) -> None:
        if not self._api:
            await self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            await self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = await self._api.get_map_rotation()
        await self._send(handler, format_map_rotation(data), channel, area)

    async def _send_crafting(self, handler, channel: str, area: str) -> None:
        if not self._api:
            await self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            await self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = await self._api.get_crafting_rotation()
        await self._send(handler, format_crafting_rotation(data), channel, area)

    async def _send_predator(self, handler, channel: str, area: str) -> None:
        if not self._api:
            await self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            await self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = await self._api.get_predator()
        await self._send(handler, format_predator(data), channel, area)
