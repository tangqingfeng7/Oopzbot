"""
LOL 封号查询插件

通过 QQ 号查询英雄联盟封禁状态。
配置文件：config/plugins/lol_ban.json
@bot 查封号/封号/lol <QQ号>、/lol <QQ号>
"""

from plugin_base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
)


class LolBanPlugin(BotModule):
    def __init__(self):
        self._handler = None
        self._config: dict = {}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="lol_ban",
            description="LOL 封号查询（按 QQ 号）",
            version="1.0.0",
            author="",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("查封号", "封号", "lol", "LOL"),
            slash_commands=("/lol",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return ("plugins._lol_query_service",)

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False),
                PluginConfigField(
                    "api_url",
                    default="",
                    example="https://yun.4png.com/api/query.html",
                ),
                PluginConfigField("token", default=""),
                PluginConfigField("proxy", default=""),
            )
        )

    def on_load(self, handler, config=None):
        self._config = (config or {}).copy()
        from ._lol_query_service import LolQueryHandler
        self._handler = LolQueryHandler(self._config)

    def _keyword(self, text: str) -> str:
        for p in self.command_capabilities.mention_prefixes:
            if text.startswith(p):
                return text[len(p):].strip()
        return text.strip()

    def handle_mention(self, text, channel, area, user, handler):
        keyword = self._keyword(text)
        if not keyword:
            handler.sender.send_message(
                "请输入QQ号，例如: @bot 查封号 123456789\n"
                "官方封号查询: https://gamesafe.qq.com/query_punish.shtml",
                channel=channel,
                area=area,
            )
            return True
        handler.sender.send_message(
            f"[search] 正在查询 QQ {keyword} 的封号状态...",
            channel=channel,
            area=area,
        )
        reply = self._handler.query_and_format(keyword)
        handler.sender.send_message(reply, channel=channel, area=area)
        return True

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler):
        keyword = (subcommand or "").strip()
        if arg:
            keyword = f"{keyword} {arg}".strip() if keyword else arg.strip()
        if not keyword:
            handler.sender.send_message(
                "用法: /lol QQ号\n"
                "示例: /lol 123456789\n\n"
                "官方封号查询: https://gamesafe.qq.com/query_punish.shtml",
                channel=channel,
                area=area,
            )
            return True
        handler.sender.send_message(
            f"[search] 正在查询 QQ {keyword} 的封号状态...",
            channel=channel,
            area=area,
        )
        reply = self._handler.query_and_format(keyword)
        handler.sender.send_message(reply, channel=channel, area=area)
        return True
