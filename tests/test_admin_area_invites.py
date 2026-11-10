import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
from oopz_sdk.models import Message  # noqa: E402
from oopz_sdk.testing.factories import make_config  # noqa: E402

from app.infrastructure.gateways.sender_gateway import SenderGateway  # noqa: E402
from app.lifecycle.oopz_session import OopzSession  # noqa: E402
from core import database  # noqa: E402
from core.database import AreaInviteRequestDB, init_database  # noqa: E402
from services.area_invite_inbox import (  # noqa: E402
    capture_private_area_invites,
    extract_area_invite_codes,
)

INVITE_DETAIL = {
    "status": "INVITE_NORMAL",
    "area": "area-1",
    "areaName": "测试域",
    "areaAvatar": "https://cdn.example/avatar.webp",
    "banner": "https://cdn.example/banner.webp",
    "channel": "channel-1",
    "channelName": "主页",
    "channelType": "TEXT",
    "isAreaInvite": True,
}

PENDING_ROW = {
    "code": "kz0nlt",
    "sender_id": "user-1",
    "sender_name": "邀请人",
    "message_id": "message-1",
    "message_timestamp": "1770000000000",
    "invite_status": "INVITE_NORMAL",
    "area_id": "area-1",
    "area_name": "测试域",
    "area_avatar": "https://cdn.example/avatar.webp",
    "banner": "https://cdn.example/banner.webp",
    "channel_id": "channel-1",
    "channel_name": "主页",
    "channel_type": "TEXT",
    "is_area_invite": 1,
    "state": "pending",
    "received_at": "2026-08-25 20:00:00",
}


class AreaInviteCodeTest(unittest.TestCase):
    def test_extracts_all_links_from_private_message_text(self) -> None:
        self.assertEqual(
            extract_area_invite_codes(
                "邀请一 https://oopz.cn/i/kz0nlt 邀请二 "
                "https://www.oopz.vip/s/Ab_12-3?from=chat"
            ),
            ["kz0nlt", "Ab_12-3"],
        )

    def test_auto_capture_requires_oopz_invite_url_not_bare_code(self) -> None:
        for value in ("kz0nlt", "https://example.com/i/kz0nlt", "https://oopz.cn/user/kz0nlt"):
            with self.subTest(value=value):
                self.assertEqual(extract_area_invite_codes(value), [])


class AreaInviteSdkTest(unittest.IsolatedAsyncioTestCase):
    async def test_invite_detail_uses_public_code_detail_endpoint(self) -> None:
        request = AsyncMock(return_value=INVITE_DETAIL)
        gateway = SenderGateway(OopzBot(make_config()))
        self.addAsyncCleanup(gateway.bot.stop)
        gateway.bot.rest.transport.request_data = request

        detail = await gateway.get_area_invite_detail(" kz0nlt ")

        self.assertEqual(detail["area"], "area-1")
        self.assertEqual(detail["areaName"], "测试域")
        self.assertTrue(detail["isAreaInvite"])
        request.assert_awaited_once_with(
            "GET",
            "/invite/v1/codeDetail",
            params={"code": "kz0nlt"},
        )


class PrivateInviteCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_is_resolved_and_saved_without_joining(self) -> None:
        sender = SimpleNamespace(get_area_invite_detail=AsyncMock(return_value=INVITE_DETAIL), bot=SimpleNamespace(areas=SimpleNamespace(enter_area=AsyncMock())))
        resolver = SimpleNamespace(
            ensure_users=AsyncMock(return_value={"user-1": "邀请人"}),
            user_cached=Mock(return_value="邀请人"),
        )
        message = {
            "content": "来我的域 https://oopz.cn/i/kz0nlt",
            "person": "user-1",
            "messageId": "message-1",
            "timestamp": "1770000000000",
        }

        with (
            patch("services.area_invite_inbox.get_resolver", return_value=resolver),
            patch.object(AreaInviteRequestDB, "upsert_pending", new=AsyncMock()) as save,
        ):
            captured = await capture_private_area_invites(sender, message)

        self.assertEqual(captured, 1)
        sender.get_area_invite_detail.assert_awaited_once_with("kz0nlt")
        sender.bot.areas.enter_area.assert_not_awaited()
        assert save.await_args is not None
        self.assertEqual(save.await_args.kwargs["sender_id"], "user-1")
        self.assertEqual(save.await_args.kwargs["detail"]["area"], "area-1")

    async def test_message_without_invite_does_not_call_oopz_api(self) -> None:
        sender = SimpleNamespace(get_area_invite_detail=AsyncMock())
        captured = await capture_private_area_invites(sender, {"content": "普通私信"})
        self.assertEqual(captured, 0)
        sender.get_area_invite_detail.assert_not_awaited()

    async def test_gateway_has_a_separate_private_message_callback(self) -> None:
        callback = AsyncMock()
        gateway = OopzSession(on_private_message=callback)
        message = Message.from_api({"content": "https://oopz.cn/i/kz0nlt", "messageId": "invite", "person": "user"})
        await gateway._handle_sdk_private_message(message, None)
        assert callback.await_args is not None
        payload = callback.await_args.args[0]
        self.assertEqual(payload["content"], "https://oopz.cn/i/kz0nlt")
        self.assertEqual(payload["messageId"], "invite")
        self.assertEqual(payload["person"], "user")

    async def test_public_message_callback_preserves_platform_field_names(self) -> None:
        callback = AsyncMock()
        gateway = OopzSession(on_chat_message=callback)
        await gateway._handle_sdk_message(Message.from_api({
            "area": "area", "channel": "channel", "content": "消息", "messageId": "message",
            "person": "user", "timestamp": "123", "mentionList": [{"person": "bot", "isBot": True}],
        }), None)
        assert callback.await_args is not None
        payload = callback.await_args.args[0]
        self.assertEqual(payload["messageId"], "message")
        self.assertEqual(payload["person"], "user")
        self.assertEqual(payload["mentionList"][0]["person"], "bot")
        self.assertTrue(payload["mentionList"][0]["isBot"])

    def test_gateway_registers_private_message_event(self) -> None:
        gateway = OopzSession(on_private_message=AsyncMock())
        bot = Mock()
        with (
            patch("app.lifecycle.oopz_session.OopzBot", return_value=bot),
            patch("app.lifecycle.oopz_session.install_project_transports"),
        ):
            gateway._install_bot(Mock(), None, None)
        bot.on_private_message.assert_called_once_with(gateway._handle_sdk_private_message)


class AreaInvitePersistenceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_patch = patch.object(
            database,
            "DB_PATH",
            os.path.join(self._tmpdir.name, "test_cache.db"),
        )
        self._db_patch.start()
        await init_database()

    async def asyncTearDown(self) -> None:
        self._db_patch.stop()
        self._tmpdir.cleanup()

    async def test_pending_invite_survives_reads_and_can_be_processed(self) -> None:
        await AreaInviteRequestDB.upsert_pending(
            code="kz0nlt",
            sender_id="user-1",
            sender_name="邀请人",
            message_id="message-1",
            message_timestamp="1770000000000",
            detail=INVITE_DETAIL,
        )

        pending = await AreaInviteRequestDB.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["area_name"], "测试域")
        self.assertTrue(await AreaInviteRequestDB.mark_processed("kz0nlt", "accepted"))
        self.assertEqual(await AreaInviteRequestDB.list_pending(), [])


