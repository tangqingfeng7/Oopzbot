import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import Request
from oopz_sdk import OopzBot
from oopz_sdk.exceptions import OopzApiError
from oopz_sdk.models import (
    AreaMemberInfo,
    AreaMembersPage,
    Message,
    MessageSendResult,
    OperationResult,
    UserInfo,
)
from oopz_sdk.testing.factories import make_config

from app.infrastructure.gateways.sender_gateway import SenderGateway
from app.services.interaction.common_command_service import CommonCommandService
from app.services.runtime import CommandRuntimeView
from app.services.runtime.command_runtime import RecentMessageStore
from app.services.safety.message_recall_scheduler import MessageRecallScheduler
from app.services.safety.recall_service import RecallService
from plugins.delta_force.login import DeltaForceLoginManager
from web.admin.members import _channels, _members


class SdkDirectCallsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = OopzBot(make_config())
        self.addAsyncCleanup(self.bot.stop)
        self.sender = SenderGateway(self.bot)
        self.send = AsyncMock()
        self.sender.send_message = self.send
        self.runtime = cast(CommandRuntimeView, SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, music=None),
            recent_messages=RecentMessageStore(),
            services=SimpleNamespace(safety=SimpleNamespace(
                message_lookup=SimpleNamespace(resolve_timestamp=AsyncMock(return_value="123")),
            )),
        ))
        _channels._channels_cache.invalidate()
        self.addCleanup(_channels._channels_cache.invalidate)

    async def test_channel_failure_is_not_cached_but_successful_empty_list_is(self):
        query = AsyncMock(side_effect=[OopzApiError("unavailable"), []])
        self.bot.areas.get_area_channels = query
        with patch.object(_channels, "_get_sender", return_value=self.sender):
            failed = await _channels.admin_channels_list("area")
            self.assertEqual(failed.status_code, 502)
            self.assertFalse(json.loads(bytes(failed.body))["ok"])
            empty = await _channels.admin_channels_list("area")
            self.assertEqual(json.loads(bytes(empty.body))["channels"], [])
            await _channels.admin_channels_list("area")
        self.assertEqual(query.await_count, 2)

    async def test_voice_query_failure_is_reported_by_web_and_command(self):
        self.bot.areas.get_area_channels = AsyncMock(return_value=[])
        self.bot.channels.get_voice_channel_members = AsyncMock(side_effect=OopzApiError("unavailable"))
        with patch.object(_channels, "_get_sender", return_value=self.sender):
            response = await _channels.admin_voice_channels("area")
        self.assertEqual(response.status_code, 502)
        await CommonCommandService(self.runtime).show_voice_channels("channel", "area")
        message = self.send.call_args.args[0]
        self.assertIn("查询语音频道成员失败", message)
        self.assertNotIn("没有语音频道在线成员", message)

    async def test_online_members_does_not_return_an_interrupted_page_as_success(self):
        self.sender.bot.areas.get_area_members = AsyncMock(side_effect=[
            AreaMembersPage.from_api({"members": [{"uid": str(i), "online": 1} for i in range(100)]}),
            OopzApiError('unavailable'),
        ])
        with patch("web.web_player.get_sender", return_value=self.sender):
            response = await _channels.admin_online_members("area")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(json.loads(bytes(response.body))["ok"])

    async def test_moderation_failure_keeps_cache_and_success_invalidates_it(self):
        self.bot.moderation.mute_user = AsyncMock(side_effect=[
            OopzApiError("no permission"),
            OperationResult(ok=False, message="rejected"),
            OperationResult(message="muted"),
        ])
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members, "read_json_body", AsyncMock(return_value={"area": "area", "duration": 10})),
            patch.object(_members, "_invalidate_members_cache") as invalidate,
        ):
            for _ in range(2):
                failed = await _members.admin_member_mute("user", Request({"type": "http"}))
                self.assertFalse(json.loads(bytes(failed.body))["ok"])
                invalidate.assert_not_called()
            succeeded = await _members.admin_member_mute("user", Request({"type": "http"}))
            self.assertTrue(json.loads(bytes(succeeded.body))["ok"])
            invalidate.assert_called_once()

    async def test_dispatch_uses_sdk_source_channel_resolution(self):
        drag = AsyncMock(return_value=OperationResult(message="moved"))
        self.bot.channels.drag_member = drag
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_channels, "read_json_body", AsyncMock(return_value={
                "area": "area", "target": "user", "to_channel": "voice",
            })),
        ):
            response = await _channels.admin_voice_dispatch(Request({"type": "http"}))
        self.assertTrue(json.loads(bytes(response.body))["ok"])
        drag.assert_awaited_once_with("area", "user", "voice", from_channel="")

    async def test_auto_recall_logs_failures_and_continues_queue(self):
        finished = asyncio.Event()
        replies = [OopzApiError("unavailable"), OperationResult(ok=False, message="rejected"), OperationResult()]

        async def recall(**_kwargs):
            result = replies.pop(0)
            if not replies:
                finished.set()
            if isinstance(result, Exception):
                raise result
            return result

        self.bot.messages.recall_message = AsyncMock(side_effect=recall)
        scheduler = MessageRecallScheduler(self.runtime)
        self.addAsyncCleanup(scheduler.stop)
        with self.assertLogs("MessageRecallScheduler", level="WARNING") as logs:
            for index in range(3):
                await scheduler.schedule_recall(str(index), "channel", "area", delay=0.01)
            await asyncio.wait_for(finished.wait(), timeout=1)
        self.assertEqual(len(logs.records), 2)
        self.assertTrue(all("自动撤回执行失败" in record.getMessage() for record in logs.records))
        self.assertEqual(self.bot.messages.recall_message.await_count, 3)

    async def test_manual_recall_reports_sdk_failure(self):
        self.bot.messages.recall_message = AsyncMock(side_effect=OopzApiError("record not found"))
        await RecallService(self.runtime).recall_message("message", "channel", "area")
        message = self.send.call_args.args[0]
        self.assertIn("撤回失败", message)
        self.assertIn("消息可能已撤回", message)

    async def test_bulk_recall_counts_failures_and_continues(self):
        self.runtime.recent_messages.replace([
            {"messageId": "first", "channel": "channel", "area": "area", "timestamp": "1"},
            {"messageId": "second", "channel": "channel", "area": "area", "timestamp": "2"},
            {"messageId": "third", "channel": "channel", "area": "area", "timestamp": "3"},
        ])
        self.bot.messages.recall_message = AsyncMock(side_effect=[
            OopzApiError("unavailable"), OperationResult(ok=False), OperationResult(),
        ])
        with patch("app.services.safety.recall_service.asyncio.sleep", AsyncMock()):
            await RecallService(self.runtime).recall_multiple(3, "channel", "area")
        message = self.send.call_args.args[0]
        self.assertIn("成功: 1 条", message)
        self.assertIn("失败: 2 条", message)

    async def test_history_failure_does_not_become_no_messages(self):
        self.bot.messages.get_channel_messages = AsyncMock(side_effect=OopzApiError("unavailable"))
        recall = AsyncMock()
        self.bot.messages.recall_message = recall
        await RecallService(self.runtime).recall_multiple(3, "channel", "area")
        self.assertIn("查询历史消息失败", self.send.call_args.args[0])
        recall.assert_not_awaited()

    async def test_history_models_merge_with_local_messages_and_recall_latest(self):
        self.runtime.recent_messages.replace([
            {"messageId": "local", "channel": "channel", "area": "area", "timestamp": "200"},
        ])
        self.bot.messages.get_channel_messages = AsyncMock(return_value=[
            Message.from_api({"messageId": mid, "timestamp": timestamp, "area": "area", "channel": "channel"})
            for mid, timestamp in [("remote", "300"), ("local", "200"), ("old", "100")]
        ])
        recall = AsyncMock(return_value=OperationResult())
        self.bot.messages.recall_message = recall
        with patch("app.services.safety.recall_service.asyncio.sleep", AsyncMock()):
            await RecallService(self.runtime).recall_multiple(2, "channel", "area")
        self.assertEqual([call.args[0] for call in recall.await_args_list], ["remote", "local"])
        self.assertEqual([call.kwargs["timestamp"] for call in recall.await_args_list], ["300", "200"])
        self.assertIn("成功: 2 条", self.send.call_args.args[0])

    async def test_member_search_uses_one_sdk_batch_and_returns_member_models(self):
        members = [AreaMemberInfo(uid=f"uid-{index}") for index in range(65)]
        self.bot.areas.get_all_area_members = AsyncMock(return_value=members)
        profiles = AsyncMock(return_value=[UserInfo(uid=m.uid, name="Alice") for m in members[1:]])
        self.bot.person.get_person_infos_batch = profiles
        result = await self.sender.search_area_members("area", "ALICE")
        self.assertEqual(result, members[1:51])
        self.assertIs(result[0], members[1])
        profiles.assert_awaited_once_with([m.uid for m in members])
        self.assertEqual(await self.sender.search_area_members("area", "UID-0"), [members[0]])
        profiles.reset_mock()
        self.assertEqual(await self.sender.search_area_members("area", ""), members[:50])
        profiles.assert_not_awaited()

    async def test_login_notice_accepts_sdk_private_message_result(self):
        private = AsyncMock(return_value=MessageSendResult(messageId="private"))
        self.bot.messages.send_private_message = private
        manager = DeltaForceLoginManager({}, None, None)
        await manager._send_login_message(SimpleNamespace(sender=self.sender), "user", "channel", "area", "notice")
        private.assert_awaited_once_with("notice", target="user")
        self.send.assert_not_awaited()

    async def test_login_notice_only_uses_public_fallback_when_allowed(self):
        self.bot.messages.send_private_message = AsyncMock(side_effect=OopzApiError("unavailable"))
        manager = DeltaForceLoginManager({}, None, None)
        handler = SimpleNamespace(sender=self.sender)
        with self.assertLogs("DeltaForceLogin", level="WARNING"):
            await manager._send_login_message(handler, "user", "channel", "area", "notice", allow_public_fallback=False)
            self.send.assert_not_awaited()
            await manager._send_login_message(handler, "user", "channel", "area", "notice", allow_public_fallback=True)
        self.send.assert_awaited_once_with("notice", channel="channel", area="area")
