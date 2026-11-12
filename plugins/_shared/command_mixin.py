"""插件共享的命令入口样板（mention/slash 分发）。

把各插件重复的 handle_mention 前缀剥离、handle_slash 命令匹配、_dispatch 异常包装
与统一发送收敛到一个 mixin。子类只需实现 ``dispatch_command``，mention 前缀与 slash
命令名取自 ``command_capabilities``，错误文案与日志通道用类属性定制。
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from core.logger_config import get_logger
from domain.plugins.base import PluginCommandCapabilities


class _CommandCapabilitiesProvider(Protocol):
    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        ...


class PluginCommandMixin:
    """为插件提供统一的 mention/slash 命令入口。

    用法::

        class FooPlugin(PluginCommandMixin, BotModule):
            command_error_prefix = "Foo 查询出错"
            command_log_name = "FooPlugin"

            async def dispatch_command(self, command_text, channel, area, user, handler):
                ...
    """

    # 命令异常时回复用户的前缀文案（如「Apex 查询出错」）。
    command_error_prefix: str = "命令出错"
    # 异常日志通道名。
    command_log_name: str = "Plugin"

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        """委托给 MRO 中的插件基类，声明 mixin 所需的宿主能力。"""

        parent = cast(_CommandCapabilitiesProvider, super())
        return parent.command_capabilities

    async def handle_mention(self, text: str, channel: str, area: str, user: str, handler: Any) -> bool:
        for prefix in sorted(self.command_capabilities.mention_prefixes, key=len, reverse=True):
            if text.startswith(prefix):
                await self._run_plugin_command(text[len(prefix):].strip(), channel, area, user, handler)
                return True
        return False

    async def handle_slash(
        self,
        command: str,
        subcommand: str | None,
        arg: str | None,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        aliases = {str(c).strip().lower() for c in self.command_capabilities.slash_commands}
        if (command or "").strip().lower() not in aliases:
            return False
        parts = []
        if subcommand:
            parts.append(str(subcommand))
        if arg:
            parts.append(str(arg))
        await self._run_plugin_command(" ".join(parts).strip(), channel, area, user, handler)
        return True

    async def _run_plugin_command(
        self, command_text: str, channel: str, area: str, user: str, handler: Any
    ) -> None:
        try:
            await self.dispatch_command(command_text, channel, area, user, handler)
        except Exception as exc:
            get_logger(self.command_log_name).exception(
                "%s: command failed: %s", self.command_log_name, command_text
            )
            await self._send(handler, f"{self.command_error_prefix}: {exc}", channel, area)

    @staticmethod
    async def _send(handler: Any, text: str, channel: str, area: str) -> None:
        await handler.sender.send_message(text, channel=channel, area=area)

    async def dispatch_command(
        self, command_text: str, channel: str, area: str, user: str, handler: Any
    ) -> None:
        """子类实现：解析并执行具体命令。"""
        raise NotImplementedError
