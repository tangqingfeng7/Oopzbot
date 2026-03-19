from dataclasses import dataclass
from typing import Optional

from chat import ChatHandler
from domain.plugins.plugin_operation import PluginOperationResult
from oopz_sender import OopzSender
from plugin_base import PluginDescriptor

from .gateways import ChatGateway, SenderGateway
from .plugin_runtime import PluginRegistry, discover_plugins, load_plugin, load_plugins_dir, reload_plugin_config, unload_plugin


class MusicGateway:
    """延迟创建音乐处理器，隔离命令层对具体实现的直接依赖。"""

    def __init__(self, sender: SenderGateway, voice_client=None):
        self._sender = sender
        self._voice_client = voice_client
        self._handler = None

    @property
    def handler(self):
        if self._handler is None:
            # 只有真正用到音乐命令时才导入并创建处理器。
            from music import MusicHandler

            self._handler = MusicHandler(self._sender, voice=self._voice_client)
        return self._handler

    def __getattr__(self, name: str):
        return getattr(self.handler, name)


class PluginRuntime:
    """插件注册、查询和动态装卸的运行时门面。"""

    def __init__(self, plugins_dir: str = "plugins"):
        self._plugins_dir = plugins_dir
        self._registry = PluginRegistry()

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    def list_descriptors(self) -> list[PluginDescriptor]:
        return self._registry.list_descriptors()

    def list_command_descriptors(self, public_only: bool = False) -> list[PluginDescriptor]:
        return self._registry.list_command_descriptors(public_only=public_only)

    def has_public_mention_prefix(self, text: str) -> bool:
        return self._registry.has_public_mention_prefix(text)

    def has_public_slash_command(self, command: str) -> bool:
        return self._registry.has_public_slash_command(command)

    def try_dispatch_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler,
    ) -> bool:
        return self._registry.try_dispatch_mention(text, channel, area, user, handler)

    def try_dispatch_slash(
        self,
        command: str,
        subcommand: Optional[str],
        arg: Optional[str],
        channel: str,
        area: str,
        user: str,
        handler,
    ) -> bool:
        return self._registry.try_dispatch_slash(command, subcommand, arg, channel, area, user, handler)

    def discover(self) -> list[str]:
        return discover_plugins(self._plugins_dir)

    def load(self, plugin_name: str, handler=None) -> PluginOperationResult:
        return load_plugin(self._registry, plugin_name, self._plugins_dir, handler=handler)

    def unload(self, plugin_name: str, handler=None) -> PluginOperationResult:
        return unload_plugin(self._registry, plugin_name, handler=handler)

    def reload_config(self, plugin_name: str, handler=None) -> PluginOperationResult:
        return reload_plugin_config(self._registry, plugin_name, handler=handler)

    def load_all(self, handler=None) -> list[str]:
        return load_plugins_dir(self._registry, self._plugins_dir, handler=handler)


class PluginHost:
    """提供给插件的受控宿主上下文。"""

    def __init__(self, infrastructure: "BotInfrastructure", services_getter):
        self._infrastructure = infrastructure
        self._services_getter = services_getter

    @property
    def sender(self) -> SenderGateway:
        return self._infrastructure.sender

    @property
    def chat(self) -> ChatGateway:
        return self._infrastructure.chat

    @property
    def music(self) -> MusicGateway:
        return self._infrastructure.music

    @property
    def services(self):
        return self._services_getter()


@dataclass(frozen=True)
class BotInfrastructure:
    """命令处理链路使用的外部依赖集合。"""

    sender: SenderGateway
    chat: ChatGateway
    music: MusicGateway
    plugins: PluginRuntime


def build_bot_infrastructure(sender: OopzSender, voice_client=None) -> BotInfrastructure:
    """构建命令处理链路需要的基础设施对象。"""
    sender_gateway = SenderGateway(sender)
    return BotInfrastructure(
        sender=sender_gateway,
        # ChatHandler 足够轻量，可以在运行时初始化时直接创建。
        chat=ChatGateway(ChatHandler()),
        music=MusicGateway(sender_gateway, voice_client=voice_client),
        plugins=PluginRuntime(),
    )
