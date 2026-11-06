from app.services.runtime import CommandRuntimeView, music_of, sender_of
from oopz.name_resolver import get_resolver


class CommonCommandService:
    """处理语音频道和每日一句。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)
        self._music = music_of(runtime)

    async def show_voice_channels(self, channel: str, area: str) -> None:
        """查看各语音频道的在线成员。"""
        resolver = get_resolver()

        try:
            channel_members = (await self._sender.bot.channels.get_voice_channel_members(area)).channel_members
        except Exception as exc:
            await self._sender.send_message(f"查询语音频道成员失败: {exc}", channel=channel, area=area)
            return
        if not channel_members:
            await self._sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
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
                name = resolver.user(member.uid)
                suffix = " [Bot]" if member.is_bot else ""
                lines.append(f"  - {name}{suffix}")
            total_online += len(members)

        if total_online == 0:
            await self._sender.send_message("当前没有语音频道在线成员", channel=channel, area=area)
            return

        lines.insert(1, f"共 {total_online} 人在线")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def enter_channel(self, channel_id: str, channel: str, area: str) -> None:
        """进入指定频道。"""
        resolver = get_resolver()
        channel_name = resolver.channel(channel_id)
        data = await self._music.enter_voice_channel(channel_id, area)
        if "error" in data:
            await self._sender.send_message(f"进入频道失败: {data['error']}", channel=channel, area=area)
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

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_daily_speech(self, channel: str, area: str) -> None:
        """获取并展示每日一句名言。"""
        try:
            data = await self._sender.bot.general.get_daily_speech()
        except Exception as exc:
            await self._sender.send_message(f"获取每日一句失败: {exc}", channel=channel, area=area)
            return

        words = data.words
        author = data.author

        if words:
            text = f"「{words}」"
            if author:
                text += f"\n—— {author}"
        else:
            text = "暂无内容"

        await self._sender.send_message(text, channel=channel, area=area)
