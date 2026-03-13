"""命令访问控制服务。"""

from typing import TYPE_CHECKING

from config import ADMIN_UIDS
from domain.routing.public_command_rules import (
    is_public_mention_text,
    is_public_slash_command,
)


if TYPE_CHECKING:
    from command_handler import CommandHandler


class CommandAccessService:
    """负责管理员权限和公共命令可见性判断。"""

    def __init__(self, handler: "CommandHandler", bot_mention: str):
        self._handler = handler
        self._bot_mention = bot_mention
        self._plugins = handler.infrastructure.plugins

    @staticmethod
    def is_admin(user: str) -> bool:
        """检查用户是否为授权管理员。ADMIN_UIDS 为空时不做限制。"""
        if not ADMIN_UIDS:
            return True
        return user in ADMIN_UIDS

    def is_public_command(self, content: str) -> bool:
        """检查是否为公共指令。"""
        if self._bot_mention and self._bot_mention in content:
            text = content.replace(self._bot_mention, "").strip()
            if is_public_mention_text(text):
                return True
            return self._plugins.has_public_mention_prefix(text)

        if content.startswith("/"):
            command = content.split()[0].lower()
            if is_public_slash_command(command):
                return True
            return self._plugins.has_public_slash_command(command)

        return False
