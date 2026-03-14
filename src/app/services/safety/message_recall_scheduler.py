"""自动撤回调度服务。"""

import threading
from typing import TYPE_CHECKING, Optional

from config import AUTO_RECALL_CONFIG


if TYPE_CHECKING:
    from command_handler import CommandHandler


class MessageRecallScheduler:
    """负责自动撤回判定和异步调度。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._sender = handler.infrastructure.sender

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
