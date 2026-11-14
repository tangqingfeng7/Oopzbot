from app.services.runtime import CommandRuntimeView, plugins_of

from .command_message_service import MessageContext


class CommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._bot_mention = runtime.bot_mention

    async def route(self, ctx: MessageContext) -> None:
        if ctx.is_mention_command(self._bot_mention):
            await self._route_mention(ctx)
            return

        if ctx.is_slash_command():
            await self._route_slash(ctx)
            return

        await self._route_chat(ctx)

    async def _route_mention(self, ctx: MessageContext) -> None:
        text = ctx.mention_text(self._bot_mention)
        if text:
            await self._services.routing.mention.dispatch(
                text,
                ctx.channel,
                ctx.area,
                ctx.user,
            )
        await self._services.safety.recall_scheduler.schedule_user_message_recall(
            ctx.message_id,
            ctx.channel,
            ctx.area,
            ctx.timestamp,
        )

    async def _route_slash(self, ctx: MessageContext) -> None:
        await self._services.routing.slash.dispatch(ctx.content, ctx.channel, ctx.area, ctx.user)
        await self._services.safety.recall_scheduler.schedule_user_message_recall(
            ctx.message_id,
            ctx.channel,
            ctx.area,
            ctx.timestamp,
        )

    async def _route_chat(self, ctx: MessageContext) -> None:
        await plugins_of(self._runtime).try_dispatch_message(
            ctx.content,
            ctx.channel,
            ctx.area,
            ctx.user,
            self._runtime.plugin_host,
        )
