
from app.services.runtime import CommandRuntimeView, sender_of


class MessageLookupService:
    """负责从本地缓存和远程接口查询消息元数据。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    async def resolve_timestamp(self, message_id: str, channel: str, area: str) -> str | None:
        """从内存记录或远程 API 查找消息时间戳。"""
        for message in reversed(self._runtime.recent_messages):
            if message.get("messageId") == message_id and message.get("timestamp"):
                return message["timestamp"]

        for message in await self._sender.bot.messages.get_channel_messages(area, channel):
            if message.message_id == message_id:
                return message.timestamp or None
        return None
