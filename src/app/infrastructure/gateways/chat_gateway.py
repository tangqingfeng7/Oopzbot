from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from chat import ChatHandler


class ChatGateway:
    """隔离应用层对 ChatHandler 具体实现的直接依赖。

    显式暴露业务方法以保留类型信息，避免纯 __getattr__ 透传。
    """

    def __init__(self, chat: ChatHandler):
        self._chat = chat

    @property
    def raw(self) -> ChatHandler:
        return self._chat

    @property
    def ai_enabled(self) -> bool:
        return bool(self._chat.ai_enabled)

    @property
    def img_enabled(self) -> bool:
        return bool(self._chat.img_enabled)

    def try_reply(self, content: str) -> Optional[str]:
        return self._chat.try_reply(content)

    def ai_reply(self, content: str, history: list[dict] | None = None) -> Optional[str]:
        return self._chat.ai_reply(content, history=history)

    def generate_image(self, prompt: str) -> Optional[str]:
        return self._chat.generate_image(prompt)

    def check_profanity(self, content: str) -> Optional[str]:
        return self._chat.check_profanity(content)

    def add_keyword(self, keyword: str, reply: str):
        self._chat.add_keyword(keyword, reply)

    def remove_keyword(self, keyword: str) -> bool:
        return self._chat.remove_keyword(keyword)

    def list_keywords(self) -> dict:
        return self._chat.list_keywords()

    def __getattr__(self, name: str):
        return getattr(self._chat, name)
