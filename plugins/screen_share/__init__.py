"""网页屏幕共享插件。"""

from collections.abc import Callable

from fastapi import APIRouter

from domain.plugins.base import BotModule, PluginCommandCapabilities, PluginMetadata
from plugins._shared.background import IntervalWorker
from plugins._shared.command_mixin import PluginCommandMixin
from web.plugin_routes import AdminNavItem

from . import admin, web
from .commands import ScreenShareCommandService
from .service import ScreenShareError, ScreenShareService, get_screen_share_service

_START = ("屏幕共享", "共享屏幕")
_STOP = ("停止屏幕共享", "结束屏幕共享")
_COMMANDS = _START + _STOP


class ScreenShareWatchdog(IntervalWorker):
    _NAME = "screen-share-watchdog"

    def __init__(self, service: ScreenShareService):
        super().__init__(interval=5)
        self._service = service

    async def _tick(self) -> None:
        if not self._service.accepting:
            return
        try:
            async with self._service.creation():
                expired = await self._service.expire_stale(heartbeat_timeout=60)
                for session in expired:
                    await web.announce_ended(session)
        except ScreenShareError as exc:
            if exc.code not in {"redis_required", "plugin_unloading"}:
                raise


class ScreenSharePlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "屏幕共享暂时不可用"
    command_log_name = "ScreenShare"

    def __init__(self):
        self._service = get_screen_share_service()
        self._watchdog = ScreenShareWatchdog(self._service)
        self._unregister_web: Callable[[], None] | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("screen_share", "通过网页发起、观看和管理屏幕共享")

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(mention_prefixes=_COMMANDS)

    @property
    def private_modules(self) -> tuple[str, ...]:
        return tuple(
            f"{__name__}.{name}"
            for name in ("admin", "web", "commands", "service", "agora_token", "labels", "messages")
        )

    async def handle_mention(self, text, channel, area, user, handler) -> bool:
        if text not in _COMMANDS:
            return False
        await self._run_plugin_command(text, channel, area, user, handler)
        return True

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        commands = ScreenShareCommandService(handler, self._service)
        if command_text in _START:
            await commands.start(channel, area, user)
        else:
            await commands.stop(channel, area, user)

    async def on_load(self, handler, config=None) -> None:
        if self._unregister_web is not None:
            return
        router = APIRouter()
        router.include_router(web.router)
        router.include_router(admin.router)
        self._unregister_web = handler.register_web(
            router,
            admin_nav=AdminNavItem("screen-share", "/admin/screen-share", "屏幕共享"),
        )
        self._watchdog._start_task()

    async def on_disable(self) -> None:
        await self._service.disable(web.announce_ended)

    async def on_unload(self) -> None:
        if self._unregister_web is not None:
            self._unregister_web()
            self._unregister_web = None
        await self._watchdog.stop()
