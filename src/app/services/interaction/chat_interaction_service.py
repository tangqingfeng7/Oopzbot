from typing import Optional

from app.services.runtime import CommandRuntimeView, chat_of, sender_of
from logger_config import get_logger

logger = get_logger("ChatInteractionService")


class ChatInteractionService:
    """负责普通聊天回复、AI 兜底回复和未知命令提示。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._chat = chat_of(runtime)
        self._memory: Optional["ConversationMemory"] = None  # noqa: F821
        self._memory_init = False

    def _ensure_memory(self):
        """延迟初始化 ConversationMemory（首次调用时）。"""
        if self._memory_init:
            return
        self._memory_init = True
        try:
            from conversation_memory import create_conversation_memory
            from queue_manager import get_redis_client
            redis_client = get_redis_client()
            self._memory = create_conversation_memory(redis_client)
        except Exception as e:
            logger.debug("ConversationMemory 初始化失败（AI 上下文记忆不可用）: %s", e)
            self._memory = None

    def handle_plain_chat(self, content: str, channel: str, area: str) -> bool:
        """处理非命令消息的自动回复。"""
        reply = self._chat.try_reply(content)
        if not reply:
            return False

        self._sender.send_message(reply, channel=channel, area=area)
        return True

    def handle_mention_fallback(self, text: str, channel: str, area: str, user: str = "") -> None:
        """处理 @bot 未匹配到已知指令时的 AI 兜底回复。支持上下文记忆。"""
        self._ensure_memory()

        history = None
        if self._memory and user:
            history = self._memory.get_history(user, channel)

        reply = self._chat.ai_reply(text, history=history)
        if reply:
            if self._memory and user:
                self._memory.add_round(user, channel, text, reply)
            self._sender.send_message(
                reply,
                channel=channel,
                area=area,
                auto_recall=self._runtime.services.safety.recall_scheduler.should_skip_auto_recall("ai_chat"),
            )
            return

        self._sender.send_message("我没听懂，输入 @bot 帮助 查看指令", channel=channel, area=area)

    def clear_memory(self, user: str, channel: str) -> bool:
        """清除指定用户在指定频道的对话记忆。"""
        self._ensure_memory()
        if self._memory:
            return self._memory.clear(user, channel)
        return False

    def clear_user_memory(self, user: str) -> int:
        """清除指定用户在所有频道的对话记忆。"""
        self._ensure_memory()
        if self._memory:
            return self._memory.clear_user(user)
        return 0

    def send_unknown_command(self, command: str, channel: str, area: str) -> None:
        """发送未知斜杠命令提示。"""
        self._sender.send_message(
            f"未知命令: {command}\n输入 /help 查看帮助",
            channel=channel,
            area=area,
        )
