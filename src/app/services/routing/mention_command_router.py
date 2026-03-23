import re

from app.services.runtime import CommandRuntimeView, plugins_of, sender_of

from .builtin_command_actions import build_builtin_command_actions


class MentionCommandRouter:
    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._services = runtime.services
        self._sender = sender_of(runtime)
        self._plugins = plugins_of(runtime)
        self._actions = build_builtin_command_actions(runtime)

    def _dispatch_exact(self, text: str, aliases: tuple[str, ...], callback) -> bool:
        if text not in aliases:
            return False
        callback()
        return True

    def _dispatch_prefixed_arg(
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
                callback(arg)
            else:
                self._sender.send_message(usage, channel=channel, area=area)
            return True
        return False

    def _dispatch_prefixed_pair(
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
                callback(rest[0], rest[1])
            else:
                self._sender.send_message(usage, channel=channel, area=area)
            return True
        return False

    def _dispatch_prefixed_raw(self, text: str, prefixes: tuple[str, ...], callback) -> bool:
        for prefix in prefixes:
            if not text.startswith(prefix):
                continue
            callback(text[len(prefix) :].strip())
            return True
        return False

    def _exact_rules(self, channel: str, area: str, user: str):
        return (
            (("成员", "在线", "成员列表", "谁在线"), lambda: self._actions.community.show_members(channel, area)),
            (("个人信息", "我是谁", "信息"), lambda: self._actions.community.show_profile(channel, area, user)),
            (("我的资料", "我的详细资料", "我的信息"), lambda: self._actions.community.show_myinfo(channel, area, user)),
            (("语音", "语音频道", "语音在线", "谁在语音"), lambda: self._actions.interaction.show_voice_channels(channel, area)),
            (("每日一句", "一句", "名言", "语录", "鸡汤"), lambda: self._actions.interaction.show_daily_speech(channel, area)),
            (("体检", "系统体检", "健康检查"), lambda: self._actions.interaction.show_health_check(channel, area)),
            (("首启向导", "向导"), lambda: self._actions.interaction.show_setup_wizard(channel, area)),
            (("清理历史", "清理记录", "清除历史", "清空历史", "清理数据"), lambda: self._actions.recall.clear_history(channel, area)),
            (("封禁列表", "封禁名单", "黑名单"), lambda: self._actions.moderation.show_block_list(channel, area)),
            (("插件列表", "扩展列表", "插件"), lambda: self._actions.plugins.show_plugin_list(channel, area)),
            (("帮助", "help", "指令", "命令"), lambda: self._actions.interaction.show_help(channel, area, user)),
            (("活跃排行", "活跃榜", "排行榜"), lambda: self._actions.scheduler.show_ranking(channel, area)),
            (("频道统计", "消息统计"), lambda: self._actions.scheduler.show_channel_stats(channel, area)),
            (("点歌排行", "播放排行", "热歌榜"), lambda: self._actions.scheduler.show_music_ranking(channel, area)),
            (("最近播放", "播放历史"), lambda: self._actions.scheduler.show_recent_songs(channel, area)),
            (("定时消息列表", "定时消息"), lambda: self._actions.scheduler.list_scheduled(channel, area)),
            (("我的提醒", "提醒列表"), lambda: self._actions.scheduler.list_reminders(channel, area, user)),
            (("清除记忆", "重置对话", "清除对话", "清空记忆"), lambda: self._clear_ai_memory(user, channel, area)),
        )

    def _arg_rules(self, channel: str, area: str, user: str):
        return (
            (("查看", "资料", "查询资料"), lambda target: self._actions.community.show_whois(target, channel, area, user), "用法: @bot 查看用户名"),
            (("角色",), lambda target: self._actions.community.show_user_roles(target, channel, area), "用法: @bot 角色用户名"),
            (
                ("可分配角色", "分配角色"),
                lambda target: self._actions.community.show_assignable_roles(target, channel, area),
                "用法: @bot 可分配角色用户名",
            ),
            (("搜索成员", "搜索", "找人"), lambda keyword: self._actions.community.search_members(keyword, channel, area, user), "用法: @bot 搜索用户名"),
            (("帮助", "help"), lambda topic: self._actions.interaction.show_help(channel, area, user, topic), "用法: @bot 帮助 音乐"),
            (("进入频道", "进入"), lambda channel_id: self._actions.interaction.enter_channel(channel_id, channel, area), "用法: @bot 进入频道 <频道ID>"),
            (("加载插件", "启用插件", "loadplugin"), lambda name: self._actions.plugins.load_plugin(name, channel, area), "用法: @bot 加载插件 <名>"),
            (("卸载插件", "禁用插件", "unloadplugin"), lambda name: self._actions.plugins.unload_plugin(name, channel, area), "用法: @bot 卸载插件 <名>"),
            (("重载插件", "刷新插件", "reloadplugin"), lambda name: self._actions.plugins.reload_plugin_config(name, channel, area), "用法: @bot 重载插件 <名>"),
            (
                ("画", "画一个", "画一张", "生成图片", "生成", "画图"),
                lambda prompt: self._actions.interaction.generate_image(prompt, channel, area, user),
                "请描述要画的内容，例如: @bot 画一只可爱的猫咪",
            ),
        )

    def _pair_rules(self, channel: str, area: str):
        return (
            (
                ("给身份组", "添加身份组", "addrole"),
                lambda target, role_name: self._actions.community.give_role(target, role_name, channel, area),
                "用法: @bot 给身份组 用户 身份组名或ID",
            ),
            (
                ("取消身份组", "移除身份组", "removerole"),
                lambda target, role_name: self._actions.community.remove_role(target, role_name, channel, area),
                "用法: @bot 取消身份组 用户 身份组名或ID",
            ),
        )

    def _raw_rules(self, channel: str, area: str, user: str):
        return (
            (("禁言",), lambda raw: self._actions.moderation.mute_user(raw, channel, area, "用法: @bot 禁言 谁 10")),
            (("解除禁言", "解禁"), lambda raw: self._actions.moderation.unmute_user(raw, channel, area, "用法: @bot 解禁 谁")),
            (("禁麦",), lambda raw: self._actions.moderation.mute_mic(raw, channel, area, "用法: @bot 禁麦 谁")),
            (("解除禁麦", "解麦"), lambda raw: self._actions.moderation.unmute_mic(raw, channel, area, "用法: @bot 解麦 谁")),
            (
                ("移出域", "踢出", "移出"),
                lambda raw: self._actions.moderation.remove_from_area(raw, channel, area, "用法: @bot 移出域 用户 或 @bot 踢出 用户"),
            ),
            (
                ("解除域内封禁", "解封"),
                lambda raw: self._actions.moderation.unblock_in_area(
                    raw,
                    channel,
                    area,
                    "用法: @bot 解封 用户（可先 @bot 封禁列表 查看）",
                ),
            ),
            (("自动撤回",), lambda arg: self._actions.recall.configure_auto_recall(arg, channel, area)),
            (("撤回",), lambda raw: self._actions.recall.recall(raw or None, channel, area)),
            (("提醒",), lambda raw: self._actions.scheduler.set_reminder(raw, channel, area, user)),
            (("删除提醒", "取消提醒"), lambda raw: self._actions.scheduler.delete_reminder(raw, channel, area, user)),
            (("添加定时消息", "新增定时消息"), lambda raw: self._actions.scheduler.add_scheduled(raw, channel, area)),
            (("删除定时消息", "移除定时消息"), lambda raw: self._actions.scheduler.delete_scheduled(raw, channel, area)),
            (("开启定时消息", "启用定时消息"), lambda raw: self._actions.scheduler.toggle_scheduled(raw, channel, area, True)),
            (("关闭定时消息", "停用定时消息"), lambda raw: self._actions.scheduler.toggle_scheduled(raw, channel, area, False)),
            (("选择", "选歌"), lambda raw: self._handle_pick(raw, channel, area, user)),
            (("搜歌", "搜索歌曲"), lambda raw: self._services.interaction.music.search_candidates(raw, channel, area, user)),
        )

    def _clear_ai_memory(self, user: str, channel: str, area: str) -> None:
        """清除用户在当前频道的 AI 对话记忆。"""
        cleared = self._services.interaction.chat.clear_memory(user, channel)
        if cleared:
            self._sender.send_message("对话记忆已清除", channel=channel, area=area)
        else:
            self._sender.send_message("当前没有对话记忆", channel=channel, area=area)

    def _handle_pick(self, raw: str, channel: str, area: str, user: str) -> None:
        token = (raw or "").strip()
        if not token.isdigit():
            self._sender.send_message("用法: @bot 选择 <编号>", channel=channel, area=area)
            return
        index = int(token)
        if self._services.interaction.music.handle_pick(index, channel, area, user):
            return
        if self._services.community.member.handle_pick(index, channel, area, user):
            return
        self._sender.send_message("当前没有可选择的候选结果，请先搜索或搜歌", channel=channel, area=area)

    def _should_treat_as_unknown_command(self, text: str) -> bool:
        return bool(self._services.interaction.help.suggest_commands(text, limit=1))

    def dispatch(self, text: str, channel: str, area: str, user: str) -> None:
        if self._plugins.try_dispatch_mention(
            text,
            channel,
            area,
            user,
            self._runtime.plugin_host,
        ):
            return
        if self._services.interaction.music.handle_mention(text, channel, area, user):
            return

        for aliases, callback in self._exact_rules(channel, area, user):
            candidate = text.strip() if "封禁列表" in aliases or "插件列表" in aliases else text
            if self._dispatch_exact(candidate, aliases, callback):
                return

        for prefixes, callback, usage in self._arg_rules(channel, area, user):
            if self._dispatch_prefixed_arg(text, prefixes, callback, usage, channel, area):
                return

        for prefixes, callback, usage in self._pair_rules(channel, area):
            if self._dispatch_prefixed_pair(text, prefixes, callback, usage, channel, area):
                return

        match = re.match(r"撤回\s*(\d+)\s*条", text.strip())
        if match:
            self._actions.recall.recall_multiple(int(match.group(1)), channel, area)
            return

        for prefixes, callback in self._raw_rules(channel, area, user):
            if self._dispatch_prefixed_raw(text, prefixes, callback):
                return

        if self._should_treat_as_unknown_command(text):
            self._services.interaction.chat.send_unknown_mention_command(
                text,
                channel,
                area,
                suggestions=self._services.interaction.help.suggest_commands(text),
            )
            return

        self._services.interaction.chat.handle_mention_fallback(text, channel, area, user=user)
