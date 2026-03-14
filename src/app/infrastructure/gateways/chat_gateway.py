from chat import ChatHandler


class ChatGateway:
    """隔离应用层对 ChatHandler 具体实现的直接依赖。"""

    def __init__(self, chat: ChatHandler):
        self._chat = chat

    @property
    def raw(self) -> ChatHandler:
        return self._chat

    def __getattr__(self, name: str):
        return getattr(self._chat, name)
