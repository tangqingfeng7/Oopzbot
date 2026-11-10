"""语音频道的存在感与域管理日志鉴权失败处理
"""

import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from music.music_playback import AudioPlayback  # noqa: E402
from services.area_join_notifier import (  # noqa: E402
    OPERATE_LOG_AUTH_FAILURE_LIMIT,
    is_operate_log_auth_failure,
    is_operate_log_permission_denied,
)


class VoiceDestroyLeavesChannelTest(unittest.IsolatedAsyncioTestCase):
    def _controller(self) -> tuple[AudioPlayback, Mock]:
        # 走正常构造，别用 __new__ 手工拼：新增字段时手工版会漏，
        # 而且只有跑全量时才暴露，单跑这个文件是绿的。
        voice = Mock()
        voice.leave = AsyncMock()
        voice.close = AsyncMock()
        controller = cast(Any, AudioPlayback(voice, proxy_value=False))
        return controller, voice

    async def test_destroy_leaves_before_closing(self) -> None:
        """必须先 leave 再 close：SDK 的 close() 不会退出频道。"""
        controller, voice = self._controller()
        order: list[str] = []
        voice.leave.side_effect = lambda: order.append("leave")
        voice.close.side_effect = lambda: order.append("close")

        await controller.destroy(timeout=1)

        self.assertEqual(order, ["leave", "close"])

    async def test_close_still_runs_when_leave_fails(self) -> None:
        """退频道失败（例如浏览器已崩）也不能卡住关停。"""
        controller, voice = self._controller()
        voice.leave.side_effect = RuntimeError("browser gone")

        await controller.destroy(timeout=1)

        voice.close.assert_awaited_once()

    async def test_destroy_is_idempotent(self) -> None:
        controller, voice = self._controller()

        await controller.destroy(timeout=1)
        await controller.destroy(timeout=1)

        voice.leave.assert_awaited_once()
        voice.close.assert_awaited_once()


class VoiceWarmupTest(unittest.IsolatedAsyncioTestCase):
    """冷启动时首次进频道的身份绑定赶不上，服务端不显示 bot 为成员"""

    def _controller(self) -> tuple[AudioPlayback, Mock]:
        voice = Mock()
        voice.start = AsyncMock()
        controller = cast(Any, AudioPlayback(voice, proxy_value=False))
        return controller, voice

    async def test_warmup_starts_the_browser_backend(self) -> None:
        controller, voice = self._controller()

        await controller.warmup()

        voice.start.assert_awaited_once()

    async def test_warmup_failure_does_not_propagate(self) -> None:
        """预热失败不能拖垮启动——真正进频道时 SDK 仍会自行 start()。"""
        controller, voice = self._controller()
        voice.start.side_effect = RuntimeError("playwright missing")

        await controller.warmup()

        voice.start.assert_awaited_once()

    async def test_warmup_is_skipped_after_close(self) -> None:
        controller, voice = self._controller()
        controller._closed = True

        await controller.warmup()

        voice.start.assert_not_awaited()


class OperateLogAuthFailureTest(unittest.TestCase):
    def test_real_401_message_is_recognised(self) -> None:
        """真机日志里的原文，必须被识别为鉴权失败。"""
        self.assertTrue(
            is_operate_log_auth_failure("Oopz authentication failed (HTTP 401): HTTP 401")
        )

    def test_428_is_also_auth_failure(self) -> None:
        self.assertTrue(is_operate_log_auth_failure("HTTP 428 credentials need refresh"))

    def test_unrelated_errors_are_not_auth_failures(self) -> None:
        for error in ("HTTP 500 server error", "HTTP 429 too many requests", "timeout", ""):
            with self.subTest(error=error):
                self.assertFalse(is_operate_log_auth_failure(error))

    def test_auth_failure_is_distinct_from_permission_denied(self) -> None:
        """两条路径要分开：403/中文权限提示一次即可停，401 需要连续多次。"""
        auth_error = "Oopz authentication failed (HTTP 401): HTTP 401"
        self.assertTrue(is_operate_log_auth_failure(auth_error))
        self.assertFalse(is_operate_log_permission_denied(auth_error))

        denied = "暂无进行此操作的权限"
        self.assertTrue(is_operate_log_permission_denied(denied))
        self.assertFalse(is_operate_log_auth_failure(denied))

    def test_limit_is_large_enough_to_ride_out_a_blip(self) -> None:
        """阈值太小会在一次凭据续期抖动时永久关掉该域的成员通知。"""
        self.assertGreaterEqual(OPERATE_LOG_AUTH_FAILURE_LIMIT, 3)


if __name__ == "__main__":
    unittest.main()
