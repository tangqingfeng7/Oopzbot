"""通用命令服务。"""

from typing import TYPE_CHECKING

from name_resolver import NameResolver, get_resolver


if TYPE_CHECKING:
    from command_handler import CommandHandler


class CommonCommandService:
    """处理语音频道、每日一句和 AI 图片生成。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._sender = handler.infrastructure.sender
        self._music = handler.infrastructure.music
        self._chat = handler.infrastructure.chat

    def show_voice_channels(self, channel: str, area: str) -> None:
        """查看各语音频道的在线成员。"""
        resolver = get_resolver()

        channel_members = self._sender.get_voice_channel_members(area=area)
        if not channel_members:
            self._sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        lines = [f"{area_name} - 语音频道在线", "---"]

        total_online = 0
        for channel_id, members in channel_members.items():
            if not members:
                continue
            channel_name = resolver.channel(channel_id)
            lines.append(f"{channel_name} ({len(members)}人):")
            for member in members:
                if isinstance(member, dict):
                    uid = member.get("uid", member.get("id", ""))
                    is_bot = member.get("isBot", False)
                    name = resolver.user(uid)
                    suffix = " [Bot]" if is_bot else ""
                    lines.append(f"  - {name}{suffix}")
                else:
                    lines.append(f"  - {resolver.user(str(member))}")
            total_online += len(members)

        if total_online == 0:
            self._sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
            return

        lines.insert(1, f"共 {total_online} 人在线")
        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def enter_channel(self, channel_id: str, channel: str, area: str) -> None:
        """进入指定频道。"""
        resolver = get_resolver()
        channel_name = resolver.channel(channel_id)
        data = self._music.enter_voice_channel(channel_id, area)
        if "error" in data:
            self._sender.send_message(f"进入频道失败: {data['error']}", channel=channel, area=area)
            return

        lines = [f"已进入频道: {channel_name}", "---"]

        for label, key in [
            ("语音质量", "voiceQuality"),
            ("语音延迟", "voiceDelay"),
            ("角色排序", "roleSort"),
        ]:
            value = data.get(key)
            if value is not None:
                lines.append(f"  {label}: {value}")

        text_mute = data.get("disableTextTo", 0)
        voice_mute = data.get("disableVoiceTo", 0)
        if text_mute and text_mute > 0:
            lines.append("  文字禁言: 是")
        if voice_mute and voice_mute > 0:
            lines.append("  语音禁言: 是")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_daily_speech(self, channel: str, area: str) -> None:
        """获取并展示每日一句名言。"""
        data = self._sender.get_daily_speech()
        if "error" in data:
            self._sender.send_message(f"获取每日一句失败: {data['error']}", channel=channel, area=area)
            return

        words = data.get("words", "")
        author = data.get("author", "")

        if words:
            text = f"「{words}」"
            if author:
                text += f"\n—— {author}"
        else:
            text = "暂无内容"

        self._sender.send_message(text, channel=channel, area=area)

    def generate_image(self, prompt: str, channel: str, area: str, user: str) -> None:
        """调用 AI 生成图片并发送到频道。"""
        names = NameResolver()
        user_name = names.user(user) if user else "未知用户"

        self._sender.send_message(
            f"[paint] {user_name} 请求生成图片，正在绘制中...",
            channel=channel,
            area=area,
        )

        image_url = self._chat.generate_image(prompt)
        if not image_url:
            self._sender.send_message("图片生成失败，请稍后再试", channel=channel, area=area)
            return

        upload_result = self._sender.upload_file_from_url(image_url)
        if upload_result.get("code") != "success":
            self._sender.send_message("图片上传失败，请稍后再试", channel=channel, area=area)
            return

        attachment = upload_result["data"]
        text = (
            f"![IMAGEw{attachment['width']}h{attachment['height']}]({attachment['fileKey']})\n"
            f"{user_name} 生成的图片\n"
            f"描述: {prompt}"
        )
        self._sender.send_message(
            text=text,
            attachments=[attachment],
            channel=channel,
            area=area,
            auto_recall=self._handler.services.safety.recall_scheduler.should_skip_auto_recall("ai_image"),
        )
