from app.infrastructure import PluginHost, build_bot_infrastructure
from app.infrastructure.gateways.sender_gateway import SenderGateway
from app.services.registry import build_command_service_registry
from app.services.runtime import CommandRuntime
from config import OOPZ_CONFIG
from core.constants import build_mention
from core.database import MessageStatsDB, cn_today
from core.logger_config import get_logger

_stats_logger = get_logger("MessageStats")

_BOT_UID = OOPZ_CONFIG.get("person_uid", "")
_BOT_MENTION = build_mention(_BOT_UID) if _BOT_UID else ""


class CommandHandler:
    """Coordinates the command runtime and dispatch pipeline."""

    def __init__(self, sender: SenderGateway, voice_client=None, supervisor=None):
        # 组装逻辑集中在这里，其他命令链路只依赖运行时对象。
        self._runtime = CommandRuntime(
            build_bot_infrastructure(
                sender,
                voice_client=voice_client,
                supervisor=supervisor,
            ),
            bot_uid=_BOT_UID,
            bot_mention=_BOT_MENTION,
        )
        self.infrastructure = self._runtime.infrastructure
        self._service_registry = build_command_service_registry(self._runtime)
        self._runtime.bind_services(self._service_registry)
        self._plugin_host = PluginHost(self.infrastructure, lambda: self.services)
        self._runtime.bind_plugin_host(self._plugin_host)
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.infrastructure.plugins.load_all(handler=self._plugin_host)
        self._started = True

    @property
    def plugin_host(self):
        return self._plugin_host

    @property
    def services(self):
        return self._service_registry

    @property
    def recent_messages(self):
        return self._runtime.recent_messages

    async def handle_message(self, msg_data: dict) -> None:
        ctx = self.services.routing.message.build_context(msg_data)
        # 先记录消息，再路由，撤回类命令才能立刻命中。
        self.services.routing.message.remember_message(ctx)

        try:
            await MessageStatsDB.increment(cn_today(), ctx.channel, ctx.area, ctx.user)
        except Exception:
            _stats_logger.debug("消息统计写入失败", exc_info=True)

        if not ctx.content:
            return

        if await self.services.routing.message.reject_unauthorized_command(ctx):
            return

        await self.services.routing.command.route(ctx)

    async def handle(self, msg_data: dict) -> None:
        await self.handle_message(msg_data)
