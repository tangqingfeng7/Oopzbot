import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class PluginRegistryContractTest(unittest.TestCase):
    def test_list_command_descriptors_filters_private_and_empty_modules(self) -> None:
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from plugin_base import BotModule, PluginCommandCapabilities, PluginMetadata

        class PublicPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="public_demo", description="public")

            @property
            def mention_prefixes(self) -> tuple[str, ...]:
                return ("测试",)

            @property
            def slash_commands(self) -> tuple[str, ...]:
                return ("/demo",)

        class PrivatePlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="private_demo", description="private")

            @property
            def slash_commands(self) -> tuple[str, ...]:
                return ("/admin-demo",)

            @property
            def is_public_command(self) -> bool:
                return False

        class EmptyPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="empty_demo", description="empty")

        class CapabilityPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="capability_demo", description="capability")

            @property
            def command_capabilities(self) -> PluginCommandCapabilities:
                return PluginCommandCapabilities(
                    mention_prefixes=("能力",),
                    slash_commands=("/CAP",),
                    is_public_command=True,
                )

        registry = PluginRegistry()
        registry.register(PublicPlugin())
        registry.register(PrivatePlugin())
        registry.register(EmptyPlugin())
        registry.register(CapabilityPlugin())

        public_descriptors = registry.list_command_descriptors(public_only=True)
        all_descriptors = registry.list_command_descriptors(public_only=False)

        self.assertEqual([item.name for item in public_descriptors], ["public_demo", "capability_demo"])
        self.assertEqual(public_descriptors[0].mention_prefixes, ("测试",))
        self.assertEqual(public_descriptors[1].slash_commands, ("/cap",))
        self.assertEqual(len(all_descriptors), 3)
        self.assertEqual(all_descriptors[1].name, "private_demo")
        self.assertFalse(all_descriptors[1].is_public_command)

    def test_describe_returns_normalized_descriptor(self) -> None:
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from plugin_base import BotModule, PluginCommandCapabilities, PluginMetadata

        class DemoPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="demo", description="demo plugin")

            @property
            def command_capabilities(self) -> PluginCommandCapabilities:
                return PluginCommandCapabilities(
                    mention_prefixes=("测试",),
                    slash_commands=("/DEMO",),
                    is_public_command=False,
                )

        registry = PluginRegistry()
        registry.register(DemoPlugin(), builtin=True)

        descriptor = registry.describe("demo")
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor.name, "demo")
        self.assertEqual(descriptor.description, "demo plugin")
        self.assertEqual(descriptor.version, "1.0.0")
        self.assertEqual(descriptor.author, "")
        self.assertTrue(descriptor.builtin)
        self.assertEqual(descriptor.mention_prefixes, ("测试",))
        self.assertEqual(descriptor.slash_commands, ("/demo",))
        self.assertFalse(descriptor.is_public_command)
        self.assertEqual([item.name for item in registry.list_descriptors()], ["demo"])
        self.assertEqual([item.name for item in registry.list_command_descriptors()], ["demo"])

    def test_try_dispatch_mention_isolates_plugin_errors(self) -> None:
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from plugin_base import BotModule, PluginMetadata

        class BrokenPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="broken_demo", description="broken")

            @property
            def mention_prefixes(self) -> tuple[str, ...]:
                return ("测试",)

            def handle_mention(self, text, channel, area, user, handler) -> bool:
                raise RuntimeError("boom")

        class WorkingPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="working_demo", description="working")

            @property
            def mention_prefixes(self) -> tuple[str, ...]:
                return ("测试",)

            def __init__(self) -> None:
                self.calls = []

            def handle_mention(self, text, channel, area, user, handler) -> bool:
                self.calls.append((text, channel, area, user, handler))
                return True

        registry = PluginRegistry()
        working = WorkingPlugin()
        registry.register(BrokenPlugin())
        registry.register(working)

        result = registry.try_dispatch_mention("测试 插件", "channel-1", "area-1", "user-1", sentinel := object())

        self.assertTrue(result)
        self.assertEqual(
            working.calls,
            [("测试 插件", "channel-1", "area-1", "user-1", sentinel)],
        )

    def test_try_dispatch_slash_only_matches_declared_commands(self) -> None:
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from plugin_base import BotModule, PluginCommandCapabilities, PluginMetadata

        class SlashPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="slash_demo", description="slash")

            @property
            def slash_commands(self) -> tuple[str, ...]:
                return ("/demo",)

            def __init__(self) -> None:
                self.calls = []

            def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
                self.calls.append((command, subcommand, arg, channel, area, user, handler))
                return True

        registry = PluginRegistry()
        plugin = SlashPlugin()
        registry.register(plugin)

        self.assertFalse(
            registry.try_dispatch_slash("/other", None, None, "channel-1", "area-1", "user-1", object())
        )

        handler = object()
        self.assertTrue(
            registry.try_dispatch_slash("/demo", "sub", "arg", "channel-1", "area-1", "user-1", handler)
        )
        self.assertEqual(
            plugin.calls,
            [("/demo", "sub", "arg", "channel-1", "area-1", "user-1", handler)],
        )

        class CapabilityOnlyPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="cap_only_demo", description="cap-only")

            @property
            def command_capabilities(self) -> PluginCommandCapabilities:
                return PluginCommandCapabilities(
                    mention_prefixes=("能力",),
                    slash_commands=("/CAP2",),
                    is_public_command=False,
                )

        registry.register(CapabilityOnlyPlugin())
        self.assertTrue(registry.has_mention_prefix("能力 测试"))
        self.assertTrue(registry.has_slash_command("/cap2"))
        self.assertFalse(registry.has_public_slash_command("/cap2"))


