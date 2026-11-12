from app.services.runtime import CommandRuntimeView, sender_of


class ChatInteractionService:
    """负责未知命令提示。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)

    async def send_unknown_mention_command(self, text: str, channel: str, area: str, suggestions: list[str] | None = None) -> None:
        """发送未知 @bot 命令提示。"""
        lines = [f"未识别的命令: {text}", "输入 @bot 帮助 查看分类帮助"]
        if suggestions:
            lines.append("你是不是想用:")
            for item in suggestions:
                lines.append(f"  {item}")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def send_unknown_command(self, command: str, channel: str, area: str, suggestions: list[str] | None = None) -> None:
        """发送未知斜杠命令提示。"""
        lines = [f"未知命令: {command}", "输入 /help 查看帮助"]
        if suggestions:
            lines.append("你是不是想用:")
            for item in suggestions:
                lines.append(f"  {item}")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)
