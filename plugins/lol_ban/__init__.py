from __future__ import annotations

from typing import TYPE_CHECKING

from core.constants import Msg
from domain.plugins.base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
)
from plugins._shared.command_mixin import PluginCommandMixin

if TYPE_CHECKING:
    from .query_service import LolQueryHandler


_HELP_TEXT = (
    "请输入QQ号\n"
    "格式: @bot 查封号 123456789  |  /lol 123456789\n"
    "官方封号查询: https://gamesafe.qq.com/query_punish.shtml"
)


class LolBanPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "封号查询出错"
    command_log_name = "LolBanPlugin"

    def __init__(self):
        self._handler: LolQueryHandler | None = None
        self._config: dict = {}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="lol_ban",
            description="LOL 封号查询（按 QQ 号）",
            version="1.0.0",
            author="",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("查封号", "封号", "lol", "LOL"),
            slash_commands=("/lol",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return ("plugins.lol_ban.query_service",)

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False),
                PluginConfigField(
                    "api_url",
                    default="",
                    example="https://yun.4png.com/api/query.html",
                ),
                PluginConfigField("token", default=""),
                PluginConfigField("proxy", default=""),
            )
        )

    async def on_load(self, handler, config=None):
        await self.on_unload()
        self._config = (config or {}).copy()
        from .query_service import LolQueryHandler
        self._handler = LolQueryHandler(self._config)

    async def on_unload(self) -> None:
        query_handler, self._handler = self._handler, None
        if query_handler is not None:
            await query_handler.close()

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        keyword = command_text.strip()
        if not keyword:
            await self._send(handler, _HELP_TEXT, channel, area)
            return
        query_handler = self._handler
        if query_handler is None:
            await self._send(handler, f"{Msg.ERR} 封号查询插件尚未初始化", channel, area)
            return
        await self._send(handler, f"{Msg.SEARCH} 正在查询 QQ {keyword} 的封号状态...", channel, area)
        reply = await query_handler.query_and_format(keyword)
        await self._send(handler, reply, channel, area)
