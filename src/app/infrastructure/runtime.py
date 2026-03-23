import json
import os
from dataclasses import dataclass
from typing import Optional

from chat import ChatHandler
from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult
from oopz_sender import OopzSender
from plugin_base import PluginDescriptor

from .gateways import ChatGateway, SenderGateway
from .plugin_runtime import PluginRegistry, discover_plugins, load_plugin, load_plugins_dir, reload_plugin_config, unload_plugin

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_PLUGIN_STATE_PATH = os.path.join(_PROJECT_ROOT, "data", "plugin_runtime_state.json")


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

    def __init__(self, plugins_dir: str = "plugins", state_path=None):
        self._plugins_dir = plugins_dir
        self._registry = PluginRegistry()
        self._state_path = os.fspath(state_path) if state_path else _DEFAULT_PLUGIN_STATE_PATH

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    @property
    def state_path(self) -> str:
        return self._state_path

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

    def enabled_plugin_names(self) -> list[str]:
        return [descriptor.name for descriptor in self.list_descriptors()]

    def _read_enabled_plugins(self) -> list[str] | None:
        if not os.path.isfile(self._state_path):
            return None
        try:
            with open(self._state_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            return None
        enabled = payload.get("enabled_plugins")
        if isinstance(enabled, list):
            return [str(name) for name in enabled if str(name).strip()]
        return None

    def _persist_enabled_plugins(self) -> str | None:
        try:
            directory = os.path.dirname(self._state_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as file:
                json.dump({"enabled_plugins": self.enabled_plugin_names()}, file, ensure_ascii=False, indent=2)
            return None
        except Exception as exc:
            return str(exc)

    def load(self, plugin_name: str, handler=None) -> PluginOperationResult:
        result = load_plugin(self._registry, plugin_name, self._plugins_dir, handler=handler)
        if not result.ok:
            return result
        error = self._persist_enabled_plugins()
        if error:
            return PluginOperationResult.failure(
                f"持久化失败: {error}",
                plugin_name=plugin_name,
                code=PluginOperationCode.LOAD_FAILED,
            )
        return result

    def unload(self, plugin_name: str, handler=None) -> PluginOperationResult:
        result = unload_plugin(self._registry, plugin_name, handler=handler)
        if not result.ok:
            return result
        error = self._persist_enabled_plugins()
        if error:
            return PluginOperationResult.failure(
                f"持久化失败: {error}",
                plugin_name=plugin_name,
                code=PluginOperationCode.LOAD_FAILED,
            )
        return result

    def reload_config(self, plugin_name: str, handler=None) -> PluginOperationResult:
        return reload_plugin_config(self._registry, plugin_name, handler=handler)

    def load_all(self, handler=None) -> list[str]:
        discovered = self.discover()
        enabled = self._read_enabled_plugins()
        to_load = [name for name in discovered if enabled is None or name in enabled]
        loaded: list[str] = []
        for name in to_load:
            result = load_plugin(self._registry, name, self._plugins_dir, handler=handler)
            if result.ok:
                loaded.append(name)
        self._persist_enabled_plugins()
        return loaded


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
