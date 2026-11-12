import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from domain.plugins.base import BotModule, PluginMetadata  # noqa: E402
from domain.plugins.plugin_operation import (  # noqa: E402
    PluginOperationCode,
    PluginOperationResult,
)


class _FakePlugin(BotModule):
    def __init__(self, name: str):
        self._metadata = PluginMetadata(name=name, description=f"{name} desc")

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata


class PluginRuntimeStateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "plugin_runtime_state.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _load_side_effect(self, registry, plugin_name, plugins_dir="plugins", handler=None):
        await registry.register(_FakePlugin(plugin_name))
        return PluginOperationResult.success(f"已加载 {plugin_name}", plugin_name=plugin_name)

    async def _unload_side_effect(self, registry, plugin_name, handler=None):
        await registry.unregister(plugin_name)
        return PluginOperationResult.success(f"已卸载 {plugin_name}", plugin_name=plugin_name)

    async def test_load_all_initializes_state_file_when_missing(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
        ):
            loaded = await runtime.load_all()

        self.assertEqual(loaded, ["alpha", "beta"])
        self.assertTrue(self.state_path.exists())
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["enabled_plugins"], ["alpha", "beta"])

    async def test_load_all_respects_existing_state_file(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        self.state_path.write_text(
            json.dumps({"enabled_plugins": ["beta"], "known_plugins": ["alpha", "beta"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect) as load_plugin,
        ):
            loaded = await runtime.load_all()

        self.assertEqual(loaded, ["beta"])
        self.assertEqual(load_plugin.call_count, 1)
        self.assertEqual(runtime.enabled_plugin_names(), ["beta"])

    async def test_load_all_loads_new_plugins_and_remembers_them(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        self.state_path.write_text(json.dumps({"enabled_plugins": ["beta"]}), encoding="utf-8")
        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
            patch("app.infrastructure.runtime.unload_plugin", side_effect=self._unload_side_effect),
        ):
            loaded = await runtime.load_all()
            await runtime.unload("alpha")

        self.assertEqual(loaded, ["alpha", "beta"])
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"enabled_plugins": ["beta"], "known_plugins": ["alpha", "beta"]})

    async def test_load_all_retries_new_plugin_that_failed_to_load(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        self.state_path.write_text(
            json.dumps({"enabled_plugins": ["beta"], "known_plugins": ["beta"]}),
            encoding="utf-8",
        )
        runtime = PluginRuntime(state_path=self.state_path)

        async def fail_alpha(registry, plugin_name, plugins_dir="plugins", handler=None):
            if plugin_name == "alpha":
                return PluginOperationResult.failure("配置错误", plugin_name=plugin_name)
            return await self._load_side_effect(registry, plugin_name, plugins_dir, handler)

        with (
            patch("app.infrastructure.runtime.discover_plugins", return_value=["alpha", "beta"]),
            patch("app.infrastructure.runtime.load_plugin", side_effect=fail_alpha),
        ):
            await runtime.load_all()

        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["known_plugins"], ["beta"])

    async def test_load_and_unload_refresh_state_file(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
            patch("app.infrastructure.runtime.unload_plugin", side_effect=self._unload_side_effect),
        ):
            load_result = await runtime.load("alpha")
            unload_result = await runtime.unload("alpha")

        self.assertTrue(load_result.ok)
        self.assertTrue(unload_result.ok)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["enabled_plugins"], [])

    async def test_persistence_failure_returns_failure_but_keeps_memory_state(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        with (
            patch("app.infrastructure.runtime.load_plugin", side_effect=self._load_side_effect),
            patch.object(runtime, "_persist_enabled_plugins_sync", return_value="disk error"),
        ):
            result = await runtime.load("alpha")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, PluginOperationCode.LOAD_FAILED)
        self.assertEqual(runtime.enabled_plugin_names(), ["alpha"])

    def test_plugin_operation_code_is_string_enum_compatible(self) -> None:
        self.assertIsInstance(PluginOperationCode.SUCCESS, str)
        self.assertEqual(PluginOperationCode.SUCCESS, "success")
        self.assertEqual(str(PluginOperationCode.SUCCESS), "success")

    async def test_stop_unloads_plugins_once_without_disabling_next_start(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        self.state_path.write_text(
            json.dumps({"enabled_plugins": ["alpha"]}),
            encoding="utf-8",
        )
        runtime = PluginRuntime(state_path=self.state_path)
        plugin = _FakePlugin("alpha")
        await runtime.registry.register(plugin)

        with patch.object(plugin, "on_unload", new_callable=AsyncMock) as on_unload:
            await runtime.stop()
            await runtime.stop()

        on_unload.assert_awaited_once_with()
        self.assertEqual(runtime.enabled_plugin_names(), [])
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["enabled_plugins"], ["alpha"])

    async def test_stop_returns_within_budget_when_plugin_unload_blocks(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        plugin = _FakePlugin("slow")
        await runtime.registry.register(plugin)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_unload() -> None:
            entered.set()
            await release.wait()

        with patch.object(plugin, "on_unload", new=AsyncMock(side_effect=blocking_unload)):
            started_at = time.monotonic()
            await runtime.stop(timeout=0.03)
            elapsed = time.monotonic() - started_at
            self.assertTrue(entered.is_set())
            self.assertLess(elapsed, 0.15)

    async def test_stop_uses_reverse_order_and_isolates_plugin_failures(self) -> None:
        from app.infrastructure.runtime import PluginRuntime

        runtime = PluginRuntime(state_path=self.state_path)
        first = _FakePlugin("first")
        second = _FakePlugin("second")
        await runtime.registry.register(first)
        await runtime.registry.register(second)
        calls: list[str] = []

        async def unload_first() -> None:
            calls.append("first")

        async def fail_second() -> None:
            calls.append("second")
            raise RuntimeError("second unload failed")

        with (
            patch.object(first, "on_unload", new=AsyncMock(side_effect=unload_first)),
            patch.object(second, "on_unload", new=AsyncMock(side_effect=fail_second)),
        ):
            await runtime.stop(timeout=1)

        self.assertEqual(calls, ["second", "first"])


if __name__ == "__main__":
    unittest.main()
