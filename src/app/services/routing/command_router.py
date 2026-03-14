"""命令路由服务。"""

from typing import TYPE_CHECKING

from .command_message_service import MessageContext


if TYPE_CHECKING:
    from command_handler import CommandHandler


class CommandRouter:
    """负责把标准化消息路由到对应处理分支。"""

    def __init__(self, handler: "CommandHandler", bot_mention: str):
        self._handler = handler
        self._services = handler.services
        self._bot_mention = bot_mention

    def route(self, ctx: MessageContext) -> None:
        """根据消息类型执行路由。"""
        if ctx.is_mention_command(self._bot_mention):
            self._route_mention(ctx)
            return

        if ctx.is_slash_command():
            self._route_slash(ctx)
            return

        self._route_chat(ctx)

    def _route_mention(self, ctx: MessageContext) -> None:
        text = ctx.mention_text(self._bot_mention)
        if text:
            self._services.routing.mention.dispatch(text, ctx.channel, ctx.area, ctx.user)
        self._services.safety.recall_scheduler.schedule_user_message_recall(
            ctx.message_id,
            ctx.channel,
            ctx.area,
            ctx.timestamp,
        )

    def _route_slash(self, ctx: MessageContext) -> None:
        self._services.routing.slash.dispatch(ctx.content, ctx.channel, ctx.area, ctx.user)
        self._services.safety.recall_scheduler.schedule_user_message_recall(
            ctx.message_id,
            ctx.channel,
            ctx.area,
            ctx.timestamp,
        )

    def _route_chat(self, ctx: MessageContext) -> None:
        self._services.interaction.chat.handle_plain_chat(
            ctx.content,
            ctx.channel,
            ctx.area,
        )
