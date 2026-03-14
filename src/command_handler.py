from app.infrastructure import PluginHost, build_bot_infrastructure
from app.services.registry import build_command_service_registry
from app.services.runtime import CommandRuntime
from config import OOPZ_CONFIG
from oopz_sender import OopzSender

_BOT_UID = OOPZ_CONFIG.get("person_uid", "")
_BOT_MENTION = f"(met){_BOT_UID}(met)" if _BOT_UID else ""


class CommandHandler:
    """Coordinates the command runtime and dispatch pipeline."""

    def __init__(self, sender: OopzSender, voice_client=None):
        # 组装逻辑集中在这里，其他命令链路只依赖运行时对象。
        self._runtime = CommandRuntime(
            build_bot_infrastructure(sender, voice_client=voice_client),
            bot_uid=_BOT_UID,
            bot_mention=_BOT_MENTION,
        )
        self.infrastructure = self._runtime.infrastructure
        self._service_registry = build_command_service_registry(self._runtime)
        self._runtime.bind_services(self._service_registry)
        self._plugin_host = PluginHost(self.infrastructure, lambda: self.services)
        self._runtime.bind_plugin_host(self._plugin_host)
        self.infrastructure.plugins.load_all(handler=self._plugin_host)

    @property
    def plugin_host(self):
        return self._plugin_host

    @property
    def services(self):
        return self._service_registry

    @property
    def recent_messages(self):
        return self._runtime.recent_messages

    @property
    def _recent_messages(self):
        # 兼容仍在访问旧属性名的调用方。
        return self._runtime.recent_messages

    @_recent_messages.setter
    def _recent_messages(self, messages):
        self._runtime.recent_messages.replace(list(messages))

    def handle_message(self, msg_data: dict):
        ctx = self.services.routing.message.build_context(msg_data)
        # 先记录消息，再路由，撤回类命令才能立刻命中。
        self.services.routing.message.remember_message(ctx)

        if not ctx.content:
            return

        if self.services.routing.message.handle_profanity(ctx):
            return

        if self.services.routing.message.reject_unauthorized_command(ctx):
            return

        self.services.routing.command.route(ctx)

    def handle(self, msg_data: dict):
        self.handle_message(msg_data)
