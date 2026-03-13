"""目标解析服务。"""

import re
from typing import TYPE_CHECKING, Optional

from name_resolver import get_resolver


if TYPE_CHECKING:
    from command_handler import CommandHandler


class TargetResolutionService:
    """负责解析用户目标和禁言参数。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler

    def resolve_target(self, text: str) -> Optional[str]:
        """从 @mention、UID 或用户名中解析目标用户 UID。"""
        text = text.strip()
        if not text:
            return None

        match = re.search(r"\(met\)(\w+)\(met\)", text)
        if match:
            return match.group(1)

        token = text.split()[0]
        if re.fullmatch(r"[a-f0-9]{32}", token):
            return token

        return get_resolver().find_uid_by_name(token)

    def parse_mute_args(self, text: str) -> tuple[Optional[str], int]:
        """解析禁言/禁麦参数，返回 `(uid, duration)`。"""
        text = text.strip()
        match = re.match(r"\(met\)(\w+)\(met\)\s*(\d+)?", text)
        if match:
            duration = int(match.group(2)) if match.group(2) else 10
            return match.group(1), duration

        parts = text.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_part, duration = parts[0], int(parts[1])
        else:
            name_part, duration = text, 10

        uid = self.resolve_target(name_part)
        return uid, duration
