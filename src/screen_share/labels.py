"""屏幕共享频道消息的名称解析。"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from oopz.name_resolver import get_resolver

logger = logging.getLogger(__name__)


async def presenter_label(session: Mapping[str, Any]) -> str:
    presenter_uid = str(session.get("presenter_uid") or "")
    if not presenter_uid:
        return "未知成员"

    resolver = get_resolver()
    try:
        resolved = await resolver.ensure_users([presenter_uid])
    except Exception:
        logger.warning("解析屏幕共享发起者名称失败: uid=%s", presenter_uid, exc_info=True)
        resolved = {}
    return resolved.get(presenter_uid) or resolver.user(presenter_uid) or presenter_uid


__all__ = ["presenter_label"]
