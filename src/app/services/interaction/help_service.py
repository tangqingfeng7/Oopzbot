from app.services.plugins.plugin_capability_formatter import format_plugin_command_summary
from app.services.runtime import CommandRuntimeView, chat_of, plugins_of, sender_of


class HelpService:
    """负责组织和发送帮助说明。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)
        self._chat = chat_of(runtime)
        self._plugins = plugins_of(runtime)

    def show_help(self, channel: str, area: str, user: str = "") -> None:
        """发送当前用户可见的帮助命令列表。"""
        is_admin = self._runtime.services.routing.access.is_admin(user)
        role_label = "管理员" if is_admin else "普通用户"
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

        lines = [
            f"**Oopz Bot 帮助** [{role_label}]",
            "",
            "**常用功能**",
            "@bot 每日一句  每日名言  |  /daily",
            "",
            "**个人信息**",
            "@bot 个人信息  个人基本信息  |  @bot 我的资料  自身详细资料",
            "/me  |  /myinfo",
            "",
            "**提醒 & 统计**",
            "@bot 提醒 30分钟后 <内容>  设置提醒  |  /remind <时间> <内容>",
            "@bot 我的提醒  查看待执行提醒  |  /remind list",
            "@bot 删除提醒 <ID>  删除提醒  |  /remind del <ID>",
            "@bot 活跃排行  近7天排行  |  /ranking",
            "@bot 频道统计  频道消息统计  |  /chatstats",
            "@bot 点歌排行  播放最多的歌  |  /topsongs",
            "@bot 最近播放  最近播放的歌  |  /recentsongs",
        ]

        ai_cmds = []
        if ai_image_available:
            ai_cmds.append("@bot 画<描述>  AI 生成图片")
        if ai_chat_available:
            ai_cmds.append("@bot <任意内容>  AI 智能聊天")
        if ai_cmds:
            lines[2:2] = [
                "**AI 功能**",
                "  |  ".join(ai_cmds),
                "",
            ]

        if is_admin:
            lines += [
                "",
                "**音乐播放**",
                "@bot 播放<歌名>  搜索并播放  |  @bot 播放 qq:<歌名>  QQ音乐  |  @bot 播放 b站:<歌名>  B站",
                "@bot 停止  停止播放  |  @bot 下一首  切换下一首  |  @bot 队列  播放队列",
                "@bot 随机  随机播放喜欢  |  @bot 喜欢列表  喜欢的音乐",
                "/bf <歌名>  /bf qq <歌名>  /bf bili <歌名>  |  /st  /next  /queue",
                "/like  /like list  /like play",
                "",
                "**成员查询**",
                "@bot 成员  域成员在线  |  @bot 查看<用户>  他人详细资料  |  @bot 搜索<关键词>  搜索域成员",
                "/members  /whois  /search",
                "",
                "**语音频道**",
                "@bot 语音  语音在线成员  |  @bot 进入频道<ID>  进入指定频道",
                "/voice  /enter <频道ID>",
                "",
                "**角色管理**",
                "@bot 角色<用户>  域内角色  |  @bot 可分配角色<用户>  角色列表",
                "@bot 给身份组 <用户><身份组>  |  @bot 取消身份组<用户><身份组>",
                "/role  /roles  /addrole  /removerole",
                "",
                "**管理操作**",
                "@bot 禁言<用户> [分钟]  禁言  |  @bot 解禁<用户>  解除  |  @bot 禁麦  @bot 解麦",
                "@bot 移出域<用户>  踢出域  |  @bot 解封<用户>  解除域内封禁  |  @bot 封禁列表  域封禁名单",
                "/禁言  /解禁  /禁麦  /解麦  |  /ban  /unblock  /blocklist",
                "@bot 撤回<消息ID>  撤回最后/撤回N条  |  /recall <ID|last|数量>",
                "@bot 自动撤回  查看/开 [秒]/关  |  /autorecall",
                "@bot 清理历史  清理历史日志  |  /clear history",
                "",
                "**定时消息管理**",
                "@bot 定时消息列表  查看全部  |  /schedule list",
                "@bot 添加定时消息 HH:MM 内容  |  /schedule add HH:MM 内容",
                "@bot 删除定时消息 <ID>  |  /schedule del <ID>",
                "@bot 开启/关闭定时消息 <ID>  |  /schedule on/off <ID>",
                "",
                "**插件扩展**",
                "@bot 插件列表  已加载/可加载  |  @bot 加载插件 <名>  @bot 卸载插件 <名>",
                "/plugins  |  /loadplugin <名>  /unloadplugin <名>",
            ]

        if plugin_caps:
            lines += [
                "",
                "**已加载扩展命令**",
            ]
            for item in plugin_caps:
                summary = format_plugin_command_summary(item, empty_text="（无）")
                lines.append(f"{item.name}: {summary}")

        lines += [
            "",
            "*发送脏话/违规内容将被自动禁言*",
        ]

        self._sender.send_message(
            "\n".join(lines),
            channel=channel,
            area=area,
            styleTags=["IMPORTANT"],
        )
