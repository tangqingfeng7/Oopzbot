"""应用组装与信号处理的冒烟。

`BotApplication` 已改为单事件循环内组装：不再有 `_build_context()` 与
`VoiceRuntimeBuilder`，语音由 `AppContextBuilder` 内部构造；信号处理改用
`loop.add_signal_handler`，处理器只记录停止请求并置位 `asyncio.Event`，
不再抛 KeyboardInterrupt。用例按新结构重写。
"""

import asyncio
import signal
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch, sentinel

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _patched_bootstrap(module):
    """把 BotApplication 的全部协作者替换成可控替身。"""
    return (
        patch.object(module, "StartupResourceBuilder"),
        patch.object(module, "AppContextBuilder"),
        patch.object(module, "BackgroundServiceRunner"),
        patch.object(module, "NeteaseApiRuntime"),
        patch.object(module, "ShutdownCoordinator"),
        patch.object(module, "TaskSupervisor"),
    )


class BotApplicationCompositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_wires_startup_context_background_and_shutdown(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder") as startup_cls,
            patch.object(bootstrap_module, "AppContextBuilder") as context_cls,
            patch.object(bootstrap_module, "BackgroundServiceRunner") as background_cls,
            patch.object(bootstrap_module, "NeteaseApiRuntime") as netease_cls,
            patch.object(bootstrap_module, "ShutdownCoordinator") as shutdown_cls,
            patch.object(bootstrap_module, "TaskSupervisor") as supervisor_cls,
        ):
            startup = startup_cls.return_value
            startup.build = AsyncMock()
            netease = netease_cls.return_value
            netease.start = AsyncMock()
            background = background_cls.return_value
            background.start = AsyncMock()
            shutdown = shutdown_cls.return_value
            shutdown.stop = AsyncMock()
            context = Mock()
            context_cls.return_value.build = AsyncMock(return_value=context)

            supervisor = supervisor_cls.return_value
            # run() 会同时等待「失败」与「停止」，这里让停止先到达
            supervisor.wait_failure = AsyncMock(side_effect=asyncio.Event().wait)

            app = bootstrap_module.BotApplication()
            app._stop_event.set()
            await app.run()

            startup.build.assert_awaited_once_with()
            netease.start.assert_awaited_once_with()
            context_cls.return_value.build.assert_awaited_once_with(supervisor)
            background.start.assert_awaited_once_with(context)
            shutdown.stop.assert_awaited_once_with(context, netease, background, supervisor)

    async def test_supervisor_failure_propagates_and_still_shuts_down(self) -> None:
        """后台任务崩了要把异常抛给调用方，但关停链路仍必须走完。"""
        from app import bootstrap as bootstrap_module

        boom = RuntimeError("background task died")
        with (
            patch.object(bootstrap_module, "StartupResourceBuilder") as startup_cls,
            patch.object(bootstrap_module, "AppContextBuilder") as context_cls,
            patch.object(bootstrap_module, "BackgroundServiceRunner") as background_cls,
            patch.object(bootstrap_module, "NeteaseApiRuntime") as netease_cls,
            patch.object(bootstrap_module, "ShutdownCoordinator") as shutdown_cls,
            patch.object(bootstrap_module, "TaskSupervisor") as supervisor_cls,
        ):
            startup_cls.return_value.build = AsyncMock()
            netease_cls.return_value.start = AsyncMock()
            background_cls.return_value.start = AsyncMock()
            shutdown_cls.return_value.stop = AsyncMock()
            context_cls.return_value.build = AsyncMock(return_value=Mock())
            supervisor_cls.return_value.wait_failure = AsyncMock(return_value=boom)

            app = bootstrap_module.BotApplication()
            with self.assertRaises(RuntimeError):
                await app.run()

            shutdown_cls.return_value.stop.assert_awaited_once()

    async def test_signal_handler_only_records_request_and_never_stops_client(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder"),
            patch.object(bootstrap_module, "AppContextBuilder"),
            patch.object(bootstrap_module, "BackgroundServiceRunner"),
            patch.object(bootstrap_module, "NeteaseApiRuntime"),
            patch.object(bootstrap_module, "ShutdownCoordinator"),
            patch.object(bootstrap_module, "TaskSupervisor"),
        ):
            app = bootstrap_module.BotApplication()
            context = Mock()
            app._context = context
            loop = asyncio.get_running_loop()
            with patch.object(loop, "add_signal_handler") as register:
                app._install_signal_handlers()
            handlers = {call.args[0]: call.args[1:] for call in register.call_args_list}
            callback, *args = handlers[signal.SIGTERM]
            callback(*args)

            # 信号处理器只负责记录意图，真正的关停交给主循环，
            # 否则会在任意线程/信号上下文里动客户端状态
            self.assertTrue(app._stop_event.is_set())
            self.assertEqual(app._stop_signal, signal.SIGTERM)
            context.client.stop.assert_not_called()

    async def test_first_signal_wins_when_two_arrive(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder"),
            patch.object(bootstrap_module, "AppContextBuilder"),
            patch.object(bootstrap_module, "BackgroundServiceRunner"),
            patch.object(bootstrap_module, "NeteaseApiRuntime"),
            patch.object(bootstrap_module, "ShutdownCoordinator"),
            patch.object(bootstrap_module, "TaskSupervisor"),
        ):
            app = bootstrap_module.BotApplication()
            loop = asyncio.get_running_loop()
            with patch.object(loop, "add_signal_handler") as register:
                app._install_signal_handlers()
            handlers = {call.args[0]: call.args[1:] for call in register.call_args_list}
            for signum in (signal.SIGTERM, signal.SIGINT):
                callback, *args = handlers[signum]
                callback(*args)

            self.assertEqual(app._stop_signal, signal.SIGTERM, "第二个信号不应覆盖首个原因")

    async def test_second_stop_does_not_reenter_shutdown(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder"),
            patch.object(bootstrap_module, "AppContextBuilder"),
            patch.object(bootstrap_module, "BackgroundServiceRunner") as background_cls,
            patch.object(bootstrap_module, "NeteaseApiRuntime") as netease_cls,
            patch.object(bootstrap_module, "ShutdownCoordinator") as shutdown_cls,
            patch.object(bootstrap_module, "TaskSupervisor") as supervisor_cls,
        ):
            shutdown_cls.return_value.stop = AsyncMock()
            app = bootstrap_module.BotApplication()
            context = Mock()
            app._context = context

            await app.stop()
            await app.stop()

            shutdown_cls.return_value.stop.assert_awaited_once_with(
                context,
                netease_cls.return_value,
                background_cls.return_value,
                supervisor_cls.return_value,
            )
            context.client.stop.assert_not_called()


class CommandHandlerCompositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_initialization_builds_runtime_registry_and_plugin_host(self) -> None:
        import bot.command_handler as command_handler_module

        infrastructure = Mock()
        infrastructure.plugins = AsyncMock()
        registry = Mock()

        with (
            patch.object(
                command_handler_module, "build_bot_infrastructure", return_value=infrastructure
            ) as build_infra,
            patch.object(
                command_handler_module, "build_command_service_registry", return_value=registry
            ) as build_registry,
            patch.object(
                command_handler_module, "PluginHost", return_value=sentinel.plugin_host
            ) as plugin_host_cls,
        ):
            handler = command_handler_module.CommandHandler(
                sentinel.sender, voice_client=sentinel.voice
            )

            self.assertIs(handler.infrastructure, infrastructure)
            self.assertIs(handler.services, registry)
            self.assertIs(handler.plugin_host, sentinel.plugin_host)
            build_infra.assert_called_once_with(
                sentinel.sender, voice_client=sentinel.voice, supervisor=None
            )

            runtime = build_registry.call_args.args[0]
            self.assertIs(runtime.infrastructure, infrastructure)
            self.assertEqual(runtime.bot_uid, command_handler_module._BOT_UID)
            self.assertEqual(runtime.bot_mention, command_handler_module._BOT_MENTION)
            self.assertIs(handler.recent_messages, runtime.recent_messages)

            plugin_host_cls.assert_called_once()
            services_getter = plugin_host_cls.call_args.args[1]
            self.assertIs(services_getter(), registry)

            # 插件加载已从构造里挪到 start()，构造期不得触发 I/O
            infrastructure.plugins.load_all.assert_not_called()
            await handler.start()
            infrastructure.plugins.load_all.assert_awaited_once_with(
                handler=sentinel.plugin_host
            )
            await handler.start()  # 幂等
            infrastructure.plugins.load_all.assert_awaited_once()

    async def test_handle_message_routes_message_context(self) -> None:
        import bot.command_handler as command_handler_module

        infrastructure = Mock()
        infrastructure.plugins = AsyncMock()
        ctx = SimpleNamespace(content="hello", channel="c", area="a", user="u")
        registry = Mock()
        registry.routing.message.build_context = Mock(return_value=ctx)
        registry.routing.message.remember_message = Mock()
        registry.routing.message.reject_unauthorized_command = AsyncMock(return_value=False)
        registry.routing.command.route = AsyncMock()

        with (
            patch.object(
                command_handler_module, "build_bot_infrastructure", return_value=infrastructure
            ),
            patch.object(
                command_handler_module, "build_command_service_registry", return_value=registry
            ),
            patch.object(command_handler_module, "PluginHost", return_value=sentinel.plugin_host),
            patch.object(command_handler_module.MessageStatsDB, "increment", new=AsyncMock()),
        ):
            handler = command_handler_module.CommandHandler(sentinel.sender)

            await handler.handle_message({"id": "message"})
            await handler.handle({"id": "message-2"})

            self.assertEqual(registry.routing.message.build_context.call_count, 2)
            self.assertEqual(registry.routing.message.remember_message.call_count, 2)
            self.assertEqual(registry.routing.command.route.await_count, 2)



class AppContextBuilderCompositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_is_bound_to_runtime_recall_scheduler(self) -> None:
        from app.lifecycle import context_builder as module

        gateway = AsyncMock()
        gateway._proxy_value = None
        gateway.bind_auto_recall_scheduler = Mock()
        session = AsyncMock(sender=gateway)
        handler = Mock()
        handler.start = AsyncMock()
        handler.services.safety.recall_scheduler = sentinel.recall_scheduler
        dispatcher = Mock()
        supervisor = Mock()

        with (
            patch.object(module.OopzSession, "create", AsyncMock(return_value=session)),
            patch.object(module, "AudioPlayback"),
            patch.object(module, "CommandHandler", return_value=handler),
            patch.object(module, "get_resolver") as get_resolver,
            patch.object(module, "start_area_join_notifier", return_value=None),
            patch.object(module, "MessageDispatcher", return_value=dispatcher),
        ):
            get_resolver.return_value.bind_gateway = AsyncMock()
            context = await module.AppContextBuilder().build(supervisor)

        # 发送侧要用运行时那一个撤回调度器，不能各自新建
        gateway.bind_auto_recall_scheduler.assert_called_once_with(sentinel.recall_scheduler)
        dispatcher.start.assert_called_once_with()
        self.assertIs(context.dispatcher, dispatcher)
        self.assertIs(context.supervisor, supervisor)

    async def test_failed_build_unloads_plugins(self) -> None:
        """组装中途失败必须回收已加载的插件，否则重试会叠加注册。"""
        from app.lifecycle import context_builder as module

        gateway = AsyncMock()
        gateway._proxy_value = None
        gateway.bind_auto_recall_scheduler = Mock()
        session = AsyncMock(sender=gateway)
        gateway.bot.areas.populate_names = AsyncMock(side_effect=RuntimeError("boom"))
        handler = Mock()
        handler.start = AsyncMock()
        handler.infrastructure.plugins.stop = AsyncMock()

        with (
            patch.object(module.OopzSession, "create", AsyncMock(return_value=session)),
            patch.object(module, "AudioPlayback"),
            patch.object(module, "CommandHandler", return_value=handler),
            patch.object(module, "get_resolver") as get_resolver,
            patch.object(module, "MessageDispatcher") as dispatcher_cls,
        ):
            get_resolver.return_value.bind_gateway = AsyncMock()
            dispatcher_cls.return_value.stop = AsyncMock()
            with self.assertRaises(RuntimeError):
                await module.AppContextBuilder().build(Mock())

        handler.infrastructure.plugins.stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
