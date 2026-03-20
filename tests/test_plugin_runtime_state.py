import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult
from plugin_base import BotModule, PluginMetadata


class _FakePlugin(BotModule):
    def __init__(self, name: str):
        self._metadata = PluginMetadata(name=name, description=f"{name} desc")

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata


class PluginRuntimeStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "plugin_runtime_state.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _load_side_effect(self, registry, plugin_name, plugins_dir="plugins", handler=None):
        registry.register(_FakePlugin(plugin_name))
        return PluginOperationResult.success(f"已加载 {plugin_name}", plugin_name=plugin_name)

    def _unload_side_effect(self, registry, plugin_name, handler=None):
        registry.unregister(plugin_name)
        return PluginOperationResult.success(f"已卸载 {plugin_name}", plugin_name=plugin_name)

    def test_load_all_initializes_state_file_when_missing(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
        ):
            loaded = runtime.load_all()

        self.assertEqual(loaded, ["alpha", "beta"])
        self.assertTrue(self.state_path.exists())
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["enabled_plugins"], ["alpha", "beta"])

    def test_load_all_respects_existing_state_file(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        self.state_path.write_text(
            json.dumps({"enabled_plugins": ["beta"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect) as load_plugin,
        ):
            loaded = runtime.load_all()

        self.assertEqual(loaded, ["beta"])
        self.assertEqual(load_plugin.call_count, 1)
        self.assertEqual(runtime.enabled_plugin_names(), ["beta"])

    def test_load_and_unload_refresh_state_file(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
            patch("app.infrastructure.runtime.unload_plugin", side_effect=self._unload_side_effect),
        ):
            load_result = runtime.load("alpha")
            unload_result = runtime.unload("alpha")

        self.assertTrue(load_result.ok)
        self.assertTrue(unload_result.ok)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["enabled_plugins"], [])

    def test_persistence_failure_returns_failure_but_keeps_memory_state(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
            patch.object(runtime, "_persist_enabled_plugins", return_value="disk error"),
        ):
            result = runtime.load("alpha")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.LOAD_FAILED)
        self.assertEqual(runtime.enabled_plugin_names(), ["alpha"])


if __name__ == "__main__":
    unittest.main()
