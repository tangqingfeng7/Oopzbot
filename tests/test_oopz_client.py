"""长连接与凭据续期的语义。

旧的 `oopz.oopz_client.OopzClient` 自己实现了 JWT 过期解析、鉴权失败识别、
心跳探活与重连退避。迁移后这些职责分散到三处：SDK 的 `utils/jwt`、
`auth/manager`、`client/ws`，以及本项目在 `app/infrastructure/oopz_connection.py` 里对
陈旧连接的加固。用例按新归属重写，守住的行为与旧实现一致。
"""

import asyncio
import base64
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.exceptions import OopzAuthError, OopzConnectionError  # noqa: E402
from oopz_sdk.utils.jwt import decode_jwt_payload, jwt_expired  # noqa: E402


def _fake_jwt(payload: dict) -> str:
    def _b64(obj) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")
        return raw.rstrip("=")

    return f"{_b64({'alg': 'RS256'})}.{_b64(payload)}.sig"


class JwtExpiryParseTest(unittest.TestCase):
    def test_expired_token_is_reported_as_expired(self) -> None:
        self.assertTrue(jwt_expired(_fake_jwt({"exp": int(time.time()) - 3600})))

    def test_valid_token_is_not_expired(self) -> None:
        self.assertFalse(jwt_expired(_fake_jwt({"exp": int(time.time()) + 3600})))

    def test_token_without_exp_is_not_treated_as_expired(self) -> None:
        # 没有 exp 无从判断，保守当作未过期，否则会把长期 token 反复顶掉
        self.assertFalse(jwt_expired(_fake_jwt({"sub": "u1"})))
        self.assertEqual(decode_jwt_payload(_fake_jwt({"sub": "u1"})).get("sub"), "u1")

    def test_garbage_token_decodes_to_empty_payload(self) -> None:
        for token in ("not-a-jwt", "", cast(str, None)):
            with self.subTest(token=token):
                self.assertEqual(decode_jwt_payload(token), {})
                self.assertFalse(jwt_expired(token))

    def test_leeway_absorbs_a_fast_local_clock(self) -> None:
        """本地时钟略快时不该误判过期，否则每次启动都会白重登一次。"""
        exp = int(time.time())
        token = _fake_jwt({"exp": exp})

        self.assertTrue(jwt_expired(token, now=exp + 10, leeway=0))
        self.assertFalse(jwt_expired(token, now=exp + 10, leeway=60))


class AuthRejectionDetectionTest(unittest.TestCase):
    """服务端用 event=21 + checkRes=false 表示运行期鉴权失效。

    关闭帧只给通用 1006，没有业务语义，所以必须靠这条事件精确识别，
    否则会把凭据失效误当成网络抖动，一直重连却永远连不上。
    """

    def _check(self, raw: str) -> None:
        from oopz_sdk.client.ws import OopzWSClient

        OopzWSClient._raise_if_auth_rejected(raw)

    def test_check_res_false_is_an_auth_error(self) -> None:
        with self.assertRaises(OopzAuthError):
            self._check(json.dumps({"event": 21, "body": {"checkRes": False}}))

    def test_body_may_arrive_as_a_json_string(self) -> None:
        with self.assertRaises(OopzAuthError):
            self._check(json.dumps({"event": 21, "body": json.dumps({"checkRes": False})}))

    def test_success_and_unrelated_shapes_pass_through(self) -> None:
        for raw in (
            json.dumps({"event": 21, "body": {"checkRes": True}}),
            json.dumps({"event": 1, "body": {"checkRes": False}}),
            json.dumps({"event": 21, "body": "not json"}),
            json.dumps({"person": "u1"}),
            "{}",
            "not json at all",
        ):
            with self.subTest(raw=raw):
                self._check(raw)


