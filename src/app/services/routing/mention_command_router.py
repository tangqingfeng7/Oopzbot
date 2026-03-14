"""@bot 中文命令路由。"""

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from command_handler import CommandHandler


class MentionCommandRouter:
    """负责解析 @bot 中文命令。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._services = handler.services
        self._sender = handler.infrastructure.sender

    def dispatch(self, text: str, channel: str, area: str, user: str) -> None:
        """将 @bot 后的文本路由到具体命令。"""
        if self._handler.infrastructure.plugins.try_dispatch_mention(
            text,
            channel,
            area,
            user,
            self._handler.plugin_host,
        ):
            return
        if self._services.interaction.music.handle_mention(text, channel, area, user):
            return

        if text in ("成员", "在线", "成员列表", "谁在线"):
            self._services.community.member.show_members(channel, area)
            return
        if text in ("个人信息", "我是谁", "信息"):
            self._services.community.member.show_profile(channel, area, user)
            return
        if text in ("我的资料", "我的详细资料", "我的信息"):
            self._services.community.member.show_myinfo(channel, area, user)
            return

        for prefix in ("查看", "资料", "查询资料"):
            if text.startswith(prefix):
                target = text[len(prefix):].strip()
                if target:
                    self._services.community.member.show_whois(target, channel, area)
                else:
                    self._sender.send_message("用法: @bot 查看用户名", channel=channel, area=area)
                return

        if text.startswith("角色"):
            target = text[2:].strip()
            if target:
                self._services.community.role.show_user_roles(target, channel, area)
            else:
                self._sender.send_message("用法: @bot 角色用户名", channel=channel, area=area)
            return

        for prefix in ("可分配角色", "分配角色"):
            if text.startswith(prefix):
                target = text[len(prefix):].strip()
                if target:
                    self._services.community.role.show_assignable_roles(target, channel, area)
                else:
                    self._sender.send_message("用法: @bot 可分配角色用户名", channel=channel, area=area)
                return

        for prefix in ("给身份组", "添加身份组", "addrole"):
            if text.startswith(prefix):
                rest = text[len(prefix):].strip().split(None, 1)
                if len(rest) >= 2:
                    self._services.community.role.give_role(rest[0], rest[1], channel, area)
                else:
                    self._sender.send_message("用法: @bot 给身份组 用户 身份组名或ID", channel=channel, area=area)
                return

        for prefix in ("取消身份组", "移除身份组", "removerole"):
            if text.startswith(prefix):
                rest = text[len(prefix):].strip().split(None, 1)
                if len(rest) >= 2:
                    self._services.community.role.remove_role(rest[0], rest[1], channel, area)
                else:
                    self._sender.send_message("用法: @bot 取消身份组 用户 身份组名或ID", channel=channel, area=area)
                return

        for prefix in ("搜索成员", "搜索", "找人"):
            if text.startswith(prefix):
                keyword = text[len(prefix):].strip()
                if keyword:
                    self._services.community.member.search_members(keyword, channel, area)
                else:
                    self._sender.send_message("用法: @bot 搜索用户名", channel=channel, area=area)
                return

        if text in ("语音", "语音频道", "语音在线", "谁在语音"):
            self._services.interaction.common.show_voice_channels(channel, area)
            return

        for prefix in ("进入频道", "进入"):
            if text.startswith(prefix):
                channel_id = text[len(prefix):].strip()
                if channel_id:
                    self._services.interaction.common.enter_channel(channel_id, channel, area)
                else:
                    self._sender.send_message("用法: @bot 进入频道<频道ID>", channel=channel, area=area)
                return

        if text in ("每日一句", "一句", "名言", "语录", "鸡汤"):
            self._services.interaction.common.show_daily_speech(channel, area)
            return

        if text.startswith("禁言"):
            uid, duration = self._services.community.target_resolution.parse_mute_args(text[2:])
            if uid:
                self._services.safety.moderation.mute_user(uid, duration, channel, area)
            else:
                self._sender.send_message("用法: @bot 禁言皇 10", channel=channel, area=area)
            return

        for prefix in ("解除禁言", "解禁"):
            if text.startswith(prefix):
                uid = self._services.community.target_resolution.resolve_target(text[len(prefix):])
                if uid:
                    self._services.safety.moderation.unmute_user(uid, channel, area)
                else:
                    self._sender.send_message("用法: @bot 解禁皇", channel=channel, area=area)
                return

        if text.startswith("禁麦"):
            uid, duration = self._services.community.target_resolution.parse_mute_args(text[2:])
            if uid:
                self._services.safety.moderation.mute_mic(uid, channel, area, duration)
            else:
                self._sender.send_message("用法: @bot 禁麦皇", channel=channel, area=area)
            return

        for prefix in ("解除禁麦", "解麦"):
            if text.startswith(prefix):
                uid = self._services.community.target_resolution.resolve_target(text[len(prefix):])
                if uid:
                    self._services.safety.moderation.unmute_mic(uid, channel, area)
                else:
                    self._sender.send_message("用法: @bot 解麦皇", channel=channel, area=area)
                return

        for prefix in ("移出域", "踢出", "移出"):
            if text.startswith(prefix):
                uid = self._services.community.target_resolution.resolve_target(text[len(prefix):].strip())
                if uid:
                    self._services.safety.moderation.remove_from_area(uid, channel, area)
                else:
                    self._sender.send_message("用法: @bot 移出域 用户 或 @bot 踢出 用户", channel=channel, area=area)
                return

        for prefix in ("解除域内封禁", "解封"):
            if text.startswith(prefix):
                uid = self._services.community.target_resolution.resolve_target(text[len(prefix):].strip())
                if uid:
                    self._services.safety.moderation.unblock_in_area(uid, channel, area)
                else:
                    self._sender.send_message("用法: @bot 解封 用户（可先 @bot 封禁列表 查看）", channel=channel, area=area)
                return

        if text.strip() in ("封禁列表", "封禁名单", "黑名单"):
            self._services.safety.moderation.show_block_list(channel, area)
            return

        match = re.match(r"撤回\s*(\d+)\s*条", text)
        if match:
            self._services.safety.recall.recall_multiple(int(match.group(1)), channel, area)
            return

        if text.startswith("撤回"):
            message_id = text[2:].strip()
            self._services.safety.recall.recall_message(message_id, channel, area)
            return

        if text.startswith("自动撤回"):
            arg = text[4:].strip()
            self._services.safety.recall.configure_auto_recall(arg, channel, area)
            return

        if text in ("清理历史", "清理记录", "清除历史", "清空历史", "清理数据"):
            self._services.safety.recall.clear_history(channel, area)
            return

        if text.strip() in ("插件列表", "扩展列表", "插件"):
            self._services.plugins.management.show_plugin_list(channel, area)
            return

        for prefix in ("加载插件", "启用插件", "loadplugin"):
            if text.startswith(prefix):
                name = text[len(prefix):].strip()
                if name:
                    self._services.plugins.management.load(name, channel, area)
                else:
                    self._sender.send_message("用法: @bot 加载插件 <名>", channel=channel, area=area)
                return

        for prefix in ("卸载插件", "禁用插件", "unloadplugin"):
            if text.startswith(prefix):
                name = text[len(prefix):].strip()
                if name:
                    self._services.plugins.management.unload(name, channel, area)
                else:
                    self._sender.send_message("用法: @bot 卸载插件 <名>", channel=channel, area=area)
                return

        if text in ("帮助", "help", "指令", "命令"):
            self._services.interaction.help.show_help(channel, area, user)
            return

        for prefix in ("画", "画一个", "画一张", "生成图片", "生成", "画图"):
            if text.startswith(prefix):
                prompt = text[len(prefix):].strip()
                if prompt:
                    self._services.interaction.common.generate_image(prompt, channel, area, user)
                else:
                    self._sender.send_message("请描述要画的内容，例如: @bot 画一只可爱的猫咪", channel=channel, area=area)
                return

        self._services.interaction.chat.handle_mention_fallback(text, channel, area)
