"""
插件抽象基类与契约

所有可注册模块必须继承 BotModule，实现元数据与处理方法。
由 PluginRegistry 统一调度，单插件异常不影响其它插件与主流程。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PluginMetadata:
    """插件元数据，用于列表展示与依赖/顺序控制。"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""


class BotModule(ABC):
    """
    机器人模块抽象基类。

    子类必须实现：
    - metadata: PluginMetadata
    - mention_prefixes 或 slash_commands 至少其一非空
    - handle_mention 和/或 handle_slash（按需实现，未注册的前缀/命令可不实现）

    生命周期：
    - on_load(handler, config) 在注册时调用，config 为插件配置文件内容（见 plugins/README）
    - on_unload() 在卸载时调用
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """插件元数据。"""
        pass

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def mention_prefixes(self) -> tuple[str, ...]:
        """@bot 后的中文指令前缀，用于匹配。"""
        return ()

    @property
    def slash_commands(self) -> tuple[str, ...]:
        """/ 命令（小写），如 ('/help', '/play')。"""
        return ()

    @property
    def is_public_command(self) -> bool:
        """
        插件命令是否对非管理员公开。
        True: 非管理员可用；False: 仅管理员可用。
        """
        return True

    @property
    def private_modules(self) -> tuple[str, ...]:
        """
        插件私有辅助模块列表（完整模块名），用于卸载时精确清理缓存。
        例如: ("plugins._my_service",)
        """
        return ()

    def handle_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler: Any,
    ) -> bool:
        """处理 @ 指令。返回 True 表示已处理。默认未处理。"""
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
        """处理 / 命令。返回 True 表示已处理。默认未处理。"""
        return False

    def on_load(self, handler: Any, config: Optional[dict] = None) -> None:
        """
        注册/加载时调用。
        config: 来自 config/plugins/<name>.json 的字典，无文件或解析失败时为 None 或 {}。
        """
        pass

    def on_unload(self) -> None:
        """卸载时调用。"""
        pass
