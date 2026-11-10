from __future__ import annotations

from app.infrastructure.gateways.sender_gateway import SenderGateway
from app.lifecycle.context import AppContext
from app.lifecycle.oopz_session import OopzSession
from app.lifecycle.task_supervisor import TaskSupervisor
from bot.command_handler import CommandHandler
from core.logger_config import get_logger
from core.message_dispatcher import MessageDispatcher
from music.music_playback import AudioPlayback
from oopz.errors import SensitiveContentError
from oopz.name_resolver import get_resolver
from services.area_invite_inbox import capture_private_area_invites
from services.area_join_notifier import AreaJoinNotifier, start_area_join_notifier

logger = get_logger("AppContext")


class AppContextBuilder:
    """在当前事件循环组装 SDK 会话、应用发送器和命令服务。"""

    async def build(self, supervisor: TaskSupervisor) -> AppContext:
        dispatcher = MessageDispatcher(workers=4, maxsize=512)
        dispatcher.start()

        # 回调在会话创建时传入，届时处理器与通知器尚未组装完成；闭包按引用
        # 读取下面的局部变量，因此启动期的事件会命中 None 分支而不是空指针。
        gateway: SenderGateway | None = None
        session: OopzSession | None = None
        handler: CommandHandler | None = None
        notifier: AreaJoinNotifier | None = None

        async def dispatch_chat(message: dict) -> None:
            current = handler
            if current is None:
                logger.warning("命令处理器尚未就绪，忽略一条启动期消息")
                return
            key = f"{message.get('area') or ''}:{message.get('channel') or ''}"

            async def handle() -> None:
                try:
                    await current.handle_message(message)
                except SensitiveContentError:
                    logger.debug("回复被平台风控拦截，已忽略（发送层已记录）")

            dispatcher.submit(key, handle)

        async def dispatch_private_message(message: dict) -> None:
            current = gateway
            if current is None:
                logger.warning("SDK 网关尚未就绪，忽略一条启动期私信")
                return

            async def handle() -> None:
                await capture_private_area_invites(current, message)

            sender_id = str(message.get("person") or "")
            dispatcher.submit(f"__private_invite__:{sender_id}", handle)

        async def dispatch_other_event(event: int, data: dict) -> None:
            current = notifier
            if current is not None:
                dispatcher.submit("__other_events__", current, event, data)

        try:
            session = await OopzSession.create(
                on_chat_message=dispatch_chat,
                on_private_message=dispatch_private_message,
                on_other_event=dispatch_other_event,
            )
            gateway = session.sender
            voice = AudioPlayback(
                gateway.bot.voice,
                proxy_value=gateway._proxy_value,
                supervisor=supervisor,
            )
            session.voice = voice
            handler = CommandHandler(
                gateway,
                voice_client=voice,
                supervisor=supervisor,
            )
            await get_resolver().bind_gateway(gateway)
            await handler.start()
            gateway.bind_auto_recall_scheduler(
                handler.services.safety.recall_scheduler
            )
            await session.start(supervisor)
            resolver = get_resolver()
            await gateway.bot.areas.populate_names(set_area=resolver.set_area, set_channel=resolver.set_channel)

            notifier = start_area_join_notifier(
                sender=gateway,
                supervisor=supervisor,
            )
            return AppContext(
                sender=gateway,
                handler=handler,
                client=session,
                notifier_callback=notifier,
                voice=voice,
                dispatcher=dispatcher,
                supervisor=supervisor,
            )
        except BaseException:
            if handler is not None:
                await handler.infrastructure.plugins.stop(timeout=2.0)
            if session is not None:
                await session.stop()
            await dispatcher.stop(timeout=2.0)
            raise
