from app.services.runtime import CommandRuntimeView

from .command_message_service import MessageContext


class CommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._bot_mention = runtime.bot_mention

    def route(self, ctx: MessageContext) -> None:
        if ctx.is_mention_command(self._bot_mention):
            self._route_mention(ctx)
            return

        if ctx.is_slash_command():
            self._route_slash(ctx)
            return

        self._route_chat(ctx)

    def _route_mention(self, ctx: MessageContext) -> None:
        text = ctx.mention_text(self._bot_mention)
        is_ai_chat = False
        if text:
            is_ai_chat = self._services.routing.mention.dispatch(text, ctx.channel, ctx.area, ctx.user)
        if not is_ai_chat:
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
