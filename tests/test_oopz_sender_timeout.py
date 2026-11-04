"""出站请求的超时契约。

旧实现由 `oopz.oopz_sender` / `oopz.oopz_api` 自己按档位给 requests 传
`timeout=(连接, 读)`。迁移到 SDK + aiohttp 后，超时有两个来源：
`RequestConfig` 配到传输层，或调用方逐次传入。这里守住的仍是同一件事——
**任何出站请求都必须有界**，不能出现连上以后无限等待的调用。
"""

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.http_constants import HTTP_TIMEOUT_API, HTTP_TIMEOUT_API_SLOW  # noqa: E402

_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "request", "ws_connect"}


class TimeoutTierTest(unittest.TestCase):
    def test_tiers_are_connect_read_tuples(self) -> None:
        for tier in (HTTP_TIMEOUT_API, HTTP_TIMEOUT_API_SLOW):
            self.assertIsInstance(tier, tuple)
            self.assertEqual(len(tier), 2)

    def test_slow_tier_reads_longer_but_connects_the_same(self) -> None:
        # 连接超时与传输量无关，各档共用；分档只分「读」
        self.assertEqual(HTTP_TIMEOUT_API[0], HTTP_TIMEOUT_API_SLOW[0])
        self.assertGreater(HTTP_TIMEOUT_API_SLOW[1], HTTP_TIMEOUT_API[1])


class SdkTransportTimeoutTest(unittest.TestCase):
    """SDK 传输层要把配置的档位真正翻译成 aiohttp 的超时。"""

    def test_tuple_becomes_socket_level_bounds(self) -> None:
        from oopz_sdk.transport.http import _build_timeout

        timeout = _build_timeout((5, 30))

        # 元组档位的语义是「连接 5 秒、两次收包间隔 30 秒」，没有总时限
        self.assertEqual(timeout.sock_connect, 5)
        self.assertEqual(timeout.sock_read, 30)
        self.assertIsNone(timeout.total)

    def test_scalar_becomes_total_bound(self) -> None:
        from oopz_sdk.transport.http import _build_timeout

        timeout = _build_timeout(12)

        self.assertEqual(timeout.total, 12)

    def test_project_config_supplies_a_bounded_tier(self) -> None:
        """本项目必须显式配档，不能让网关落到无界请求上。"""
        import oopz.sdk_config as sdk_config

        source = Path(sdk_config.__file__).read_text(encoding="utf-8")
        self.assertIn("RequestConfig(timeout=", source)

        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "RequestConfig"
            ):
                for kw in node.keywords:
                    if kw.arg == "timeout":
                        found.append(ast.literal_eval(kw.value))
        self.assertTrue(found, "sdk_config 必须给 RequestConfig 显式配置 timeout")
        for value in found:
            connect, read = value
            self.assertGreater(connect, 0)
            self.assertGreater(read, connect, "读超时应比连接超时宽松")


class ManagedHttpClientTimeoutTest(unittest.IsolatedAsyncioTestCase):
    """自建的异步 HTTP 客户端要把 timeout 透传到 aiohttp，而不是只在签名上摆着。"""

    async def test_timeout_reaches_aiohttp(self) -> None:
        import aiohttp

        from core.async_http import ManagedHttpClient

        captured = {}

        class _Resp:
            status = 200

            async def json(self, content_type=None):
                return {"ok": True}

            def raise_for_status(self):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class _Session:
            def request(self, method, url, **kwargs):
                captured.update(kwargs)
                return _Resp()

        client = ManagedHttpClient()
        client.session = AsyncMock(return_value=_Session())

        await client.request_json("GET", "https://example.com/x", timeout=7)

        self.assertIsInstance(captured["timeout"], aiohttp.ClientTimeout)
        self.assertEqual(captured["timeout"].total, 7)

    async def test_timeout_is_required_by_signature(self) -> None:
        """timeout 是 keyword-only 且无默认值，漏传会在调用处直接报错。"""
        import inspect

        from core.async_http import ManagedHttpClient

        for name in ("request_json", "request_payload", "request_text"):
            with self.subTest(method=name):
                param = inspect.signature(getattr(ManagedHttpClient, name)).parameters["timeout"]
                self.assertIs(param.default, inspect.Parameter.empty)
                self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)


