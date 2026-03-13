"""
命令解析与路由
支持 @bot 中文指令 和 / 开头的命令
"""

from app.infrastructure import PluginHost, build_bot_infrastructure
from app.services.registry import build_command_service_registry
from config import OOPZ_CONFIG
from oopz_sender import OopzSender

# Bot 自身的 @mention 标记
_BOT_UID = OOPZ_CONFIG.get("person_uid", "")
_BOT_MENTION = f"(met){_BOT_UID}(met)" if _BOT_UID else ""


class CommandHandler:
    """
    消息命令路由器。

    在 main.py 中将此实例的 handle() 方法注册为 OopzClient 的消息回调。
    """

    def __init__(self, sender: OopzSender, voice_client=None):
        self.infrastructure = build_bot_infrastructure(sender, voice_client=voice_client)
        self._recent_messages = []  # 记录最近的消息（最多保留50条）
        self._service_registry = build_command_service_registry(
            self,
            bot_uid=_BOT_UID,
            bot_mention=_BOT_MENTION,
        )
        self._plugin_host = PluginHost(self.infrastructure, lambda: self.services)
        self.infrastructure.plugins.load_all(handler=self._plugin_host)

    @property
    def plugin_host(self):
        """返回提供给插件使用的宿主上下文。"""
        return self._plugin_host

    @property
    def services(self):
        """返回命令处理相关的应用层服务注册表。"""
        return self._service_registry

    def handle_message(self, msg_data: dict):
        """新的消息入口，逐步替代旧的 handle。"""
        ctx = self.services.routing.message.build_context(msg_data)
        self.services.routing.message.remember_message(ctx)

        if not ctx.content:
            return

        if self.services.routing.message.handle_profanity(ctx):
            return

        if self.services.routing.message.reject_unauthorized_command(ctx):
            return

        self.services.routing.command.route(ctx)

    def handle(self, msg_data: dict):
        """兼容旧入口，内部统一走新的消息处理链路。"""
        self.handle_message(msg_data)
