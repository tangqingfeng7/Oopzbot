from app.services.runtime import CommandRuntimeView
from config import ADMIN_UIDS
from core.area_config import get_area_registry
from domain.routing.public_command_rules import (
    is_public_mention_text,
    is_public_slash_command,
)


class CommandAccessService:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._plugins = runtime.plugins

    @staticmethod
    def has_configured_admins(area: str = "") -> bool:
        """是否配置过管理员名单（域级非空时优先，否则检查全局）。"""
        area_id = str(area or "").strip()
        if area_id and get_area_registry().get(area_id).admin_uids:
            return True
        return bool(ADMIN_UIDS)

    @staticmethod
    def is_admin(user: str, area: str = "") -> bool:
        area_id = str(area or "").strip()
        if area_id:
            area_admins = get_area_registry().get(area_id).admin_uids
            if area_admins:
                return user in area_admins
        return user in ADMIN_UIDS

    def is_public_command(self, content: str) -> bool:
        bot_mention = self._runtime.bot_mention
        if bot_mention and bot_mention in content:
            text = content.replace(bot_mention, "").strip()
            if self._plugins.has_admin_only_mention_prefix(text):
                return False
            if is_public_mention_text(text):
                return True
            return self._plugins.has_public_mention_prefix(text)

        if content.startswith("/"):
            command = content.split()[0].lower()
            if self._plugins.has_admin_only_slash_command(command):
                return False
            if is_public_slash_command(command):
                return True
            return self._plugins.has_public_slash_command(command)

        return False
