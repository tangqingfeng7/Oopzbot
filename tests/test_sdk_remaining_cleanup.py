import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import aiohttp
from fastapi import Request
from oopz_sdk import OopzBot
from oopz_sdk.config.constants import (
    EVENT_CHANNEL_DELETE,
    EVENT_CHANNEL_UPDATE,
    EVENT_PUBLIC_CHANNEL_CREATE,
)
from oopz_sdk.events.context import EventContext
from oopz_sdk.exceptions import OopzApiError, OopzAuthError
from oopz_sdk.models import AreaInfo, AreaMembersPage, ChannelGroupInfo, OperationResult, UserInfo
from oopz_sdk.testing.factories import make_config

from app.infrastructure.gateways.sender_gateway import SenderGateway
from app.infrastructure.oopz_connection import ProjectWebSocketTransport, install_project_transports
from core.proxy_utils import ProxySettings
from music.music import MusicHandler
from oopz import credentials
from web.admin.members import _channels, _members


class RemainingSdkCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = OopzBot(make_config())
        install_project_transports(self.bot, ProxySettings(mode="direct"), None)
        self.addAsyncCleanup(self.bot.stop)
        self.sender = SenderGateway(self.bot)
        self.send = AsyncMock()
        self.sender.send_message = self.send
        _channels._channels_cache.invalidate()
        self.addCleanup(_channels._channels_cache.invalidate)

    async def test_create_and_delete_refresh_voice_channel_index(self):
        ids = ["old"]
        requested = []

        async def groups(_area):
            return [ChannelGroupInfo.model_validate({"id": "group", "channels": [
                {"id": channel, "name": channel, "type": "VOICE"} for channel in ids
            ]})]

        async def request(_method, path, **kwargs):
            if path.endswith("/create"):
                ids.append("new")
                return {"id": "new", "name": "new", "type": "VOICE"}
            if path.endswith("/delete"):
                ids.remove("new")
                return {"status": True}
            requested.append(kwargs["body"]["channels"])
            return {"channelMembers": {}}

        self.bot.areas.get_area_channels = AsyncMock(side_effect=groups)
        self.bot.channels._request_data = AsyncMock(side_effect=request)
        self.assertIs(self.bot.channels, self.bot.rest.channels)
        await self.bot.channels.get_voice_channel_members("area")
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_channels, "read_json_body", AsyncMock(return_value={
                "area": "area", "name": "new", "type": "VOICE", "group_id": "group",
            })),
        ):
            result = await _channels.admin_channel_create(Request({"type": "http"}))
            self.assertTrue(json.loads(bytes(result.body))["ok"])
            await self.bot.channels.get_voice_channel_members("area")
            result = await _channels.admin_channel_delete("new", Request({"type": "http"}))
            self.assertTrue(json.loads(bytes(result.body))["ok"])
            await self.bot.channels.get_voice_channel_members("area")
        self.assertEqual(requested, [["old"], ["old", "new"], ["old"]])

    async def test_channel_settings_translate_web_fields(self):
        update = AsyncMock(return_value=OperationResult())
        self.bot.channels.update_channel = update
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_channels, "read_json_body", AsyncMock(return_value={
                "area": "area", "maxMember": 10, "textGapSecond": 5, "secret": True,
                "accessibleMembers": ["user"],
            })),
        ):
            result = await _channels.admin_channel_settings_edit("channel", Request({"type": "http"}))
        self.assertTrue(json.loads(bytes(result.body))["ok"])
        update.assert_awaited_once_with(
            area="area", channel_id="channel", max_member=10, text_gap_second=5,
            secret=True, accessible_members=["user"],
        )

    async def test_sdk_channel_events_refresh_web_and_voice_caches_for_their_area(self):
        channels = {"area": ["old"], "other": ["unrelated"]}
        requested = []

        async def groups(area):
            return [ChannelGroupInfo.model_validate({"id": "group", "channels": [
                {"id": channel, "name": channel, "type": "VOICE"} for channel in channels[area]
            ]})]

        async def request(_method, _path, **kwargs):
            requested.append(kwargs["body"]["channels"])
            return {"channelMembers": {}}

        query = AsyncMock(side_effect=groups)
        self.bot.areas.get_area_channels = query
        self.bot.channels._request_data = AsyncMock(side_effect=request)
        with patch.object(_channels, "_get_sender", return_value=self.sender):
            for area in channels:
                await _channels.admin_channels_list(area)
                await self.bot.channels.get_voice_channel_members(area)
            for event_type, expected in [
                (EVENT_PUBLIC_CHANNEL_CREATE, ["old", "new"]),
                (EVENT_CHANNEL_UPDATE, ["renamed"]),
                (EVENT_CHANNEL_DELETE, []),
            ]:
                channels["area"] = expected
                event = self.bot.parser.parse({"event": event_type, "body": {
                    "area": "area", "channel": "new", "type": "VOICE", "name": "new",
                }})
                self.assertIn(event.event_name, {"channel.create", "channel.update", "channel.delete"})
                await self.bot.dispatcher.dispatch(
                    event.event_name, event, EventContext(bot=self.bot, config=self.bot.config, event=event),
                )
                response = await _channels.admin_channels_list("area")
                self.assertEqual([ch["id"] for ch in json.loads(bytes(response.body))["channels"]], expected)
                await self.bot.channels.get_voice_channel_members("area")
                self.assertEqual(requested[-1], expected)
                query.reset_mock()
                await _channels.admin_channels_list("other")
                await self.bot.channels.get_voice_channel_members("other")
                query.assert_not_awaited()

    async def test_failed_delete_preserves_cached_voice_index(self):
        self.bot.areas.get_area_channels = AsyncMock(return_value=[
            ChannelGroupInfo.model_validate({"id": "group", "channels": [
                {"id": "voice", "type": "VOICE"},
            ]}),
        ])
        self.bot.channels._request_data = AsyncMock(side_effect=[
            {"channelMembers": {}}, False, {"channelMembers": {}},
        ])
        await self.bot.channels.get_voice_channel_members("area")
        result = await self.bot.channels.delete_channel("area", "voice")
        self.assertFalse(result.ok)
        await self.bot.channels.get_voice_channel_members("area")
        self.bot.areas.get_area_channels.assert_awaited_once_with("area")

    async def test_failed_private_channel_configuration_cleans_up(self):
        self.sender._pick_channel_group = AsyncMock(return_value="group")
        self.bot.channels.create_channel = AsyncMock(return_value=SimpleNamespace(channel_id="temporary"))
        self.bot.channels.update_channel = AsyncMock(return_value=OperationResult(ok=False, message="denied"))
        delete = AsyncMock(return_value=OperationResult())
        self.bot.channels.delete_channel = delete
        with self.assertRaisesRegex(RuntimeError, "denied"):
            await self.sender.create_restricted_text_channel("user", area="area")
        delete.assert_awaited_once_with("area", "temporary")

    async def test_private_channel_uses_preferred_channel_group_or_first_group(self):
        self.bot.areas.get_area_channels = AsyncMock(return_value=[
            ChannelGroupInfo.model_validate({"id": "first"}),
            ChannelGroupInfo.model_validate({"id": "preferred", "channels": [{"id": "text"}]}),
        ])
        self.assertEqual(await self.sender._pick_channel_group("area", "text"), "preferred")
        self.assertEqual(await self.sender._pick_channel_group("area", "missing"), "first")

    async def test_joined_area_models_drive_diagnostics_and_member_warmup(self):
        from app.lifecycle.background_services import BackgroundServiceRunner
        from app.services.interaction.setup_diagnostics import SetupDiagnostics

        self.bot.areas.get_joined_areas = AsyncMock(return_value=[
            AreaInfo.model_validate({"id": "area", "name": "测试域"}),
        ])
        self.bot.areas.get_area_members = AsyncMock(return_value=AreaMembersPage())
        report = await SetupDiagnostics(sender=self.sender)._check_joined_areas()
        self.assertEqual(report["level"], "pass")
        self.assertEqual(report["detail"], "首个域: 测试域")
        registry = Mock()
        registry.get_all_area_ids.return_value = []
        with (
            patch("core.area_config.get_area_registry", return_value=registry),
            patch("config.OOPZ_CONFIG", {}),
        ):
            await BackgroundServiceRunner()._warmup_members_cache(self.sender)
        self.bot.areas.get_area_members.assert_awaited_once_with("area")

    async def test_background_music_area_uses_joined_area_model(self):
        music: Any = MusicHandler.__new__(MusicHandler)
        music.sender = self.sender
        music._background_area_cache = ("", 0.0)
        music._resolve_background_area = Mock(side_effect=lambda: music._background_area_cache[0])
        self.bot.areas.get_joined_areas = AsyncMock(return_value=[AreaInfo.model_validate({"id": "area"})])
        with (
            patch("music.music.get_redis_client", new=AsyncMock()),
            patch("music.music.get_active_area", new=AsyncMock(return_value="")),
        ):
            self.assertEqual(await music._resolve_background_area_async(), "area")

    async def test_voice_query_error_does_not_ask_user_to_join(self):
        music: Any = MusicHandler.__new__(MusicHandler)
        music.sender = self.sender
        music.voice = SimpleNamespace(available=True)
        self.bot.channels.get_voice_channel_for_user = AsyncMock(side_effect=OopzApiError("unavailable"))
        with self.assertLogs("Music", level="WARNING"):
            result = await music._check_and_enter_voice_channel("user", "channel", "area")
        self.assertFalse(result)
        self.assertIn("查询语音频道失败", self.send.call_args.args[0])
        self.assertNotIn("请先加入", self.send.call_args.args[0])

    async def test_stale_voice_leave_failure_is_logged(self):
        music: Any = MusicHandler.__new__(MusicHandler)
        music.sender = self.sender
        self.bot.channels.get_voice_channel_for_user = AsyncMock(return_value="stale")
        for response in (OopzApiError("unavailable"), OperationResult(ok=False, message="denied")):
            with self.subTest(response=type(response).__name__):
                self.bot.channels.leave_voice_channel = AsyncMock(
                    side_effect=response if isinstance(response, Exception) else None,
                    return_value=response,
                )
                with patch.dict("music.music.OOPZ_CONFIG", {"person_uid": "bot"}), self.assertLogs("Music", level="WARNING") as logs:
                    await music._cleanup_stale_voice_membership("area")
                self.assertIn("清理残留语音状态失败", logs.output[0])

    async def test_block_queries_distinguish_failure_partial_and_empty(self):
        async def blocks(area):
            if area == "failed":
                raise OopzApiError("no permission")
            return [UserInfo(uid="blocked-user")]

        self.bot.moderation.get_area_blocks = AsyncMock(side_effect=blocks)
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members, "_area_name_map", AsyncMock(return_value={"failed": "失败域", "good": "成功域"})),
        ):
            failed = await _members.admin_members_blocks("failed")
            self.assertEqual(failed.status_code, 502)
            partial = await _members.admin_members_blocks(_members.ALL_AREAS)
        payload = json.loads(bytes(partial.body))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["blocks"][0]["areaId"], "good")
        self.assertEqual(payload["partial"][0]["areaId"], "failed")
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members, "_area_name_map", AsyncMock(return_value={"failed": "失败域"})),
        ):
            all_failed = await _members.admin_members_blocks(_members.ALL_AREAS)
            self.assertEqual(all_failed.status_code, 502)
            self.bot.moderation.get_area_blocks = AsyncMock(return_value=[])
            empty = await _members.admin_members_blocks("failed")
            self.assertTrue(json.loads(bytes(empty.body))["ok"])
            self.assertEqual(json.loads(bytes(empty.body))["blocks"], [])


