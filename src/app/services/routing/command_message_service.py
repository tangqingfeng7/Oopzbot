from dataclasses import dataclass

from config import PROFANITY_CONFIG
from logger_config import get_logger

from app.services.runtime import CommandRuntimeView

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
        self._bot_uid = runtime.bot_uid
        self._bot_mention = runtime.bot_mention
        self._sender = runtime.sender
        self._chat = runtime.chat

    def build_context(self, msg_data: dict) -> MessageContext:
        return MessageContext.from_message(msg_data)

    def remember_message(self, ctx: MessageContext) -> None:
        if not ctx.message_id:
            return

        self._runtime.recent_messages.append(
            {
                "messageId": str(ctx.message_id) if ctx.message_id is not None else "",
                "channel": ctx.channel,
                "area": ctx.area,
                # 保留短预览就够用了，也能避免缓存膨胀。
                "content": ctx.content[:50],
                "user": ctx.user,
                "timestamp": ctx.timestamp,
            }
        )

    def handle_profanity(self, ctx: MessageContext) -> bool:
        if not PROFANITY_CONFIG.get("enabled"):
            return False

        skip = PROFANITY_CONFIG.get("skip_admins") and self._runtime.services.routing.access.is_admin(ctx.user)
        if skip or ctx.user == self._bot_uid:
            return False

        msg_ref = [
            {
                "message_id": ctx.message_id,
                "channel": ctx.channel,
                "area": ctx.area,
                "timestamp": ctx.timestamp,
            }
        ]

        # 先跑便宜的关键词检查，再决定是否进入更重的上下文和 AI 检测。
        matched = self._runtime.services.safety.profanity.check_profanity(ctx.content)
        if matched:
            self._runtime.services.safety.profanity.handle_profanity(
                ctx.user,
                ctx.channel,
                ctx.area,
                matched,
                msg_ref,
            )
            return True

        use_context = PROFANITY_CONFIG.get("context_detection") or PROFANITY_CONFIG.get("ai_detection")
        if use_context:
            # 上下文检测和 AI 检测共用同一份用户滚动缓冲区。
            self._runtime.services.safety.profanity.push_user_buffer(
                ctx.user,
                ctx.content,
                ctx.message_id,
                ctx.channel,
                ctx.area,
                ctx.timestamp,
            )

        if PROFANITY_CONFIG.get("context_detection"):
            context_match = self._runtime.services.safety.profanity.check_context_profanity(ctx.user)
            if context_match:
                matched_keyword, involved_messages = context_match
                self._runtime.services.safety.profanity.handle_profanity(
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
        clean_content = self._runtime.services.safety.profanity.clean_text(ctx.content)
        if len(clean_content) >= min_len:
            logger.info('AI review single message: "%s" (len=%s)', ctx.content[:30], len(clean_content))
            reason = self._chat.check_profanity(ctx.content)
            if reason:
                logger.info("AI detected violation: %s -> %s", ctx.content[:30], reason)
                self._runtime.services.safety.profanity.handle_profanity(
                    ctx.user,
                    ctx.channel,
                    ctx.area,
                    f"AI:{reason}",
                    msg_ref,
                )
                return True

        user_buffer = self._runtime.services.safety.profanity.get_user_buffer(ctx.user)
        if len(user_buffer) < 2:
            return False

        combined = "".join(message["content"] for message in user_buffer)
        combined_clean = self._runtime.services.safety.profanity.clean_text(combined)
        if len(combined_clean) < min_len:
            return False

        logger.info(
            'AI review with context: "%s" (%s segments, len=%s)',
            combined[:40],
            len(user_buffer),
            len(combined_clean),
        )
        reason = self._chat.check_profanity(combined)
        if not reason:
            return False

        logger.info("AI contextual violation: %s -> %s", combined[:40], reason)
        self._runtime.services.safety.profanity.handle_profanity(
            ctx.user,
            ctx.channel,
            ctx.area,
            f"AI:{reason}",
            list(user_buffer),
        )
        return True

    def reject_unauthorized_command(self, ctx: MessageContext) -> bool:
        if not ctx.is_command(self._bot_mention):
            return False

        if (
            self._runtime.services.routing.access.is_admin(ctx.user)
            or self._runtime.services.routing.access.is_public_command(ctx.content)
        ):
            return False

        logger.info("Non-admin user %s attempted command: %s", ctx.user, ctx.content[:40])
        self._sender.send_message(
            "[x] 无权限，仅管理员可使用该指令",
            channel=ctx.channel,
            area=ctx.area,
        )
        return True
