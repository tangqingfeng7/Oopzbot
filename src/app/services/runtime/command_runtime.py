from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Protocol

from app.infrastructure import (
    BotInfrastructure,
    MusicGateway,
    PluginHost,
    PluginRuntime,
    SenderGateway,
)
from config import OOPZ_CONFIG
from core.constants import build_mention

if TYPE_CHECKING:
    from app.services.registry import CommandServiceRegistry


class RecentMessageStore:
    """Bounded in-memory storage for recent message metadata."""

    def __init__(self, limit: int = 50):
        self._limit = limit
        self._messages: list[dict[str, Any]] = []

    def append(self, message: dict[str, Any]) -> None:
        self._messages.append(message)
        overflow = len(self._messages) - self._limit
        if overflow > 0:
            # 撤回和历史查询只需要保留最近一段消息。
            del self._messages[:overflow]

    def clear(self) -> int:
        count = len(self._messages)
        self._messages.clear()
        return count

    def filtered(self, *, channel: str | None = None, area: str | None = None) -> list[dict[str, Any]]:
        return [
            message
            for message in self._messages
            if (channel is None or message.get("channel") == channel)
            and (area is None or message.get("area") == area)
        ]

    def replace(self, messages: list[dict[str, Any]]) -> None:
        self._messages = list(messages)[-self._limit :]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._messages)

    def __reversed__(self) -> Iterator[dict[str, Any]]:
        return reversed(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index):
        return self._messages[index]


class ServiceRegistryProxy:
    """Late-bound proxy that lets services capture the registry before it is fully built."""

    def __init__(self) -> None:
        self._target: CommandServiceRegistry | None = None

    def bind(self, target: CommandServiceRegistry) -> None:
        self._target = target

    def __getattr__(self, name: str):
        if self._target is None:
            raise RuntimeError("Command service registry has not been bound yet.")
        return getattr(self._target, name)


class CommandRuntimeView(Protocol):
    """Minimal runtime surface shared by services and routers."""

    infrastructure: BotInfrastructure
    services: ServiceRegistryProxy
    sender: Any
    music: Any
    plugins: Any

    @property
    def bot_uid(self) -> str:
        ...

    @property
    def bot_mention(self) -> str:
        ...

    @property
    def plugin_host(self) -> PluginHost:
        ...

    @property
    def recent_messages(self) -> RecentMessageStore:
        ...


def _resolve_live_bot_uid(sender: Any) -> str:
    bot = getattr(sender, "bot", None)
    bot_config = getattr(bot, "config", None)
    uid = getattr(bot_config, "person_uid", None)
    if isinstance(uid, str):
        return uid.strip()
    return str(OOPZ_CONFIG.get("person_uid") or "").strip()


class CommandRuntime:
    """Owns mutable runtime state for the command processing pipeline."""

    def __init__(
        self,
        infrastructure: BotInfrastructure,
        *,
        bot_uid: str | None = None,
        bot_mention: str | None = None,
    ) -> None:
        self.infrastructure = infrastructure
        self.services = ServiceRegistryProxy()
        self._bot_uid_override = bot_uid
        self._bot_mention_override = bot_mention
        self._recent_messages = RecentMessageStore()
        self._plugin_host: PluginHost | None = None

    @property
    def bot_uid(self) -> str:
        if self._bot_uid_override is not None:
            return self._bot_uid_override
        return _resolve_live_bot_uid(self.infrastructure.sender)

    @property
    def bot_mention(self) -> str:
        if self._bot_mention_override is not None:
            return self._bot_mention_override
        uid = self.bot_uid
        return build_mention(uid) if uid else ""

    @property
    def sender(self):
        return self.infrastructure.sender

    @property
    def music(self):
        return self.infrastructure.music

    @property
    def plugins(self):
        return self.infrastructure.plugins

    @property
    def plugin_host(self) -> PluginHost:
        if self._plugin_host is None:
            # 插件宿主依赖 services，所以要在服务装配完成后再绑定。
            raise RuntimeError("Plugin host has not been bound yet.")
        return self._plugin_host

    @property
    def recent_messages(self) -> RecentMessageStore:
        return self._recent_messages

    def bind_services(self, services: CommandServiceRegistry) -> None:
        self.services.bind(services)

    def bind_plugin_host(self, plugin_host: PluginHost) -> None:
        self._plugin_host = plugin_host


_MISSING = object()


def _view_attr(runtime_view, name: str) -> Any:
    value = getattr(runtime_view, name, _MISSING)
    if value is _MISSING:
        return getattr(runtime_view.infrastructure, name)
    return value


def sender_of(runtime_view) -> SenderGateway:
    return _view_attr(runtime_view, "sender")


def music_of(runtime_view) -> MusicGateway:
    return _view_attr(runtime_view, "music")


def plugins_of(runtime_view) -> PluginRuntime:
    return _view_attr(runtime_view, "plugins")
