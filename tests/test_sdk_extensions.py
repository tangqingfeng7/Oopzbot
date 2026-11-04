"""安装版 SDK 与项目接口扩展的接入测试。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oopz_sdk import OopzBot
from oopz_sdk.adapters.onebot.v11.types import make_group_source
from oopz_sdk.config.settings import OneBotV11Config
from oopz_sdk.exceptions import OopzApiError
from oopz_sdk.testing.factories import make_config
from oopz_sdk.transport.http import HttpResponse, HttpTransport

from core.proxy_utils import ProxySettings
from oopz.sdk_services import install_project_services
from oopz.sdk_transport import ProjectHttpTransport, install_project_transports


def response(status, payload):
    text = json.dumps(payload)
    return HttpResponse(status_code=status, headers={}, content=text.encode(), text=text)


class ProjectHttpAuthTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.auth = SimpleNamespace(token_version=0, handle_auth_error=AsyncMock(return_value=True))
        self.transport = ProjectHttpTransport(
            make_config(), object(), auth_manager=self.auth, proxy=ProxySettings(mode="direct")
        )

    async def test_permission_403_does_not_relogin(self):
        with (
            patch.object(HttpTransport, "request", AsyncMock(return_value=response(403, {"message": "无权限"}))),
            self.assertRaises(OopzApiError) as raised,
        ):
            await self.transport.request_data("GET", "/area/v3/info")
        self.assertEqual(raised.exception.status_code, 403)
        self.auth.handle_auth_error.assert_not_awaited()

    async def test_operate_log_401_preserves_other_requests_auth_recovery(self):
        replies = [
            response(401, {"message": "暂无进行此操作的权限"}),
            response(401, {"message": "expired"}),
            response(200, {"status": True, "data": {"id": "area-1"}}),
        ]
        with patch.object(HttpTransport, "request", AsyncMock(side_effect=replies)) as request:
            with self.assertRaises(OopzApiError) as raised:
                await self.transport.request_data("GET", "/client/v1/area/v1/operateLogs")
            self.assertEqual(raised.exception.status_code, 401)
            self.assertIn("HTTP 401", str(raised.exception))
            self.auth.handle_auth_error.assert_not_awaited()
            result = await self.transport.request_data("GET", "/area/v3/info")
        self.assertEqual(result, {"id": "area-1"})
        self.assertEqual(request.await_count, 3)
        self.auth.handle_auth_error.assert_awaited_once()

    async def test_operate_log_428_still_recovers_auth(self):
        with patch.object(HttpTransport, "request", AsyncMock(side_effect=[
            response(428, {}), response(200, {"status": True, "data": {"logs": []}}),
        ])):
            result = await self.transport.request_data("GET", "/client/v1/area/v1/operateLogs")
        self.assertEqual(result, {"logs": []})
        self.auth.handle_auth_error.assert_awaited_once()


class OneBotSharedServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_onebot_leave_uses_project_service(self):
        with tempfile.TemporaryDirectory() as directory:
            config = make_config()
            config.onebot_v11 = OneBotV11Config(
                enabled=True, auto_start_server=False,
                db_path=str(Path(directory) / "onebot.sqlite3"),
                enable_set_group_leave_as_area_leave=True,
            )
            bot = OopzBot(config)
            install_project_transports(bot, ProxySettings(mode="direct"), None)
            install_project_services(bot)
            self.assertIs(bot.areas, bot.rest.areas)
            self.assertIs(bot.areas.transport, bot.rest.transport)
            adapter = bot.adapters[0]
            group_id = adapter.ids.createId(make_group_source(area="area-1", channel="channel-1")).number
            try:
                with patch.object(HttpTransport, "request", AsyncMock(return_value=response(200, {"status": True, "data": {"status": True}}))) as request:
                    result = await adapter.call_action("set_group_leave", {"group_id": group_id})
                self.assertEqual(result["status"], "ok")
                request.assert_awaited_once_with(
                    "DELETE", "/client/v1/area/v1/quit", body=None, params={"area": "area-1"}
                )
                actions = await adapter.get_supported_actions({})
                self.assertIn("send_group_msg", actions)
                self.assertNotIn("get_group_msg_history", actions)
                self.assertNotIn("set_group_admin", actions)
            finally:
                await bot.stop()


class OneBotConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_config_defaults_keep_existing_connection_settings(self):
        import config
        from oopz import sdk_config

        with (
            patch.object(config, "ONEBOT_V11_CONFIG", {}),
            patch.dict("os.environ", {"ONEBOT_V11_ENABLED": "0"}),
            patch.object(sdk_config, "migrate_onebot_v11_database", AsyncMock()) as migrate,
        ):
            result = await sdk_config._onebot_v11_config()
        self.assertIsInstance(result, OneBotV11Config)
        self.assertFalse(result.enabled)
        self.assertFalse(result.enable_http_post)
        self.assertFalse(result.enable_ws_reverse)
        self.assertEqual(result.http_post_timeout, 10.0)
        assert result.db_path is not None
        self.assertTrue(Path(result.db_path).is_absolute())
        migrate.assert_not_awaited()

    async def test_enabled_sdk_config_migrates_resolved_database(self):
        import config
        from oopz import sdk_config

        with (
            patch.object(config, "ONEBOT_V11_CONFIG", {
                "enabled": False, "db_path": "data/onebot-test.sqlite3",
                "http_post_urls": "http://localhost:8081, http://localhost:8082",
                "enable_ws_reverse": "true", "http_post_timeout": 5,
            }),
            patch.dict("os.environ", {"ONEBOT_V11_ENABLED": "1"}),
            patch.object(sdk_config, "migrate_onebot_v11_database", AsyncMock()) as migrate,
        ):
            result = await sdk_config._onebot_v11_config()
        self.assertTrue(result.enabled)
        self.assertTrue(result.enable_ws_reverse)
        self.assertEqual(result.http_post_urls, ["http://localhost:8081", "http://localhost:8082"])
        self.assertEqual(result.http_post_timeout, 5)
        migrate.assert_awaited_once_with(result.db_path)
