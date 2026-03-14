from app.services.runtime import CommandRuntimeView, chat_of, sender_of


class ChatInteractionService:
    """负责普通聊天回复、AI 兜底回复和未知命令提示。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._chat = chat_of(runtime)

    def handle_plain_chat(self, content: str, channel: str, area: str) -> bool:
        """处理非命令消息的自动回复。"""
        reply = self._chat.try_reply(content)
        if not reply:
            return False

        self._sender.send_message(reply, channel=channel, area=area)
        return True

    def handle_mention_fallback(self, text: str, channel: str, area: str) -> None:
        """处理 @bot 未匹配到已知指令时的 AI 兜底回复。"""
        reply = self._chat.ai_reply(text)
        if reply:
            self._sender.send_message(
                reply,
                channel=channel,
                area=area,
                auto_recall=self._runtime.services.safety.recall_scheduler.should_skip_auto_recall("ai_chat"),
            )
            return

        self._sender.send_message("我没听懂，输入 @bot 帮助 查看指令", channel=channel, area=area)

    def send_unknown_command(self, command: str, channel: str, area: str) -> None:
        """发送未知斜杠命令提示。"""
        self._sender.send_message(
            f"未知命令: {command}\n输入 /help 查看帮助",
            channel=channel,
            area=area,
        )
