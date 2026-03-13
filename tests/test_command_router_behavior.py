import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _build_handler_for_mention():
    sender = Mock()
    plugins = Mock()
    services = SimpleNamespace(
        interaction=SimpleNamespace(
            music=Mock(),
            common=Mock(),
            help=Mock(),
            chat=Mock(),
        ),
        community=SimpleNamespace(
            member=Mock(),
            role=Mock(),
            target_resolution=Mock(),
        ),
        safety=SimpleNamespace(
            moderation=Mock(),
            recall=Mock(),
        ),
        plugins=SimpleNamespace(
            management=Mock(),
        ),
    )
    handler = SimpleNamespace(
        infrastructure=SimpleNamespace(sender=sender, plugins=plugins),
        services=services,
        plugin_host=sentinel_plugin_host,
    )
    return handler, sender, plugins, services


def _build_handler_for_slash():
    sender = Mock()
    plugins = Mock()
    access = Mock()
    services = SimpleNamespace(
        routing=SimpleNamespace(access=access),
        interaction=SimpleNamespace(
            music=Mock(),
            common=Mock(),
            help=Mock(),
            chat=Mock(),
        ),
        community=SimpleNamespace(
            member=Mock(),
            role=Mock(),
            target_resolution=Mock(),
        ),
        safety=SimpleNamespace(
            moderation=Mock(),
            recall=Mock(),
        ),
        plugins=SimpleNamespace(
            management=Mock(),
        ),
    )
    handler = SimpleNamespace(
        infrastructure=SimpleNamespace(sender=sender, plugins=plugins),
        services=services,
        plugin_host=sentinel_plugin_host,
    )
    return handler, sender, plugins, access, services


sentinel_plugin_host = object()


class MentionCommandRouterTest(unittest.TestCase):
    def test_plugin_dispatch_short_circuits_other_branches(self) -> None:
        from app.services.routing.mention_command_router import MentionCommandRouter

        handler, _, plugins, services = _build_handler_for_mention()
        plugins.try_dispatch_mention.return_value = True

        router = MentionCommandRouter(handler)
        router.dispatch("任意命令", "channel", "area", "user-1")

        services.interaction.music.handle_mention.assert_not_called()
        services.interaction.help.show_help.assert_not_called()

    def test_music_dispatch_short_circuits_builtin_branches(self) -> None:
        from app.services.routing.mention_command_router import MentionCommandRouter

        handler, _, plugins, services = _build_handler_for_mention()
        plugins.try_dispatch_mention.return_value = False
        services.interaction.music.handle_mention.return_value = True

        router = MentionCommandRouter(handler)
        router.dispatch("播放 周杰伦", "channel", "area", "user-1")

        services.interaction.help.show_help.assert_not_called()
        services.community.member.show_members.assert_not_called()

    def test_members_command_routes_to_member_service(self) -> None:
        from app.services.routing.mention_command_router import MentionCommandRouter

        handler, _, plugins, services = _build_handler_for_mention()
        plugins.try_dispatch_mention.return_value = False
        services.interaction.music.handle_mention.return_value = False

        router = MentionCommandRouter(handler)
        router.dispatch("成员列表", "channel", "area", "user-1")

        services.community.member.show_members.assert_called_once_with("channel", "area")

    def test_help_command_routes_to_help_service(self) -> None:
        from app.services.routing.mention_command_router import MentionCommandRouter

        handler, _, plugins, services = _build_handler_for_mention()
        plugins.try_dispatch_mention.return_value = False
        services.interaction.music.handle_mention.return_value = False

        router = MentionCommandRouter(handler)
        router.dispatch("帮助", "channel", "area", "user-1")

        services.interaction.help.show_help.assert_called_once_with("channel", "area", "user-1")

    def test_unknown_mention_falls_back_to_chat_service(self) -> None:
        from app.services.routing.mention_command_router import MentionCommandRouter

        handler, _, plugins, services = _build_handler_for_mention()
        plugins.try_dispatch_mention.return_value = False
        services.interaction.music.handle_mention.return_value = False

        router = MentionCommandRouter(handler)
        router.dispatch("未知命令", "channel", "area", "user-1")

        services.interaction.chat.handle_mention_fallback.assert_called_once_with(
            "未知命令",
            "channel",
            "area",
        )


class SlashCommandRouterTest(unittest.TestCase):
    def test_plugin_dispatch_short_circuits_other_branches(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, _, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = True

        router = SlashCommandRouter(handler)
        router.dispatch("/custom run", "channel", "area", "user-1")

        services.interaction.help.show_help.assert_not_called()
        services.interaction.chat.send_unknown_command.assert_not_called()

    def test_admin_plugins_command_routes_to_plugin_management(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, access, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = False
        access.is_admin.return_value = True

        router = SlashCommandRouter(handler)
        router.dispatch("/plugins", "channel", "area", "user-1")

        services.plugins.management.show_plugin_list.assert_called_once_with("channel", "area")

    def test_help_command_routes_to_help_service(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, access, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = False
        access.is_admin.return_value = False
        services.interaction.music.handle_slash.return_value = False

        router = SlashCommandRouter(handler)
        router.dispatch("/help", "channel", "area", "user-1")

        services.interaction.help.show_help.assert_called_once_with("channel", "area", "user-1")

    def test_music_handler_can_short_circuit_builtin_branches(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, access, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = False
        access.is_admin.return_value = False
        services.interaction.music.handle_slash.return_value = True

        router = SlashCommandRouter(handler)
        router.dispatch("/play test", "channel", "area", "user-1")

        services.community.member.show_members.assert_not_called()
        services.interaction.chat.send_unknown_command.assert_not_called()

    def test_members_command_routes_to_member_service(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, access, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = False
        access.is_admin.return_value = False
        services.interaction.music.handle_slash.return_value = False

        router = SlashCommandRouter(handler)
        router.dispatch("/members", "channel", "area", "user-1")

        services.community.member.show_members.assert_called_once_with("channel", "area")

    def test_unknown_command_falls_back_to_chat_service(self) -> None:
        from app.services.routing.slash_command_router import SlashCommandRouter

        handler, _, plugins, access, services = _build_handler_for_slash()
        plugins.try_dispatch_slash.return_value = False
        access.is_admin.return_value = False
        services.interaction.music.handle_slash.return_value = False

        router = SlashCommandRouter(handler)
        router.dispatch("/unknown", "channel", "area", "user-1")

        services.interaction.chat.send_unknown_command.assert_called_once_with(
            "/unknown",
            "channel",
            "area",
        )


if __name__ == "__main__":
    unittest.main()
