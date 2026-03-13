"""消息查询服务。"""

from typing import TYPE_CHECKING, Optional


if TYPE_CHECKING:
    from command_handler import CommandHandler


class MessageLookupService:
    """负责从本地缓存和远程接口查询消息元数据。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._sender = handler.infrastructure.sender

    def resolve_timestamp(self, message_id: str, channel: str, area: str) -> Optional[str]:
        """从内存记录或远程 API 查找消息时间戳。"""
        for message in reversed(self._handler._recent_messages):
            if message.get("messageId") == message_id and message.get("timestamp"):
                return message["timestamp"]

        return self._sender.find_message_timestamp(message_id, area=area, channel=channel)
