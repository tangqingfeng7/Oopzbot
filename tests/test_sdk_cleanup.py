import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oopz_sdk import OopzBot
from oopz_sdk.exceptions import OopzApiError
from oopz_sdk.models import JoinedAreaInfo, UserInfo
from oopz_sdk.models.message import MessageSendResult
from oopz_sdk.testing.factories import make_config

from app.infrastructure.gateways.sender_gateway import SenderGateway
from oopz.name_resolver import NameResolver
from web.admin.members import _members, _messaging


class SdkCleanupTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = OopzBot(make_config())
        self.addAsyncCleanup(self.bot.stop)
        self.sender = SenderGateway(self.bot)
        _members._areas_cache.invalidate()
        self.addCleanup(_members._areas_cache.invalidate)
        _members._members_resp_cache.invalidate()
        self.addCleanup(_members._members_resp_cache.invalidate)

    async def test_area_failure_is_not_cached_as_empty_success(self):
        query = AsyncMock(side_effect=[OopzApiError("unavailable"), []])
        self.bot.areas.get_joined_areas = query
        with patch.object(_members, "_get_sender", return_value=self.sender):
            failed = await _members.admin_areas_list()
            self.assertEqual(failed.status_code, 502)
            self.assertFalse(json.loads(bytes(failed.body))["ok"])
            empty = await _members.admin_areas_list()
            self.assertEqual(json.loads(bytes(empty.body)), {"ok": True, "areas": []})
            await _members.admin_areas_list()
        self.assertEqual(query.await_count, 2)

    async def test_area_list_preserves_sdk_fields(self):
        self.bot.areas.get_joined_areas = AsyncMock(return_value=[
            JoinedAreaInfo.from_api({"id": "area", "name": "测试域", "owner": "owner", "code": "code", "avatar": "avatar"}),
        ])
        with patch.object(_members, "_get_sender", return_value=self.sender):
            response = await _members.admin_areas_list()
        self.assertEqual(json.loads(bytes(response.body))["areas"][0]["name"], "测试域")

    async def test_cross_area_lookup_failure_is_reported(self):
        self.bot.areas.get_joined_areas = AsyncMock(side_effect=OopzApiError("unavailable"))
        with patch.object(_members, "_get_sender", return_value=self.sender):
            response = await _members._members_across_all_areas(offset=0, limit=50, keyword="")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(json.loads(bytes(response.body))["ok"])

    async def test_member_search_does_not_turn_query_failure_into_no_matches(self):
        self.bot.areas.get_all_area_members = AsyncMock(side_effect=OopzApiError("unavailable"))
        with self.assertRaises(OopzApiError):
            await self.sender.search_area_members(area="area", keyword="name")

    async def test_sdk_batching_uses_cache_and_propagates_middle_failure(self):
        uids = [f"u{i}" for i in range(65)]
        self.bot.person.cache.set_userinfo("u0", UserInfo(uid="u0", name="cached"))

        async def reply(_method, _path, *, body):
            return [{"uid": uid, "name": uid} for uid in body["persons"]]

        request = AsyncMock(side_effect=reply)
        self.bot.person._request_data = request
        result = await self.bot.person.get_person_infos_batch(uids)
        self.assertEqual([person.uid for person in result], uids)
        self.assertEqual(result[0].name, "cached")
        self.assertEqual([len(call.kwargs["body"]["persons"]) for call in request.await_args_list], [30, 30, 4])
        await self.bot.person.get_person_infos_batch(uids)
        self.assertEqual(request.await_count, 3)

        self.bot.person.cache.invalidate_userinfos()
        request.reset_mock()
        request.side_effect = [await reply("", "", body={"persons": uids[:30]}), OopzApiError("failed")]
        with self.assertRaises(OopzApiError):
            await self.bot.person.get_person_infos_batch(uids)
        self.assertEqual(request.await_count, 2)
        self.assertIsNotNone(self.bot.person.cache.get_userinfo("u0"))
        self.assertIsNone(self.bot.person.cache.get_userinfo("u30"))

    async def test_message_model_and_auto_recall_keep_identifiers(self):
        result = MessageSendResult(messageId="message", timestamp="123")
        self.bot.messages.send_message = AsyncMock(return_value=result)
        scheduler = Mock()
        self.sender.bind_auto_recall_scheduler(scheduler)
        with patch.dict("app.infrastructure.gateways.sender_gateway.AUTO_RECALL_CONFIG", {"enabled": True, "delay": 30}):
            response = await self.sender.send_message("回复", area="area", channel="channel", referenceMessageId="parent")
        self.assertIs(response, result)
        scheduler.schedule_recall.assert_called_once_with(message_id="message", channel="channel", area="area", timestamp="123", delay=30)
        assert self.bot.messages.send_message.await_args is not None
        self.assertEqual(self.bot.messages.send_message.await_args.kwargs["reference_message_id"], "parent")
        self.bot.messages.send_message.side_effect = OopzApiError("failed")
        with self.assertRaises(OopzApiError):
            await self.sender.send_message("失败", area="area", channel="channel")
        self.assertEqual(scheduler.schedule_recall.call_count, 1)

    async def test_admin_message_formats_model_and_reports_failure(self):
        self.bot.messages.send_message = AsyncMock(return_value=MessageSendResult(messageId="id", timestamp="456"))
        request = Mock()
        request.json = AsyncMock(return_value={"area": "area", "channel": "channel", "text": "text"})
        with (
            patch("web.admin.shared._runtime._get_sender", return_value=self.sender),
            patch.object(_messaging, "_require_sender", return_value=self.sender),
        ):
            for route in (_messaging.admin_send_message, _messaging.admin_send_announcement):
                response = await route(request)
                self.assertEqual(json.loads(bytes(response.body))["messageId"], "id")
                self.assertEqual(json.loads(bytes(response.body))["timestamp"], "456")
            self.bot.messages.send_message.side_effect = OopzApiError("failed")
            response = await _messaging.admin_send_message(request)
            self.assertFalse(json.loads(bytes(response.body))["ok"])


class NameCacheTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "names.json"
        for patcher in (
            patch("oopz.name_resolver.NAMES_FILE", str(self.file)),
            patch.object(NameResolver, "_instance", None),
            patch.dict("config.NAME_MAP", {"users": {"manual": "人工名称"}}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bot = OopzBot(make_config())
        self.addAsyncCleanup(self.bot.stop)
        self.sender = SenderGateway(self.bot)
        self.resolver = NameResolver()
        self.addAsyncCleanup(self.resolver.close)

    async def test_manual_priority_and_expired_automatic_name_refresh(self):
        self.file.write_text(json.dumps({"users": {"manual": "旧人工名称", "auto": "旧自动名称"}}), encoding="utf-8")
        await self.resolver.bind_gateway(self.sender)
        request = AsyncMock(side_effect=[[{"uid": "auto", "name": "新名称"}], [{"uid": "auto", "name": "改名"}]])
        self.bot.person._request_data = request
        self.assertEqual(await self.resolver.ensure_users(["manual", "auto"]), {"manual": "人工名称", "auto": "新名称"})
        await self.resolver.ensure_users(["auto"])
        self.assertEqual(request.await_count, 1)
        with patch("oopz_sdk.state.store.time.time", return_value=10**12):
            self.assertEqual(self.resolver.user_cached("auto", fallback=False), "")
            self.assertEqual((await self.resolver.ensure_users(["auto"]))["auto"], "改名")
        self.assertEqual(request.await_count, 2)
        assert request.await_args is not None
        self.assertEqual(request.await_args.kwargs["body"]["persons"], ["auto"])
        await self.resolver.flush()
        saved = json.loads(self.file.read_text("utf-8"))
        self.assertEqual(saved["users"]["auto"], "")

    async def test_explicit_override_persists_and_new_session_uses_its_cache(self):
        await self.resolver.bind_gateway(self.sender)
        self.resolver.set_user("override", "手工备注")
        await self.resolver.flush()
        with patch.object(NameResolver, "_instance", None):
            restarted = NameResolver()
        self.addAsyncCleanup(restarted.close)
        await restarted.bind_gateway(self.sender)
        self.assertEqual(await restarted.ensure_users(["override"]), {"override": "手工备注"})
        self.bot.person.cache.set_userinfo("auto", UserInfo(uid="auto", name="会话一"))
        self.assertEqual(restarted.user("auto"), "会话一")
        other = OopzBot(make_config())
        self.addAsyncCleanup(other.stop)
        await restarted.bind_gateway(SenderGateway(other))
        self.assertEqual(restarted.user_cached("auto", fallback=False), "")
