from config import ADMIN_UIDS
from domain.routing.public_command_rules import (
    is_public_mention_text,
    is_public_slash_command,
)

from app.services.runtime import CommandRuntimeView


class CommandAccessService:
    def __init__(self, runtime: CommandRuntimeView):
        self._bot_mention = runtime.bot_mention
        self._plugins = runtime.plugins

    @staticmethod
    def is_admin(user: str) -> bool:
        if not ADMIN_UIDS:
            return True
        return user in ADMIN_UIDS

    def is_public_command(self, content: str) -> bool:
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
