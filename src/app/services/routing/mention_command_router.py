import re

from app.services.runtime import CommandRuntimeView, plugins_of, sender_of
from core.constants import Msg
from domain.routing.command_registry import mention_of
from domain.routing.public_command_rules import is_public_mention_text

from .builtin_command_actions import build_builtin_command_actions


class MentionCommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._sender = sender_of(runtime)
        self._plugins = plugins_of(runtime)
        self._actions = build_builtin_command_actions(runtime)

    async def _dispatch_exact(self, text: str, aliases: tuple[str, ...], callback) -> bool:
        if text not in aliases:
            return False
        await callback()
        return True

    async def _dispatch_prefixed_arg(
        self,
        text: str,
        prefixes: tuple[str, ...],
        callback,
        usage: str,
        channel: str,
        area: str,
    ) -> bool:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            arg = text[len(prefix) :].strip()
            if arg:
                await callback(arg)
            else:
                await self._sender.send_message(usage, channel=channel, area=area)
            return True
        return False

    async def _dispatch_prefixed_pair(
        self,
        text: str,
        prefixes: tuple[str, ...],
        callback,
        usage: str,
        channel: str,
        area: str,
    ) -> bool:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            rest = text[len(prefix) :].strip().split(None, 1)
            if len(rest) >= 2:
                await callback(rest[0], rest[1])
            else:
                await self._sender.send_message(usage, channel=channel, area=area)
            return True
        return False

    async def _dispatch_prefixed_raw(self, text: str, prefixes: tuple[str, ...], callback) -> bool:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            await callback(text[len(prefix) :].strip())
            return True
        return False

    def _exact_rules(self, channel: str, area: str, user: str):
        return (
            (mention_of("members"), lambda: self._actions.community.show_members(channel, area)),
            (mention_of("profile"), lambda: self._actions.community.show_profile(channel, area, user)),
            (mention_of("myinfo"), lambda: self._actions.community.show_myinfo(channel, area, user)),
            (mention_of("voice"), lambda: self._actions.interaction.show_voice_channels(channel, area)),
            (mention_of("daily"), lambda: self._actions.interaction.show_daily_speech(channel, area)),
            (mention_of("health"), lambda: self._actions.interaction.show_health_check(channel, area)),
            (mention_of("setup"), lambda: self._actions.interaction.show_setup_wizard(channel, area, user)),
            (mention_of("clear_history"), lambda: self._actions.recall.clear_history(channel, area)),
            (mention_of("blocklist"), lambda: self._actions.moderation.show_block_list(channel, area)),
            (mention_of("plugin_list"), lambda: self._actions.plugins.show_plugin_list(channel, area)),
            (mention_of("help"), lambda: self._actions.interaction.show_help(channel, area, user)),
            (mention_of("ranking"), lambda: self._actions.scheduler.show_ranking(channel, area)),
            (mention_of("chatstats"), lambda: self._actions.scheduler.show_channel_stats(channel, area)),
            (mention_of("topsongs"), lambda: self._actions.scheduler.show_music_ranking(channel, area)),
            (mention_of("recentsongs"), lambda: self._actions.scheduler.show_recent_songs(channel, area)),
            # 定时消息为「1 slash 命令 : 5 mention 动词」形态不对称，mention 子动作别名保留字面量（另见 _raw_rules）
            (("定时消息列表", "定时消息"), lambda: self._actions.scheduler.list_scheduled(channel, area)),
            (mention_of("reminders_list"), lambda: self._actions.scheduler.list_reminders(channel, area, user)),
            (mention_of("screen_share"), lambda: self._services.interaction.screen_share.start(channel, area, user)),
            (mention_of("screen_share_stop"), lambda: self._services.interaction.screen_share.stop(channel, area, user)),
        )

    def _arg_rules(self, channel: str, area: str, user: str):
        return (
            (mention_of("whois"), lambda target: self._actions.community.show_whois(target, channel, area, user), "用法: @bot 查看用户名"),
            (mention_of("role"), lambda target: self._actions.community.show_user_roles(target, channel, area), "用法: @bot 角色用户名"),
            (
                mention_of("roles"),
                lambda target: self._actions.community.show_assignable_roles(target, channel, area),
                "用法: @bot 可分配角色用户名",
            ),
            (mention_of("search"), lambda keyword: self._actions.community.search_members(keyword, channel, area, user), "用法: @bot 搜索用户名"),
            # help 的全部别名见 _exact_rules；仅「帮助/help」接受主题参数，故此处保留字面量子集
            (("帮助", "help"), lambda topic: self._actions.interaction.show_help(channel, area, user, topic), "用法: @bot 帮助 音乐"),
            (mention_of("enter"), lambda channel_id: self._actions.interaction.enter_channel(channel_id, channel, area), "用法: @bot 进入频道 <频道ID>"),
            (mention_of("plugin_load"), lambda name: self._actions.plugins.load_plugin(name, channel, area), "用法: @bot 加载插件 <名>"),
            (mention_of("plugin_unload"), lambda name: self._actions.plugins.unload_plugin(name, channel, area), "用法: @bot 卸载插件 <名>"),
            (mention_of("plugin_reload"), lambda name: self._actions.plugins.reload_plugin_config(name, channel, area), "用法: @bot 重载插件 <名>"),
        )

    def _pair_rules(self, channel: str, area: str):
        return (
            (
                mention_of("addrole"),
                lambda target, role_name: self._actions.community.give_role(target, role_name, channel, area),
                "用法: @bot 给身份组 用户 身份组名或ID",
            ),
            (
                mention_of("removerole"),
                lambda target, role_name: self._actions.community.remove_role(target, role_name, channel, area),
                "用法: @bot 取消身份组 用户 身份组名或ID",
            ),
        )

    def _raw_rules(self, channel: str, area: str, user: str):
        return (
            (mention_of("mute"), lambda raw: self._actions.moderation.mute_user(raw, channel, area, "用法: @bot 禁言 谁 10")),
            (mention_of("unmute"), lambda raw: self._actions.moderation.unmute_user(raw, channel, area, "用法: @bot 解禁 谁")),
            (mention_of("mute_mic"), lambda raw: self._actions.moderation.mute_mic(raw, channel, area, "用法: @bot 禁麦 谁")),
            (mention_of("unmute_mic"), lambda raw: self._actions.moderation.unmute_mic(raw, channel, area, "用法: @bot 解麦 谁")),
            (
                mention_of("remove_from_area"),
                lambda raw: self._actions.moderation.remove_from_area(raw, channel, area, "用法: @bot 移出域 用户 或 @bot 踢出 用户"),
            ),
            (
                mention_of("unblock"),
                lambda raw: self._actions.moderation.unblock_in_area(
                    raw,
                    channel,
                    area,
                    "用法: @bot 解封 用户（可先 @bot 封禁列表 查看）",
                ),
            ),
            (mention_of("autorecall"), lambda arg: self._actions.recall.configure_auto_recall(arg, channel, area)),
            (mention_of("recall"), lambda raw: self._actions.recall.recall(raw or None, channel, area)),
            (mention_of("remind"), lambda raw: self._actions.scheduler.set_reminder(raw, channel, area, user)),
            (mention_of("delete_reminder"), lambda raw: self._actions.scheduler.delete_reminder(raw, channel, area, user)),
            # 定时消息子动作：与 slash /schedule 子命令形态不对称，保留字面量（见 _exact_rules 注释）
            (("添加定时消息", "新增定时消息"), lambda raw: self._actions.scheduler.add_scheduled(raw, channel, area)),
            (("删除定时消息", "移除定时消息"), lambda raw: self._actions.scheduler.delete_scheduled(raw, channel, area)),
            (("开启定时消息", "启用定时消息"), lambda raw: self._actions.scheduler.toggle_scheduled(raw, channel, area, True)),
            (("关闭定时消息", "停用定时消息"), lambda raw: self._actions.scheduler.toggle_scheduled(raw, channel, area, False)),
            (mention_of("pick"), lambda raw: self._actions.interaction.handle_pick(raw, channel, area, user, "用法: @bot 选择 <编号>")),
            (mention_of("songsearch"), lambda raw: self._services.interaction.music.search_candidates(raw, channel, area, user)),
        )

    def _should_treat_as_unknown_command(self, text: str) -> bool:
        from app.services.interaction.help_catalog import suggest_command_usages
        return bool(suggest_command_usages(text, limit=1))

    async def _reject_admin_only(self, text: str, channel: str, area: str, user: str) -> bool:
        """第二层权限门：与 slash 侧 dispatch 里的 is_admin 判断对称。

        第一层闸门在 CommandMessageService.reject_unauthorized_command，但插件可以用
        公开前缀盖过内置管理命令的判定（见 CommandAccessService.is_public_command），
        所以内置管理命令在真正执行前必须自己再确认一次身份。

        管理命令名单同样从注册表派生，新增 admin=True 的命令自动纳入。
        """
        if is_public_mention_text(text):
            return False
        if self._services.routing.access.is_admin(user):
            return False
        await self._sender.send_message(
            f"{Msg.ERR} 无权限，仅管理员可使用该指令",
            channel=channel,
            area=area,
        )
        return True

    async def dispatch(self, text: str, channel: str, area: str, user: str) -> bool:
        """分发 @bot 命令；返回值保留给调用兼容，当前分支均返回 False。"""
        if await self._plugins.try_dispatch_mention(
            text,
            channel,
            area,
            user,
            self._runtime.plugin_host,
        ):
            return False
        if await self._services.interaction.music.handle_mention(text, channel, area, user):
            return False

        # 插件与音乐保持既有优先级；进入内置命令前补一层与 slash 侧对称的管理员门。
        # 必须排在插件之后：否则某个公开插件的合法前缀若恰是管理前缀的延伸
        # （如「插件商店」之于「插件」），会被误杀。
        if await self._reject_admin_only(text, channel, area, user):
            return False

        for aliases, callback in self._exact_rules(channel, area, user):
            candidate = text.strip() if "封禁列表" in aliases or "插件列表" in aliases else text
            if await self._dispatch_exact(candidate, aliases, callback):
                return False

        for prefixes, callback, usage in self._arg_rules(channel, area, user):
            if await self._dispatch_prefixed_arg(text, prefixes, callback, usage, channel, area):
                return False

        for prefixes, callback, usage in self._pair_rules(channel, area):
            if await self._dispatch_prefixed_pair(text, prefixes, callback, usage, channel, area):
                return False

        match = re.match(r"撤回\s*(\d+)\s*条", text.strip())
        if match:
            await self._actions.recall.recall_multiple(int(match.group(1)), channel, area)
            return False

        for prefixes, callback in self._raw_rules(channel, area, user):
            if await self._dispatch_prefixed_raw(text, prefixes, callback):
                return False

        if self._should_treat_as_unknown_command(text):
            await self._services.interaction.chat.send_unknown_mention_command(
                text,
                channel,
                area,
                suggestions=self._services.interaction.help.suggest_commands(text),
            )
            return False

        await self._services.interaction.chat.send_unknown_mention_command(text, channel, area)
        return False
