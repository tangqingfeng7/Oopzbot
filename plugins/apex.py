"""Apex Legends 玩家战绩与游戏信息查询插件。"""

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

from ._apex_api import ApexApiClient
from ._apex_formatters import (
    build_help_text,
    format_crafting_rotation,
    format_map_rotation,
    format_player_stats,
    format_predator,
)

logger = get_logger("ApexPlugin")


class ApexPlugin(BotModule):
    def __init__(self) -> None:
        self._config: dict = {}
        self._api: Optional[ApexApiClient] = None
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
            "plugins._apex_api",
            "plugins._apex_formatters",
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

    def on_load(self, handler, config=None) -> None:
        self._handler = handler
        self._config = (config or {}).copy()
        self._api = ApexApiClient(self._config)

    def on_unload(self) -> None:
        pass

    def handle_mention(self, text, channel, area, user, handler) -> bool:
        for prefix in self.command_capabilities.mention_prefixes:
            if text.startswith(prefix):
                command = text[len(prefix):].strip()
                self._dispatch(command, channel, area, user, handler)
                return True
        return False

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        if (command or "").strip().lower() != "/apex":
            return False
        parts = []
        if subcommand:
            parts.append(subcommand)
        if arg:
            parts.append(arg)
        self._dispatch(" ".join(parts).strip(), channel, area, user, handler)
        return True

    def _dispatch(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        try:
            self._dispatch_inner(command_text, channel, area, user, handler)
        except Exception as exc:
            logger.exception("ApexPlugin: command failed: %s", command_text)
            self._send(handler, f"Apex 查询出错: {exc}", channel, area)

    def _dispatch_inner(self, command_text: str, channel: str, area: str, user: str, handler) -> None:
        text = command_text.strip()
        lower = text.lower()

        if not text or lower in {"help", "帮助"}:
            self._send(handler, build_help_text(), channel, area)
            return

        if lower in {"map", "地图", "地图轮换", "轮换"}:
            self._send_map_rotation(handler, channel, area)
            return

        if lower in {"crafting", "合成", "复制器", "制造"}:
            self._send_crafting(handler, channel, area)
            return

        if lower in {"predator", "猎杀者", "猎杀", "pred", "大师"}:
            self._send_predator(handler, channel, area)
            return

        if lower.startswith("player "):
            args = text.split(None, 2)
            player_name = args[1] if len(args) > 1 else ""
            platform = args[2] if len(args) > 2 else ""
            if player_name:
                self._send_player(player_name, platform, handler, channel, area)
                return
            self._send(handler, "请提供玩家名称，例如: /apex player Shroud PC", channel, area)
            return

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].lower() in (
            "pc", "origin", "steam", "ps", "ps4", "ps5",
            "playstation", "xbox", "x1", "xb", "switch", "ns",
        ):
            self._send_player(parts[0], parts[1], handler, channel, area)
            return

        self._send_player(text, "", handler, channel, area)

    def _send_player(self, player_name: str, platform: str, handler, channel: str, area: str) -> None:
        if not self._api:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key，请先在配置中填写 Apex Legends API Key。", channel, area)
            return

        if not platform:
            platform = str(self._config.get("default_platform", "PC") or "PC")

        self._send(handler, f"正在查询 \"{player_name}\" ({platform}) ...", channel, area)

        data = self._api.get_player(player_name, platform)
        result = format_player_stats(data)
        self._send(handler, result, channel, area)

    def _send_map_rotation(self, handler, channel: str, area: str) -> None:
        if not self._api:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = self._api.get_map_rotation()
        self._send(handler, format_map_rotation(data), channel, area)

    def _send_crafting(self, handler, channel: str, area: str) -> None:
        if not self._api:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = self._api.get_crafting_rotation()
        self._send(handler, format_crafting_rotation(data), channel, area)

    def _send_predator(self, handler, channel: str, area: str) -> None:
        if not self._api:
            self._send(handler, "插件未正确初始化。", channel, area)
            return

        if not self._api.configured:
            self._send(handler, "插件未配置 api_key。", channel, area)
            return

        data = self._api.get_predator()
        self._send(handler, format_predator(data), channel, area)

    @staticmethod
    def _send(handler, text: str, channel: str, area: str) -> None:
        handler.sender.send_message(text, channel=channel, area=area)
