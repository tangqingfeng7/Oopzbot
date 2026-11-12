import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.constants import PLUGINS_DIR_NAME
from core.logger_config import get_logger
from core.paths import DATA_DIR
from domain.plugins.base import PluginDescriptor
from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

from .gateways import SenderGateway
from .plugin_runtime import (
    PluginRegistry,
    discover_plugins,
    load_plugin,
    reload_plugin_config,
    unload_plugin,
)

if TYPE_CHECKING:
    from fastapi import APIRouter

    from web.plugin_routes import AdminNavItem

_DEFAULT_PLUGIN_STATE_PATH = os.path.join(DATA_DIR, "plugin_runtime_state.json")
logger = get_logger("PluginRuntime")


class MusicGateway:
    """延迟创建音乐处理器，隔离命令层对具体实现的直接依赖。"""

    def __init__(self, sender: SenderGateway, voice_client=None, supervisor=None):
        self._sender = sender
        self._voice_client = voice_client
        self._supervisor = supervisor
        self._handler = None

    @property
    def handler(self):
        if self._handler is None:
            # 只有真正用到音乐命令时才导入并创建处理器。
            from music.music import MusicHandler

            self._handler = MusicHandler(
                self._sender,
                voice=self._voice_client,
                supervisor=self._supervisor,
            )
        return self._handler

    def __getattr__(self, name: str):
        return getattr(self.handler, name)

    def refresh_platforms(self) -> dict:
        """配置热更新时刷新已创建的音乐平台实例。"""
        if self._handler is None:
            return {"available": True, "refreshed": False, "reason": "音乐处理器尚未初始化"}
        return self._handler.refresh_platforms()


class PluginRuntime:
    """插件注册、查询和动态装卸的运行时门面。"""

    def __init__(self, plugins_dir: str = PLUGINS_DIR_NAME, state_path=None):
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

    def has_admin_only_mention_prefix(self, text: str) -> bool:
        return self._registry.has_admin_only_mention_prefix(text)

    def has_admin_only_slash_command(self, command: str) -> bool:
        return self._registry.has_admin_only_slash_command(command)

    async def try_dispatch_mention(
        self,
        text: str,
        channel: str,
        area: str,
        user: str,
        handler,
    ) -> bool:
        return await self._registry.try_dispatch_mention(text, channel, area, user, handler)

    async def try_dispatch_slash(
        self,
        command: str,
        subcommand: str | None,
        arg: str | None,
        channel: str,
        area: str,
        user: str,
        handler,
    ) -> bool:
        return await self._registry.try_dispatch_slash(command, subcommand, arg, channel, area, user, handler)

    def discover(self) -> list[str]:
        return discover_plugins(self._plugins_dir)

    def enabled_plugin_names(self) -> list[str]:
        return [descriptor.name for descriptor in self.list_descriptors()]

    def _read_enabled_plugins_sync(self) -> list[str] | None:
        if not os.path.isfile(self._state_path):
            return None
        try:
            with open(self._state_path, encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            return None
        enabled = payload.get("enabled_plugins")
        if isinstance(enabled, list):
            return [str(name) for name in enabled if str(name).strip()]
        return None

    def _persist_enabled_plugins_sync(self) -> str | None:
        try:
            directory = os.path.dirname(self._state_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as file:
                json.dump({"enabled_plugins": self.enabled_plugin_names()}, file, ensure_ascii=False, indent=2)
            return None
        except Exception as exc:
            return str(exc)

    async def load(self, plugin_name: str, handler=None) -> PluginOperationResult:
        result = await load_plugin(self._registry, plugin_name, self._plugins_dir, handler=handler)
        if not result.ok:
            return result
        error = await asyncio.to_thread(self._persist_enabled_plugins_sync)
        if error:
            return PluginOperationResult.failure(
                f"持久化失败: {error}",
                plugin_name=plugin_name,
                code=PluginOperationCode.LOAD_FAILED,
            )
        return result

    async def unload(self, plugin_name: str, handler=None) -> PluginOperationResult:
        result = await unload_plugin(self._registry, plugin_name, handler=handler)
        if not result.ok:
            return result
        error = await asyncio.to_thread(self._persist_enabled_plugins_sync)
        if error:
            return PluginOperationResult.failure(
                f"持久化失败: {error}",
                plugin_name=plugin_name,
                code=PluginOperationCode.LOAD_FAILED,
            )
        return result

    async def reload_config(self, plugin_name: str, handler=None) -> PluginOperationResult:
        return await reload_plugin_config(self._registry, plugin_name, handler=handler)

    async def stop(self, timeout: float = 5.0) -> None:
        """在调用方预算内停止全部插件，不改写下次启用状态。"""
        if not self._registry.list_descriptors():
            return
        try:
            await asyncio.wait_for(self._registry.stop_all(), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            logger.warning("服务停止超时: PluginShutdown，插件仍在停止")

    async def load_all(self, handler=None) -> list[str]:
        discovered = await asyncio.to_thread(self.discover)
        enabled = await asyncio.to_thread(self._read_enabled_plugins_sync)
        to_load = [name for name in discovered if enabled is None or name in enabled]
        loaded: list[str] = []
        for name in to_load:
            result = await load_plugin(self._registry, name, self._plugins_dir, handler=handler)
            if result.ok:
                loaded.append(name)
        await asyncio.to_thread(self._persist_enabled_plugins_sync)
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
    def music(self) -> MusicGateway:
        return self._infrastructure.music

    @property
    def services(self):
        return self._services_getter()

    def register_web(
        self, router: "APIRouter", *, admin_nav: "AdminNavItem | None" = None
    ) -> Callable[[], None]:
        """在现有 Web 应用注册插件路由，返回注销函数。"""
        from web.plugin_routes import register_web
        from web.web_player import app

        return register_web(app, router, admin_nav=admin_nav)


@dataclass(frozen=True)
class BotInfrastructure:
    """命令处理链路使用的外部依赖集合。"""

    sender: SenderGateway
    music: MusicGateway
    plugins: PluginRuntime


def build_bot_infrastructure(sender: SenderGateway, voice_client=None, supervisor=None) -> BotInfrastructure:
    """构建命令处理链路需要的基础设施对象。"""
    return BotInfrastructure(
        sender=sender,
        music=MusicGateway(sender, voice_client=voice_client, supervisor=supervisor),
        plugins=PluginRuntime(),
    )
