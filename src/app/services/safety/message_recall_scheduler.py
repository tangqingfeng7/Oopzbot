import threading
from typing import Optional

from config import AUTO_RECALL_CONFIG
from app.services.runtime import CommandRuntimeView, sender_of


class MessageRecallScheduler:
    """负责自动撤回判定和异步调度。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)
        self._pending_timers: list[threading.Timer] = []
        self._lock = threading.Lock()

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

        def _do_recall():
            self._sender.recall_message(
                message_id=message_id, area=area,
                channel=channel, timestamp=timestamp,
            )
            with self._lock:
                self._pending_timers = [t for t in self._pending_timers if t.is_alive()]

        timer = threading.Timer(delay, _do_recall)
        timer.daemon = True
        with self._lock:
            self._pending_timers.append(timer)
        timer.start()

    def cancel_all(self) -> int:
        """取消所有待执行的撤回计时器，返回取消数量。"""
        with self._lock:
            count = 0
            for t in self._pending_timers:
                if t.is_alive():
                    t.cancel()
                    count += 1
            self._pending_timers.clear()
        return count
