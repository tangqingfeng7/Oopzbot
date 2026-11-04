from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.command_handler import CommandHandler
from oopz.sdk_gateway import AsyncOopzGateway


@dataclass(slots=True)
class AppContext:
    """保存单一事件循环中的长生命周期服务。"""

    sender: AsyncOopzGateway
    handler: CommandHandler
    client: AsyncOopzGateway
    notifier_callback: Any | None = None
    voice: Any | None = None
    dispatcher: Any | None = None
    supervisor: Any | None = None
