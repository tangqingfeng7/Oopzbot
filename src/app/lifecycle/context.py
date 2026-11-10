from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.infrastructure.gateways.sender_gateway import SenderGateway
from bot.command_handler import CommandHandler

if TYPE_CHECKING:
    from app.lifecycle.oopz_session import OopzSession


@dataclass(slots=True)
class AppContext:
    """保存单一事件循环中的长生命周期服务。"""

    sender: SenderGateway
    handler: CommandHandler
    client: OopzSession
    notifier_callback: Any | None = None
    voice: Any | None = None
    dispatcher: Any | None = None
    supervisor: Any | None = None
