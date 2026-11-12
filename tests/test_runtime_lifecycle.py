"""运行时关停编排。

关停链路已整体改为 asyncio：`ShutdownCoordinator.stop` 是协程，各后台服务用
`asyncio.Task` 而非线程（`_task`，不再有 `_thread` / `_auto_play_thread`），
`_MessageStatsBatcher` 也换成任务 + `asyncio.Event`。以下用例按新模型重写，
守住的顺序与隔离语义与线程版一致。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _handler_stub(plugins: Any = None, music: Any = None) -> Any:
    """关停编排会依次触碰这些协作者，缺一个就会在半路抛错。"""
    return SimpleNamespace(
        infrastructure=SimpleNamespace(
            music=music if music is not None else AsyncMock(),
            plugins=plugins if plugins is not None else AsyncMock(),
            chat=AsyncMock(),
        ),
        services=SimpleNamespace(
            safety=SimpleNamespace(recall_scheduler=AsyncMock()),
        ),
    )


class ShutdownCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_order_keeps_dependencies_alive_during_dispatcher_drain(self) -> None:
        from app.lifecycle.shutdown_coordinator import ShutdownCoordinator
        from core.database import MessageStatsDB

        events: list[str] = []
        netease = AsyncMock()
        dispatcher = AsyncMock()
        background = AsyncMock()
        client = AsyncMock()
        supervisor = AsyncMock()

        def recorder(name: str):
            async def _record(*_args, **_kwargs) -> None:
                events.append(name)

            return _record

        background.stop_ingress.side_effect = recorder("ingress")
        background.stop_producers.side_effect = recorder("producers")
        background.stop_plugins.side_effect = recorder("plugins")
        client.stop.side_effect = recorder("client")
        netease.stop.side_effect = recorder("netease")
        supervisor.close.side_effect = recorder("supervisor")

        async def stop_dispatcher(*, timeout: float) -> bool:
            # 分发器排空期间，插件与下游依赖都必须还活着
            self.assertLessEqual(timeout, ShutdownCoordinator.DISPATCHER_DRAIN_SECONDS)
            netease.stop.assert_not_called()
            background.stop_plugins.assert_not_called()
            events.append("dispatcher")
            return True

        dispatcher.stop.side_effect = stop_dispatcher

        handler = _handler_stub()
        context: Any = SimpleNamespace(
            client=client,
            dispatcher=dispatcher,
            handler=handler,
            supervisor=supervisor,
        )

        coordinator = ShutdownCoordinator()
        with mock.patch.object(
            MessageStatsDB,
            "stop",
            side_effect=recorder("database"),
        ):
            await coordinator.stop(context, netease, background)
            await coordinator.stop(context, netease, background)  # 幂等

        self.assertEqual(
            events,
            [
                "ingress",
                "client",
                "producers",
                "dispatcher",
                "plugins",
                "database",
                "netease",
                "supervisor",
            ],
        )
        background.stop_ingress.assert_awaited_once()
        background.stop_producers.assert_awaited_once()
        background.stop_plugins.assert_awaited_once()
        dispatcher.stop.assert_awaited_once()
        netease.stop.assert_awaited_once()

    async def test_dispatcher_drains_plugin_command_before_registry_unload(self) -> None:
        from app.infrastructure.runtime import PluginRuntime
        from app.lifecycle.background_services import BackgroundServiceRunner
        from app.lifecycle.shutdown_coordinator import ShutdownCoordinator
        from core.database import MessageStatsDB
        from core.message_dispatcher import MessageDispatcher
        from domain.plugins.base import (
            BotModule,
            PluginCommandCapabilities,
            PluginMetadata,
        )

        events: list[str] = []
        dispatch_results: list[bool] = []
        blocker_entered = asyncio.Event()
        release_blocker = asyncio.Event()

        class QueuedPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="queued", description="queued command")

            @property
            def command_capabilities(self) -> PluginCommandCapabilities:
                return PluginCommandCapabilities(mention_prefixes=("queued",))

            async def handle_mention(
                self,
                text: str,
                channel: str,
                area: str,
                user: str,
                handler: Any,
            ) -> bool:
                events.append("handled")
                return True

            async def on_unload(self) -> None:
                events.append("unloaded")

        plugins = PluginRuntime()
        await plugins.registry.register(QueuedPlugin())
        dispatcher = MessageDispatcher(workers=1, maxsize=4)

        async def block_worker() -> None:
            blocker_entered.set()
            await asyncio.wait_for(release_blocker.wait(), timeout=2)

        async def dispatch_queued() -> None:
            dispatch_results.append(
                await plugins.try_dispatch_mention(
                    "queued command", "channel", "area", "user", None
                )
            )

        dispatcher.submit("same-shard", block_worker)
        dispatcher.submit("same-shard", dispatch_queued)
        await asyncio.wait_for(blocker_entered.wait(), timeout=1)

        context: Any = SimpleNamespace(
            client=AsyncMock(),
            onebot_v11=None,
            notifier_callback=None,
            handler=_handler_stub(plugins=plugins),
            dispatcher=dispatcher,
            supervisor=None,
        )
        background = BackgroundServiceRunner()
        background._context = context
        netease = AsyncMock()
        coordinator = ShutdownCoordinator()

        async def shutdown() -> None:
            await coordinator.stop(context, netease, background)

        try:
            with mock.patch.object(MessageStatsDB, "stop", new=AsyncMock()):
                task = asyncio.create_task(shutdown())
                # 让关停推进到分发器排空，再放行 in-flight 任务
                await asyncio.sleep(0.05)
                release_blocker.set()
                await asyncio.wait_for(task, timeout=3)
        finally:
            release_blocker.set()

        # 排队中的插件命令必须先被消费，注册表才能卸载
        self.assertEqual(dispatch_results, [True])
        self.assertEqual(events, ["handled", "unloaded"])
        self.assertEqual(plugins.enabled_plugin_names(), [])

    async def test_dispatcher_timeout_skips_plugin_unload_until_worker_exits(self) -> None:
        from app.infrastructure.runtime import PluginRuntime
        from app.lifecycle.background_services import BackgroundServiceRunner
        from app.lifecycle.shutdown_coordinator import ShutdownCoordinator
        from core.database import MessageStatsDB
        from core.message_dispatcher import MessageDispatcher
        from domain.plugins.base import (
            BotModule,
            PluginCommandCapabilities,
            PluginMetadata,
        )

        entered = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()
        unloaded = asyncio.Event()

        class BlockingPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="blocking", description="blocking command")

            @property
            def command_capabilities(self) -> PluginCommandCapabilities:
                return PluginCommandCapabilities(mention_prefixes=("blocking",))

            async def handle_mention(
                self,
                text: str,
                channel: str,
                area: str,
                user: str,
                handler: Any,
            ) -> bool:
                entered.set()
                try:
                    await asyncio.wait_for(release.wait(), timeout=2)
                except asyncio.CancelledError:
                    raise
                finished.set()
                return True

            async def on_unload(self) -> None:
                unloaded.set()

        plugins = PluginRuntime()
        await plugins.registry.register(BlockingPlugin())
        dispatcher = MessageDispatcher(workers=1, maxsize=4)
        self.assertTrue(
            dispatcher.submit(
                "plugin-command",
                plugins.try_dispatch_mention,
                "blocking command",
                "channel",
                "area",
                "user",
                None,
            )
        )
        await asyncio.wait_for(entered.wait(), timeout=1)

        context: Any = SimpleNamespace(
            client=AsyncMock(),
            onebot_v11=None,
            notifier_callback=None,
            handler=_handler_stub(plugins=plugins),
            dispatcher=dispatcher,
            supervisor=None,
        )
        background = BackgroundServiceRunner()
        background._context = context
        netease = AsyncMock()
        coordinator = ShutdownCoordinator()
        coordinator.DISPATCHER_DRAIN_SECONDS = 0.03

        try:
            with (
                mock.patch.object(MessageStatsDB, "stop", new=AsyncMock()),
                mock.patch("app.lifecycle.shutdown_coordinator.logger.warning") as warning,
            ):
                await coordinator.stop(context, netease, background)

            self.assertFalse(unloaded.is_set(), "不得与 in-flight 插件命令并发卸载")
            self.assertEqual(plugins.enabled_plugin_names(), ["blocking"])
            self.assertTrue(
                any("跳过插件卸载" in call.args[0] for call in warning.call_args_list),
                "跳过插件卸载必须留下明确告警",
            )
            netease.stop.assert_awaited_once()
        finally:
            release.set()
            await dispatcher.stop(timeout=1)
            await plugins.stop(timeout=1)

        self.assertTrue(unloaded.is_set(), "worker 退出后插件仍应被卸载")


class BackgroundServiceRunnerIsolationTest(unittest.IsolatedAsyncioTestCase):
    async def test_stop_ingress_survives_web_player_failure(self) -> None:
        from app.lifecycle.background_services import BackgroundServiceRunner

        web_player = AsyncMock()
        web_player.stop.side_effect = RuntimeError("web player stop failed")
        runner = BackgroundServiceRunner()
        runner._web_player = web_player

        # 单个服务失败不能让关停链路断在这里
        await runner.stop_ingress(timeout=1)

        web_player.stop.assert_awaited_once()
        self.assertIsNone(runner._web_player, "失败也要清引用，避免二次关停重复触发")

    async def test_stop_producers_continues_after_each_service_fails(self) -> None:
        from app.lifecycle.background_services import BackgroundServiceRunner

        music = AsyncMock()
        music.stop.side_effect = RuntimeError("music stop failed")
        notifier = AsyncMock()
        recall = AsyncMock()
        recall.stop.side_effect = RuntimeError("recall stop failed")
        plugins = AsyncMock()
        context: Any = SimpleNamespace(
            handler=SimpleNamespace(
                infrastructure=SimpleNamespace(music=music, plugins=plugins),
                services=SimpleNamespace(
                    safety=SimpleNamespace(recall_scheduler=recall),
                ),
            ),
            notifier_callback=notifier,
            onebot_v11=None,
        )
        runner = BackgroundServiceRunner()
        runner._context = context

        await runner.stop_producers(timeout=1)

        # 前面的服务抛异常也不能影响后面的服务被停掉
        music.stop.assert_awaited_once()
        recall.stop.assert_awaited_once()
        notifier.stop.assert_awaited_once()
        plugins.stop.assert_not_awaited()

        await runner.stop_plugins(timeout=1)
        plugins.stop.assert_awaited_once()


class MessageStatsLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_final_flush_does_not_exceed_remaining_stop_budget(self) -> None:
        from core.database import _MessageStatsBatcher

        batcher = _MessageStatsBatcher()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_flush() -> None:
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=1)

        with mock.patch.object(batcher, "flush", side_effect=blocking_flush):
            await batcher.increment("2026-08-02", "channel", "area", "user")
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            await batcher.stop(timeout=0.03)
            elapsed = loop.time() - started_at

            self.assertTrue(entered.is_set(), "关停必须真的触发最终刷入")
            self.assertLess(elapsed, 0.5, "刷入超预算时不得无限期阻塞关停")
            release.set()

    async def test_stop_cancels_the_flush_task_when_over_budget(self) -> None:
        """超预算的刷入任务必须被取消，不能留下悬挂任务拖住事件循环。"""
        from core.database import _MessageStatsBatcher

        batcher = _MessageStatsBatcher()
        release = asyncio.Event()

        async def blocking_flush() -> None:
            await asyncio.wait_for(release.wait(), timeout=2)

        with mock.patch.object(batcher, "flush", side_effect=blocking_flush):
            await batcher.increment("2026-08-02", "channel", "area", "user")
            task = batcher._task
            self.assertIsNotNone(task)

            await batcher.stop(timeout=0.02)

            assert task is not None
            self.assertTrue(task.done())
            self.assertIsNone(batcher._task, "停过之后不应残留任务引用")
            release.set()

    async def test_stop_without_running_task_still_flushes(self) -> None:
        from core.database import _MessageStatsBatcher

        batcher = _MessageStatsBatcher()
        flush = AsyncMock()

        with mock.patch.object(batcher, "flush", flush):
            await batcher.stop(timeout=1)

        flush.assert_awaited_once()


class MusicListenerLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_stop_is_idempotent_and_prevents_further_blpop_calls(self) -> None:
        import music.music as music_module

        class BlockingRedis:
            def __init__(self) -> None:
                self.calls = 0
                self.entered = asyncio.Event()

            async def blpop(self, _key: str, timeout: int):
                self.calls += 1
                self.entered.set()
                await asyncio.sleep(min(0.02, timeout))
                return None

        redis_client = BlockingRedis()
        handler = cast(Any, music_module.MusicHandler.__new__(music_module.MusicHandler))
        handler._service_stop_event = asyncio.Event()
        handler._auto_play_task = None
        handler._web_command_task = None
        handler._liked_refresh_task = None
        handler._cover_prefetch = {}
        handler.platforms = AsyncMock()
        handler.voice = None
        handler._create_task = lambda coro, name=None: asyncio.create_task(coro, name=name)

        with mock.patch.object(music_module, "get_redis_client", AsyncMock(return_value=redis_client)):
            await handler.start_web_command_listener()
            await asyncio.wait_for(redis_client.entered.wait(), timeout=1)

            await handler.stop(timeout=1)
            calls_after_stop = redis_client.calls
            await handler.stop(timeout=1)  # 幂等
            await asyncio.sleep(0.05)

        self.assertEqual(redis_client.calls, calls_after_stop, "停止后不得再发起 BLPOP")
        self.assertTrue(handler._service_stop_event.is_set())


class AreaNotifierLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_notifier_stop_wakes_and_cancels_poll_task(self) -> None:
        import services.area_join_notifier as notifier_module

        stopped = asyncio.Event()

        async def poll_loop(*_args, stop_event, **_kwargs) -> None:
            await stop_event.wait()
            stopped.set()

        with mock.patch.object(notifier_module, "_run_join_poll_loop", poll_loop):
            notifier = notifier_module.AreaJoinNotifier(lambda *_args: None, (), {})
            notifier.start()
            await notifier.stop(timeout=1)
            await notifier.stop(timeout=1)  # 幂等

        self.assertTrue(stopped.is_set(), "stop 必须唤醒轮询任务而不是干等超时")
        self.assertIsNone(notifier._task, "停过之后不应残留任务引用")


if __name__ == "__main__":
    unittest.main()
