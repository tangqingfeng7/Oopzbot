from dataclasses import dataclass

from app.services.runtime import CommandRuntimeView
from core.constants import Msg
from core.logger_config import get_logger

logger = get_logger("CommandMessageService")


@dataclass(frozen=True)
class MessageContext:
    raw: dict
    content: str
    channel: str
    area: str
    user: str
    message_id: str
    timestamp: str

    @classmethod
    def from_message(cls, msg_data: dict) -> "MessageContext":
        return cls(
            raw=msg_data,
            content=(msg_data.get("content") or "").strip(),
            channel=msg_data.get("channel") or "",
            area=msg_data.get("area") or "",
            user=msg_data.get("person") or "",
            message_id=msg_data.get("messageId") or "",
            timestamp=msg_data.get("timestamp") or "",
        )

    def is_slash_command(self) -> bool:
        return self.content.startswith("/")

    def is_mention_command(self, bot_mention: str) -> bool:
        return bool(bot_mention and bot_mention in self.content)

    def is_command(self, bot_mention: str) -> bool:
        return self.is_mention_command(bot_mention) or self.is_slash_command()

    def mention_text(self, bot_mention: str) -> str:
        if not self.is_mention_command(bot_mention):
            return ""
        return self.content.replace(bot_mention, "").strip()


class CommandMessageService:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._bot_mention = runtime.bot_mention
        self._sender = runtime.sender

    def build_context(self, msg_data: dict) -> MessageContext:
        return MessageContext.from_message(msg_data)

    def remember_message(self, ctx: MessageContext) -> None:
        if not ctx.message_id:
            return

        self._runtime.recent_messages.append(
            {
                "messageId": str(ctx.message_id),
                "channel": ctx.channel,
                "area": ctx.area,
                # 保留短预览就够用了，也能避免缓存膨胀。
                "content": ctx.content[:50],
                "user": ctx.user,
                "timestamp": ctx.timestamp,
            }
        )

    async def reject_unauthorized_command(self, ctx: MessageContext) -> bool:
        if not ctx.is_command(self._bot_mention):
            return False

        if (
            self._runtime.services.routing.access.is_admin(ctx.user)
            or self._runtime.services.routing.access.is_public_command(ctx.content)
        ):
            return False

        logger.info("Non-admin user %s attempted command: %s", ctx.user, ctx.content[:40])
        await self._sender.send_message(
            f"{Msg.ERR} 无权限，仅管理员可使用该指令",
            channel=ctx.channel,
            area=ctx.area,
        )
        return True
