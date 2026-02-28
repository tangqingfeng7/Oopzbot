"""
插件注册表：注册/卸载、按序分发、错误隔离

- 单插件异常仅记录日志，不中断其它插件与内置逻辑
- 支持内置模块(builtin)与动态加载模块的区分，便于管理员卸载仅限扩展
"""

from typing import Any, Optional
from logger_config import get_logger

from plugin_base import BotModule

logger = get_logger("PluginRegistry")


class PluginRegistry:
    """插件注册表：持有所有已注册模块，负责按序分发与异常隔离。"""

    def __init__(self) -> None:
        self._modules: dict[str, BotModule] = {}
        self._order: list[str] = []  # 调度顺序
        self._builtin: set[str] = set()  # 内置模块名，不可被动态卸载

    def register(self, module: BotModule, *, builtin: bool = False) -> bool:
        """
        注册一个模块。同名已存在则先卸载再注册。
        builtin=True 的模块不会被「卸载插件」命令卸载。
        """
        name = module.metadata.name
        if not name.strip():
            logger.warning("PluginRegistry: 拒绝注册无 name 的模块")
            return False
        if name in self._modules:
            self.unregister(name)
        self._modules[name] = module
        if name not in self._order:
            self._order.append(name)
        if builtin:
            self._builtin.add(name)
        return True

    def unregister(self, name: str, handler: Any = None) -> bool:
        """卸载模块并调用 on_unload。内置模块可被 unregister 但通常由管理员命令只卸载非内置。"""
        if name not in self._modules:
            return False
        module = self._modules.pop(name)
        self._order = [n for n in self._order if n != name]
        self._builtin.discard(name)
        try:
            module.on_unload()
        except Exception as e:
            logger.exception("PluginRegistry: 模块 %s on_unload 异常: %s", name, e)
        return True

    def get(self, name: str) -> Optional[BotModule]:
        return self._modules.get(name)

    def is_builtin(self, name: str) -> bool:
        return name in self._builtin

    def list_all(self) -> list[dict]:
        """返回所有已注册模块信息，用于插件列表展示。"""
        result = []
        for name in self._order:
            m = self._modules.get(name)
            if not m:
                continue
            meta = m.metadata
            result.append({
                "name": name,
                "description": meta.description,
                "version": meta.version,
                "author": meta.author or "",
                "builtin": name in self._builtin,
            })
        return result

    def list_command_caps(self, public_only: bool = False) -> list[dict]:
        """返回插件可用命令能力（用于 help 动态展示）。"""
        out = []
        for name in self._order:
            module = self._modules.get(name)
            if not module:
                continue
            if public_only and not module.is_public_command:
                continue
            mentions = tuple(module.mention_prefixes or ())
            slashes = tuple(module.slash_commands or ())
            if not mentions and not slashes:
                continue
            out.append({
                "name": name,
                "mention_prefixes": mentions,
                "slash_commands": slashes,
            })
        return out

    def has_mention_prefix(self, text: str) -> bool:
        """判断是否存在插件声明的 @ 指令前缀匹配。"""
        if not text:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.mention_prefixes:
                continue
            if any(text.startswith(p) for p in module.mention_prefixes):
                return True
        return False

    def has_slash_command(self, command: str) -> bool:
        """判断是否存在插件声明的 / 命令匹配。"""
        cmd = (command or "").strip().lower()
        if not cmd:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.slash_commands:
                continue
            if cmd in module.slash_commands:
                return True
        return False

    def has_public_mention_prefix(self, text: str) -> bool:
        """判断是否存在公开插件声明的 @ 指令前缀匹配。"""
        if not text:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.mention_prefixes or not module.is_public_command:
                continue
            if any(text.startswith(p) for p in module.mention_prefixes):
                return True
        return False

    def has_public_slash_command(self, command: str) -> bool:
        """判断是否存在公开插件声明的 / 命令匹配。"""
        cmd = (command or "").strip().lower()
        if not cmd:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.slash_commands or not module.is_public_command:
                continue
            if cmd in module.slash_commands:
                return True
        return False

    def try_dispatch_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """
        按注册顺序尝试由插件处理 @ 指令。
        任一插件返回 True 即返回 True；单插件异常仅打日志并继续。
        """
        if not text.strip():
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.mention_prefixes:
                continue
            if not any(text.startswith(p) for p in module.mention_prefixes):
                continue
            try:
                if module.handle_mention(text, channel, area, user, handler):
                    return True
            except Exception as e:
                logger.exception("PluginRegistry: 模块 %s handle_mention 异常: %s", name, e)
        return False

    def try_dispatch_slash(
        self,
        command: str,
        subcommand: Optional[str],
        arg: Optional[str],
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """
        按注册顺序尝试由插件处理 / 命令。
        任一插件返回 True 即返回 True；单插件异常仅打日志并继续。
        """
        cmd_lower = (command or "").strip().lower()
        if not cmd_lower:
            return False
        for name in self._order:
            module = self._modules.get(name)
            if not module or not module.slash_commands:
                continue
            if cmd_lower not in module.slash_commands:
                continue
            try:
                if module.handle_slash(command, subcommand, arg, channel, area, user, handler):
                    return True
            except Exception as e:
                logger.exception("PluginRegistry: 模块 %s handle_slash 异常: %s", name, e)
        return False
