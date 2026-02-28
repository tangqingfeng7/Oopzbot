"""
LOL 封号查询插件

通过 QQ 号查询英雄联盟封禁状态。
配置文件：config/plugins/lol_ban.json
@bot 查封号/封号/lol <QQ号>、/lol <QQ号>
"""

from plugin_base import BotModule, PluginMetadata


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
    def mention_prefixes(self) -> tuple[str, ...]:
        return ("查封号", "封号", "lol", "LOL")

    @property
    def slash_commands(self) -> tuple[str, ...]:
        return ("/lol",)

    @property
    def private_modules(self) -> tuple[str, ...]:
        return ("plugins._lol_query_service",)

    def on_load(self, handler, config=None):
        self._config = (config or {}).copy()
        from ._lol_query_service import LolQueryHandler
        self._handler = LolQueryHandler(self._config)

    def _keyword(self, text: str) -> str:
        for p in self.mention_prefixes:
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
