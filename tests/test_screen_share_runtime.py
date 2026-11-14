from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock, patch

import httpx2
from oopz_sdk.models import MessageSendResult, OperationResult

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from app.infrastructure.runtime import BotInfrastructure, PluginHost, PluginRuntime  # noqa: E402
from domain.plugins.plugin_operation import PluginOperationCode  # noqa: E402
from tests.test_screen_share import CONFIG, FakeRedis  # noqa: E402
from web import web_player  # noqa: E402
from web.admin.shared import _pages  # noqa: E402
from web.web_rate_limit import reset_all  # noqa: E402

if TYPE_CHECKING:
    from plugins.screen_share import ScreenSharePlugin


class ScreenShareRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.state_path = Path(directory) / "plugins.json"
        self.runtime = PluginRuntime(state_path=self.state_path)
        self.addAsyncCleanup(self.runtime.stop)
        self.sender = SimpleNamespace(
            bot=SimpleNamespace(
                messages=SimpleNamespace(
                    send_private_message=AsyncMock(),
                    recall_message=AsyncMock(return_value=OperationResult()),
                ),
            ),
            send_message=AsyncMock(return_value=MessageSendResult(messageId="viewer-message")),
        )
        services = SimpleNamespace(
            routing=SimpleNamespace(access=SimpleNamespace(is_admin=lambda _user: True))
        )
        self.host = PluginHost(Mock(spec=BotInfrastructure, sender=self.sender), lambda: services)
        self.redis = FakeRedis()
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=web_player.app, client=("127.0.0.1", 50000)),
            base_url="http://localhost",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.stack.enter_context(patch.object(web_player, "get_sender", return_value=self.sender))
        self.stack.enter_context(patch.object(_pages, "_admin_enabled", return_value=True))
        reset_all()

    async def _load(self) -> None:
        result = await self.runtime.load("screen_share", handler=self.host)
        self.assertTrue(result.ok, result.message)
        service_module = importlib.import_module("plugins.screen_share.service")
        web = importlib.import_module("plugins.screen_share.web")
        self.stack.enter_context(patch.object(service_module, "_config", return_value=CONFIG))
        self.stack.enter_context(patch.object(service_module, "get_redis_client", AsyncMock(return_value=self.redis)))
        self.stack.enter_context(patch.object(service_module, "is_degraded", return_value=False))
        self.stack.enter_context(patch.object(web, "_secure_cookie", return_value=False))
        self.stack.enter_context(patch.object(web, "presenter_label", AsyncMock(return_value="共享者")))
        self.service = service_module.get_screen_share_service()

    async def _create(self, user: str):
        return await self.service.create_session(
            sender=self.sender, user=user, area="area", channel="channel", is_bot_admin=True
        )

    async def test_load_reload_and_unload_web_commands_and_watchdog(self) -> None:
        page_paths = ("/screen-share/p", "/screen-share/w", "/screen-share/assets/app.js", "/admin/screen-share")
        original_routes = list(web_player.app.router.routes)
        for path in page_paths:
            self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertNotIn("/admin/screen-share", (await self.client.get("/admin")).text)

        await self._load()
        plugin = self.runtime.registry.get("screen_share")
        assert plugin is not None
        plugin = cast("ScreenSharePlugin", plugin)
        first_task = plugin._watchdog._task
        assert first_task is not None
        for path in page_paths:
            self.assertEqual((await self.client.get(path)).status_code, 200)
        self.assertIn("/admin/screen-share", (await self.client.get("/admin")).text)
        route_count = len(web_player.app.router.routes)
        self.assertTrue((await self.runtime.reload_config("screen_share", handler=self.host)).ok)
        self.assertIs(plugin._watchdog._task, first_task)
        self.assertEqual(len(web_player.app.router.routes), route_count)

        with patch.object(plugin, "dispatch_command", AsyncMock()) as dispatch:
            for alias in ("屏幕共享", "共享屏幕", "停止屏幕共享", "结束屏幕共享"):
                self.assertTrue(
                    await self.runtime.try_dispatch_mention(alias, "channel", "area", "user", self.host)
                )
                self.assertFalse(
                    await self.runtime.try_dispatch_mention(alias + " abc", "channel", "area", "user", self.host)
                )
            self.assertEqual(dispatch.await_count, 4)

        self.assertTrue((await self.runtime.unload("screen_share", handler=self.host)).ok)
        self.assertTrue(first_task.done())
        self.assertEqual(web_player.app.router.routes, original_routes)
        self.assertNotIn("/admin/screen-share", (await self.client.get("/admin")).text)
        self.assertFalse(
            await self.runtime.try_dispatch_mention("屏幕共享", "channel", "area", "user", self.host)
        )
        await self._load()
        self.assertEqual(len(web_player.app.router.routes), route_count)
        self.assertEqual((await self.client.get("/screen-share/w")).status_code, 200)

    async def test_unload_ends_all_session_states_and_recalls_active_link(self) -> None:
        await self._load()
        await self._create("pending")
        claimed = await self._create("claimed")
        await self.service.claim(claimed.presenter_url.split("#")[1])
        active = await self._create("active")
        claim = await self.client.post(
            "/screen-share/api/presenter/claim", json={"token": active.presenter_url.split("#")[1]}
        )
        self.assertEqual(claim.status_code, 200, claim.text)
        ready = await self.client.post("/screen-share/api/presenter/ready")
        self.assertEqual(ready.status_code, 200, ready.text)
        viewer = {"token": ready.json()["viewer_url"].split("#")[1], "viewer_instance": "viewer"}
        self.assertEqual((await self.client.post("/screen-share/api/viewer/token", json=viewer)).status_code, 200)
        await self.service.admin_active_shares()

        self.assertTrue((await self.runtime.unload("screen_share", handler=self.host)).ok)
        self.assertFalse(self.redis.data)
        self.sender.bot.messages.recall_message.assert_awaited_once_with(
            "viewer-message", area="area", channel="channel", timestamp=None
        )
        self.sender.send_message.assert_awaited_with(
            "共享者 的屏幕共享已结束", area="area", channel="channel"
        )
        self.assertEqual((await self.client.post("/screen-share/api/presenter/heartbeat")).status_code, 404)
        await self._load()
        self.assertEqual((await self.client.post("/screen-share/api/viewer/token", json=viewer)).status_code, 404)

    async def test_unload_waits_for_in_flight_creation(self) -> None:
        await self._load()
        started = asyncio.Event()
        release = asyncio.Event()

        async def send_private_message(*args, **kwargs):
            started.set()
            await release.wait()

        self.sender.bot.messages.send_private_message.side_effect = send_private_message
        creating = asyncio.create_task(
            self.runtime.try_dispatch_mention("屏幕共享", "channel", "area", "user", self.host)
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        unloading = asyncio.create_task(self.runtime.unload("screen_share", handler=self.host))
        await asyncio.sleep(0)
        try:
            self.assertFalse(unloading.done())
            claim = await self.client.post("/screen-share/api/presenter/claim", json={"token": "pending"})
            self.assertEqual(claim.status_code, 410)
            self.assertEqual(claim.json()["code"], "plugin_unloading")
        finally:
            release.set()
            await asyncio.wait_for(creating, timeout=2)
            result = await asyncio.wait_for(unloading, timeout=2)
        self.assertTrue(result.ok, result.message)
        self.assertFalse(self.redis.data)

    async def test_cleanup_failure_keeps_plugin_loaded(self) -> None:
        await self._load()
        first = await self._create("first")
        second = await self._create("second")
        redis_eval = self.redis.eval
        calls = 0

        async def fail_on_second_stop(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Redis unavailable")
            return await redis_eval(*args)

        with patch.object(self.redis, "eval", side_effect=fail_on_second_stop):
            result = await self.runtime.unload("screen_share", handler=self.host)
        self.assertEqual(result.code, PluginOperationCode.UNLOAD_FAILED)
        self.assertEqual(self.runtime.enabled_plugin_names(), ["screen_share"])
        self.assertTrue(self.service.accepting)
        self.assertEqual((await self.client.get("/screen-share/p")).status_code, 200)
        self.assertIsNone(await self.service.get_by_id(first.session_id))
        self.assertIsNotNone(await self.service.get_by_id(second.session_id))
        self.assertTrue((await self.runtime.unload("screen_share", handler=self.host)).ok)
        self.assertFalse(self.redis.data)

    async def test_shutdown_detaches_web_and_preserves_session_state(self) -> None:
        await self._load()
        share = await self._create("pending")
        await self.runtime.stop()
        self.assertEqual((await self.client.get("/screen-share/p")).status_code, 404)
        self.assertIsNotNone(await self.service.get_by_id(share.session_id))
        self.assertIn("screen_share", self.state_path.read_text(encoding="utf-8"))