class PluginLoaderContractTest(unittest.TestCase):
    def test_load_plugin_injects_host_and_config(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_config import PluginConfig
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        plugin_source = textwrap.dedent(
            """
            from plugin_base import BotModule, PluginMetadata

            class DemoPlugin(BotModule):
                def __init__(self):
                    self.loaded_with = None

                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def slash_commands(self):
                    return ("/demo",)

                def on_load(self, handler, config=None):
                    self.loaded_with = (handler, config)
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"enabled": True, "threshold": 2}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            plugin_host = SimpleNamespace(name="host")
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=plugin_host)
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertEqual(
            result,
            PluginOperationResult.success(
                "已加载: demo",
                plugin_name="demo",
                code=PluginOperationCode.SUCCESS,
            ),
        )
        plugin = registry.get("demo")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.loaded_with, (plugin_host, {"enabled": True, "threshold": 2}))
        self.assertIsInstance(plugin.loaded_with[1], PluginConfig)
        self.assertTrue(plugin.loaded_with[1].exists)
        self.assertEqual(plugin.loaded_with[1].plugin_name, "demo")

    def test_get_plugin_config_returns_config_object(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from domain.plugins.plugin_config import PluginConfig

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_dir = project_root / "config" / "plugins"
            config_dir.mkdir(parents=True)
            (config_dir / "demo.json").write_text(
                json.dumps({"enabled": True, "threshold": 2}),
                encoding="utf-8",
            )

            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                config = loader_module.get_plugin_config("demo")
            finally:
                loader_module._PROJECT_ROOT = old_project_root

        self.assertIsInstance(config, PluginConfig)
        self.assertTrue(config.exists)
        self.assertEqual(config.plugin_name, "demo")
        self.assertEqual(config["threshold"], 2)
        self.assertTrue(config.get("enabled"))
        self.assertEqual(config.copy(), {"enabled": True, "threshold": 2})

    def test_config_spec_casts_values_before_on_load(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
                parse_bool,
                parse_int,
            )

            class DemoPlugin(BotModule):
                def __init__(self):
                    self.loaded_with = None

                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField("enabled", default=False, cast=parse_bool),
                            PluginConfigField("timeout", default=30, cast=parse_int),
                        )
                    )

                def on_load(self, handler, config=None):
                    self.loaded_with = config
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"enabled": "true", "timeout": "45"}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertTrue(result.ok)
        plugin = registry.get("demo")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.loaded_with["enabled"], True)
        self.assertEqual(plugin.loaded_with["timeout"], 45)

    def test_load_plugin_applies_config_spec_defaults(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
            )

            class DemoPlugin(BotModule):
                def __init__(self):
                    self.loaded_with = None

                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField("enabled", default=False),
                            PluginConfigField("timeout", default=30),
                        )
                    )

                def on_load(self, handler, config=None):
                    self.loaded_with = config
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"enabled": True}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertTrue(result.ok)
        plugin = registry.get("demo")
        self.assertIsNotNone(plugin)
        self.assertEqual(plugin.loaded_with["enabled"], True)
        self.assertEqual(plugin.loaded_with["timeout"], 30)

    def test_load_plugin_rejects_invalid_config_by_spec(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
            )

            class DemoPlugin(BotModule):
                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField("api_key", required=True),
                        )
                    )
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text("{}", encoding="utf-8")

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.INVALID_CONFIG)
        self.assertEqual(result.plugin_name, "demo")
        self.assertIn("缺少必填配置", result.message)
        self.assertIsNone(registry.get("demo"))

    def test_load_plugin_rejects_invalid_choice_by_spec(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
            )

            class DemoPlugin(BotModule):
                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField("mode", default="auto", choices=("auto", "safe")),
                        )
                    )
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"mode": "invalid"}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.INVALID_CONFIG)
        self.assertIn("不在允许范围内", result.message)

    def test_load_plugin_rejects_invalid_time_format_by_spec(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
                validate_hhmm,
            )

            class DemoPlugin(BotModule):
                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField("push_time", default="08:00", validator=validate_hhmm),
                        )
                    )
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"push_time": "25:99"}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.INVALID_CONFIG)
        self.assertIn("字段 push_time 校验失败", result.message)

    def test_load_plugin_rejects_invalid_url_list_by_spec(self) -> None:
        import app.infrastructure.plugin_runtime.loader as loader_module
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode

        plugin_source = textwrap.dedent(
            """
            from plugin_base import (
                BotModule,
                PluginConfigField,
                PluginConfigSpec,
                PluginMetadata,
                parse_string_list,
                validate_http_url_list,
            )

            class DemoPlugin(BotModule):
                @property
                def metadata(self):
                    return PluginMetadata(name="demo", description="demo plugin")

                @property
                def config_spec(self):
                    return PluginConfigSpec(
                        (
                            PluginConfigField(
                                "base_urls",
                                cast=parse_string_list,
                                validator=validate_http_url_list,
                            ),
                        )
                    )
            """
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            plugins_dir = project_root / "plugins"
            config_dir = project_root / "config" / "plugins"
            plugins_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            (plugins_dir / "demo.py").write_text(plugin_source, encoding="utf-8")
            (config_dir / "demo.json").write_text(
                json.dumps({"base_urls": ["ftp://invalid.example.com"]}),
                encoding="utf-8",
            )

            registry = PluginRegistry()
            old_project_root = loader_module._PROJECT_ROOT
            try:
                loader_module._PROJECT_ROOT = str(project_root)
                result = loader_module.load_plugin(registry, "demo", handler=SimpleNamespace())
            finally:
                loader_module._PROJECT_ROOT = old_project_root
                sys.modules.pop("plugins.demo", None)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.INVALID_CONFIG)
        self.assertIn("字段 base_urls 校验失败", result.message)

    def test_unload_plugin_cleans_private_module_cache(self) -> None:
        from app.infrastructure.plugin_runtime.loader import unload_plugin
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult
        from plugin_base import BotModule, PluginMetadata

        class DemoPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="demo", description="demo")

            @property
            def private_modules(self) -> tuple[str, ...]:
                return ("plugins.demo_helper",)

        registry = PluginRegistry()
        registry.register(DemoPlugin())
        sys.modules["plugins.demo"] = object()
        sys.modules["plugins.demo_helper"] = object()

        result = unload_plugin(registry, "demo")

        self.assertEqual(
            result,
            PluginOperationResult.success(
                "已卸载: demo",
                plugin_name="demo",
                code=PluginOperationCode.SUCCESS,
            ),
        )
        self.assertNotIn("plugins.demo", sys.modules)
        self.assertNotIn("plugins.demo_helper", sys.modules)

    def test_unload_plugin_rejects_builtin_module(self) -> None:
        from app.infrastructure.plugin_runtime.loader import unload_plugin
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult
        from plugin_base import BotModule, PluginMetadata

        class BuiltinPlugin(BotModule):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="builtin_demo", description="builtin")

        registry = PluginRegistry()
        registry.register(BuiltinPlugin(), builtin=True)

        result = unload_plugin(registry, "builtin_demo")

        self.assertEqual(
            result,
            PluginOperationResult.failure(
                "内置模块不可卸载: builtin_demo",
                plugin_name="builtin_demo",
                code=PluginOperationCode.BUILTIN_FORBIDDEN,
            ),
        )

    def test_load_plugin_reports_not_found_code(self) -> None:
        from app.infrastructure.plugin_runtime.loader import load_plugin
        from app.infrastructure.plugin_runtime.registry import PluginRegistry
        from domain.plugins.plugin_operation import PluginOperationCode

        registry = PluginRegistry()
        result = load_plugin(registry, "missing_plugin")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.NOT_FOUND)
        self.assertEqual(result.plugin_name, "missing_plugin")


if __name__ == "__main__":
    unittest.main()
