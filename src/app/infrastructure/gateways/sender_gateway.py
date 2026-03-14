from oopz_sender import OopzSender


class SenderGateway:
    """隔离应用层对 OopzSender 具体实现的直接依赖。"""

    def __init__(self, sender: OopzSender):
        self._sender = sender

    @property
    def raw(self) -> OopzSender:
        return self._sender

    def __getattr__(self, name: str):
        return getattr(self._sender, name)
