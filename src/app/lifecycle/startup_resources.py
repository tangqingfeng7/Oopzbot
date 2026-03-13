"""启动前资源准备。"""

from dataclasses import dataclass

from database import init_database
from oopz_sender import OopzSender


@dataclass(frozen=True)
class StartupResources:
    """保存启动阶段准备好的基础资源。"""

    sender: OopzSender


class StartupResourceBuilder:
    """负责初始化数据库并预热发送端资源。"""

    def build(self) -> StartupResources:
        init_database()

        sender = OopzSender()
        sender.populate_names()

        return StartupResources(sender=sender)
