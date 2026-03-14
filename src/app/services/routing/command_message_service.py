"""命令消息预处理服务。"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from config import PROFANITY_CONFIG
from logger_config import get_logger

logger = get_logger("CommandMessageService")


if TYPE_CHECKING:
    from command_handler import CommandHandler


@dataclass(frozen=True)
class MessageContext:
    """标准化后的消息上下文。"""

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
            channel=msg_data.get("channel"),
            area=msg_data.get("area"),
            user=msg_data.get("person"),
            message_id=msg_data.get("messageId"),
            timestamp=msg_data.get("timestamp", ""),
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
    """在命令路由前处理消息预校验和上下文整理。"""

    def __init__(self, handler: "CommandHandler", bot_uid: str, bot_mention: str):
        self._handler = handler
        self._bot_uid = bot_uid
        self._bot_mention = bot_mention
        self._sender = handler.infrastructure.sender
        self._chat = handler.infrastructure.chat

    def build_context(self, msg_data: dict) -> MessageContext:
        return MessageContext.from_message(msg_data)

    def remember_message(self, ctx: MessageContext) -> None:
        """记录最近消息，用于撤回等后续操作。"""
        if not ctx.message_id:
            return

        self._handler._recent_messages.append({
            "messageId": str(ctx.message_id) if ctx.message_id is not None else "",
            "channel": ctx.channel,
            "area": ctx.area,
            "content": ctx.content[:50],
            "user": ctx.user,
            "timestamp": ctx.timestamp,
        })
        if len(self._handler._recent_messages) > 50:
            self._handler._recent_messages.pop(0)

    def handle_profanity(self, ctx: MessageContext) -> bool:
        """处理违禁词与 AI 审核，命中时直接中断后续流程。"""
        if not PROFANITY_CONFIG.get("enabled"):
            return False

        skip = (
            PROFANITY_CONFIG.get("skip_admins")
            and self._handler.services.routing.access.is_admin(ctx.user)
        )
        if skip or ctx.user == self._bot_uid:
            return False

        msg_ref = [{
            "message_id": ctx.message_id,
            "channel": ctx.channel,
            "area": ctx.area,
            "timestamp": ctx.timestamp,
        }]

        matched = self._handler.services.safety.profanity.check_profanity(ctx.content)
        if matched:
            self._handler.services.safety.profanity.handle_profanity(
                ctx.user,
                ctx.channel,
                ctx.area,
                matched,
                msg_ref,
            )
            return True

        use_context = PROFANITY_CONFIG.get("context_detection") or PROFANITY_CONFIG.get("ai_detection")
        if use_context:
            self._handler.services.safety.profanity.push_user_buffer(
                ctx.user,
                ctx.content,
                ctx.message_id,
                ctx.channel,
                ctx.area,
                ctx.timestamp,
            )

        if PROFANITY_CONFIG.get("context_detection"):
            context_match = self._handler.services.safety.profanity.check_context_profanity(ctx.user)
            if context_match:
                matched_keyword, involved_messages = context_match
                self._handler.services.safety.profanity.handle_profanity(
                    ctx.user,
                    ctx.channel,
                    ctx.area,
                    matched_keyword,
                    involved_messages,
                )
                return True

        if not PROFANITY_CONFIG.get("ai_detection"):
            return False

        min_len = PROFANITY_CONFIG.get("ai_min_length", 2)
        clean_content = self._handler.services.safety.profanity.clean_text(ctx.content)
        if len(clean_content) >= min_len:
            logger.info('AI 审核单条: "%s" (长度=%s)', ctx.content[:30], len(clean_content))
            reason = self._chat.check_profanity(ctx.content)
            if reason:
                logger.info("AI 检测到违规: %s -> %s", ctx.content[:30], reason)
                self._handler.services.safety.profanity.handle_profanity(
                    ctx.user,
                    ctx.channel,
                    ctx.area,
                    f"AI:{reason}",
                    msg_ref,
                )
                return True

        user_buffer = self._handler.services.safety.profanity.get_user_buffer(ctx.user)
        if len(user_buffer) < 2:
            return False

        combined = "".join(message["content"] for message in user_buffer)
        combined_clean = self._handler.services.safety.profanity.clean_text(combined)
        if len(combined_clean) < min_len:
            return False

        logger.info(
            'AI 审核上下文: "%s" (%s条拼接, 长度=%s)',
            combined[:40],
            len(user_buffer),
            len(combined_clean),
        )
        reason = self._chat.check_profanity(combined)
        if not reason:
            return False

        logger.info("AI 上下文检测到违规: %s -> %s", combined[:40], reason)
        self._handler.services.safety.profanity.handle_profanity(
            ctx.user,
            ctx.channel,
            ctx.area,
            f"AI:{reason}",
            list(user_buffer),
        )
        return True

    def reject_unauthorized_command(self, ctx: MessageContext) -> bool:
        """拦截无权限命令。"""
        if not ctx.is_command(self._bot_mention):
            return False

        if (
            self._handler.services.routing.access.is_admin(ctx.user)
            or self._handler.services.routing.access.is_public_command(ctx.content)
        ):
            return False

        logger.info("非管理员用户 %s 尝试执行指令: %s", ctx.user, ctx.content[:40])
        self._sender.send_message(
            "[x] 无权限，仅管理员可使用指令",
            channel=ctx.channel,
            area=ctx.area,
        )
        return True
