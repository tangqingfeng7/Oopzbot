import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import Request
from oopz_sdk import OopzBot
from oopz_sdk.exceptions import OopzApiError, OopzRateLimitError
from oopz_sdk.models import (
    AreaInfo,
    AreaMembersPage,
    AreaUserDetail,
    ChannelGroupInfo,
    OperationResult,
    RoleInfo,
    UserInfo,
)
from oopz_sdk.models.channel import ChannelSetting, VoiceChannelMembersResult
from oopz_sdk.testing.factories import make_config

from app.infrastructure.gateways.sender_gateway import SenderGateway
from app.infrastructure.member_cache import members_response_cache
from app.services.community.member_service import MemberService
from app.services.community.role_service import RoleService
from app.services.community.target_resolution_service import TargetResolutionService
from app.services.routing.builtin_command_actions import ModerationCommandActions
from app.services.runtime import CommandRuntimeView
from app.services.safety.moderation_service import ModerationService
from core.area_config import AreaConfig
from services.area_join_notifier import _run_join_poll_loop, fetch_member_uid_snapshot
from web.admin.members import _channels, _members


class SdkMemberQueriesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = OopzBot(make_config())
        self.addAsyncCleanup(self.bot.stop)
        self.sender = SenderGateway(self.bot)
        self.send = AsyncMock()
        self.sender.send_message = self.send
        self.runtime = cast(CommandRuntimeView, SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(community=SimpleNamespace(), safety=SimpleNamespace(moderation=AsyncMock())),
        ))
        self.runtime.services.community.target_resolution = TargetResolutionService(self.runtime)
        members_response_cache.invalidate()
        self.addCleanup(members_response_cache.invalidate)

    async def test_kick_refreshes_sdk_and_web_cache_from_both_entrances(self):
        for entrance in ("web", "command"):
            with self.subTest(entrance=entrance):
                self.bot.areas.cache.invalidate_area_members_pages()
                query = AsyncMock(side_effect=[
                    {"members": [{"uid": "removed"}], "totalCount": 1},
                    {"members": [], "totalCount": 0},
                ])
                self.bot.areas._request_data_with_retry = query
                self.bot.moderation.remove_from_area = AsyncMock(return_value=OperationResult())
                await self.bot.areas.get_area_members("area")
                members_response_cache.set("area:0:50", {"members": ["removed"]})
                if entrance == "web":
                    with (
                        patch("web.web_player.get_sender", return_value=self.sender),
                        patch.object(_members, "read_json_body", AsyncMock(return_value={"area": "area"})),
                    ):
                        response = await _members.admin_member_kick("removed", Request({"type": "http"}))
                    self.assertTrue(json.loads(bytes(response.body))["ok"])
                else:
                    await ModerationService(self.runtime).remove_from_area("removed", "channel", "area")
                self.assertIsNone(members_response_cache.get("area:0:50"))
                page = await self.bot.areas.get_area_members("area")
                self.assertEqual(page.members, [])
                self.assertEqual(query.await_count, 2)

    async def test_rejected_command_keeps_both_caches(self):
        self.bot.areas.cache.set_area_members_page("area", 0, 49, AreaMembersPage.from_api({"members": [{"uid": "member"}]}))
        members_response_cache.set("area:0:50", {"members": ["member"]})
        self.bot.moderation.remove_from_area = AsyncMock(return_value=OperationResult(ok=False, message="拒绝"))
        await ModerationService(self.runtime).remove_from_area("member", "channel", "area")
        self.assertIsNotNone(self.bot.areas.cache.get_area_members_page("area", 0, 49))
        self.assertIsNotNone(members_response_cache.get("area:0:50"))

    async def test_role_edit_clears_web_display_cache(self):
        members_response_cache.set("area:0:50", {"role": 1})
        self.bot.areas.edit_user_role = AsyncMock(return_value=OperationResult())
        result = await self.sender.edit_user_role("member", 2, True, area="area")
        self.assertTrue(result.ok)
        self.assertIsNone(members_response_cache.get("area:0:50"))

    async def test_web_mute_status_uses_sdk_string_deadlines(self):
        self.bot.person.get_person_info = AsyncMock(return_value=UserInfo(uid="member", name="成员"))
        self.bot.areas.get_area_can_give_list = AsyncMock(return_value=[])
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members.MessageStatsDB, "get_user_total", AsyncMock(return_value=0)),
            patch.object(_members.time, "time", return_value=1800000000),
        ):
            for value, expected in [("1800000060000", True), ("1799999999000", False), (None, False)]:
                self.bot.areas.get_area_user_detail = AsyncMock(return_value=AreaUserDetail.from_api({
                    "disableTextTo": value, "disableVoiceTo": value,
                }))
                response = await _members.admin_member_detail("member", "area")
                data = json.loads(bytes(response.body))
                self.assertEqual(data["muted"], expected)
                self.assertEqual(data["mic_muted"], expected)
                self.assertEqual(data["muted_until"], int(value) if expected else 0)

    async def test_member_detail_preserves_frontend_fields(self):
        self.bot.person.get_person_info = AsyncMock(return_value=UserInfo.from_api({
            "uid": "member", "name": "成员", "userCommonId": "123", "online": True,
        }))
        self.bot.areas.get_area_user_detail = AsyncMock(return_value=AreaUserDetail.from_api({
            "list": [{"roleID": 2, "name": "成员组", "owned": True}],
        }))
        self.bot.areas.get_area_can_give_list = AsyncMock(return_value=[
            RoleInfo.from_api({"roleID": 3, "name": "新身份", "owned": False}),
        ])
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members.MessageStatsDB, "get_user_total", AsyncMock(return_value=7)),
        ):
            data = json.loads(bytes((await _members.admin_member_detail("member", "area")).body))
        self.assertEqual(data["person"], {
            "name": "成员", "avatar": "", "pid": "123", "online": True, "introduction": "",
        })
        self.assertEqual(data["roles"], [{"roleID": 2, "name": "成员组"}])
        self.assertEqual(data["assignable_roles"][0]["roleID"], 3)
        self.assertFalse(data["assignable_roles"][0]["owned"])
        self.assertEqual(data["messages_7d"], 7)

    async def test_channel_models_preserve_lists_settings_and_member_names(self):
        self.bot.areas.get_area_channels = AsyncMock(return_value=[ChannelGroupInfo.from_api({
            "id": "group", "name": "分组", "channels": [
                {"id": "text", "name": "文字", "type": "TEXT", "secret": True},
                {"id": "voice", "name": "语音", "type": "AUDIO"},
            ],
        })])
        self.bot.channels.get_channel_setting_info = AsyncMock(return_value=ChannelSetting.from_api({
            "channel": "text", "secret": True, "accessibleMembers": ["member", "missing"],
        }))
        self.bot.person.get_person_infos_batch = AsyncMock(return_value=[UserInfo.from_api({
            "uid": "member", "name": "SDK名称", "avatar": "avatar",
        })])
        self.bot.channels.get_voice_channel_members = AsyncMock(return_value=VoiceChannelMembersResult.from_api({
            "channelMembers": {"voice": [{"uid": "member"}, {"uid": "missing"}]},
        }))
        resolver = Mock()
        resolver.user_cached.side_effect = lambda uid, **kwargs: "人工名称" if uid == "member" else ""
        _channels._channels_cache.invalidate()
        self.addCleanup(_channels._channels_cache.invalidate)
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_channels, "get_resolver", return_value=resolver),
        ):
            channels = json.loads(bytes((await _channels.admin_channels_list("area")).body))["channels"]
            self.assertEqual(channels[0], {"id": "text", "name": "文字", "group": "分组", "type": "TEXT", "secret": True})
            settings = json.loads(bytes((await _channels.admin_channel_settings("text", "area")).body))["settings"]
            self.assertEqual(settings["accessibleMembers"], ["member", "missing"])
            accessible = json.loads(bytes((await _channels.admin_channel_accessible_members("text")).body))["members"]
            expected = [
                {"uid": "member", "name": "人工名称", "avatar": "avatar"},
                {"uid": "missing", "name": "missing", "avatar": ""},
            ]
            self.assertEqual(accessible, expected)
            voices = json.loads(bytes((await _channels.admin_voice_channels("area")).body))["voice_channels"]
            self.assertEqual(voices, [{"id": "voice", "name": "语音", "group": "分组", "users": expected}])
            self.bot.person.get_person_infos_batch.side_effect = RuntimeError("网络错误")
            failed = await _channels.admin_channel_accessible_members("text")
            self.assertEqual(failed.status_code, 502)
            voices = json.loads(bytes((await _channels.admin_voice_channels("area")).body))["voice_channels"]
            self.assertEqual(len(voices[0]["users"]), 2)
            self.assertEqual(voices[0]["users"][0]["name"], "人工名称")

    async def test_default_area_and_invite_membership_use_area_models(self):
        from web.admin.members._area_invites import _resolve_invite
        from web.admin.shared import _area

        query = AsyncMock(return_value=[AreaInfo.model_validate({"id": "area", "name": "测试域"})])
        self.bot.areas.get_joined_areas = query
        with (
            patch.object(_area.cfg, "OOPZ_CONFIG", {}),
            patch.object(_area, "_resolved_area_cache", {"value": "", "ts": 0.0}),
            patch.object(_area, "_get_sender", return_value=self.sender),
        ):
            self.assertEqual(await _area._resolve_area_async(), "area")
            self.assertEqual(await _area._resolve_area_async(), "area")
            query.assert_awaited_once()
        self.sender.get_area_invite_detail = AsyncMock(return_value={
            "area": "area", "status": "INVITE_NORMAL", "isAreaInvite": True,
        })
        _, invite = await _resolve_invite(self.sender, "abcdef")
        self.assertTrue(invite["joined"])
        self.assertFalse(invite["canAccept"])

    async def test_role_edit_preserves_sdk_exception_and_rejected_result(self):
        error = OopzApiError("没有权限", status_code=403)
        rejected = OperationResult(ok=False, message="拒绝")
        self.bot.areas.edit_user_role = AsyncMock(side_effect=[error, rejected])
        members_response_cache.set("area:0:50", {"role": 1})
        with self.assertRaises(OopzApiError) as caught:
            await self.sender.edit_user_role("member", 2, True, area="area")
        self.assertIs(caught.exception, error)
        result = await self.sender.edit_user_role("member", 2, True, area="area")
        self.assertIs(result, rejected)
        self.assertIsNotNone(members_response_cache.get("area:0:50"))

    async def test_web_role_failures_return_502_without_success_cache_clear(self):
        self.bot.areas.edit_user_role = AsyncMock(side_effect=[
            OopzApiError("没有权限"), OperationResult(ok=False, message="拒绝"),
        ])
        with (
            patch("web.web_player.get_sender", return_value=self.sender),
            patch.object(_members, "read_json_body", AsyncMock(return_value={"area": "area", "role_id": 2})),
        ):
            for _ in range(2):
                members_response_cache.set("area:0:50", {"role": 1})
                response = await _members.admin_member_role("member", Request({"type": "http"}))
                self.assertEqual(response.status_code, 502)
                self.assertFalse(json.loads(bytes(response.body))["ok"])
                self.assertIsNotNone(members_response_cache.get("area:0:50"))

    async def test_member_query_failure_is_502_and_not_cached(self):
        self.bot.areas.get_area_members = AsyncMock(side_effect=[OopzApiError("请求失败"), AreaMembersPage()])
        self.bot.areas.get_area_info = AsyncMock(return_value=AreaInfo())
        with patch.object(_members, "_get_sender", return_value=self.sender):
            response = await _members.admin_members_list(offset=0, limit=50, keyword="", area="area")
            self.assertEqual(response.status_code, 502)
            self.assertIsNone(members_response_cache.get("area:0:50"))
            response = await _members.admin_members_list(offset=0, limit=50, keyword="", area="area")
        self.assertTrue(json.loads(bytes(response.body))["ok"])

    async def test_member_statistics_come_from_sdk_model(self):
        self.bot.areas.get_area_members = AsyncMock(return_value=AreaMembersPage.from_api({
            "members": [{"uid": "member", "online": 1}], "totalCount": 201,
            "roleCount": [{"role": -1, "count": 190}, {"role": 1, "count": 11}],
        }))
        self.bot.areas.get_area_info = AsyncMock(return_value=AreaInfo())
        self.bot.person.get_person_infos_batch = AsyncMock(return_value=[])
        with patch.object(_members, "_get_sender", return_value=self.sender):
            response = await _members.admin_members_list(offset=0, limit=50, keyword="", area="area")
        data = json.loads(bytes(response.body))
        self.assertEqual((data["total"], data["online"]), (201, 11))

    async def test_online_member_after_first_200_is_included(self):
        async def query(_method, _path, *, params, **_kwargs):
            start, end = int(params["offsetStart"]), int(params["offsetEnd"])
            return {"totalCount": 201, "members": [
                {"uid": f"u{i}", "online": int(i == 200)} for i in range(start, min(end + 1, 201))
            ]}
        self.bot.areas._request_data_with_retry = AsyncMock(side_effect=query)
        self.bot.person.get_person_infos_batch = AsyncMock(return_value=[UserInfo(uid="u200", name="在线用户")])
        with patch("web.web_player.get_sender", return_value=self.sender):
            response = await _channels.admin_online_members("area")
        self.assertEqual([m["uid"] for m in json.loads(bytes(response.body))["members"]], ["u200"])
        self.assertEqual(self.bot.areas._request_data_with_retry.await_count, 3)

    async def test_lookup_failure_propagates_and_commands_report_query_failure(self):
        self.bot.areas.get_all_area_members = AsyncMock(side_effect=OopzApiError("请求失败"))
        resolver = Mock()
        resolver.find_uid_by_name.return_value = None
        target = self.runtime.services.community.target_resolution
        with patch("app.services.community.target_resolution_service.get_resolver", return_value=resolver):
            with self.assertRaises(OopzApiError):
                await target.resolve_target("小明", "area")
            await ModerationCommandActions(self.runtime).mute_user("小明 10", "channel", "area", "用法")
            await RoleService(self.runtime).show_user_roles("小明", "channel", "area")
            await MemberService(self.runtime).show_whois("小明", "channel", "area")
        self.assertEqual(self.send.await_count, 3)
        for call in self.send.await_args_list:
            self.assertIn("查询成员失败", call.args[0])
            self.assertNotIn("找不到用户", call.args[0])
        self.runtime.services.safety.moderation.mute_user.assert_not_awaited()

    async def test_snapshot_honors_non_page_aligned_cap_and_reads_fresh_data(self):
        query = AsyncMock(side_effect=[
            AreaMembersPage.from_api({"members": [{"uid": str(i)} for i in range(100)], "totalCount": 200}),
            AreaMembersPage.from_api({"members": [{"uid": str(i)} for i in range(100, 150)], "totalCount": 200}),
        ])
        self.bot.areas.get_area_members = query
        uids, delay, truncated = await fetch_member_uid_snapshot(self.sender, "area", member_fetch_max=150)
        self.assertEqual(len(uids or []), 150)
        self.assertTrue(truncated)
        self.assertEqual(delay, 0)
        query.assert_awaited_with(area="area", offset_start=100, offset_end=149, force=True)

    async def test_poll_honors_typed_rate_limit_without_429_text_and_recovers(self):
        for source in ("operate_logs", "member_snapshot"):
            with self.subTest(source=source):
                self.bot.areas.get_area_operate_logs = AsyncMock(side_effect=[
                    OopzRateLimitError("请求过于频繁", retry_after=75), [],
                ])
                self.bot.areas.get_area_members = AsyncMock(side_effect=[
                    OopzRateLimitError("请求过于频繁", retry_after=75), AreaMembersPage(),
                ])
                registry = Mock()
                registry.get_all_area_ids.return_value = ["area"]
                registry.get.return_value = AreaConfig("area", default_channel="channel")
                delays = []
                stop = asyncio.Event()

                async def wait(event, seconds, captured_delays=delays):
                    captured_delays.append(seconds)
                    if len(captured_delays) == 2:
                        event.set()

                with (
                    patch("core.area_config.get_area_registry", return_value=registry),
                    patch("services.area_join_notifier._wait_or_stop", side_effect=wait),
                ):
                    await _run_join_poll_loop(self.sender, "欢迎 {name}", 5, "bot", event_source=source, stop_event=stop)
                self.assertEqual(delays, [75, 5])
                self.send.assert_not_awaited()
