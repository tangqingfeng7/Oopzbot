import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from yarl import URL

REPO_ROOT = Path(__file__).resolve().parents[1]
for root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from plugins.lol_fa8.service import BASE_URL, FA8Client, _sign_api  # noqa: E402


class Fa8SignatureTest(unittest.TestCase):
    def test_frontend_signature_vectors(self):
        for action, fields, expected in (
            ("check", ["测试玩家", "12345"],
             "df65d9b53dc149aa9374811bf95e9907717c30cd6fa6aa1b0cf51c881183ac15"),
            ("matches", ["player-id", "CQ100", "0", ""],
             "5d97f62c5a07b29d142c23f704873b9484dd0cd099e4ea6d07fd70c4a89a05b8"),
        ):
            result = _sign_api(action, fields, "1793804612", "0123456789abcdef0123456789abcdef")
            self.assertEqual(result["api_sign"], expected)


class Fa8ClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = FA8Client("account", " password ", "sign=test-session")
        self.http = AsyncMock()
        self.http.session.return_value = SimpleNamespace(cookie_jar=Mock())
        self.client._http = self.http

    async def asyncTearDown(self):
        await self.client.stop()

    async def test_cookie_is_loaded_once_and_checked_by_server(self):
        self.http.request_payload.return_value = (200, {"code": 0, "data": {"logged_in": True}})
        self.assertTrue(await self.client._ensure_login())
        jar = self.http.session.return_value.cookie_jar
        cookie = jar.update_cookies.call_args.args[0]
        self.assertEqual(cookie["sign"].value, "test-session")
        self.assertEqual(jar.update_cookies.call_args.kwargs["response_url"], URL(BASE_URL))
        self.assertTrue(await self.client._ensure_login())
        self.http.request_payload.assert_awaited_once()

    async def test_captcha_response_keeps_actionable_login_message(self):
        self.http.request_payload.side_effect = [
            (200, {"code": 0, "data": {"logged_in": False}}),
            (422, {"code": 1, "message": "请完成人机验证", "data": {"field": "captcha"}}),
        ]
        result = await self.client.find_player("测试玩家", "12345")
        self.assertIn("session_cookie", result["message"])
        call = self.http.request_payload.await_args_list[-1]
        self.assertEqual(call.args, ("POST", BASE_URL + "/api/user.php?act=login"))
        self.assertEqual(call.kwargs["data"], {"account": "account", "password": " password "})
        self.assertFalse(call.kwargs["raise_for_status"])

    async def test_cookie_without_credentials_can_query(self):
        self.client._user = self.client._pwd = ""
        self.http.request_payload.side_effect = [
            (200, {"code": 0, "data": {"logged_in": True}}),
            (200, {"code": 0, "data": {"exists": False}}),
        ]
        self.http.request_text.return_value = (200, '<html data-server-time="1793804612000">')
        with patch("plugins.lol_fa8.service.time.time", return_value=1793804620):
            result = await self.client.find_player("测试玩家", "12345")
        self.assertEqual(result["code"], 0)
        data = self.http.request_payload.await_args_list[-1].kwargs["data"]
        self.assertEqual(data["api_timestamp"], "1793804612")
        self.assertEqual(data["game_name"], "测试玩家")
        self.assertEqual(len(data["api_nonce"]), 32)

    async def test_signature_expiration_refreshes_time_and_nonce(self):
        self.client._logged_in = True
        self.client._time_offset = 0
        self.http.request_payload.side_effect = [
            (403, {"code": 1, "data": {"sign_expired": True}}),
            (200, {"code": 0, "data": {"games": []}}),
        ]
        self.http.request_text.return_value = (200, '<html data-server-time="1793804612000">')
        with patch("plugins.lol_fa8.service.time.time", return_value=1793804620):
            result = await self.client.query_games("player-id", "CQ100")
        self.assertEqual(result["code"], 0)
        first, second = [call.kwargs["data"] for call in self.http.request_payload.await_args_list]
        self.assertEqual((first["api_timestamp"], second["api_timestamp"]), ("1793804620", "1793804612"))
        self.assertNotEqual(first["api_nonce"], second["api_nonce"])
        self.assertEqual(second["tag"], "")
        self.assertEqual(second["start"], "0")
        self.http.request_text.assert_awaited_once()

    async def test_login_expiration_rechecks_server_session(self):
        self.client._logged_in = True
        self.client._time_offset = 0
        self.http.request_payload.side_effect = [
            (401, {"code": 1, "message": "登录失效", "data": {"login_required": True}}),
            (200, {"code": 0, "data": {"logged_in": True}}),
            (200, {"code": 0, "data": {"games": []}}),
        ]
        self.assertEqual((await self.client.query_games("player-id", "CQ100"))["code"], 0)
        self.assertEqual(self.http.request_payload.await_count, 3)

    async def test_expired_session_without_credentials_requests_cookie_update(self):
        self.client._logged_in = True
        self.client._time_offset = 0
        self.client._user = self.client._pwd = ""
        self.http.request_payload.side_effect = [
            (401, {"code": 1, "data": {"login_required": True, "expired": True}}),
            (200, {"code": 0, "data": {"logged_in": False}}),
        ]
        result = await self.client.query_games("player-id", "CQ100")
        self.assertIn("更新 FA8 插件的 session_cookie", result["message"])
        self.assertFalse(self.client._logged_in)

    async def test_member_error_is_preserved_without_login_retry(self):
        self.client._logged_in = True
        self.client._time_offset = 0
        error = {"code": 1, "message": "请开通赞助会员", "data": {"vip_required": True}}
        self.http.request_payload.return_value = (403, error)
        self.assertEqual(await self.client.query_summoner("player-id", "CQ100"), error)
        self.http.request_payload.assert_awaited_once()

    async def test_concurrent_queries_share_session_check(self):
        self.http.request_payload.return_value = (200, {"code": 0, "data": {"logged_in": True}})
        self.assertEqual(await asyncio.gather(*(self.client._ensure_login() for _ in range(3))), [True] * 3)
        self.http.request_payload.assert_awaited_once()

    async def test_transport_failure_is_reported(self):
        self.http.request_payload.side_effect = TimeoutError("请求超时")
        result = await self.client.find_player("测试玩家", "12345")
        self.assertEqual(result["code"], -1)
        self.assertIn("请求超时", result["message"])


if __name__ == "__main__":
    unittest.main()
