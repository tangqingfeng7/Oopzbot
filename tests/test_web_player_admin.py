import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    _TESTCLIENT_ERROR = None
except Exception as exc:  # pragma: no cover - 依赖缺失时跳过
    TestClient = None
    _TESTCLIENT_ERROR = exc


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from plugin_base import PluginCommandCapabilities, PluginDescriptor, PluginMetadata


class _FakePlugins:
    def __init__(self):
        self._descriptors = [
            PluginDescriptor(
                metadata=PluginMetadata(name="alpha", description="alpha desc", version="1.0.0"),
                capabilities=PluginCommandCapabilities(
                    mention_prefixes=("alpha",),
                    slash_commands=("alpha",),
                    is_public_command=True,
                ),
                builtin=False,
            )
        ]

    def discover(self):
        return ["alpha"]

    def list_descriptors(self):
        return list(self._descriptors)

    def enabled_plugin_names(self):
        return ["alpha"]

    def get_last_results(self):
        return {}

    @property
    def state_path(self):
        return "data/plugin_runtime_state.json"


class WebPlayerAdminTest(unittest.TestCase):
    def setUp(self) -> None:
        if TestClient is None:
            self.skipTest(f"缺少 TestClient 依赖: {_TESTCLIENT_ERROR}")
        import web_player

        self.module = web_player
        self.module.register_runtime_dependencies(
            music=SimpleNamespace(),
            plugins=_FakePlugins(),
            plugin_host=SimpleNamespace(),
        )
        self.client = TestClient(self.module.app)

    def test_plugins_api_requires_login(self) -> None:
        with patch.object(self.module, "_admin_enabled", return_value=True):
            response = self.client.get("/admin/api/plugins")

        self.assertEqual(response.status_code, 401)

    def test_plugins_api_returns_inventory_when_logged_in(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
        ):
            response = self.client.get("/admin/api/plugins")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["enabled_plugins"], ["alpha"])
        self.assertEqual(data["plugins"][0]["name"], "alpha")

    def test_admin_html_pages_reference_shared_shell_assets(self) -> None:
        paths = [
            "/admin",
            "/admin/music",
            "/admin/config",
            "/admin/stats",
            "/admin/system",
            "/admin/setup",
        ]

        with patch.object(self.module, "_admin_enabled", return_value=True):
            for path in paths:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('/admin-assets/admin-shell.css', response.text)
                    self.assertIn('/admin-assets/admin-shell.js', response.text)
                    self.assertIn('class="shell-topbar"', response.text)
                    self.assertIn('id="topNav"', response.text)
                    self.assertIn('id="mobileNav"', response.text)
                    self.assertIn('id="topStatus"', response.text)

    def test_setup_diagnostics_api_returns_report_when_logged_in(self) -> None:
        fake_report = {
            "status": "warn",
            "summary": {"pass": 3, "warn": 1, "fail": 0, "info": 1},
            "checks": [{"id": "redis", "level": "pass", "title": "Redis 连接", "summary": "Redis 连接正常"}],
            "wizard_steps": [{"id": "runtime", "status": "done", "title": "打通基础运行时"}],
            "first_run_needed": True,
            "quick_links": [],
        }

        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web_player_admin.SetupDiagnostics") as diagnostics_cls,
        ):
            diagnostics_cls.return_value.build_report.return_value = fake_report
            response = self.client.get("/admin/api/setup/diagnostics")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "warn")
        self.assertEqual(data["summary"]["warn"], 1)
        self.assertEqual(data["checks"][0]["title"], "Redis 连接")

    def test_scheduled_message_templates_api_returns_items_when_logged_in(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
        ):
            response = self.client.get("/admin/api/scheduled-message-templates")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(len(data["items"]) >= 1)
        self.assertIn("key", data["items"][0])

    def test_scheduled_message_template_apply_creates_task(self) -> None:
        with (
            patch.object(self.module, "_admin_enabled", return_value=True),
            patch.object(self.module, "_is_admin_authorized", return_value=True),
            patch("web_player_admin.ScheduledMessageDB.create", return_value=99) as create_task,
        ):
            response = self.client.post(
                "/admin/api/scheduled-message-templates/morning/apply",
                json={"channel_id": "channel-1", "area_id": "area-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 99)
        create_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
