from app.services.plugins.plugin_capability_formatter import format_plugin_command_summary
from app.services.runtime import CommandRuntimeView, chat_of, plugins_of, sender_of

from .help_catalog import HELP_TOPICS, resolve_help_topic, suggest_command_usages, suggest_help_topics


class HelpService:
    """负责组织和发送帮助说明。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._chat = chat_of(runtime)
        self._plugins = plugins_of(runtime)

    def resolve_topic(self, raw_topic: str) -> str | None:
        return resolve_help_topic(raw_topic)

    def suggest_topics(self, raw_topic: str, limit: int = 3) -> list[str]:
        return suggest_help_topics(raw_topic, limit=limit)

    def suggest_commands(self, raw_text: str, limit: int = 3) -> list[str]:
        suggestions = suggest_command_usages(raw_text, limit=limit)
        for item in self._plugins.list_command_descriptors():
            if len(suggestions) >= limit:
                break
            if item.capabilities.mention_prefixes:
                mention = item.capabilities.mention_prefixes[0]
                candidate = f"@bot {mention}"
                if candidate not in suggestions:
                    suggestions.append(candidate)
            elif item.capabilities.slash_commands:
                slash = item.capabilities.slash_commands[0]
                if slash not in suggestions:
                    suggestions.append(slash)
        return suggestions[:limit]

    def _overview_lines(self, is_admin: bool, ai_chat_available: bool, ai_image_available: bool) -> list[str]:
        role_label = "管理员" if is_admin else "普通用户"
        lines = [
            f"**Oopz Bot 帮助** [{role_label}]",
            "",
            f"**{HELP_TOPICS['overview'].title}**",
            HELP_TOPICS["overview"].description,
            *HELP_TOPICS["overview"].lines,
        ]

        if ai_chat_available or ai_image_available:
            lines += ["", "**AI 功能**"]
            if ai_image_available:
                lines.append("@bot 画<描述>  AI 生成图片")
            if ai_chat_available:
                lines.append("@bot <任意内容>  AI 智能聊天")

        lines += [
            "",
            "**提醒 & 统计**",
            "@bot 提醒 30分钟后 <内容>  设置提醒  |  /remind <时间> <内容>",
            "@bot 我的提醒  查看待执行提醒  |  /remind list",
            "@bot 活跃排行  近7天排行  |  /ranking",
            "@bot 频道统计  频道消息统计  |  /chatstats",
            "@bot 点歌排行  播放最多的歌  |  /topsongs",
            "@bot 最近播放  最近播放的歌  |  /recentsongs",
        ]

        if is_admin:
            lines += [
                "",
                "**管理操作**",
                "@bot 禁言<用户> [分钟]  禁言  |  @bot 解禁<用户>  解除  |  @bot 禁麦  @bot 解麦",
                "@bot 撤回<消息ID>  撤回最后/撤回N条  |  /recall <ID|last|数量>",
                "@bot 自动撤回  查看/开 [秒]/关  |  /autorecall",
                "@bot 清理历史  清理历史日志  |  /clear history",
                "",
                "**插件扩展**",
                "@bot 插件列表  已加载/可加载  |  @bot 加载插件 <名>  @bot 卸载插件 <名>",
                "/plugins  |  /loadplugin <名>  /unloadplugin <名>",
            ]
        return lines

    def _topic_lines(self, topic_key: str, is_admin: bool) -> list[str]:
        topic = HELP_TOPICS[topic_key]
        lines = [
            f"**帮助 - {topic.title}**",
            topic.description,
            "",
            *topic.lines,
        ]
        if topic_key == "admin" and not is_admin:
            lines += [
                "",
                "提示: 管理类命令通常仅管理员可用",
            ]
        return lines

    def show_help(self, channel: str, area: str, user: str = "", topic: str = "") -> None:
        """发送当前用户可见的帮助命令列表。"""
        is_admin = self._runtime.services.routing.access.is_admin(user)
        plugin_caps = self._plugins.list_command_descriptors(public_only=not is_admin)

        ai_chat_available = (
            self._chat.ai_enabled
            and bool(getattr(self._chat, "_ai_key", ""))
            and bool(getattr(self._chat, "_ai_base", ""))
            and bool(getattr(self._chat, "_ai_model", ""))
        )
        ai_image_available = (
            self._chat.img_enabled
            and bool(getattr(self._chat, "_img_key", ""))
            and bool(getattr(self._chat, "_img_base", ""))
            and bool(getattr(self._chat, "_img_model", ""))
        )

        topic_key = self.resolve_topic(topic)
        if topic and not topic_key:
            suggested = self.suggest_topics(topic)
            lines = [
                f"未找到帮助主题: {topic}",
                "可用示例: 帮助 音乐 / 帮助 管理 / 帮助 插件",
            ]
            if suggested:
                lines.append(f"你是不是想看: {', '.join(suggested)}")
        elif topic_key and topic_key != "overview":
            lines = self._topic_lines(topic_key, is_admin)
        else:
            lines = self._overview_lines(is_admin, ai_chat_available, ai_image_available)

        lines += [
            "",
            "**个人信息**",
            "@bot 个人信息  个人基本信息  |  @bot 我的资料  自身详细资料",
            "/me  |  /myinfo",
        ]

        if plugin_caps:
            lines += ["", "**已加载扩展命令**"]
            for item in plugin_caps:
                summary = format_plugin_command_summary(item, empty_text="（无）")
                lines.append(f"{item.name}: {summary}")

        lines += [
            "",
            "提示: 可用 `帮助 <主题>` 继续查看分层帮助",
            "*发送脏话/违规内容将被自动禁言*",
        ]

        self._sender.send_message(
            "\n".join(lines),
            channel=channel,
            area=area,
            styleTags=["IMPORTANT"],
        )