class AdminAreaInviteApiTest(unittest.TestCase):
    def setUp(self) -> None:
        if TestClient is None:
            self.skipTest(f"缺少 TestClient 依赖: {_TESTCLIENT_ERROR}")
        import web.web_player as web_player

        self.web_player = web_player
        import web.web_rate_limit as web_rate_limit

        web_rate_limit.reset_all()
        self.client = TestClient(web_player.app, client=("127.0.0.1", 50001))

    def _request(self, sender, method: str, path: str, payload: dict | None = None):
        import web.admin.shared._runtime as runtime

        with (
            patch.object(self.web_player, "_admin_enabled", return_value=True),
            patch.object(self.web_player, "_is_admin_authorized", return_value=True),
            patch.object(runtime, "_get_sender", return_value=sender),
        ):
            return self.client.request(method, path, json=payload)

    def test_list_returns_only_stored_private_invites(self) -> None:
        sender = SimpleNamespace(bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[]))))
        with patch.object(
            AreaInviteRequestDB,
            "list_pending",
            new=AsyncMock(return_value=[PENDING_ROW]),
        ):
            response = self._request(sender, "GET", "/admin/api/area-invites")

        self.assertEqual(response.status_code, 200)
        invite = response.json()["invites"][0]
        self.assertEqual(invite["senderName"], "邀请人")
        self.assertEqual(invite["area"], "area-1")
        self.assertTrue(invite["canAccept"])

    def test_accept_requires_a_stored_pending_private_invite(self) -> None:
        sender = SimpleNamespace(get_area_invite_detail=AsyncMock(), bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[]), enter_area=AsyncMock())))
        with patch.object(
            AreaInviteRequestDB,
            "get_pending",
            new=AsyncMock(return_value=None),
        ):
            response = self._request(
                sender,
                "POST",
                "/admin/api/area-invites/accept",
                {"code": "kz0nlt"},
            )

        self.assertEqual(response.status_code, 404)
        sender.get_area_invite_detail.assert_not_awaited()
        sender.bot.areas.enter_area.assert_not_awaited()

    def test_accept_reresolves_and_joins_server_supplied_area(self) -> None:
        sender = SimpleNamespace(get_area_invite_detail=AsyncMock(return_value=INVITE_DETAIL), bot=SimpleNamespace(areas=SimpleNamespace(get_joined_areas=AsyncMock(return_value=[]), enter_area=AsyncMock(return_value=SimpleNamespace(ok=True, message='')))))
        import web.admin.members._members as member_routes

        with (
            patch.object(
                AreaInviteRequestDB,
                "get_pending",
                new=AsyncMock(return_value=PENDING_ROW),
            ),
            patch.object(
                AreaInviteRequestDB,
                "mark_processed",
                new=AsyncMock(return_value=True),
            ) as mark_processed,
            patch.object(member_routes._areas_cache, "invalidate") as invalidate,
        ):
            response = self._request(
                sender,
                "POST",
                "/admin/api/area-invites/accept",
                {"code": "kz0nlt", "area": "tampered-area"},
            )

        self.assertEqual(response.status_code, 200)
        sender.bot.areas.enter_area.assert_awaited_once_with(area="area-1", recover=False)
        mark_processed.assert_awaited_once_with("kz0nlt", "accepted")
        invalidate.assert_called_once_with("all")

    def test_reject_removes_pending_invite_without_joining(self) -> None:
        sender = SimpleNamespace(bot=SimpleNamespace(areas=SimpleNamespace(enter_area=AsyncMock())))
        with patch.object(
            AreaInviteRequestDB,
            "mark_processed",
            new=AsyncMock(return_value=True),
        ) as mark_processed:
            response = self._request(
                sender,
                "POST",
                "/admin/api/area-invites/reject",
                {"code": "kz0nlt"},
            )

        self.assertEqual(response.status_code, 200)
        mark_processed.assert_awaited_once_with("kz0nlt", "rejected")
        sender.bot.areas.enter_area.assert_not_awaited()


class AreaInviteUiContractTest(unittest.TestCase):
    def test_area_admin_page_exposes_private_message_approval_flow(self) -> None:
        content = (SRC_ROOT / "web/assets/admin/pages/areas_content.html").read_text(encoding="utf-8")
        script = (SRC_ROOT / "web/assets/admin/pages/areas_script.js").read_text(encoding="utf-8")

        self.assertIn('id="areaInviteList"', content)
        self.assertIn("Bot 从收到的私信中自动识别", content)
        self.assertNotIn('id="areaInviteInput"', content)
        for modal_id in ("modalOverlay", "modalDialog", "modalTitle", "modalBody", "modalFooter"):
            with self.subTest(modal_id=modal_id):
                self.assertIn(f'id="{modal_id}"', content)
        self.assertIn('AdminShell.req("/admin/api/area-invites")', script)
        self.assertIn('/admin/api/area-invites/accept', script)
        self.assertIn('/admin/api/area-invites/reject', script)
        self.assertIn('AdminShell.confirm(', script)


if __name__ == "__main__":
    unittest.main()
