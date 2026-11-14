"""每日一句插件。"""

from domain.plugins.base import BotModule, PluginCommandCapabilities, PluginMetadata
from plugins._shared.command_mixin import PluginCommandMixin

_MENTIONS = ("每日一句", "一句", "名言", "语录", "鸡汤")
_SLASH = ("/daily", "/quote")


class DailySpeechPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "获取每日一句失败"
    command_log_name = "DailySpeech"

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("daily_speech", "每日一句名言")

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(mention_prefixes=_MENTIONS, slash_commands=_SLASH)

    async def handle_mention(self, text, channel, area, user, handler) -> bool:
        if text.strip() not in _MENTIONS:
            return False
        await self._run_plugin_command("", channel, area, user, handler)
        return True

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        data = await handler.sender.bot.general.get_daily_speech()
        if data.words:
            text = f"「{data.words}」"
            if data.author:
                text += f"\n—— {data.author}"
        else:
            text = "暂无内容"
        await self._send(handler, text, channel, area)
