import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


class CommandAccessServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plugins = Mock()
        self.handler = SimpleNamespace(infrastructure=SimpleNamespace(plugins=self.plugins))

    def test_is_admin_allows_anyone_when_admin_list_empty(self) -> None:
        import app.services.routing.command_access_service as module

        with patch.object(module, "ADMIN_UIDS", []):
            self.assertTrue(module.CommandAccessService.is_admin("user-1"))

    def test_is_admin_checks_membership_when_admin_list_present(self) -> None:
        import app.services.routing.command_access_service as module

        with patch.object(module, "ADMIN_UIDS", ["admin-1"]):
            self.assertTrue(module.CommandAccessService.is_admin("admin-1"))
            self.assertFalse(module.CommandAccessService.is_admin("user-1"))

    def test_public_mention_prefers_domain_rule(self) -> None:
        from app.services.routing.command_access_service import CommandAccessService

        service = CommandAccessService(self.handler, bot_mention="(met)bot(met)")

        self.assertTrue(service.is_public_command("(met)bot(met) 帮助"))
        self.plugins.has_public_mention_prefix.assert_not_called()

    def test_public_mention_can_fallback_to_plugin_capability(self) -> None:
        import app.services.routing.command_access_service as module

        service = module.CommandAccessService(self.handler, bot_mention="(met)bot(met)")
        self.plugins.has_public_mention_prefix.return_value = True

        with patch.object(module, "is_public_mention_text", return_value=False):
            self.assertTrue(service.is_public_command("(met)bot(met) 插件命令"))

        self.plugins.has_public_mention_prefix.assert_called_once_with("插件命令")

    def test_public_slash_can_fallback_to_plugin_capability(self) -> None:
        import app.services.routing.command_access_service as module

        service = module.CommandAccessService(self.handler, bot_mention="(met)bot(met)")
        self.plugins.has_public_slash_command.return_value = True

        with patch.object(module, "is_public_slash_command", return_value=False):
            self.assertTrue(service.is_public_command("/plugin-demo arg"))

        self.plugins.has_public_slash_command.assert_called_once_with("/plugin-demo")


class RoleServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.target_resolution = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                community=SimpleNamespace(target_resolution=self.target_resolution),
            ),
        )

    def test_give_role_delegates_edit_when_role_resolves(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.get_assignable_roles.return_value = [
            {"roleID": 7, "name": "成员"},
        ]
        self.sender.edit_user_role.return_value = {"message": "ok"}

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            service.give_role("@user", "成员", "channel-1", "area-1")

        self.sender.edit_user_role.assert_called_once_with("user-1", 7, add=True, area="area-1")
        self.sender.send_message.assert_called_once()

    def test_give_role_reports_unknown_role_without_edit(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.get_assignable_roles.return_value = [
            {"roleID": 7, "name": "成员"},
        ]

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            service.give_role("@user", "不存在", "channel-1", "area-1")

        self.sender.edit_user_role.assert_not_called()
        self.sender.send_message.assert_called_once()

    def test_remove_role_delegates_edit_when_role_resolves(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = "user-1"
        self.sender.get_user_area_detail.return_value = {
            "list": [{"roleID": 9, "name": "管理员"}],
        }
        self.sender.edit_user_role.return_value = {"message": "ok"}

        with patch("app.services.community.role_service.get_resolver") as get_resolver:
            get_resolver.return_value.user.return_value = "测试用户"

            service = RoleService(self.handler)
            service.remove_role("@user", "管理员", "channel-1", "area-1")

        self.sender.edit_user_role.assert_called_once_with("user-1", 9, add=False, area="area-1")
        self.sender.send_message.assert_called_once()

    def test_show_assignable_roles_reports_missing_target(self) -> None:
        from app.services.community.role_service import RoleService

        self.target_resolution.resolve_target.return_value = None

        service = RoleService(self.handler)
        service.show_assignable_roles("@missing", "channel-1", "area-1")

        self.sender.get_assignable_roles.assert_not_called()
        self.sender.send_message.assert_called_once()


class MemberServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.target_resolution = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                community=SimpleNamespace(target_resolution=self.target_resolution),
            ),
        )

    def test_show_members_stops_on_sender_error(self) -> None:
        from app.services.community.member_service import MemberService

        self.sender.get_area_members.return_value = {"error": "网络错误"}

        service = MemberService(self.handler)
        service.show_members("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("失败", self.sender.send_message.call_args.args[0])

    def test_show_members_aggregates_unique_members(self) -> None:
        from app.services.community.member_service import MemberService

        self.sender.get_area_members.side_effect = [
            {
                "members": [
                    {"uid": "u1", "online": 1, "playingState": "游戏中"},
                    {"uid": "u2", "online": 0},
                    {"uid": "u1", "online": 1, "playingState": "游戏中"},
                ]
            },
            {"members": []},
        ]

        with patch("app.services.community.member_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.user.side_effect = lambda uid: {"u1": "用户1", "u2": "用户2"}.get(uid, uid)

            service = MemberService(self.handler)
            service.show_members("channel-1", "area-1")

        self.assertEqual(self.sender.get_area_members.call_count, 1)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("总计 2", message)
        self.assertIn("在线 1", message)

    def test_show_whois_reports_missing_target(self) -> None:
        from app.services.community.member_service import MemberService

        self.target_resolution.resolve_target.return_value = None

        service = MemberService(self.handler)
        service.show_whois("@missing", "channel-1", "area-1")

        self.sender.get_person_detail_full.assert_not_called()
        self.sender.send_message.assert_called_once()


class ProfanityGuardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.handler = SimpleNamespace(infrastructure=SimpleNamespace(sender=self.sender))

    def test_handle_profanity_warns_before_muting(self) -> None:
        from app.services.safety.profanity_guard_service import ProfanityGuardService

        config = {
            "keywords": ["坏词"],
            "mute_duration": 5,
            "recall_message": False,
            "warn_before_mute": True,
        }

        with patch("app.services.safety.profanity_guard_service.PROFANITY_CONFIG", config):
            service = ProfanityGuardService(self.handler)
            with patch("name_resolver.NameResolver") as resolver:
                resolver.return_value.user.return_value = "测试用户"

                service.handle_profanity(
                    "user-1",
                    "channel-1",
                    "area-1",
                    "坏词",
                    [{"message_id": "m1", "channel": "channel-1", "area": "area-1", "timestamp": "t1"}],
                )

        self.sender.mute_user.assert_not_called()
        self.sender.send_message.assert_called_once()
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("请文明发言", message)
        self.assertIn("5 分钟", message)

    def test_handle_profanity_mutes_and_recalls_on_second_violation(self) -> None:
        from app.services.safety.profanity_guard_service import ProfanityGuardService

        config = {
            "keywords": ["坏词"],
            "mute_duration": 5,
            "recall_message": True,
            "warn_before_mute": True,
        }
        self.sender.mute_user.return_value = {"ok": True}

        with patch("app.services.safety.profanity_guard_service.PROFANITY_CONFIG", config):
            service = ProfanityGuardService(self.handler)
            service._warnings["user-1"] = 1
            with patch("name_resolver.NameResolver") as resolver:
                resolver.return_value.user.return_value = "测试用户"

                service.handle_profanity(
                    "user-1",
                    "channel-1",
                    "area-1",
                    "坏词",
                    [{"message_id": "m1", "channel": "channel-1", "area": "area-1", "timestamp": "t1"}],
                )

        self.sender.recall_message.assert_called_once_with("m1", area="area-1", channel="channel-1", timestamp="t1")
        self.sender.mute_user.assert_called_once_with("user-1", area="area-1", duration=5)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("自动禁言", message)
        self.assertIn("5 分钟", message)

    def test_handle_profanity_reports_mute_failure(self) -> None:
        from app.services.safety.profanity_guard_service import ProfanityGuardService

        config = {
            "keywords": ["坏词"],
            "mute_duration": 5,
            "recall_message": False,
            "warn_before_mute": False,
        }
        self.sender.mute_user.return_value = {"error": "权限不足"}

        with patch("app.services.safety.profanity_guard_service.PROFANITY_CONFIG", config):
            service = ProfanityGuardService(self.handler)
            with patch("name_resolver.NameResolver") as resolver:
                resolver.return_value.user.return_value = "测试用户"

                service.handle_profanity(
                    "user-1",
                    "channel-1",
                    "area-1",
                    "坏词",
                    [{"message_id": "m1", "channel": "channel-1", "area": "area-1", "timestamp": "t1"}],
                )

        self.sender.mute_user.assert_called_once_with("user-1", area="area-1", duration=5)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("自动禁言失败", message)


class RecallServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.message_lookup = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender),
            services=SimpleNamespace(
                safety=SimpleNamespace(message_lookup=self.message_lookup),
            ),
            _recent_messages=[],
        )

    def test_recall_message_reports_empty_recent_messages(self) -> None:
        from app.services.safety.recall_service import RecallService

        service = RecallService(self.handler)
        service.recall_message(None, "channel-1", "area-1")

        self.sender.recall_message.assert_not_called()
        self.sender.send_message.assert_called_once()

    def test_recall_message_uses_latest_message_in_same_channel(self) -> None:
        from app.services.safety.recall_service import RecallService

        self.handler._recent_messages = [
            {"messageId": "old", "channel": "channel-2", "area": "area-1", "content": "旧消息", "timestamp": "ts-old"},
            {"messageId": "new", "channel": "channel-1", "area": "area-1", "content": "新消息", "timestamp": "ts-new"},
        ]
        self.message_lookup.resolve_timestamp.return_value = "resolved-ts"
        self.sender.recall_message.return_value = {"ok": True}

        service = RecallService(self.handler)
        service.recall_message("last", "channel-1", "area-1")

        self.message_lookup.resolve_timestamp.assert_called_once_with("new", "channel-1", "area-1")
        self.sender.recall_message.assert_called_once_with("new", area="area-1", channel="channel-1", timestamp="resolved-ts")
        self.sender.send_message.assert_called_once()

    def test_recall_multiple_rejects_invalid_count(self) -> None:
        from app.services.safety.recall_service import RecallService

        service = RecallService(self.handler)
        service.recall_multiple(0, "channel-1", "area-1")

        self.sender.recall_message.assert_not_called()
        self.sender.send_message.assert_called_once()

    def test_configure_auto_recall_can_enable_and_disable(self) -> None:
        import app.services.safety.recall_service as module

        service = module.RecallService(self.handler)
        config = {"enabled": False, "delay": 30, "exclude_commands": []}

        with patch.object(module, "AUTO_RECALL_CONFIG", config):
            service.configure_auto_recall("开 15", "channel-1", "area-1")
            self.assertTrue(config["enabled"])
            self.assertEqual(config["delay"], 15)

            service.configure_auto_recall("关", "channel-1", "area-1")
            self.assertFalse(config["enabled"])

        self.assertEqual(self.sender.send_message.call_count, 2)


class ModerationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender),
        )

    def test_mute_user_sends_success_message(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.mute_user.return_value = {"message": "已禁言 测试用户"}

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            service.mute_user("user-1", 10, "channel-1", "area-1")

        self.sender.mute_user.assert_called_once_with("user-1", area="area-1", duration=10)
        self.assertIn("[ok]", self.sender.send_message.call_args.args[0])

    def test_unmute_user_sends_error_message(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.unmute_user.return_value = {"error": "权限不足"}

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            service.unmute_user("user-1", "channel-1", "area-1")

        self.sender.unmute_user.assert_called_once_with("user-1", area="area-1")
        self.assertIn("[x]", self.sender.send_message.call_args.args[0])
        self.assertIn("权限不足", self.sender.send_message.call_args.args[0])

    def test_remove_from_area_delegates_to_sender(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.remove_from_area.return_value = {"message": "已移出域 测试用户"}

        with patch("app.services.safety.moderation_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = ModerationService(self.handler)
            service.remove_from_area("user-1", "channel-1", "area-1")

        self.sender.remove_from_area.assert_called_once_with("user-1", area="area-1")
        self.assertIn("[ok]", self.sender.send_message.call_args.args[0])

    def test_show_block_list_reports_empty_list(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.get_area_blocks.return_value = {"blocks": []}

        with patch("app.services.safety.moderation_service.get_resolver") as get_resolver:
            get_resolver.return_value.area.return_value = "测试区域"

            service = ModerationService(self.handler)
            service.show_block_list("channel-1", "area-1")

        self.assertIn("当前无封禁用户", self.sender.send_message.call_args.args[0])

    def test_show_block_list_formats_entries(self) -> None:
        from app.services.safety.moderation_service import ModerationService

        self.sender.get_area_blocks.return_value = {
            "blocks": [
                {"uid": "user-1234567890"},
                {"person": "user-abcdef1234"},
            ]
        }

        with patch("app.services.safety.moderation_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.user.side_effect = lambda uid: {"user-1234567890": "用户甲", "user-abcdef1234": "用户乙"}.get(uid, "")

            service = ModerationService(self.handler)
            service.show_block_list("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("测试区域 - 封禁列表", message)
        self.assertIn("用户甲", message)
        self.assertIn("用户乙", message)


class HelpServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        from plugin_base import PluginCommandCapabilities, PluginDescriptor, PluginMetadata

        self.sender = Mock()
        self.chat = SimpleNamespace(
            ai_enabled=True,
            img_enabled=True,
            _ai_key="key",
            _ai_base="base",
            _ai_model="model",
            _img_key="img-key",
            _img_base="img-base",
            _img_model="img-model",
        )
        self.plugins = Mock()
        self.access = Mock()
        self.plugin_descriptor_cls = PluginDescriptor
        self.plugin_metadata_cls = PluginMetadata
        self.plugin_capabilities_cls = PluginCommandCapabilities
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, chat=self.chat, plugins=self.plugins),
            services=SimpleNamespace(
                routing=SimpleNamespace(access=self.access),
            ),
        )

    def test_show_help_for_normal_user_filters_plugin_caps(self) -> None:
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
        service.show_help("channel-1", "area-1", user="user-1")

        self.plugins.list_command_descriptors.assert_called_once_with(public_only=True)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("普通用户", message)
        self.assertIn("AI 功能", message)
        self.assertIn("demo", message)
        self.assertIn("@bot 测试 / 测试二  |  /demo / /demo2", message)
        self.assertEqual(self.sender.send_message.call_args.kwargs["styleTags"], ["IMPORTANT"])

    def test_show_help_for_admin_includes_admin_sections(self) -> None:
        from app.services.interaction.help_service import HelpService

        self.access.is_admin.return_value = True
        self.plugins.list_command_descriptors.return_value = []

        service = HelpService(self.handler)
        service.show_help("channel-1", "area-1", user="admin-1")

        self.plugins.list_command_descriptors.assert_called_once_with(public_only=False)
        message = self.sender.send_message.call_args.args[0]
        self.assertIn("管理员", message)
        self.assertIn("插件扩展", message)
        self.assertIn("管理操作", message)

    def test_show_help_hides_ai_section_when_ai_is_unavailable(self) -> None:
        from app.services.interaction.help_service import HelpService

        self.access.is_admin.return_value = False
        self.plugins.list_command_descriptors.return_value = []
        self.chat.ai_enabled = False
        self.chat.img_enabled = False

        service = HelpService(self.handler)
        service.show_help("channel-1", "area-1", user="user-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertNotIn("AI 功能", message)


class PluginManagementServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        from plugin_base import PluginCommandCapabilities, PluginDescriptor, PluginMetadata

        self.sender = Mock()
        self.plugins = Mock()
        self.plugin_descriptor_cls = PluginDescriptor
        self.plugin_metadata_cls = PluginMetadata
        self.plugin_capabilities_cls = PluginCommandCapabilities
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, plugins=self.plugins),
            plugin_host=object(),
        )

    def test_show_plugin_list_splits_loaded_and_available(self) -> None:
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
        service.show_plugin_list("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("已加载: 1", message)
        self.assertIn("可加载: 1", message)
        self.assertIn("loaded_a", message)
        self.assertIn("命令: @bot 测试  |  /demo", message)
        self.assertIn("extra_b", message)

    def test_load_rejects_invalid_plugin_name(self) -> None:
        import app.services.plugins.plugin_management_service as module

        with patch.object(module, "normalize_plugin_name", return_value=None):
            service = module.PluginManagementService(self.handler)
            service.load("bad name!", "channel-1", "area-1")

        self.plugins.load.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("不合法", self.sender.send_message.call_args.args[0])

    def test_load_delegates_to_plugin_runtime(self) -> None:
        import app.services.plugins.plugin_management_service as module
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        self.plugins.load.return_value = PluginOperationResult.success(
            "已加载 demo",
            plugin_name="demo",
            code=PluginOperationCode.SUCCESS,
        )
        with patch.object(module, "normalize_plugin_name", return_value="demo"):
            service = module.PluginManagementService(self.handler)
            service.load("demo.py", "channel-1", "area-1")

        self.plugins.load.assert_called_once_with("demo", handler=self.handler.plugin_host)
        self.assertEqual(self.sender.send_message.call_args.args[0], "[ok] 已加载: demo")

    def test_unload_delegates_to_plugin_runtime(self) -> None:
        import app.services.plugins.plugin_management_service as module
        from domain.plugins.plugin_operation import PluginOperationCode, PluginOperationResult

        self.plugins.unload.return_value = PluginOperationResult.failure(
            "卸载失败",
            plugin_name="demo",
            code=PluginOperationCode.NOT_LOADED,
        )
        with patch.object(module, "normalize_plugin_name", return_value="demo"):
            service = module.PluginManagementService(self.handler)
            service.unload("demo.py", "channel-1", "area-1")

        self.plugins.unload.assert_called_once_with("demo", handler=self.handler.plugin_host)
        self.assertEqual(self.sender.send_message.call_args.args[0], "[x] 插件未加载: demo")


class CommonCommandServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.music = Mock()
        self.chat = Mock()
        self.recall_scheduler = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, music=self.music, chat=self.chat),
            services=SimpleNamespace(
                safety=SimpleNamespace(recall_scheduler=self.recall_scheduler),
            ),
        )

    def test_show_voice_channels_reports_empty_state(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.sender.get_voice_channel_members.return_value = {}

        service = CommonCommandService(self.handler)
        service.show_voice_channels("channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("没有语音频道在线成员", self.sender.send_message.call_args.args[0])

    def test_show_voice_channels_formats_online_members(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.sender.get_voice_channel_members.return_value = {
            "voice-1": [
                {"uid": "u1", "isBot": False},
                {"uid": "u2", "isBot": True},
            ]
        }

        with patch("app.services.interaction.common_command_service.get_resolver") as get_resolver:
            resolver = get_resolver.return_value
            resolver.area.return_value = "测试区域"
            resolver.channel.return_value = "语音一厅"
            resolver.user.side_effect = lambda uid: {"u1": "用户1", "u2": "机器人2"}.get(uid, uid)

            service = CommonCommandService(self.handler)
            service.show_voice_channels("channel-1", "area-1")

        message = self.sender.send_message.call_args.args[0]
        self.assertIn("测试区域 - 语音频道在线", message)
        self.assertIn("共 2 人在线", message)
        self.assertIn("机器人2 [Bot]", message)

    def test_generate_image_reports_failure_when_generation_fails(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.chat.generate_image.return_value = ""

        with patch("app.services.interaction.common_command_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = CommonCommandService(self.handler)
            service.generate_image("一只猫", "channel-1", "area-1", "user-1")

        self.assertEqual(self.sender.send_message.call_count, 2)
        self.assertIn("正在绘制中", self.sender.send_message.call_args_list[0].args[0])
        self.assertIn("图片生成失败", self.sender.send_message.call_args_list[1].args[0])

    def test_generate_image_sends_attachment_message_on_success(self) -> None:
        from app.services.interaction.common_command_service import CommonCommandService

        self.chat.generate_image.return_value = "https://example.com/demo.png"
        self.sender.upload_file_from_url.return_value = {
            "code": "success",
            "data": {
                "width": 512,
                "height": 512,
                "fileKey": "demo-key",
            },
        }
        self.recall_scheduler.should_skip_auto_recall.return_value = True

        with patch("app.services.interaction.common_command_service.NameResolver") as resolver_cls:
            resolver_cls.return_value.user.return_value = "测试用户"

            service = CommonCommandService(self.handler)
            service.generate_image("一只猫", "channel-1", "area-1", "user-1")

        self.sender.upload_file_from_url.assert_called_once_with("https://example.com/demo.png")
        final_call = self.sender.send_message.call_args_list[-1]
        self.assertIn("测试用户 生成的图片", final_call.kwargs["text"])
        self.assertEqual(final_call.kwargs["attachments"][0]["fileKey"], "demo-key")
        self.assertTrue(final_call.kwargs["auto_recall"])


class ChatInteractionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.chat = Mock()
        self.recall_scheduler = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, chat=self.chat),
            services=SimpleNamespace(
                safety=SimpleNamespace(recall_scheduler=self.recall_scheduler),
            ),
        )

    def test_handle_plain_chat_returns_false_when_no_reply(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        self.chat.try_reply.return_value = ""

        service = ChatInteractionService(self.handler)
        result = service.handle_plain_chat("hello", "channel-1", "area-1")

        self.assertFalse(result)
        self.sender.send_message.assert_not_called()

    def test_handle_plain_chat_sends_reply_when_available(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        self.chat.try_reply.return_value = "自动回复"

        service = ChatInteractionService(self.handler)
        result = service.handle_plain_chat("hello", "channel-1", "area-1")

        self.assertTrue(result)
        self.sender.send_message.assert_called_once_with("自动回复", channel="channel-1", area="area-1")

    def test_handle_mention_fallback_uses_ai_reply_when_available(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        self.chat.ai_reply.return_value = "AI 回复"
        self.recall_scheduler.should_skip_auto_recall.return_value = False

        service = ChatInteractionService(self.handler)
        service.handle_mention_fallback("未知问题", "channel-1", "area-1")

        self.sender.send_message.assert_called_once_with(
            "AI 回复",
            channel="channel-1",
            area="area-1",
            auto_recall=False,
        )

    def test_handle_mention_fallback_sends_default_hint_when_ai_fails(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        self.chat.ai_reply.return_value = ""

        service = ChatInteractionService(self.handler)
        service.handle_mention_fallback("未知问题", "channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("@bot 帮助", self.sender.send_message.call_args.args[0])

    def test_send_unknown_command_sends_help_hint(self) -> None:
        from app.services.interaction.chat_interaction_service import ChatInteractionService

        service = ChatInteractionService(self.handler)
        service.send_unknown_command("/unknown", "channel-1", "area-1")

        self.sender.send_message.assert_called_once()
        self.assertIn("/help", self.sender.send_message.call_args.args[0])


class MusicCommandServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = Mock()
        self.music = Mock()
        self.handler = SimpleNamespace(
            infrastructure=SimpleNamespace(sender=self.sender, music=self.music),
        )

    def test_handle_mention_play_delegates_with_keyword(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_mention("播放 稻香", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_called_once_with("稻香", "channel-1", "area-1", "user-1")
        self.sender.send_message.assert_not_called()

    def test_handle_mention_play_without_keyword_sends_usage(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_mention("播放", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("请输入歌名", self.sender.send_message.call_args.args[0])

    def test_handle_mention_like_list_parses_page(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_mention("喜欢列表 3", "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.show_liked_list.assert_called_once_with("channel-1", "area-1", 3)

    def test_handle_mention_returns_false_for_unknown_text(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_mention("天气不错", "channel-1", "area-1", "user-1")

        self.assertFalse(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_not_called()

    def test_handle_slash_play_without_keyword_sends_usage(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/play", None, None, ["/play"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("用法: /bf 歌曲名", self.sender.send_message.call_args.args[0])

    def test_handle_slash_yun_play_delegates_with_arg(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/yun", "play", "晴天", ["/yun", "play", "晴天"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_netease.assert_called_once_with("晴天", "channel-1", "area-1", "user-1")

    def test_handle_slash_like_list_defaults_to_first_page_when_arg_invalid(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/like", "list", "abc", ["/like", "list", "abc"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.show_liked_list.assert_called_once_with("channel-1", "area-1", 1)

    def test_handle_slash_like_play_reports_invalid_index(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/like", "play", "abc", ["/like", "play", "abc"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_liked_by_index.assert_not_called()
        self.sender.send_message.assert_called_once()
        self.assertIn("/like play <编号>", self.sender.send_message.call_args.args[0])

    def test_handle_slash_like_count_is_clamped(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/like", "99", None, ["/like", "99"], "channel-1", "area-1", "user-1")

        self.assertTrue(result)
        self.music.play_liked.assert_called_once_with("channel-1", "area-1", "user-1", 20)

    def test_handle_slash_returns_false_for_non_music_command(self) -> None:
        from app.services.interaction.music_command_service import MusicCommandService

        service = MusicCommandService(self.handler)
        result = service.handle_slash("/members", None, None, ["/members"], "channel-1", "area-1", "user-1")

        self.assertFalse(result)
        self.music.play_liked.assert_not_called()
        self.sender.send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
