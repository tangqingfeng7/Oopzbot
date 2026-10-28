from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def sent_message_reference(response: Any) -> tuple[str, str]:
    """从 Oopz 发送结果中取出后续撤回必需的消息引用。"""
    payload: Any = response
    json_method = getattr(response, "json", None)
    if callable(json_method):
        try:
            payload = json_method()
        except Exception:
            return "", ""
    if not isinstance(payload, dict) or payload.get("error"):
        return "", ""
    data = payload.get("data")
    if not isinstance(data, dict):
        return "", ""
    return (
        str(data.get("messageId") or data.get("message_id") or "").strip(),
        str(data.get("timestamp") or "").strip(),
    )


async def recall_viewer_link(sender: Any, session: dict[str, Any]) -> bool:
    """撤回某个共享会话在频道中的观看链接。"""
    message_id = str(session.get("viewer_message_id") or "").strip()
    if not message_id:
        return False
    try:
        result = await sender.recall_message(
            message_id,
            area=str(session.get("area") or ""),
            channel=str(session.get("channel") or ""),
            timestamp=str(session.get("viewer_message_timestamp") or "") or None,
        )
        if isinstance(result, dict) and result.get("error"):
            logger.warning(
                "撤回屏幕共享观看链接失败: session_id=%s error=%s",
                session.get("id", ""),
                result.get("error"),
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
