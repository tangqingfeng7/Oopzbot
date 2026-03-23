from app.services.runtime import CommandRuntimeView, plugins_of, sender_of

from .builtin_command_actions import build_builtin_command_actions


class SlashCommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._sender = sender_of(runtime)
        self._plugins = plugins_of(runtime)
        self._actions = build_builtin_command_actions(runtime)
        self._current_user = ""

    def _rest(self, parts: list[str]) -> str:
        return " ".join(parts[1:]).strip()

    def _dispatch_exact(self, command: str, aliases: tuple[str, ...], callback) -> bool:
        if command not in aliases:
            return False
        callback()
        return True

    def _dispatch_required_arg(
        self,
        command: str,
        aliases: tuple[str, ...],
        raw: str,
        callback,
        usage: str,
        channel: str,
        area: str,
    ) -> bool:
        if command not in aliases:
            return False
        if raw:
            callback(raw)
        else:
            self._sender.send_message(usage, channel=channel, area=area)
        return True

    def _dispatch_required_pair(
        self,
        command: str,
        aliases: tuple[str, ...],
        parts: list[str],
        callback,
        usage: str,
        channel: str,
        area: str,
    ) -> bool:
        if command not in aliases:
            return False
        if len(parts) >= 3:
            role_arg = " ".join(parts[2:]).strip()
            if role_arg:
                callback(parts[1], role_arg)
                return True
        self._sender.send_message(usage, channel=channel, area=area)
        return True

    def _admin_rules(self, channel: str, area: str):
        return (
            (("/plugins",), lambda: self._actions.plugins.show_plugin_list(channel, area), None),
            (("/loadplugin",), lambda name: self._actions.plugins.load_plugin(name, channel, area), "用法: /loadplugin <名>"),
            (("/unloadplugin",), lambda name: self._actions.plugins.unload_plugin(name, channel, area), "用法: /unloadplugin <名>"),
            (("/reloadplugin",), lambda name: self._actions.plugins.reload_plugin_config(name, channel, area), "用法: /reloadplugin <名>"),
        )

    def _exact_rules(self, channel: str, area: str, user: str, raw: str):
        return (
            (("/members", "/online"), lambda: self._actions.community.show_members(channel, area)),
            (("/me",), lambda: self._actions.community.show_profile(channel, area, user)),
            (("/myinfo",), lambda: self._actions.community.show_myinfo(channel, area, user)),
            (("/voice",), lambda: self._actions.interaction.show_voice_channels(channel, area)),
            (("/daily", "/quote"), lambda: self._actions.interaction.show_daily_speech(channel, area)),
            (("/health", "/doctor"), lambda: self._actions.interaction.show_health_check(channel, area)),
            (("/setup", "/wizard"), lambda: self._actions.interaction.show_setup_wizard(channel, area)),
            (("/禁言", "/mute"), lambda: self._actions.moderation.mute_user(raw, channel, area, "用法: /禁言 谁 10")),
            (("/解禁", "/unmute"), lambda: self._actions.moderation.unmute_user(raw, channel, area, "用法: /解禁 谁")),
            (("/禁麦", "/mutemic"), lambda: self._actions.moderation.mute_mic(raw, channel, area, "用法: /禁麦 谁")),
            (("/解麦", "/unmutemic"), lambda: self._actions.moderation.unmute_mic(raw, channel, area, "用法: /解麦 谁")),
            (("/ban",), lambda: self._actions.moderation.remove_from_area(raw, channel, area, "用法: /ban 用户")),
            (
                ("/unblock",),
                lambda: self._actions.moderation.unblock_in_area(
                    raw,
                    channel,
                    area,
                    "用法: /unblock 用户（可先 /blocklist 查看封禁列表）",
                ),
            ),
            (("/blocklist",), lambda: self._actions.moderation.show_block_list(channel, area)),
            (("/autorecall",), lambda: self._actions.recall.configure_auto_recall(raw, channel, area)),
            (("/recall",), lambda: self._actions.recall.recall(raw or None, channel, area)),
            (("/ranking", "/活跃", "/活跃排行"), lambda: self._actions.scheduler.show_ranking(channel, area)),
            (("/chatstats", "/频道统计"), lambda: self._actions.scheduler.show_channel_stats(channel, area)),
            (("/topsongs", "/点歌排行", "/播放排行"), lambda: self._actions.scheduler.show_music_ranking(channel, area)),
            (("/recentsongs", "/最近播放"), lambda: self._actions.scheduler.show_recent_songs(channel, area)),
        )

    def _arg_rules(self, channel: str, area: str):
        return (
            (("/whois",), lambda target: self._actions.community.show_whois(target, channel, area, self._current_user), "用法: /whois 用户名"),
            (("/role",), lambda target: self._actions.community.show_user_roles(target, channel, area), "用法: /role 用户名"),
            (("/roles",), lambda target: self._actions.community.show_assignable_roles(target, channel, area), "用法: /roles 用户名"),
            (("/search",), lambda keyword: self._actions.community.search_members(keyword, channel, area, self._current_user), "用法: /search 关键词"),
            (("/help",), lambda topic: self._actions.interaction.show_help(channel, area, self._current_user, topic), "用法: /help 音乐"),
            (("/enter",), lambda channel_id: self._actions.interaction.enter_channel(channel_id, channel, area), "用法: /enter 频道ID"),
            (("/songsearch",), lambda keyword: self._services.interaction.music.search_candidates(keyword, channel, area, self._current_user), "用法: /songsearch 关键词"),
            (("/pick",), lambda raw: self._handle_pick(raw, channel, area, self._current_user), "用法: /pick <编号>"),
        )

    def _pair_rules(self, channel: str, area: str):
        return (
            (
                ("/addrole",),
                lambda target, role_name: self._actions.community.give_role(target, role_name, channel, area),
                "用法: /addrole 用户 身份组名或ID\n示例: /addrole 谁 管理员",
            ),
            (
                ("/removerole",),
                lambda target, role_name: self._actions.community.remove_role(target, role_name, channel, area),
                "用法: /removerole 用户 身份组名或ID\n示例: /removerole 谁 管理员",
            ),
        )

    def dispatch(self, content: str, channel: str, area: str, user: str) -> None:
        self._current_user = user
        parts = content.split()
        if not parts:
            return

        command = parts[0].lower()
        subcommand = parts[1].lower() if len(parts) > 1 else None
        arg = " ".join(parts[2:]) if len(parts) > 2 else None
        raw = self._rest(parts)

        if self._plugins.try_dispatch_slash(
            command,
            subcommand,
            arg,
            channel,
            area,
            user,
            self._runtime.plugin_host,
        ):
            return

        if self._services.routing.access.is_admin(user):
            for aliases, callback, usage in self._admin_rules(channel, area):
                if usage is None and self._dispatch_exact(command, aliases, callback):
                    return
                if usage is not None and self._dispatch_required_arg(command, aliases, raw, callback, usage, channel, area):
                    return

        if not raw and self._dispatch_exact(command, ("/help",), lambda: self._actions.interaction.show_help(channel, area, user)):
            return
        if self._services.interaction.music.handle_slash(command, subcommand, arg, parts, channel, area, user):
            return

        for aliases, callback in self._exact_rules(channel, area, user, raw):
            if self._dispatch_exact(command, aliases, callback):
                return

        for aliases, callback, usage in self._arg_rules(channel, area):
            if self._dispatch_required_arg(command, aliases, raw, callback, usage, channel, area):
                return

        for aliases, callback, usage in self._pair_rules(channel, area):
            if self._dispatch_required_pair(command, aliases, parts, callback, usage, channel, area):
                return

        if command == "/clear" and subcommand == "history":
            self._actions.recall.clear_history(channel, area)
            return

        if command in ("/remind", "/提醒"):
            if subcommand == "list":
                self._actions.scheduler.list_reminders(channel, area, user)
            elif subcommand == "del" and arg:
                self._actions.scheduler.delete_reminder(arg, channel, area, user)
            elif raw:
                self._actions.scheduler.set_reminder(raw, channel, area, user)
            else:
                self._sender.send_message(
                    "用法:\n/remind 30分钟后 提醒内容\n/remind list  查看我的提醒\n/remind del <ID>  删除提醒",
                    channel=channel, area=area,
                )
            return

        if command == "/schedule":
            if subcommand == "list" or not subcommand:
                self._actions.scheduler.list_scheduled(channel, area)
            elif subcommand == "add":
                if arg:
                    self._actions.scheduler.add_scheduled(arg, channel, area)
                else:
                    self._sender.send_message("用法: /schedule add 08:00 早上好", channel=channel, area=area)
            elif subcommand == "del":
                if arg:
                    self._actions.scheduler.delete_scheduled(arg, channel, area)
                else:
                    self._sender.send_message("用法: /schedule del <ID>", channel=channel, area=area)
            elif subcommand == "on":
                if arg:
                    self._actions.scheduler.toggle_scheduled(arg, channel, area, True)
                else:
                    self._sender.send_message("用法: /schedule on <ID>", channel=channel, area=area)
            elif subcommand == "off":
                if arg:
                    self._actions.scheduler.toggle_scheduled(arg, channel, area, False)
                else:
                    self._sender.send_message("用法: /schedule off <ID>", channel=channel, area=area)
            else:
                self._sender.send_message(
                    "用法: /schedule list | add | del | on | off", channel=channel, area=area,
                )
            return

        if command in ("/clearai", "/清除记忆", "/重置对话"):
            cleared = self._services.interaction.chat.clear_memory(user, channel)
            if cleared:
                self._sender.send_message("对话记忆已清除", channel=channel, area=area)
            else:
                self._sender.send_message("当前没有对话记忆", channel=channel, area=area)
            return

        self._services.interaction.chat.send_unknown_command(
            command,
            channel,
            area,
            suggestions=self._services.interaction.help.suggest_commands(command),
        )

    def _handle_pick(self, raw: str, channel: str, area: str, user: str) -> None:
        token = (raw or "").strip()
        if not token.isdigit():
            self._sender.send_message("用法: /pick <编号>", channel=channel, area=area)
            return
        index = int(token)
        if self._services.interaction.music.handle_pick(index, channel, area, user):
            return
        if self._services.community.member.handle_pick(index, channel, area, user):
            return
        self._sender.send_message("当前没有可选择的候选结果，请先搜索或搜歌", channel=channel, area=area)