class NoUnboundedOutboundCallTest(unittest.TestCase):
    """AST 守卫：项目代码里不能出现「会话无超时 + 调用也不传超时」的组合。

    aiohttp 允许把超时设在 ClientSession 上，所以旧的「每个调用点都必须带
    timeout」规则不再适用；真正要挡住的是两处都没有、请求彻底无界。
    """

    def test_no_unbounded_outbound_call(self) -> None:
        offenders = []
        for path in SRC_ROOT.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))

            # 把「无超时的会话」按其赋值目标记下来，才能和调用方精确配对；
            # 只按文件配对会把 HTTP 会话和 WS 调用错配。
            unbounded_sessions = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                value = node.value
                if not isinstance(value, ast.Call):
                    continue
                func = value.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name != "ClientSession":
                    continue
                if any(kw.arg == "timeout" for kw in value.keywords):
                    continue
                for target in node.targets:
                    unbounded_sessions.add(ast.unparse(target))

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_VERBS:
                    continue
                if any(kw.arg == "timeout" for kw in node.keywords):
                    continue
                if ast.unparse(func.value) in unbounded_sessions:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno} "
                        f"({ast.unparse(func.value)}.{func.attr})"
                    )

        self.assertEqual(offenders, [], f"存在无界的出站请求: {offenders}")

    def test_requests_style_calls_always_pass_timeout(self) -> None:
        """requests 没有会话级默认超时，漏传就是无限等待。"""
        offenders = []
        for path in SRC_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "import requests" not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_VERBS:
                    continue
                if "requests" not in ast.unparse(func.value):
                    continue
                if not any(kw.arg == "timeout" for kw in node.keywords):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")

        self.assertEqual(offenders, [], f"这些 requests 调用没有 timeout: {offenders}")


class AutoRecallSchedulingTest(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_delegates_to_shared_scheduler(self) -> None:
        import oopz.sdk_gateway as module

        gateway = module.AsyncOopzGateway.__new__(module.AsyncOopzGateway)
        gateway._auto_recall_scheduler = mock.Mock()
        gateway._auto_recall_scheduler.schedule_recall = AsyncMock(return_value=True)

        with mock.patch.object(module, "AUTO_RECALL_CONFIG", {"enabled": True, "delay": 12}):
            await gateway._schedule_auto_recall("message-1", "area-1", "channel-1", "ts-1")

        gateway._auto_recall_scheduler.schedule_recall.assert_awaited_once_with(
            message_id="message-1",
            channel="channel-1",
            area="area-1",
            timestamp="ts-1",
            delay=12.0,
        )

    async def test_disabled_config_skips_scheduling(self) -> None:
        import oopz.sdk_gateway as module

        gateway = module.AsyncOopzGateway.__new__(module.AsyncOopzGateway)
        gateway._auto_recall_scheduler = mock.Mock()
        gateway._auto_recall_scheduler.schedule_recall = AsyncMock()

        with mock.patch.object(module, "AUTO_RECALL_CONFIG", {"enabled": False, "delay": 12}):
            await gateway._schedule_auto_recall("message-1", "area-1", "channel-1", "ts-1")

        gateway._auto_recall_scheduler.schedule_recall.assert_not_awaited()

    async def test_non_positive_delay_skips_scheduling(self) -> None:
        """延迟为 0 意味着立即撤回，等同于没发出去，必须当作未启用。"""
        import oopz.sdk_gateway as module

        gateway = module.AsyncOopzGateway.__new__(module.AsyncOopzGateway)
        gateway._auto_recall_scheduler = mock.Mock()
        gateway._auto_recall_scheduler.schedule_recall = AsyncMock()

        with mock.patch.object(module, "AUTO_RECALL_CONFIG", {"enabled": True, "delay": 0}):
            await gateway._schedule_auto_recall("message-1", "area-1", "channel-1", "ts-1")

        gateway._auto_recall_scheduler.schedule_recall.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
