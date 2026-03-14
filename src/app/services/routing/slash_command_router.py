"""斜杠命令路由。"""

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from command_handler import CommandHandler


class SlashCommandRouter:
    """负责解析 `/` 命令。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._services = handler.services
        self._sender = handler.infrastructure.sender

    def dispatch(self, content: str, channel: str, area: str, user: str) -> None:
        """将斜杠命令路由到具体处理逻辑。"""
        parts = content.split()
        if not parts:
            return

        command = parts[0].lower()
        subcommand = parts[1].lower() if len(parts) > 1 else None
        arg = " ".join(parts[2:]) if len(parts) > 2 else None

        if self._handler.infrastructure.plugins.try_dispatch_slash(
            command,
            subcommand,
            arg,
            channel,
            area,
            user,
            self._handler.plugin_host,
        ):
            return

        if self._services.routing.access.is_admin(user):
            if command == "/plugins":
                self._services.plugins.management.show_plugin_list(channel, area)
                return
            if command == "/loadplugin":
                raw_name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                if raw_name:
                    self._services.plugins.management.load(raw_name, channel, area)
                else:
                    self._sender.send_message("用法: /loadplugin <名>", channel=channel, area=area)
                return
            if command == "/unloadplugin":
                raw_name = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                if raw_name:
                    self._services.plugins.management.unload(raw_name, channel, area)
                else:
                    self._sender.send_message("用法: /unloadplugin <名>", channel=channel, area=area)
                return

        if command == "/help":
            self._services.interaction.help.show_help(channel, area, user)
            return
        if self._services.interaction.music.handle_slash(command, subcommand, arg, parts, channel, area, user):
            return

        if command in ("/members", "/online"):
            self._services.community.member.show_members(channel, area)
            return
        if command == "/me":
            self._services.community.member.show_profile(channel, area, user)
            return
        if command == "/myinfo":
            self._services.community.member.show_myinfo(channel, area, user)
            return

        if command == "/whois":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._services.community.member.show_whois(target, channel, area)
            else:
                self._sender.send_message("用法: /whois 用户名", channel=channel, area=area)
            return

        if command == "/role":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._services.community.role.show_user_roles(target, channel, area)
            else:
                self._sender.send_message("用法: /role 用户名", channel=channel, area=area)
            return

        if command == "/roles":
            target = " ".join(parts[1:]) if len(parts) > 1 else None
            if target:
                self._services.community.role.show_assignable_roles(target, channel, area)
            else:
                self._sender.send_message("用法: /roles 用户名", channel=channel, area=area)
            return

        if command == "/addrole":
            if len(parts) >= 3:
                role_arg = " ".join(parts[2:]).strip()
                if role_arg:
                    self._services.community.role.give_role(parts[1], role_arg, channel, area)
                else:
                    self._sender.send_message("用法: /addrole 用户 身份组名或ID", channel=channel, area=area)
            else:
                self._sender.send_message("用法: /addrole 用户 身份组名或ID\n示例: /addrole 皇 管理员", channel=channel, area=area)
            return

        if command == "/removerole":
            if len(parts) >= 3:
                role_arg = " ".join(parts[2:]).strip()
                if role_arg:
                    self._services.community.role.remove_role(parts[1], role_arg, channel, area)
                else:
                    self._sender.send_message("用法: /removerole 用户 身份组名或ID", channel=channel, area=area)
            else:
                self._sender.send_message("用法: /removerole 用户 身份组名或ID\n示例: /removerole 皇 管理员", channel=channel, area=area)
            return

        if command == "/search":
            keyword = " ".join(parts[1:]) if len(parts) > 1 else None
            if keyword:
                self._services.community.member.search_members(keyword, channel, area)
            else:
                self._sender.send_message("用法: /search 关键词", channel=channel, area=area)
            return

        if command == "/voice":
            self._services.interaction.common.show_voice_channels(channel, area)
            return
        if command == "/enter":
            channel_id = " ".join(parts[1:]) if len(parts) > 1 else None
            if channel_id:
                self._services.interaction.common.enter_channel(channel_id, channel, area)
            else:
                self._sender.send_message("用法: /enter 频道ID", channel=channel, area=area)
            return
        if command in ("/daily", "/quote"):
            self._services.interaction.common.show_daily_speech(channel, area)
            return

        if command in ("/禁言", "/mute"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid, duration = self._services.community.target_resolution.parse_mute_args(raw)
            if uid:
                self._services.safety.moderation.mute_user(uid, duration, channel, area)
            else:
                self._sender.send_message("用法: /禁言 皇 10", channel=channel, area=area)
            return

        if command in ("/解禁", "/unmute"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._services.community.target_resolution.resolve_target(raw)
            if uid:
                self._services.safety.moderation.unmute_user(uid, channel, area)
            else:
                self._sender.send_message("用法: /解禁 皇", channel=channel, area=area)
            return

        if command in ("/禁麦", "/mutemic"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid, duration = self._services.community.target_resolution.parse_mute_args(raw)
            if uid:
                self._services.safety.moderation.mute_mic(uid, channel, area, duration)
            else:
                self._sender.send_message("用法: /禁麦 皇", channel=channel, area=area)
            return

        if command in ("/解麦", "/unmutemic"):
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._services.community.target_resolution.resolve_target(raw)
            if uid:
                self._services.safety.moderation.unmute_mic(uid, channel, area)
            else:
                self._sender.send_message("用法: /解麦 皇", channel=channel, area=area)
            return

        if command == "/ban":
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._services.community.target_resolution.resolve_target(raw)
            if uid:
                self._services.safety.moderation.remove_from_area(uid, channel, area)
            else:
                self._sender.send_message("用法: /ban 用户", channel=channel, area=area)
            return

        if command == "/unblock":
            raw = " ".join(parts[1:]) if len(parts) > 1 else ""
            uid = self._services.community.target_resolution.resolve_target(raw)
            if uid:
                self._services.safety.moderation.unblock_in_area(uid, channel, area)
            else:
                self._sender.send_message("用法: /unblock 用户（可先 /blocklist 查看封禁列表）", channel=channel, area=area)
            return

        if command == "/blocklist":
            self._services.safety.moderation.show_block_list(channel, area)
            return
        if command == "/autorecall":
            arg = " ".join(parts[1:]) if len(parts) > 1 else ""
            self._services.safety.recall.configure_auto_recall(arg, channel, area)
            return
        if command == "/clear" and subcommand == "history":
            self._services.safety.recall.clear_history(channel, area)
            return
        if command == "/recall":
            arg = " ".join(parts[1:]) if len(parts) > 1 else None
            if arg and arg.isdigit():
                self._services.safety.recall.recall_multiple(int(arg), channel, area)
            else:
                self._services.safety.recall.recall_message(arg, channel, area)
            return

        self._services.interaction.chat.send_unknown_command(command, channel, area)
