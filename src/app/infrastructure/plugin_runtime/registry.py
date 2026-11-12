from collections.abc import Iterator
from typing import Any

from core.logger_config import get_logger
from domain.plugins.base import BotModule, PluginCommandCapabilities, PluginDescriptor

logger = get_logger("PluginRegistry")


class PluginRegistry:
    """持有已注册插件，并负责查询、分发和异常隔离。"""

    def __init__(self) -> None:
        self._modules: dict[str, BotModule] = {}
        self._order: list[str] = []  # 插件调度顺序
        self._builtin: set[str] = set()  # 内置插件名，禁止动态卸载

    async def register(self, module: BotModule, *, builtin: bool = False) -> bool:
        """
        注册一个插件。
        如果名称已存在，则先卸载旧插件再注册新实例。
        """
        name = module.metadata.name
        if not name.strip():
            logger.warning("PluginRegistry: 拒绝注册无 name 的模块")
            return False
        if name in self._modules:
            await self.unregister(name)
        self._modules[name] = module
        if name not in self._order:
            # 注册顺序直接决定插件分发顺序，保持可预测性。
            self._order.append(name)
        if builtin:
            self._builtin.add(name)
        return True

    async def unregister(self, name: str, handler: Any = None) -> bool:
        """卸载插件并调用 `on_unload()`。"""
        if name not in self._modules:
            return False
        module = self._modules.pop(name)
        self._order = [n for n in self._order if n != name]
        self._builtin.discard(name)
        try:
            await module.on_unload()
        except Exception as e:
            logger.exception("PluginRegistry: 模块 %s on_unload 异常: %s", name, e)
        return True

    async def stop_all(self) -> None:
        """按注册的相反顺序卸载全部插件；可重复调用。"""
        for name in tuple(reversed(self._order)):
            await self.unregister(name)

    def get(self, name: str) -> BotModule | None:
        return self._modules.get(name)

    def is_builtin(self, name: str) -> bool:
        return name in self._builtin

    @staticmethod
    def _normalize_command_capabilities(capabilities: PluginCommandCapabilities) -> PluginCommandCapabilities:
        mention_prefixes = tuple(
            prefix for prefix in capabilities.mention_prefixes if isinstance(prefix, str) and prefix
        )
        slash_commands = tuple(
            command.strip().lower()
            for command in capabilities.slash_commands
            if isinstance(command, str) and command.strip()
        )
        return PluginCommandCapabilities(
            mention_prefixes=mention_prefixes,
            slash_commands=slash_commands,
            is_public_command=bool(capabilities.is_public_command),
        )

    @classmethod
    def _get_command_capabilities(cls, module: BotModule) -> PluginCommandCapabilities:
        capabilities = getattr(module, "command_capabilities", None)
        if isinstance(capabilities, PluginCommandCapabilities):
            return cls._normalize_command_capabilities(capabilities)
        return PluginCommandCapabilities()

    def describe(self, name: str) -> PluginDescriptor | None:
        """返回单个插件的标准描述对象。"""
        module = self._modules.get(name)
        if not module:
            return None
        return PluginDescriptor(
            metadata=module.metadata,
            capabilities=self._get_command_capabilities(module),
            builtin=name in self._builtin,
        )

    def list_descriptors(self) -> list[PluginDescriptor]:
        """返回所有已注册插件的标准描述对象。"""
        result: list[PluginDescriptor] = []
        for name in self._order:
            descriptor = self.describe(name)
            if descriptor:
                result.append(descriptor)
        return result

    def list_command_descriptors(self, public_only: bool = False) -> list[PluginDescriptor]:
        """返回带命令声明的插件描述对象。"""
        result: list[PluginDescriptor] = []
        for descriptor in self.list_descriptors():
            if public_only and not descriptor.capabilities.is_public_command:
                continue
            if not descriptor.capabilities.mention_prefixes and not descriptor.capabilities.slash_commands:
                continue
            result.append(descriptor)
        return result

    def _capabilities(self, public: bool | None) -> Iterator[PluginCommandCapabilities]:
        """按调度顺序产出插件命令声明；``public`` 为 None 时不按公开性过滤。"""
        for name in self._order:
            capabilities = self._get_command_capabilities(self._modules[name])
            if public is None or capabilities.is_public_command == public:
                yield capabilities

    def _matches_mention(self, text: str, public: bool | None = None) -> bool:
        return bool(text) and any(
            text.startswith(prefix)
            for capabilities in self._capabilities(public)
            for prefix in capabilities.mention_prefixes
        )

    def _matches_slash(self, command: str, public: bool | None = None) -> bool:
        cmd = (command or "").strip().lower()
        return bool(cmd) and any(cmd in capabilities.slash_commands for capabilities in self._capabilities(public))

    def has_mention_prefix(self, text: str) -> bool:
        """判断是否存在插件声明的 mention 前缀匹配。"""
        return self._matches_mention(text)

    def has_slash_command(self, command: str) -> bool:
        """判断是否存在插件声明的 slash 命令匹配。"""
        return self._matches_slash(command)

    def has_public_mention_prefix(self, text: str) -> bool:
        """判断是否存在公开插件声明的 mention 前缀匹配。"""
        return self._matches_mention(text, public=True)

    def has_public_slash_command(self, command: str) -> bool:
        """判断是否存在公开插件声明的 slash 命令匹配。"""
        return self._matches_slash(command, public=True)

    def has_admin_only_mention_prefix(self, text: str) -> bool:
        """判断是否存在声明为管理员专属的插件 mention 前缀匹配。"""
        return self._matches_mention(text, public=False)

    def has_admin_only_slash_command(self, command: str) -> bool:
        """判断是否存在声明为管理员专属的插件 slash 命令匹配。"""
        return self._matches_slash(command, public=False)

    async def try_dispatch_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """
        按注册顺序尝试由插件处理 mention 指令。
        任一插件返回 `True` 即视为已处理。
        """
        if not text.strip():
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module:
                continue
            capabilities = self._get_command_capabilities(module)
            if not capabilities.mention_prefixes:
                continue
            if not any(text.startswith(p) for p in capabilities.mention_prefixes):
                continue
            try:
                # 第一个声明自己已处理的插件会终止后续分发。
                if await module.handle_mention(text, channel, area, user, handler):
                    return True
            except Exception as e:
                logger.exception("PluginRegistry: 模块 %s handle_mention 异常: %s", name, e)
        return False

    async def try_dispatch_slash(
        self,
        command: str,
        subcommand: str | None,
        arg: str | None,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """
        按注册顺序尝试由插件处理 slash 命令。
        任一插件返回 `True` 即视为已处理。
        """
        cmd_lower = (command or "").strip().lower()
        if not cmd_lower:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module:
                continue
            capabilities = self._get_command_capabilities(module)
            if not capabilities.slash_commands:
                continue
            if cmd_lower not in capabilities.slash_commands:
                continue
            try:
                # 第一个声明自己已处理的插件会终止后续分发。
                if await module.handle_slash(command, subcommand, arg, channel, area, user, handler):
                    return True
            except Exception as e:
                logger.exception("PluginRegistry: 模块 %s handle_slash 异常: %s", name, e)
        return False
