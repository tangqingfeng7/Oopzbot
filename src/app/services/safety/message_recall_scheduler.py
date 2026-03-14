import threading
from typing import Optional

from config import AUTO_RECALL_CONFIG
from app.services.runtime import CommandRuntimeView, sender_of


class MessageRecallScheduler:
    """负责自动撤回判定和异步调度。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)

    @staticmethod
    def should_skip_auto_recall(command_type: str) -> Optional[bool]:
        """检查指定命令类型是否应跳过自动撤回。"""
        if AUTO_RECALL_CONFIG.get("enabled"):
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            if command_type in exclude:
                return False
        return None

    def schedule_user_message_recall(
        self,
        message_id: str,
        channel: str,
        area: str,
        timestamp: str = "",
    ) -> None:
        """在自动撤回开启时延迟撤回用户指令消息。"""
        if not message_id:
            return
        if not AUTO_RECALL_CONFIG.get("enabled"):
            return

        delay = AUTO_RECALL_CONFIG.get("delay", 30)
        if delay <= 0:
            return

        timer = threading.Timer(
            delay,
            self._sender.recall_message,
            kwargs={
                "message_id": message_id,
                "area": area,
                "channel": channel,
                "timestamp": timestamp,
            },
        )
        timer.daemon = True
        timer.start()