class WebSocketProxyTest(unittest.IsolatedAsyncioTestCase):
    async def test_connect_preserves_http_proxy_and_sdk_auth_errors(self):
        from app.lifecycle.oopz_session import _sdk_proxy

        settings = ProxySettings(mode="explicit", server="http://127.0.0.1:9000", scheme="http")
        config = make_config()
        config.proxy = _sdk_proxy(settings)
        transport = ProjectWebSocketTransport(config, proxy=settings)
        session = Mock(closed=False)
        session.ws_connect = AsyncMock(side_effect=aiohttp.WSServerHandshakeError(
            Mock(real_url="wss://example.test"), (), status=401, message="unauthorized",
        ))
        with (
            patch("app.infrastructure.oopz_connection.aiohttp.ClientSession", return_value=session) as factory,
            self.assertRaises(OopzAuthError),
        ):
            await transport.connect()
        self.assertEqual(session.ws_connect.await_args.kwargs["proxy"], settings.server)
        timeout = factory.call_args.kwargs["timeout"]
        self.assertIsNone(timeout.total)
        self.assertIsNotNone(timeout.sock_connect)


class PartialCredentialSaveTest(unittest.TestCase):
    def test_capture_tool_uses_shared_persistence_and_writes_summary(self):
        from tools import credential_tool

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(credential_tool, "PROJECT_ROOT", directory),
            patch.object(credentials, "save_credentials", return_value=["config.py"]) as save,
            patch("builtins.print"),
        ):
            credential_tool.save_config({"jwt_token": "captured-token"})
            save.assert_called_once_with({"jwt_token": "captured-token"}, require_private_key=False)
            self.assertIn("captured-token", (Path(directory) / "data" / "credentials.txt").read_text("utf-8"))

    def test_partial_capture_preserves_unsupplied_credentials_and_private_key(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.py"
            key = Path(directory) / "private_key.py"
            config.write_text('OOPZ_CONFIG = {"device_id": "old-device", "jwt_token": "old-token"}', encoding="utf-8")
            key.write_text("old-key", encoding="utf-8")
            with (
                patch.object(credentials, "CONFIG_PATH", str(config)),
                patch.object(credentials, "PRIVATE_KEY_PATH", str(key)),
                patch.object(credentials, "_apply_runtime"),
            ):
                saved = credentials.save_credentials({"jwt_token": "new-token"}, require_private_key=False)
                self.assertEqual(saved, ["config.py"])
                self.assertIn('"device_id": "old-device"', config.read_text("utf-8"))
                self.assertIn('"jwt_token": "new-token"', config.read_text("utf-8"))
                self.assertEqual(key.read_text("utf-8"), "old-key")
                previous = config.read_text("utf-8")
                saved = credentials.save_credentials({"private_key_pem": "captured-key"}, require_private_key=False)
                self.assertEqual(saved, ["private_key.py"])
                self.assertEqual(config.read_text("utf-8"), previous)
                self.assertIn("captured-key", key.read_text("utf-8"))
