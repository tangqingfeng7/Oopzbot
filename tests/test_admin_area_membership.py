import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

from oopz_sdk import OopzBot  # noqa: E402
from oopz_sdk.models import AreaInfo  # noqa: E402
from oopz_sdk.testing.factories import make_config  # noqa: E402
from oopz_sdk.transport.http import HttpResponse, HttpTransport  # noqa: E402

from app.infrastructure.oopz_connection import install_project_transports  # noqa: E402
from core.proxy_utils import ProxySettings  # noqa: E402


class AreaLeaveSdkTest(unittest.IsolatedAsyncioTestCase):
    async def test_leave_area_uses_quit_endpoint(self) -> None:
        bot = OopzBot(make_config())
        self.addAsyncCleanup(bot.stop)
        install_project_transports(bot, ProxySettings(mode="direct"), None)
        text = json.dumps({"status": True, "data": {"status": True}})
        response = HttpResponse(status_code=200, headers={}, content=text.encode(), text=text)
        with patch.object(HttpTransport, "request", AsyncMock(return_value=response)) as request:
            result = await bot.areas.leave_area("area-1")

        self.assertTrue(result.ok)
        request.assert_awaited_once_with(
            "DELETE",
            "/client/v1/area/v1/quit",
            body=None,
            params={"area": "area-1"},
        )


class AdminAreaLeaveApiTest(unittest.TestCase):
    def setUp(self) -> None:
        if TestClient is None:
            self.skipTest(f"缺少 TestClient 依赖: {_TESTCLIENT_ERROR}")
        import web.web_player as web_player

        self.web_player = web_player
        import web.web_rate_limit as web_rate_limit

        web_rate_limit.reset_all()
        self.client = TestClient(web_player.app, client=("127.0.0.1", 50002))

    def _request(self, sender, payload: dict):
        import web.admin.shared._runtime as runtime

        with (
            patch.object(self.web_player, "_admin_enabled", return_value=True),
            patch.object(self.web_player, "_is_admin_authorized", return_value=True),
            patch.object(runtime, "_get_sender", return_value=sender),
        ):
            return self.client.post("/admin/api/areas/leave", json=payload)

    def test_rejects_area_that_bot_has_not_joined(self) -> None:
        sender = SimpleNamespace(bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[AreaInfo.model_validate({'id': 'area-1', 'name': '测试域'})]), leave_area=AsyncMock())))

        response = self._request(sender, {"area": "area-other"})

        self.assertEqual(response.status_code, 404)
        sender.bot.areas.leave_area.assert_not_awaited()

    def test_leaves_joined_area_and_invalidates_related_caches(self) -> None:
        sender = SimpleNamespace(bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[AreaInfo.model_validate({'id': 'area-1', 'name': '测试域'})]), leave_area=AsyncMock(return_value=SimpleNamespace(ok=True, message='')))))
        import web.admin.members._area_membership as route
        import web.admin.members._channels as channel_routes
        import web.admin.members._members as member_routes

        with (
            patch.object(member_routes._areas_cache, "invalidate") as areas_invalidate,
            patch.object(member_routes._area_meta_cache, "invalidate") as meta_invalidate,
            patch.object(channel_routes._channels_cache, "invalidate") as channels_invalidate,
            patch.object(route, "_invalidate_members_cache") as members_invalidate,
        ):
            response = self._request(sender, {"area": "area-1", "name": "伪造名称"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("测试域", response.json()["message"])
        sender.bot.areas.leave_area.assert_awaited_once_with("area-1")
        areas_invalidate.assert_called_once_with("all")
        meta_invalidate.assert_called_once_with("area-1")
        channels_invalidate.assert_called_once_with("area-1")
        members_invalidate.assert_called_once_with()

    def test_oopz_failure_keeps_caches_and_returns_error(self) -> None:
        sender = SimpleNamespace(bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[AreaInfo.model_validate({'id': 'area-1'})]), leave_area=AsyncMock(side_effect=RuntimeError('没有权限')))))
        import web.admin.members._area_membership as route

        with patch.object(route, "_invalidate_members_cache") as invalidate:
            response = self._request(sender, {"area": "area-1"})

        self.assertEqual(response.status_code, 502)
        self.assertIn("没有权限", response.json()["error"])
        invalidate.assert_not_called()


class AdminAreaLeaveUiContractTest(unittest.TestCase):
    def test_area_page_exposes_confirmed_leave_flow(self) -> None:
        content = (SRC_ROOT / "web/assets/admin/pages/areas_content.html").read_text(encoding="utf-8")
        script = (SRC_ROOT / "web/assets/admin/pages/areas_script.js").read_text(encoding="utf-8")

        self.assertIn('id="leaveAreaBtn"', content)
        self.assertIn('data-action="leave-current-area"', content)
        self.assertIn('AdminShell.confirm(', script)
        self.assertIn('/admin/api/areas/leave', script)
        self.assertIn('"leave-current-area": () => leaveCurrentArea()', script)


if __name__ == "__main__":
    unittest.main()
