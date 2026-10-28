"""基于声网 Web SDK 的临时屏幕共享。"""

from .service import ScreenShareError, ScreenShareService, get_screen_share_service

__all__ = ["ScreenShareError", "ScreenShareService", "get_screen_share_service"]
