import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, sentinel


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class BotApplicationCompositionTest(unittest.TestCase):
    def test_build_context_uses_resource_voice_and_context_builders(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder") as startup_builder_cls,
            patch.object(bootstrap_module, "VoiceRuntimeBuilder") as voice_builder_cls,
            patch.object(bootstrap_module, "AppContextBuilder") as context_builder_cls,
            patch.object(bootstrap_module, "BackgroundServiceRunner"),
            patch.object(bootstrap_module, "NeteaseApiRuntime"),
            patch.object(bootstrap_module, "ShutdownCoordinator"),
        ):
            startup_builder = startup_builder_cls.return_value
            voice_builder = voice_builder_cls.return_value
            context_builder = context_builder_cls.return_value
            startup_builder.build.return_value = SimpleNamespace(sender=sentinel.sender)
            voice_builder.build.return_value = sentinel.voice
            context_builder.build.return_value = sentinel.context

            app = bootstrap_module.BotApplication()

            result = app._build_context()

            self.assertIs(result, sentinel.context)
            startup_builder.build.assert_called_once_with()
            voice_builder.build.assert_called_once_with()
            context_builder.build.assert_called_once_with(sentinel.sender, voice=sentinel.voice)

    def test_run_wires_start_background_client_and_shutdown(self) -> None:
        from app import bootstrap as bootstrap_module

        with (
            patch.object(bootstrap_module, "StartupResourceBuilder") as startup_builder_cls,
            patch.object(bootstrap_module, "VoiceRuntimeBuilder") as voice_builder_cls,
            patch.object(bootstrap_module, "AppContextBuilder") as context_builder_cls,
            patch.object(bootstrap_module, "BackgroundServiceRunner") as background_runner_cls,
            patch.object(bootstrap_module, "NeteaseApiRuntime") as netease_runtime_cls,
            patch.object(bootstrap_module, "ShutdownCoordinator") as shutdown_cls,
        ):
            startup_builder = startup_builder_cls.return_value
            voice_builder = voice_builder_cls.return_value
            context_builder = context_builder_cls.return_value
            background_runner = background_runner_cls.return_value
            netease_runtime = netease_runtime_cls.return_value
            shutdown = shutdown_cls.return_value

            startup_builder.build.return_value = SimpleNamespace(sender=sentinel.sender)
            voice_builder.build.return_value = sentinel.voice
            context = Mock()
            context_builder.build.return_value = context

            app = bootstrap_module.BotApplication()
            app.run()

            netease_runtime.start.assert_called_once_with()
            background_runner.start.assert_called_once_with(context)
            context.client.start.assert_called_once_with()
            shutdown.stop.assert_called_once_with(context, netease_runtime)


class CommandHandlerCompositionTest(unittest.TestCase):
    def test_initialization_builds_infrastructure_registry_and_plugin_host(self) -> None:
        import command_handler as command_handler_module

        infrastructure = Mock()
        infrastructure.plugins = Mock()
        registry = Mock()

        with (
            patch.object(command_handler_module, "build_bot_infrastructure", return_value=infrastructure) as build_infra,
            patch.object(command_handler_module, "build_command_service_registry", return_value=registry) as build_registry,
            patch.object(command_handler_module, "PluginHost", return_value=sentinel.plugin_host) as plugin_host_cls,
        ):
            handler = command_handler_module.CommandHandler(sentinel.sender, voice_client=sentinel.voice)

            self.assertIs(handler.infrastructure, infrastructure)
            self.assertIs(handler.services, registry)
            self.assertIs(handler.plugin_host, sentinel.plugin_host)
            build_infra.assert_called_once_with(sentinel.sender, voice_client=sentinel.voice)
            build_registry.assert_called_once_with(
                handler,
                bot_uid=command_handler_module._BOT_UID,
                bot_mention=command_handler_module._BOT_MENTION,
            )
            plugin_host_cls.assert_called_once()
            infrastructure.plugins.load_all.assert_called_once_with(handler=sentinel.plugin_host)

            services_getter = plugin_host_cls.call_args.args[1]
            self.assertIs(services_getter(), registry)

    def test_handle_message_routes_message_context(self) -> None:
        import command_handler as command_handler_module

        infrastructure = Mock()
        infrastructure.plugins = Mock()
        ctx = SimpleNamespace(content="hello")
        registry = Mock()
        registry.routing.message.build_context.return_value = ctx
        registry.routing.message.handle_profanity.return_value = False
        registry.routing.message.reject_unauthorized_command.return_value = False

        with (
            patch.object(command_handler_module, "build_bot_infrastructure", return_value=infrastructure),
            patch.object(command_handler_module, "build_command_service_registry", return_value=registry),
            patch.object(command_handler_module, "PluginHost", return_value=sentinel.plugin_host),
        ):
            handler = command_handler_module.CommandHandler(sentinel.sender)

            handler.handle_message({"id": "message"})
            handler.handle({"id": "message-2"})

            self.assertEqual(registry.routing.message.build_context.call_count, 2)
            self.assertEqual(registry.routing.message.remember_message.call_count, 2)
            self.assertEqual(registry.routing.command.route.call_count, 2)


if __name__ == "__main__":
    unittest.main()
