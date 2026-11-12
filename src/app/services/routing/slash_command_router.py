from app.services.runtime import CommandRuntimeView, plugins_of, sender_of
from core.constants import Msg
from domain.routing.command_registry import slash_of
from domain.routing.public_command_rules import is_public_slash_command

from .builtin_command_actions import build_builtin_command_actions


class SlashCommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._sender = sender_of(runtime)
        self._plugins = plugins_of(runtime)
        self._actions = build_builtin_command_actions(runtime)

    def _rest(self, parts: list[str]) -> str:
        return " ".join(parts[1:]).strip()

    async def _dispatch_exact(self, command: str, aliases: tuple[str, ...], callback) -> bool:
        if command not in aliases:
            return False
        await callback()
        return True

    async def _dispatch_required_arg(
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
            await callback(raw)
        else:
            await self._sender.send_message(usage, channel=channel, area=area)
        return True

    async def _dispatch_required_pair(
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
                await callback(parts[1], role_arg)
                return True
        await self._sender.send_message(usage, channel=channel, area=area)
        return True

    def _admin_rules(self, channel: str, area: str):
        return (
            (slash_of("plugin_list"), lambda: self._actions.plugins.show_plugin_list(channel, area), None),
            (slash_of("plugin_load"), lambda name: self._actions.plugins.load_plugin(name, channel, area), "用法: /loadplugin <名>"),
            (slash_of("plugin_unload"), lambda name: self._actions.plugins.unload_plugin(name, channel, area), "用法: /unloadplugin <名>"),
            (slash_of("plugin_reload"), lambda name: self._actions.plugins.reload_plugin_config(name, channel, area), "用法: /reloadplugin <名>"),
        )

    def _exact_rules(self, channel: str, area: str, user: str, raw: str):
        return (
            (slash_of("members"), lambda: self._actions.community.show_members(channel, area)),
            (slash_of("profile"), lambda: self._actions.community.show_profile(channel, area, user)),
            (slash_of("myinfo"), lambda: self._actions.community.show_myinfo(channel, area, user)),
            (slash_of("voice"), lambda: self._actions.interaction.show_voice_channels(channel, area)),
            (slash_of("health"), lambda: self._actions.interaction.show_health_check(channel, area)),
            (slash_of("setup"), lambda: self._actions.interaction.show_setup_wizard(channel, area, user)),
            (slash_of("mute"), lambda: self._actions.moderation.mute_user(raw, channel, area, "用法: /禁言 谁 10")),
            (slash_of("unmute"), lambda: self._actions.moderation.unmute_user(raw, channel, area, "用法: /解禁 谁")),
            (slash_of("mute_mic"), lambda: self._actions.moderation.mute_mic(raw, channel, area, "用法: /禁麦 谁")),
            (slash_of("unmute_mic"), lambda: self._actions.moderation.unmute_mic(raw, channel, area, "用法: /解麦 谁")),
            (slash_of("remove_from_area"), lambda: self._actions.moderation.remove_from_area(raw, channel, area, "用法: /ban 用户")),
            (
                slash_of("unblock"),
                lambda: self._actions.moderation.unblock_in_area(
                    raw,
                    channel,
                    area,
                    "用法: /unblock 用户（可先 /blocklist 查看封禁列表）",
                ),
            ),
            (slash_of("blocklist"), lambda: self._actions.moderation.show_block_list(channel, area)),
            (slash_of("autorecall"), lambda: self._actions.recall.configure_auto_recall(raw, channel, area)),
            (slash_of("recall"), lambda: self._actions.recall.recall(raw or None, channel, area)),
        )

    def _arg_rules(self, channel: str, area: str, user: str):
        # user 必须走形参：router 在 registry 里是单例，而 MessageDispatcher 有 4 个
        # worker 并行跑不同频道，挂在实例字段上会被后到的消息覆盖（与 mention 侧一致）。
        return (
            (slash_of("whois"), lambda target: self._actions.community.show_whois(target, channel, area, user), "用法: /whois 用户名"),
            (slash_of("role"), lambda target: self._actions.community.show_user_roles(target, channel, area), "用法: /role 用户名"),
            (slash_of("roles"), lambda target: self._actions.community.show_assignable_roles(target, channel, area), "用法: /roles 用户名"),
            (slash_of("search"), lambda keyword: self._actions.community.search_members(keyword, channel, area, user), "用法: /search 关键词"),
            (slash_of("help"), lambda topic: self._actions.interaction.show_help(channel, area, user, topic), "用法: /help 音乐"),
            (slash_of("enter"), lambda channel_id: self._actions.interaction.enter_channel(channel_id, channel, area), "用法: /enter 频道ID"),
            (slash_of("songsearch"), lambda keyword: self._services.interaction.music.search_candidates(keyword, channel, area, user), "用法: /songsearch 关键词"),
            (slash_of("pick"), lambda raw: self._actions.interaction.handle_pick(raw, channel, area, user, "用法: /pick <编号>"), "用法: /pick <编号>"),
        )

    def _pair_rules(self, channel: str, area: str):
        return (
            (
                slash_of("addrole"),
                lambda target, role_name: self._actions.community.give_role(target, role_name, channel, area),
                "用法: /addrole 用户 身份组名或ID\n示例: /addrole 谁 管理员",
            ),
            (
                slash_of("removerole"),
                lambda target, role_name: self._actions.community.remove_role(target, role_name, channel, area),
                "用法: /removerole 用户 身份组名或ID\n示例: /removerole 谁 管理员",
            ),
        )

    async def _reject_admin_only(
        self,
        command: str,
        channel: str,
        area: str,
        user: str,
    ) -> bool:
        """插件未处理后，在进入任何内置路由前再次校验管理员身份。"""
        if is_public_slash_command(command):
            return False
        if self._services.routing.access.is_admin(user):
            return False
        await self._sender.send_message(
            f"{Msg.ERR} 无权限，仅管理员可使用该指令",
            channel=channel,
            area=area,
        )
        return True

    async def dispatch(self, content: str, channel: str, area: str, user: str) -> None:
        parts = content.split()
        if not parts:
            return

        command = parts[0].lower()
        subcommand = parts[1].lower() if len(parts) > 1 else None
        arg = " ".join(parts[2:]) if len(parts) > 2 else None
        raw = self._rest(parts)

        if await self._plugins.try_dispatch_slash(
            command,
            subcommand,
            arg,
            channel,
            area,
            user,
            self._runtime.plugin_host,
        ):
            return

        # 第一层消息闸门可能因公开插件声明与内置管理别名碰撞而放行；插件返回
        # False 后，所有内置命令必须统一经过注册表派生的第二层权限门。
        if await self._reject_admin_only(command, channel, area, user):
            return

        if self._services.routing.access.is_admin(user):
            for aliases, callback, usage in self._admin_rules(channel, area):
                if usage is None and await self._dispatch_exact(command, aliases, callback):
                    return
                if usage is not None and await self._dispatch_required_arg(command, aliases, raw, callback, usage, channel, area):
                    return

        if not raw and await self._dispatch_exact(command, slash_of("help"), lambda: self._actions.interaction.show_help(channel, area, user)):
            return
        if await self._services.interaction.music.handle_slash(command, subcommand, arg, parts, channel, area, user):
            return

        for aliases, callback in self._exact_rules(channel, area, user, raw):
            if await self._dispatch_exact(command, aliases, callback):
                return

        for aliases, callback, usage in self._arg_rules(channel, area, user):
            if await self._dispatch_required_arg(command, aliases, raw, callback, usage, channel, area):
                return

        for aliases, callback, usage in self._pair_rules(channel, area):
            if await self._dispatch_required_pair(command, aliases, parts, callback, usage, channel, area):
                return

        if command in slash_of("clear_history") and subcommand == "history":
            await self._actions.recall.clear_history(channel, area)
            return

        await self._services.interaction.chat.send_unknown_command(
            command,
            channel,
            area,
            suggestions=self._services.interaction.help.suggest_commands(command),
        )
