"""
LOL 战绩查询插件（FA8）

通过 FA8 API 查询召唤师战绩。
配置文件：config/plugins/lol_fa8.json
@bot 战绩/查战绩/查询战绩 <召唤师名#编号>、/zj <召唤师名#编号>
"""

from plugin_base import BotModule, PluginMetadata


class LolFa8Plugin(BotModule):
    def __init__(self):
        self._handler = None
        self._config: dict = {}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="lol_fa8",
            description="LOL 战绩查询（FA8 召唤师）",
            version="1.0.0",
            author="",
        )

    @property
    def mention_prefixes(self) -> tuple[str, ...]:
        return ("查询战绩", "查战绩", "战绩")

    @property
    def slash_commands(self) -> tuple[str, ...]:
        return ("/zj",)

    @property
    def private_modules(self) -> tuple[str, ...]:
        return ("plugins._lol_fa8_service",)

    def on_load(self, handler, config=None):
        self._config = (config or {}).copy()
        self._handler = None

    def on_unload(self) -> None:
        if self._handler is not None:
            try:
                self._handler.close()
            except Exception:
                pass
        self._handler = None

    def _service(self):
        if self._handler is None:
            from ._lol_fa8_service import FA8Handler
            self._handler = FA8Handler(self._config)
        return self._handler

    def _keyword(self, text: str) -> str:
        for p in self.mention_prefixes:
            if text.startswith(p):
                return text[len(p):].strip()
        return text.strip()

    def handle_mention(self, text, channel, area, user, handler):
        keyword = self._keyword(text)
        if not keyword:
            handler.sender.send_message(
                "请输入召唤师名称\n"
                "格式: @bot 战绩 召唤师名#编号\n"
                "示例: @bot 战绩 艺术就是充钱丶#72269\n"
                "指定大区: @bot 战绩 班德尔城 召唤师名#编号\n"
                "按区搜索: @bot 战绩 3 召唤师名#编号 (1-5对应联盟一~五区)",
                channel=channel,
                area=area,
            )
            return True
        handler.sender.send_message(
            f"[search] 正在查询 {keyword} 的战绩...",
            channel=channel,
            area=area,
        )
        reply = self._service().query_and_format(keyword)
        handler.sender.send_message(reply, channel=channel, area=area)
        return True

    def handle_slash(self, command, subcommand, arg, channel, area, user, handler):
        keyword = (subcommand or "").strip()
        if arg:
            keyword = f"{keyword} {arg}".strip() if keyword else arg.strip()
        if not keyword:
            handler.sender.send_message(
                "用法: /zj 召唤师名#编号\n"
                "示例: /zj 艺术就是充钱丶#72269\n"
                "指定大区: /zj 班德尔城 召唤师名#编号",
                channel=channel,
                area=area,
            )
            return True
        handler.sender.send_message(
            f"[search] 正在查询 {keyword} 的战绩...",
            channel=channel,
            area=area,
        )
        reply = self._service().query_and_format(keyword)
        handler.sender.send_message(reply, channel=channel, area=area)
        return True
