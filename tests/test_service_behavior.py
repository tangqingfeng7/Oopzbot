import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


from oopz_sdk.models import (  # noqa: E402
    AreaMemberInfo,
    AreaUserDetail,
    OperationResult,
    Profile,
    RoleInfo,
    UserInfo,
)
from oopz_sdk.models.channel import VoiceChannelMembersResult  # noqa: E402
from oopz_sdk.models.general import DailySpeech  # noqa: E402

from app.services.runtime import CommandRuntimeView  # noqa: E402


def _runtime(**components: object) -> CommandRuntimeView:
    """把每个用例需要的最小运行时切片标记为服务协议测试桩。"""

    return cast(CommandRuntimeView, SimpleNamespace(**components))


class CommandAccessServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plugins = Mock()
        self.plugins.load = AsyncMock()
        self.plugins.load_all = AsyncMock()
        self.plugins.reload_config = AsyncMock()
        self.plugins.stop = AsyncMock()
        self.plugins.try_dispatch_mention = AsyncMock()
        self.plugins.try_dispatch_slash = AsyncMock()
        self.plugins.unload = AsyncMock()
        # 裸 Mock 的任意方法都返回真值；这两个是「拦截」语义，默认必须为假
        self.plugins.has_admin_only_mention_prefix.return_value = False
        self.plugins.has_admin_only_slash_command.return_value = False
        self.runtime = _runtime(plugins=self.plugins, bot_mention="(met)bot(met)")

    def test_is_admin_is_fail_closed_when_admin_list_empty(self) -> None:
        # 空名单曾被当作「所有人都是管理员」——那是首启默认态，
        # 等于装好即全员可用禁言/封禁/撤回/插件管理
        import app.services.routing.command_access_service as module

        with patch.object(module, "ADMIN_UIDS", []):
            self.assertFalse(module.CommandAccessService.is_admin("user-1"))
            self.assertFalse(module.CommandAccessService.has_configured_admins())

    def test_is_admin_checks_membership_when_admin_list_present(self) -> None:
        import app.services.routing.command_access_service as module

        with patch.object(module, "ADMIN_UIDS", ["admin-1"]):
            self.assertTrue(module.CommandAccessService.is_admin("admin-1"))
            self.assertFalse(module.CommandAccessService.is_admin("user-1"))

    def test_public_mention_prefers_domain_rule(self) -> None:
        from app.services.routing.command_access_service import CommandAccessService

        service = CommandAccessService(self.runtime)

        self.assertTrue(service.is_public_command("(met)bot(met) 帮助"))
        self.plugins.has_public_mention_prefix.assert_not_called()

    def test_public_mention_can_fallback_to_plugin_capability(self) -> None:
        import app.services.routing.command_access_service as module

        service = module.CommandAccessService(self.runtime)
        self.plugins.has_public_mention_prefix.return_value = True

        with patch.object(module, "is_public_mention_text", return_value=False):
            self.assertTrue(service.is_public_command("(met)bot(met) 插件命令"))

        self.plugins.has_public_mention_prefix.assert_called_once_with("插件命令")

    def test_public_slash_can_fallback_to_plugin_capability(self) -> None:
        import app.services.routing.command_access_service as module

        service = module.CommandAccessService(self.runtime)
        self.plugins.has_public_slash_command.return_value = True

        with patch.object(module, "is_public_slash_command", return_value=False):
            self.assertTrue(service.is_public_command("/plugin-demo arg"))

        self.plugins.has_public_slash_command.assert_called_once_with("/plugin-demo")

    def test_admin_membership_still_checked_when_list_present(self) -> None:
        import app.services.routing.command_access_service as module

        with patch.object(module, "ADMIN_UIDS", ["admin-1"]):
            self.assertTrue(module.CommandAccessService.has_configured_admins())
            self.assertTrue(module.CommandAccessService.is_admin("admin-1"))
            self.assertFalse(module.CommandAccessService.is_admin("user-1"))

    def test_plugin_declared_admin_only_mention_is_not_public(self) -> None:
        # 内置管理名单只覆盖内置命令；插件声明的 is_public_command=False
        # 若不在这里拦住，闸门会因为内置名单没命中而直接放行
        from app.services.routing.command_access_service import CommandAccessService

        service = CommandAccessService(self.runtime)
        self.plugins.has_admin_only_mention_prefix.return_value = True

        self.assertFalse(service.is_public_command("(met)bot(met) 签到"))
        self.plugins.has_public_mention_prefix.assert_not_called()

    def test_plugin_declared_admin_only_slash_is_not_public(self) -> None:
        from app.services.routing.command_access_service import CommandAccessService

        service = CommandAccessService(self.runtime)
        self.plugins.has_admin_only_slash_command.return_value = True

        self.assertFalse(service.is_public_command("/checkin"))
        self.plugins.has_public_slash_command.assert_not_called()


class RoleServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.target_resolution = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                community=SimpleNamespace(target_resolution=self.target_resolution),
            ),
        )

    async def test_give_role_delegates_edit_when_role_resolves(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.bot.areas.get_area_can_give_list.return_value = [
            RoleInfo(roleID=7, name="成员"),
        ]
        self.sender.edit_user_role.return_value = OperationResult(message="ok")

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            await service.give_role("@user", "成员", "channel-1", "area-1")

        self.sender.edit_user_role.assert_called_once_with("user-1", 7, add=True, area="area-1")
        self.sender.send_message.assert_called_once()

    async def test_give_role_reports_unknown_role_without_edit(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.bot.areas.get_area_can_give_list.return_value = [
            RoleInfo(roleID=7, name="成员"),
        ]

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            await service.give_role("@user", "不存在", "channel-1", "area-1")

        self.sender.edit_user_role.assert_not_called()
        self.sender.send_message.assert_called_once()

    async def test_remove_role_delegates_edit_when_role_resolves(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.bot.areas.get_area_user_detail.return_value = AreaUserDetail.from_api({
            "list": [{"roleID": 9, "name": "管理员"}],
        })
        self.sender.edit_user_role.return_value = OperationResult(message="ok")

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            await service.remove_role("@user", "管理员", "channel-1", "area-1")

        self.sender.edit_user_role.assert_called_once_with("user-1", 9, add=False, area="area-1")
        self.sender.send_message.assert_called_once()

    async def test_show_assignable_roles_reports_missing_target(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = None

        service = RoleService(self.handler)
        await service.show_assignable_roles("@missing", "channel-1", "area-1")

        self.sender.bot.areas.get_area_can_give_list.assert_not_called()

    async def test_show_roles_formats_sdk_string_mute_deadlines(self) -> None:
        import datetime

        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.bot.areas.get_area_user_detail.return_value = AreaUserDetail.from_api({
            "list": [{"roleID": 7, "name": "成员"}],
            "disableTextTo": "1800000000000", "disableVoiceTo": "1800000060000",
        })
        await RoleService(self.handler).show_user_roles("用户", "channel", "area")
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("成员 (ID=7)", message)
        for label, seconds in (("禁言至", 1800000000), ("禁麦至", 1800000060)):
            self.assertIn(f"{label}: {datetime.datetime.fromtimestamp(seconds):%Y-%m-%d %H:%M}", message)

    async def test_rejected_role_change_is_reported_as_failure(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.bot.areas.get_area_can_give_list.return_value = [RoleInfo(roleID=7, name="成员")]
        self.sender.edit_user_role.return_value = OperationResult(ok=False, message="没有权限")
        await RoleService(self.handler).give_role("用户", "7", "channel", "area")
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("添加身份组失败", message)
        self.assertIn("没有权限", message)
        self.sender.send_message.assert_called_once()


class MemberServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.target_resolution = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                community=SimpleNamespace(target_resolution=self.target_resolution),
            ),
        )

    async def test_show_members_stops_on_sender_error(self) -> None:
        from app.services.community.member_service import MemberService

        self.sender.bot.areas.get_all_area_members.side_effect = RuntimeError("网络错误")

        service = MemberService(self.handler)
        await service.show_members("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("失败", self.sender.send_message.call_args.args[0])

    async def test_show_members_aggregates_unique_members(self) -> None:
        from app.services.community.member_service import MemberService

        self.sender.bot.areas.get_all_area_members.return_value = [
            AreaMemberInfo.model_validate({"uid": "u1", "online": 1, "playingState": "游戏中"}),
            AreaMemberInfo.model_validate({"uid": "u2", "online": 0}),
            AreaMemberInfo.model_validate({"uid": "u1", "online": 1, "playingState": "游戏中"}),
        ]

        with patch("app.services.community.member_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.user.side_effect = lambda uid: {"u1": "用户1", "u2": "用户2"}.get(uid, uid)
            resolver.ensure_users = AsyncMock(return_value={"u1": "用户1", "u2": "用户2"})

            service = MemberService(self.handler)
            await service.show_members("channel-1", "area-1")

        self.sender.bot.areas.get_all_area_members.assert_awaited_once_with("area-1", page_size=100, max_pages=5)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("总计 2", message)
        self.assertIn("在线 1", message)

    async def test_show_whois_reports_missing_target(self) -> None:
        from app.services.community.member_service import MemberService

        self.target_resolution.resolve_target.return_value = None

        service = MemberService(self.handler)
        await service.show_whois("@missing", "channel-1", "area-1")

        self.sender.bot.person.get_person_detail_full.assert_not_called()
        self.sender.send_message.assert_called_once()


    async def test_profiles_display_sdk_fields(self) -> None:
        from app.services.community.member_service import MemberService

        service = MemberService(self.handler)
        self.sender.bot.person.get_person_info.return_value = UserInfo.from_api({
            "uid": "user", "name": "名字", "online": True, "introduction": "简介内容",
            "personType": "NORMAL", "avatar": "https://example.test/avatar", "badges": [{"name": "徽章"}],
        })
        await service.show_profile("channel", "area", "user")
        text = self.sender.send_message.call_args.args[0]
        for expected in ("个人信息 - 名字", "状态: 在线", "简介内容", "类型: NORMAL", "徽章: 1 个"):
            self.assertIn(expected, text)

        self.sender.bot.person.get_person_detail_full.return_value = Profile.from_api({
            "uid": "user", "name": "名字", "online": False, "ipAddress": "上海",
            "personVIPEndTime": "1800000000000", "playingState": "游戏中",
            "badges": [{"name": "徽章"}], "avatar": "https://example.test/avatar",
        })
        for method, args, title in [
            (service.show_myinfo, ("channel", "area", "user"), "我的详细资料"),
            (service._show_whois_by_uid, ("user", "channel", "area"), "用户资料"),
        ]:
            with self.subTest(method=title):
                await method(*args)
                text = self.sender.send_message.call_args.args[0]
                for expected in (title, "状态: 离线", "IP属地: 上海", "VIP到期:", "徽章(1): 徽章"):
                    self.assertIn(expected, text)
        self.assertIn("正在玩: 游戏中", text)
        self.assertIn("头像: https://example.test/avatar", text)

    async def test_member_search_preserves_name_mapping_and_selection(self) -> None:
        from app.services.community.member_service import MemberService

        self.sender.search_area_members.return_value = [AreaMemberInfo(uid="user")]
        selection = Mock()
        with (
            patch("app.services.community.member_service.get_resolver") as get_resolver,
            patch.object(MemberService, "_selection_service", return_value=selection),
        ):
            resolver = get_resolver.return_value
            resolver.ensure_users = AsyncMock()
            resolver.user.return_value = "人工名称"
            await MemberService(self.handler).search_members("名字", "channel", "area", "requester")
        self.assertIn("人工名称", self.sender.send_message.call_args.args[0])
        self.assertEqual(selection.store.call_args.kwargs["items"], [{"uid": "user", "name": "人工名称"}])
        resolver.ensure_users.assert_awaited_once_with(["user"])


class TargetResolutionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.runtime = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
        )

    async def test_resolve_target_returns_unique_prefix_match_in_area(self) -> None:
        from app.services.community.target_resolution_service import TargetResolutionService

        self.sender.bot.areas.get_all_area_members.return_value = [
            SimpleNamespace(uid="user-1"), SimpleNamespace(uid="user-2"),
        ]

        service = TargetResolutionService(self.runtime)
        with patch("app.services.community.target_resolution_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.find_uid_by_name.return_value = None
            resolver.ensure_users = AsyncMock(return_value={"user-1": "皇帝", "user-2": "小明"})
            resolver.user_cached.side_effect = lambda uid: {"user-1": "皇帝", "user-2": "小明"}.get(uid, "")

            uid = await service.resolve_target("皇", area="area-1")

        self.assertEqual(uid, "user-1")
        self.sender.bot.areas.get_all_area_members.assert_called_once_with("area-1", page_size=100, max_pages=10)
        resolver.ensure_users.assert_called_once_with(["user-1", "user-2"])

    async def test_resolve_target_rejects_ambiguous_matches_in_area(self) -> None:
        from app.services.community.target_resolution_service import TargetResolutionService

        self.sender.bot.areas.get_all_area_members.return_value = [
            SimpleNamespace(uid="user-1"), SimpleNamespace(uid="user-2"),
        ]

        service = TargetResolutionService(self.runtime)
        with patch("app.services.community.target_resolution_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.find_uid_by_name.return_value = None
            resolver.ensure_users = AsyncMock(return_value={"user-1": "皇帝", "user-2": "皇后"})
            resolver.user_cached.side_effect = lambda uid: {"user-1": "皇帝", "user-2": "皇后"}.get(uid, "")

            uid = await service.resolve_target("皇", area="area-1")

        self.assertIsNone(uid)


class ModerationCommandActionsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.target_resolution = AsyncMock()
        self.moderation = AsyncMock()
        self.runtime = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                community=SimpleNamespace(target_resolution=self.target_resolution),
                safety=SimpleNamespace(moderation=self.moderation),
            ),
        )

    async def test_mute_user_reports_missing_target_instead_of_usage(self) -> None:
        from app.services.routing.builtin_command_actions import ModerationCommandActions

        self.target_resolution.parse_mute_args.return_value = (None, 10)

        actions = ModerationCommandActions(self.runtime)
        await actions.mute_user("皇 10", "channel-1", "area-1", "用法: @bot 禁言 谁 10")

        self.moderation.mute_user.assert_not_called()
        self.sender.send_message.assert_called_once_with("找不到用户: 皇", channel="channel-1", area="area-1")

    async def test_mute_user_still_reports_usage_when_target_is_empty(self) -> None:
        from app.services.routing.builtin_command_actions import ModerationCommandActions

        self.target_resolution.parse_mute_args.return_value = (None, 10)

        actions = ModerationCommandActions(self.runtime)
        await actions.mute_user("   ", "channel-1", "area-1", "用法: @bot 禁言 谁 10")

        self.sender.send_message.assert_called_once_with("用法: @bot 禁言 谁 10", channel="channel-1", area="area-1")




class RecallServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from app.services.runtime import RecentMessageStore

        self.sender = AsyncMock()
        self.message_lookup = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                safety=SimpleNamespace(message_lookup=self.message_lookup),
            ),
            recent_messages=RecentMessageStore(),
        )

    async def test_recall_message_reports_empty_recent_messages(self) -> None:
        from app.services.safety.recall_service import RecallService

        service = RecallService(self.handler)
        await service.recall_message(None, "channel-1", "area-1")

        self.sender.bot.messages.recall_message.assert_not_called()
        self.sender.send_message.assert_called_once()

    async def test_recall_message_uses_latest_message_in_same_channel(self) -> None:
        from app.services.safety.recall_service import RecallService

        self.handler.recent_messages.replace([
            {"messageId": "old", "channel": "channel-2", "area": "area-1", "content": "旧消息", "timestamp": "ts-old"},
            {"messageId": "new", "channel": "channel-1", "area": "area-1", "content": "新消息", "timestamp": "ts-new"},
        ])
        self.message_lookup.resolve_timestamp.return_value = "resolved-ts"
        self.sender.bot.messages.recall_message.return_value = OperationResult()

        service = RecallService(self.handler)
        await service.recall_message("last", "channel-1", "area-1")

        self.message_lookup.resolve_timestamp.assert_called_once_with("new", "channel-1", "area-1")
        self.sender.bot.messages.recall_message.assert_called_once_with("new", area="area-1", channel="channel-1", timestamp="resolved-ts")
        self.sender.send_message.assert_called_once()

    async def test_recall_multiple_rejects_invalid_count(self) -> None:
        from app.services.safety.recall_service import RecallService

        service = RecallService(self.handler)
        await service.recall_multiple(0, "channel-1", "area-1")

        self.sender.bot.messages.recall_message.assert_not_called()
        self.sender.send_message.assert_called_once()

    async def test_configure_auto_recall_can_enable_and_disable(self) -> None:
        import app.services.safety.recall_service as module

        service = module.RecallService(self.handler)
        config = {"enabled": False, "delay": 30}

        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            await service.configure_auto_recall("开 15", "channel-1", "area-1")
            self.assertTrue(config["enabled"])
            self.assertEqual(config["delay"], 15)

            await service.configure_auto_recall("关", "channel-1", "area-1")
            self.assertFalse(config["enabled"])

        self.assertEqual(self.sender.send_message.call_count, 2)


class MessageRecallSchedulerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.runtime = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender)
        )

    async def test_schedules_recall_on_single_worker(self) -> None:
        import asyncio
        import time

        import app.services.safety.message_recall_scheduler as module

        config = {"enabled": True, "delay": 0.01, "max_pending": 10}
        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            service = module.MessageRecallScheduler(self.runtime)
            try:
                await service.schedule_user_message_recall("msg-1", "channel-1", "area-1", "ts-1")
                # 调度器已是 asyncio 的，忙等必须让出循环，否则被等的任务永远跑不到
                deadline = time.time() + 1.0
                while time.time() < deadline and not self.sender.bot.messages.recall_message.called:
                    await asyncio.sleep(0.01)

                self.sender.bot.messages.recall_message.assert_called_once_with(
                    message_id="msg-1",
                    area="area-1",
                    channel="channel-1",
                    timestamp="ts-1",
                )
            finally:
                await service.stop()

    async def test_pending_limit_skips_extra_tasks(self) -> None:
        import app.services.safety.message_recall_scheduler as module

        config = {"enabled": True, "delay": 30, "max_pending": 1}
        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            service = module.MessageRecallScheduler(self.runtime)
            try:
                await service.schedule_user_message_recall("msg-1", "channel-1", "area-1")
                await service.schedule_user_message_recall("msg-2", "channel-1", "area-1")

                self.assertEqual(await service.cancel_all(), 1)
                self.sender.bot.messages.recall_message.assert_not_called()
            finally:
                await service.stop()

    async def test_schedule_after_stop_does_not_restart_worker(self) -> None:
        import app.services.safety.message_recall_scheduler as module

        config = {"enabled": True, "delay": 30, "max_pending": 10}
        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            service = module.MessageRecallScheduler(self.runtime)
            await service.stop()
            await service.schedule_user_message_recall(
                "late-message",
                "channel-1",
                "area-1",
            )

        self.assertIsNone(service._worker)
        self.assertEqual(await service.cancel_all(), 0)

    async def test_explicit_schedule_uses_same_bounded_worker(self) -> None:
        import app.services.safety.message_recall_scheduler as module

        config = {"enabled": True, "delay": 30, "max_pending": 1}
        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            service = module.MessageRecallScheduler(self.runtime)
            try:
                self.assertTrue(
                    await service.schedule_recall(
                        "bot-message",
                        "channel-1",
                        "area-1",
                        delay=30,
                    )
                )
                self.assertFalse(
                    await service.schedule_recall(
                        "overflow",
                        "channel-1",
                        "area-1",
                        delay=30,
                    )
                )
                self.assertEqual(await service.cancel_all(), 1)
            finally:
                await service.stop()


class ModerationServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.sender.bot.areas.cache = Mock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
        )

    async def test_mute_user_sends_success_message(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.bot.moderation.mute_user.return_value = OperationResult(message="已禁言 测试用户")

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            await service.mute_user("user-1", 10, "channel-1", "area-1")

        self.sender.bot.moderation.mute_user.assert_called_once_with("area-1", "user-1", duration=10)
        self.assertIn("[ok]", self.sender.send_message.call_args.args[0])

    async def test_unmute_user_sends_error_message(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.bot.moderation.unmute_user.side_effect = RuntimeError("权限不足")

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            await service.unmute_user("user-1", "channel-1", "area-1")

        self.sender.bot.moderation.unmute_user.assert_called_once_with("area-1", "user-1")
        self.assertIn("[x]", self.sender.send_message.call_args.args[0])
        self.assertIn("权限不足", self.sender.send_message.call_args.args[0])

    async def test_remove_from_area_delegates_to_sender(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.bot.moderation.remove_from_area.return_value = OperationResult(message="已移出域 测试用户")

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            await service.remove_from_area("user-1", "channel-1", "area-1")

        self.sender.bot.moderation.remove_from_area.assert_called_once_with("area-1", "user-1")
        self.assertIn("[ok]", self.sender.send_message.call_args.args[0])

    async def test_show_block_list_reports_empty_list(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.bot.moderation.get_area_blocks.return_value = []

        with patch("app.services.safety.moderation_service.get_resolver") as get_resolver:
            get_resolver.return_value.area.return_value = "测试区域"

            service = ModerationService(self.handler)
            await service.show_block_list("channel-1", "area-1")

        self.assertIn("当前无封禁用户", self.sender.send_message.call_args.args[0])

    async def test_show_block_list_formats_entries(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.bot.moderation.get_area_blocks.return_value = [
            UserInfo(uid='user-1234567890'), UserInfo(uid='user-abcdef1234'),
        ]

        with patch("app.services.safety.moderation_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.user.side_effect = lambda uid: {"user-1234567890": "用户甲", "user-abcdef1234": "用户乙"}.get(uid, "")

            service = ModerationService(self.handler)
            await service.show_block_list("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("测试区域 - 封禁列表", message)
        self.assertIn("用户甲", message)
        self.assertIn("用户乙", message)


class HelpServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from domain.plugins.base import PluginCommandCapabilities, PluginDescriptor, PluginMetadata

        self.sender = AsyncMock()
        self.plugins = Mock()
        self.plugins.load = AsyncMock()
        self.plugins.load_all = AsyncMock()
        self.plugins.reload_config = AsyncMock()
        self.plugins.stop = AsyncMock()
        self.plugins.try_dispatch_mention = AsyncMock()
        self.plugins.try_dispatch_slash = AsyncMock()
        self.plugins.unload = AsyncMock()
        self.access = Mock()
        self.plugin_descriptor_cls = PluginDescriptor
        self.plugin_metadata_cls = PluginMetadata
        self.plugin_capabilities_cls = PluginCommandCapabilities
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender, plugins=self.plugins),
            services=SimpleNamespace(
                routing=SimpleNamespace(access=self.access),
            ),
        )

    async def test_show_help_for_normal_user_filters_plugin_caps(self) -> None:
        from app.services.interaction.help_service import HelpService

        self.access.is_admin.return_value = False
        self.plugins.list_command_descriptors.return_value = [
            self.plugin_descriptor_cls(
                metadata=self.plugin_metadata_cls(name="demo", description="demo"),
                capabilities=self.plugin_capabilities_cls(
                    mention_prefixes=("测试", "测试二"),
                    slash_commands=("/demo", "/demo2"),
                    is_public_command=True,
                ),
            ),
        ]

        service = HelpService(self.handler)
        await service.show_help("channel-1", "area-1", user="user-1")

        self.plugins.list_command_descriptors.assert_called_once_with(public_only=True)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("普通用户", message)
        self.assertIn("demo", message)
        self.assertIn("@bot 测试 / 测试二  |  /demo / /demo2", message)
        self.assertEqual(self.sender.send_message.call_args.kwargs["styleTags"], ["IMPORTANT"])

    async def test_show_help_for_admin_includes_admin_sections(self) -> None:
        from app.services.interaction.help_service import HelpService

        self.access.is_admin.return_value = True
        self.plugins.list_command_descriptors.return_value = []

        service = HelpService(self.handler)
        await service.show_help("channel-1", "area-1", user="admin-1")

        self.plugins.list_command_descriptors.assert_called_once_with(public_only=False)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("管理员", message)
        self.assertIn("插件扩展", message)
        self.assertIn("管理操作", message)


    async def test_show_help_can_render_topic_view(self) -> None:
        from app.services.interaction.help_service import HelpService

        self.access.is_admin.return_value = False
        self.plugins.list_command_descriptors.return_value = []

        service = HelpService(self.handler)
        await service.show_help("channel-1", "area-1", user="user-1", topic="音乐")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("帮助 - 音乐", message)
        self.assertIn("选歌", message)


class PluginManagementServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from domain.plugins.base import PluginCommandCapabilities, PluginDescriptor, PluginMetadata

        self.sender = AsyncMock()
        self.plugins = Mock()
        self.plugins.load = AsyncMock()
        self.plugins.load_all = AsyncMock()
        self.plugins.reload_config = AsyncMock()
        self.plugins.stop = AsyncMock()
        self.plugins.try_dispatch_mention = AsyncMock()
        self.plugins.try_dispatch_slash = AsyncMock()
        self.plugins.unload = AsyncMock()
        self.plugin_descriptor_cls = PluginDescriptor
        self.plugin_metadata_cls = PluginMetadata
        self.plugin_capabilities_cls = PluginCommandCapabilities
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender, plugins=self.plugins),
            plugin_host=object(),
        )

    async def test_show_plugin_list_splits_loaded_and_available(self) -> None:
        from app.services.plugins.plugin_management_service import PluginManagementService

        self.plugins.list_descriptors.return_value = [
            self.plugin_descriptor_cls(
                metadata=self.plugin_metadata_cls(name="loaded_a", description="内置模块"),
                capabilities=self.plugin_capabilities_cls(
                    mention_prefixes=("测试",),
                    slash_commands=("/demo",),
                    is_public_command=True,
                ),
                builtin=True,
            ),
        ]
        self.plugins.discover.return_value = ["loaded_a", "extra_b"]

        service = PluginManagementService(self.handler)
        await service.show_plugin_list("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("已加载: 1", message)
        self.assertIn("可加载: 1", message)
        self.assertIn("loaded_a", message)
        self.assertIn("命令: @bot 测试  |  /demo", message)
        self.assertIn("extra_b", message)

    async def test_load_rejects_invalid_plugin_name(self) -> None:
        import app.services.plugins.plugin_management_service as module

        with patch.object(module, "normalize_plugin_name", return_value=None):
            service = module.PluginManagementService(self.handler)
            await service.load("bad name!", "channel-1", "area-1")

        self.plugins.load.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("不合法", self.sender.send_message.call_args.args[0])

    async def test_load_delegates_to_plugin_runtime(self) -> None:
        import app.services.plugins.plugin_management_service as module
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        self.plugins.load.return_value = PluginOperationResult.success(
            "已加载 demo",
            plugin_name="demo",
            code=cast(PluginOperationCode, PluginOperationCode.SUCCESS),
        )
        with patch.object(module, "normalize_plugin_name", return_value="demo"):
            service = module.PluginManagementService(self.handler)
            await service.load("demo.py", "channel-1", "area-1")

        self.plugins.load.assert_called_once_with("demo", handler=self.handler.plugin_host)
        self.assertEqual(self.sender.send_message.call_args.args[0], "[ok] 已加载: demo")

    async def test_unload_delegates_to_plugin_runtime(self) -> None:
        import app.services.plugins.plugin_management_service as module
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        self.plugins.unload.return_value = PluginOperationResult.failure(
            "卸载失败",
            plugin_name="demo",
            code=cast(PluginOperationCode, PluginOperationCode.NOT_LOADED),
        )
        with patch.object(module, "normalize_plugin_name", return_value="demo"):
            service = module.PluginManagementService(self.handler)
            await service.unload("demo.py", "channel-1", "area-1")

        self.plugins.unload.assert_called_once_with("demo", handler=self.handler.plugin_host)
        self.assertEqual(self.sender.send_message.call_args.args[0], "[x] 插件未加载: demo")


class CommonCommandServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.music = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender, music=self.music),
        )

    async def test_show_voice_channels_reports_empty_state(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.sender.bot.channels.get_voice_channel_members.return_value = VoiceChannelMembersResult()

        service = CommonCommandService(self.handler)
        await service.show_voice_channels("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("没有语音频道在线成员", self.sender.send_message.call_args.args[0])

    async def test_show_voice_channels_formats_online_members(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.sender.bot.channels.get_voice_channel_members.return_value = VoiceChannelMembersResult.from_api({
            'channelMembers': {'voice-1': [{'uid': 'u1', 'isBot': False}, {'uid': 'u2', 'isBot': True}]},
        })

        with patch("app.services.interaction.common_command_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.channel.return_value = "语音一厅"
            resolver.user.side_effect = lambda uid: {"u1": "用户1", "u2": "机器人2"}.get(uid, uid)

            service = CommonCommandService(self.handler)
            await service.show_voice_channels("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("测试区域 - 语音频道在线", message)
        self.assertIn("共 2 人在线", message)
        self.assertIn("机器人2 [Bot]", message)

    async def test_daily_speech_formats_sdk_result_and_reports_query_failure(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        service = CommonCommandService(self.handler)
        for payload, expected in [
            ({"words": "一句话", "author": "作者"}, "「一句话」\n—— 作者"),
            ({"words": "一句话"}, "「一句话」"),
            ({}, "暂无内容"),
        ]:
            with self.subTest(payload=payload):
                self.sender.bot.general.get_daily_speech.return_value = DailySpeech.from_api(payload)
                await service.show_daily_speech("channel", "area")
                self.assertEqual(self.sender.send_message.call_args.args[0], expected)
        self.sender.bot.general.get_daily_speech.side_effect = RuntimeError("请求失败")
        await service.show_daily_speech("channel", "area")
        self.assertEqual(self.sender.send_message.call_args.args[0], "获取每日一句失败: 请求失败")



class ChatInteractionServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
        )

    async def test_handle_plain_chat_returns_false_when_no_reply(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        with patch(
            "app.services.interaction.chat_interaction_service.CHAT_CONFIG",
            {"enabled": True, "keyword_replies": {}},
        ):
            service = ChatInteractionService(self.handler)
            result = await service.handle_plain_chat("hello", "channel-1", "area-1")

        self.assertFalse(result)
        self.sender.send_message.assert_not_called()

    async def test_handle_plain_chat_sends_reply_when_available(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        with patch(
            "app.services.interaction.chat_interaction_service.CHAT_CONFIG",
            {"enabled": True, "keyword_replies": {"hello": "自动回复"}},
        ):
            service = ChatInteractionService(self.handler)
            result = await service.handle_plain_chat("hello", "channel-1", "area-1")

        self.assertTrue(result)
        self.sender.send_message.assert_called_once_with("自动回复", channel="channel-1", area="area-1")


    async def test_send_unknown_command_sends_help_hint(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        service = ChatInteractionService(self.handler)
        await service.send_unknown_command("/unknown", "channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("/help", self.sender.send_message.call_args.args[0])


class MusicCommandServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.music = AsyncMock()
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender, music=self.music),
        )

    async def test_handle_mention_play_delegates_with_keyword(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_mention("播放 稻香", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_called_once_with("稻香", "channel-1", "area-1", "user-1")
        self.sender.send_message.assert_not_called()

    async def test_handle_mention_play_without_keyword_sends_usage(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_mention("播放", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("请输入歌名", self.sender.send_message.call_args.args[0])

    async def test_handle_mention_like_list_parses_page(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_mention("喜欢列表 3", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.show_liked_list.assert_called_once_with("channel-1", "area-1", 3)

    async def test_handle_mention_returns_false_for_unknown_text(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_mention("天气不错", "channel-1", "area-1", "user-1")

        self.assertFalse(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_not_called()

    async def test_handle_slash_play_without_keyword_sends_usage(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/play", None, None, ["/play"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("用法: /bf 歌曲名", self.sender.send_message.call_args.args[0])

    async def test_handle_slash_yun_play_delegates_with_arg(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/yun", "play", "晴天", ["/yun", "play", "晴天"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_called_once_with("晴天", "channel-1", "area-1", "user-1")

    async def test_handle_slash_like_list_defaults_to_first_page_when_arg_invalid(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/like", "list", "abc", ["/like", "list", "abc"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.show_liked_list.assert_called_once_with("channel-1", "area-1", 1)

    async def test_handle_slash_like_play_reports_invalid_index(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/like", "play", "abc", ["/like", "play", "abc"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_liked_by_index.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("/like play <编号>", self.sender.send_message.call_args.args[0])

    async def test_handle_slash_like_count_is_clamped(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/like", "99", None, ["/like", "99"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_liked.assert_called_once_with("channel-1", "area-1", "user-1", 20)

    async def test_handle_slash_returns_false_for_non_music_command(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/members", None, None, ["/members"], "channel-1", "area-1", "user-1")

        self.assertFalse(result)
        self.music.play_liked.assert_not_called()
        self.sender.send_message.assert_not_called()


class MusicCommandInteractiveSelectionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.selection = Mock()
        self.music = AsyncMock()
        self.music.supports_interactive_selection = True
        self.music.search_best_candidate.return_value = None
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender, music=self.music),
            services=SimpleNamespace(
                interaction=SimpleNamespace(selection=self.selection),
            ),
        )

    async def test_search_candidates_stores_song_choices(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        self.music.search_candidates.return_value = [
            {"id": 1, "name": "稻香", "artists": "周杰伦", "durationText": "3:42"},
            {"id": 2, "name": "稻香 (Live)", "artists": "周杰伦", "durationText": "4:01"},
        ]

        service = MusicCommandService(self.handler)
        await service.search_candidates("稻香", "channel-1", "area-1", "user-1")

        self.selection.store.assert_called_once()
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("搜歌", message)
        self.assertIn("选择", message)

    async def test_handle_pick_plays_selected_song(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        self.selection.pick.return_value = (
            SimpleNamespace(kind="song", items=[{"id": 1}]),
            {"id": 1, "name": "稻香", "artists": "周杰伦", "platform": "netease"},
        )

        service = MusicCommandService(self.handler)
        result = await service.handle_pick(1, "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_song_choice.assert_called_once_with(
            {"id": 1, "name": "稻香", "artists": "周杰伦", "platform": "netease"},
            "channel-1",
            "area-1",
            "user-1",
        )
        self.selection.clear.assert_called_once_with("user-1", "channel-1", "area-1")

    async def test_handle_slash_play_uses_fast_match_before_candidate_search(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        self.music.search_best_candidate.return_value = {
            "id": 1,
            "name": "稻香",
            "artists": "周杰伦",
            "durationText": "3:42",
        }

        service = MusicCommandService(self.handler)
        result = await service.handle_slash("/bf", None, None, ["/bf", "稻香"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.search_best_candidate.assert_called_once_with("稻香", "netease")
        self.music.play_song_choice.assert_called_once_with(
            {"id": 1, "name": "稻香", "artists": "周杰伦", "durationText": "3:42", "platform": "netease"},
            "channel-1",
            "area-1",
            "user-1",
        )
        self.music.search_candidates.assert_not_called()


class SetupServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.sender = AsyncMock()
        self.plugins = Mock()
        self.plugins.load = AsyncMock()
        self.plugins.load_all = AsyncMock()
        self.plugins.reload_config = AsyncMock()
        self.plugins.stop = AsyncMock()
        self.plugins.try_dispatch_mention = AsyncMock()
        self.plugins.try_dispatch_slash = AsyncMock()
        self.plugins.unload = AsyncMock()
        self.access = Mock()
        self.access.has_configured_admins.return_value = True
        self.handler = _runtime(
            infrastructure=SimpleNamespace(sender=self.sender),
            plugins=self.plugins,
            services=SimpleNamespace(routing=SimpleNamespace(access=self.access)),
        )

    async def test_show_health_check_reports_failures_and_next_steps(self) -> None:
        from app.services.interaction.setup_service import SetupService

        service = SetupService(self.handler)
        fake_report = {
            "status": "fail",
            "summary": {"pass": 2, "warn": 1, "fail": 1, "info": 0},
            "checks": [
                {"level": "fail", "title": "Redis 连接", "summary": "Redis 无法连接"},
                {"level": "warn", "title": "默认域与频道", "summary": "默认域与频道未配置"},
            ],
            "wizard_steps": [],
        }
        with patch.object(service, "build_report", return_value=fake_report):
            await service.show_health_check("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("系统体检", message)
        self.assertIn("Redis 无法连接", message)
        self.assertIn("@bot 首启向导", message)
        self.assertIn("/admin/setup", message)

    async def test_show_setup_wizard_formats_steps(self) -> None:
        from app.services.interaction.setup_service import SetupService

        service = SetupService(self.handler)
        fake_report = {
            "wizard_steps": [
                {
                    "status": "blocked",
                    "title": "设置后台安全与持久化",
                    "description": "先保证密码和写权限可用。",
                    "summary": "后台密码未配置",
                    "actions": ["前往配置中心设置 admin_password"],
                    "page": "/admin/config",
                },
                {
                    "status": "done",
                    "title": "打通基础运行时",
                    "description": "Redis 与数据库已就绪。",
                    "summary": "Redis 连接正常",
                    "actions": [],
                    "page": "/admin/system",
                },
            ]
        }
        with patch.object(service, "build_report", return_value=fake_report):
            await service.show_setup_wizard("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("首启向导", message)
        self.assertIn("设置后台安全与持久化", message)
        self.assertIn("前往配置中心设置 admin_password", message)
        self.assertIn("/health", message)
        # 已配置管理员时不该出现引导段
        self.assertNotIn("尚未配置管理员", message)

    async def _wizard_message(self, user: str) -> str:
        from app.services.interaction.setup_service import SetupService

        service = SetupService(self.handler)
        with patch.object(service, "build_report", return_value={"wizard_steps": []}):
            await service.show_setup_wizard("channel-1", "area-1", user)
        return self.sender.send_message.call_args.args[0]

    async def test_wizard_echoes_caller_uid_when_no_admins_configured(self) -> None:
        # 权限是 fail-closed 的，空名单下所有管理命令不可用；
        # 向导必须回显 UID，否则用户拿不到填进 ADMIN_UIDS 的值
        self.access.has_configured_admins.return_value = False

        message = await self._wizard_message("uid-abc123")

        self.assertIn("尚未配置管理员", message)
        self.assertIn("uid-abc123", message)
        self.assertIn("ADMIN_UIDS", message)

    async def test_wizard_falls_back_when_caller_uid_unknown(self) -> None:
        self.access.has_configured_admins.return_value = False

        message = await self._wizard_message("")

        self.assertIn("尚未配置管理员", message)
        self.assertIn("个人信息", message)




if __name__ == "__main__":
    unittest.main()
