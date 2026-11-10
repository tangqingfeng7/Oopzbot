from __future__ import annotations

import logging
from typing import Any

from oopz_sdk.models.message import MessageSendResult

logger = logging.getLogger(__name__)


def sent_message_reference(response: MessageSendResult) -> tuple[str, str]:
    """从 Oopz 发送结果中取出后续撤回必需的消息引用。"""
    return response.message_id, response.timestamp


async def recall_viewer_link(sender: Any, session: dict[str, Any]) -> bool:
    """撤回某个共享会话在频道中的观看链接。"""
    message_id = str(session.get("viewer_message_id") or "").strip()
    if not message_id:
        return False
    try:
        result = await sender.bot.messages.recall_message(message_id, channel=str(session.get("channel") or ""), timestamp=str(session.get("viewer_message_timestamp") or "") or None, area=str(session.get("area") or ""))
        if not result.ok:
            logger.warning(
                "撤回屏幕共享观看链接失败: session_id=%s error=%s",
                session.get("id", ""),
                result.message,
            )
            return False
    except Exception:
        logger.warning(
            "撤回屏幕共享观看链接异常: session_id=%s",
            session.get("id", ""),
            exc_info=True,
        )
        return False
    return True


__all__ = ["recall_viewer_link", "sent_message_reference"]
