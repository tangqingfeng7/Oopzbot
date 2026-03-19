from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from domain.plugins.plugin_config import (
    PluginConfig,
    PluginConfigField,
    PluginConfigSpec,
    PluginConfigValidationError,
    parse_bool,
    parse_float,
    parse_int,
    parse_string_list,
    validate_hhmm,
    validate_http_url_list,
    validate_min,
    validate_range,
)


@dataclass(frozen=True)
class PluginMetadata:
    """插件元数据。"""

    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""


@dataclass(frozen=True)
class PluginCommandCapabilities:
    """插件命令能力声明。"""

    mention_prefixes: tuple[str, ...] = ()
    slash_commands: tuple[str, ...] = ()
    is_public_command: bool = True


@dataclass(frozen=True)
class PluginDescriptor:
    """插件标准描述对象。"""

    metadata: PluginMetadata
    capabilities: PluginCommandCapabilities
    builtin: bool = False

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def version(self) -> str:
        return self.metadata.version

    @property
    def author(self) -> str:
        return self.metadata.author

    @property
    def mention_prefixes(self) -> tuple[str, ...]:
        return self.capabilities.mention_prefixes

    @property
    def slash_commands(self) -> tuple[str, ...]:
        return self.capabilities.slash_commands

    @property
    def is_public_command(self) -> bool:
        return self.capabilities.is_public_command


class BotModule(ABC):
    """插件抽象基类。"""

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """返回插件元数据。"""

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        """返回插件命令能力声明。"""
        return PluginCommandCapabilities(
            mention_prefixes=self.mention_prefixes,
            slash_commands=self.slash_commands,
            is_public_command=self.is_public_command,
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        """返回插件配置规范。"""
        return PluginConfigSpec.empty()

    @property
    def mention_prefixes(self) -> tuple[str, ...]:
        """返回旧版 mention 前缀声明。"""
        return ()

    @property
    def slash_commands(self) -> tuple[str, ...]:
        """返回旧版 slash 命令声明。"""
        return ()

    @property
    def is_public_command(self) -> bool:
        """指令是否对非管理员公开。"""
        return True

    @property
    def private_modules(self) -> tuple[str, ...]:
        """返回插件私有模块列表，用于卸载时清理缓存。"""
        return ()

    def handle_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """处理 mention 指令，返回是否已处理。"""
        return False

    def handle_slash(
        self,
        command: str,
        subcommand: Optional[str],
        arg: Optional[str],
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """处理 slash 命令，返回是否已处理。"""
        return False

    def on_load(self, handler: Any, config: Optional[PluginConfig] = None) -> None:
        """插件加载完成后调用。"""

    def on_config_reload(self, handler: Any, config: PluginConfig) -> None:
        """配置热重载时调用。默认行为等同于 on_load，子类可覆盖以实现更精细的重载。"""
        self.on_load(handler, config)

    def on_unload(self) -> None:
        """插件卸载前调用。"""