class StaleConnectionDetectionTest(unittest.IsolatedAsyncioTestCase):
    """长时间收不到任何数据说明连接已经死了，必须主动断开触发重连。"""

    def _transport(self, stale: float):
        import app.infrastructure.oopz_connection as module

        transport = cast(
            Any, module.ProjectWebSocketTransport.__new__(module.ProjectWebSocketTransport)
        )
        transport.stale_timeout = stale
        transport.close = AsyncMock()
        return transport

    async def test_no_data_beyond_threshold_closes_and_raises(self) -> None:
        import app.infrastructure.oopz_connection as module

        transport = self._transport(0.02)
        never = asyncio.Event()

        async def blocked_recv(_self):
            await never.wait()

        with (
            patch.object(module.WebSocketTransport, "recv", blocked_recv),
            self.assertRaises(OopzConnectionError),
        ):
            await transport.recv()

        transport.close.assert_awaited_once()

    async def test_recent_data_passes_straight_through(self) -> None:
        import app.infrastructure.oopz_connection as module

        transport = self._transport(5.0)

        async def quick_recv(_self):
            return "payload"

        with patch.object(module.WebSocketTransport, "recv", quick_recv):
            self.assertEqual(await transport.recv(), "payload")

        transport.close.assert_not_awaited()

    async def test_non_positive_timeout_disables_the_check(self) -> None:
        import app.infrastructure.oopz_connection as module

        transport = self._transport(0)
        calls: list[str] = []

        async def recv(_self):
            calls.append("recv")
            return "payload"

        with patch.object(module.WebSocketTransport, "recv", recv):
            self.assertEqual(await transport.recv(), "payload")

        # 关掉探活时不应再包一层 wait_for
        self.assertEqual(calls, ["recv"])
        transport.close.assert_not_awaited()


class CredentialRefreshTest(unittest.IsolatedAsyncioTestCase):
    def _manager(self, *, exp_offset: float, threshold: float = 300.0):
        from oopz_sdk.auth.manager import AuthManager

        manager = cast(Any, AuthManager.__new__(AuthManager))
        manager._config = Mock()
        manager._config.jwt_token = _fake_jwt({"exp": time.time() + exp_offset})
        manager._refresh_threshold = threshold
        manager._token_version = 0
        manager._relogin = None
        manager._lock = asyncio.Lock()
        return manager

    async def test_token_inside_the_window_needs_refresh(self) -> None:
        manager = self._manager(exp_offset=60)
        self.assertTrue(manager.needs_refresh())

    async def test_fresh_token_does_not_need_refresh(self) -> None:
        manager = self._manager(exp_offset=3600)
        self.assertFalse(manager.needs_refresh())

    async def test_token_without_exp_never_triggers_refresh(self) -> None:
        manager = self._manager(exp_offset=0)
        manager._config.jwt_token = _fake_jwt({"sub": "u1"})
        self.assertFalse(manager.needs_refresh())
        self.assertIsNone(manager.seconds_until_expiry())

    async def test_ensure_fresh_skips_relogin_when_not_expiring(self) -> None:
        manager = self._manager(exp_offset=3600)
        manager.refresh = AsyncMock(return_value=True)

        self.assertTrue(await manager.ensure_fresh())
        manager.refresh.assert_not_awaited()

    async def test_concurrent_refresh_relogins_only_once(self) -> None:
        """续期是 single-flight：并发失效不能打出多次重登。"""
        manager = self._manager(exp_offset=-10)
        relogins: list[int] = []

        async def relogin():
            relogins.append(1)
            await asyncio.sleep(0.01)
            return Mock()

        manager._relogin = object()  # can_refresh 由是否持有重登回调决定
        manager._relogin_with_transient_retry = relogin
        manager._apply = lambda _credentials: setattr(
            manager, "_token_version", manager._token_version + 1
        )

        results = await asyncio.gather(
            manager.refresh(force=True),
            manager.refresh(force=True),
        )

        self.assertEqual(results, [True, True])
        self.assertEqual(len(relogins), 1, "等锁期间已完成的续期应被复用")

    async def test_refresh_is_skipped_when_credentials_cannot_relogin(self) -> None:
        manager = self._manager(exp_offset=-10)
        manager._relogin = None  # 没有重登回调就无从续期

        self.assertFalse(await manager.refresh(force=True))
        self.assertFalse(await manager.ensure_fresh())


if __name__ == "__main__":
    unittest.main()
