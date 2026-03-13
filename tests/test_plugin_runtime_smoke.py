import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, sentinel


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class PluginHostSmokeTest(unittest.TestCase):
    def test_plugin_host_only_exposes_controlled_runtime_objects(self) -> None:
        from app.infrastructure.runtime import PluginHost

        infrastructure = SimpleNamespace(
            sender=sentinel.sender,
            chat=sentinel.chat,
            music=sentinel.music,
        )
        host = PluginHost(infrastructure, lambda: sentinel.services)

        self.assertIs(host.sender, sentinel.sender)
        self.assertIs(host.chat, sentinel.chat)
        self.assertIs(host.music, sentinel.music)
        self.assertIs(host.services, sentinel.services)


class PluginRuntimeSmokeTest(unittest.TestCase):
    def test_plugin_runtime_delegates_registry_queries(self) -> None:
        import app.infrastructure.runtime as runtime_module

        registry = Mock()
        registry.list_descriptors.return_value = [sentinel.descriptor]
        registry.list_command_descriptors.return_value = [sentinel.command_descriptor]
        registry.has_public_mention_prefix.return_value = True
        registry.has_public_slash_command.return_value = True
        registry.try_dispatch_mention.return_value = True
        registry.try_dispatch_slash.return_value = True

        with patch.object(runtime_module, "PluginRegistry", return_value=registry):
            plugin_runtime = runtime_module.PluginRuntime(plugins_dir="custom_plugins")

        self.assertIs(plugin_runtime.registry, registry)
        self.assertEqual(plugin_runtime.list_descriptors(), [sentinel.descriptor])
        self.assertEqual(
            plugin_runtime.list_command_descriptors(public_only=True),
            [sentinel.command_descriptor],
        )
        self.assertTrue(plugin_runtime.has_public_mention_prefix("@bot test"))
        self.assertTrue(plugin_runtime.has_public_slash_command("demo"))
        self.assertTrue(
            plugin_runtime.try_dispatch_mention("text", "channel", "area", "user", sentinel.handler)
        )
        self.assertTrue(
            plugin_runtime.try_dispatch_slash(
                "demo",
                "sub",
                "arg",
                "channel",
                "area",
                "user",
                sentinel.handler,
            )
        )

        registry.list_descriptors.assert_called_once_with()
        registry.list_command_descriptors.assert_called_once_with(public_only=True)
        registry.has_public_mention_prefix.assert_called_once_with("@bot test")
        registry.has_public_slash_command.assert_called_once_with("demo")
        registry.try_dispatch_mention.assert_called_once_with(
            "text",
            "channel",
            "area",
            "user",
            sentinel.handler,
        )
        registry.try_dispatch_slash.assert_called_once_with(
            "demo",
            "sub",
            "arg",
            "channel",
            "area",
            "user",
            sentinel.handler,
        )

    def test_plugin_runtime_delegates_loader_operations(self) -> None:
        import app.infrastructure.runtime as runtime_module
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        registry = Mock()

        with (
            patch.object(runtime_module, "PluginRegistry", return_value=registry),
            patch.object(runtime_module, "discover_plugins", return_value=["a", "b"]) as discover_plugins,
            patch.object(
                runtime_module,
                "load_plugin",
                return_value=PluginOperationResult.success("ok", "demo", code=PluginOperationCode.SUCCESS),
            ) as load_plugin,
            patch.object(
                runtime_module,
                "unload_plugin",
                return_value=PluginOperationResult.success("removed", "demo", code=PluginOperationCode.SUCCESS),
            ) as unload_plugin,
            patch.object(runtime_module, "load_plugins_dir", return_value=["a", "b"]) as load_plugins_dir,
        ):
            plugin_runtime = runtime_module.PluginRuntime(plugins_dir="custom_plugins")

            self.assertEqual(plugin_runtime.discover(), ["a", "b"])
            self.assertEqual(
                plugin_runtime.load("demo", handler=sentinel.handler),
                PluginOperationResult.success("ok", "demo", code=PluginOperationCode.SUCCESS),
            )
            self.assertEqual(
                plugin_runtime.unload("demo", handler=sentinel.handler),
                PluginOperationResult.success("removed", "demo", code=PluginOperationCode.SUCCESS),
            )
            self.assertEqual(plugin_runtime.load_all(handler=sentinel.handler), ["a", "b"])

        discover_plugins.assert_called_once_with("custom_plugins")
        load_plugin.assert_called_once_with(registry, "demo", "custom_plugins", handler=sentinel.handler)
        unload_plugin.assert_called_once_with(registry, "demo", handler=sentinel.handler)
        load_plugins_dir.assert_called_once_with(registry, "custom_plugins", handler=sentinel.handler)


if __name__ == "__main__":
    unittest.main()
