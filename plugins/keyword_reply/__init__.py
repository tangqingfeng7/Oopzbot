"""普通聊天消息的关键词自动回复插件。"""

from collections.abc import Callable, Mapping
from typing import Any

from domain.plugins.base import BotModule, PluginMetadata
from domain.plugins.plugin_config import PluginConfigField, PluginConfigSpec
from web.plugin_routes import AdminNavItem

from . import admin

DEFAULT_REPLIES = {
    "你好": "你好呀！我是 Oopz Bot ~",  # noqa: RUF001
    "帮助": "输入 /help 查看可用命令",
    "ping": "pong!",
}


def parse_replies(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("keyword_replies 必须是 {关键词: 回复} 对象")
    return {str(k).strip(): str(v) for k, v in value.items() if str(k).strip() and str(v).strip()}


def match_reply(replies: Mapping[str, str], content: str) -> str | None:
    """先找与整条消息相同的关键词，再找消息中包含的关键词（均不区分大小写）。"""
    text = content.strip().lower()
    if not text:
        return None
    for keyword, reply in replies.items():
        if keyword.lower() == text:
            return reply
    for keyword, reply in replies.items():
        if keyword.lower() in text:
            return reply
    return None


class KeywordReplyPlugin(BotModule):
    def __init__(self):
        self._replies: dict[str, str] = dict(DEFAULT_REPLIES)
        self._unregister_web: Callable[[], None] | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("keyword_reply", "普通聊天消息的关键词自动回复")

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec((
            PluginConfigField(
                "keyword_replies",
                default=DEFAULT_REPLIES,
                cast=parse_replies,
                description="关键词 → 回复内容；先整句匹配，再按包含匹配，不区分大小写",
            ),
        ))

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (f"{__name__}.admin",)

    @property
    def replies(self) -> dict[str, str]:
        return dict(self._replies)

    async def handle_message(self, text, channel, area, user, handler) -> bool:
        reply = match_reply(self._replies, text)
        if not reply:
            return False
        await handler.sender.send_message(reply, channel=channel, area=area)
        return True

    async def on_load(self, handler, config=None) -> None:
        self._replies = parse_replies((config or {}).get("keyword_replies", DEFAULT_REPLIES))
        if self._unregister_web is None:
            self._unregister_web = handler.register_web(
                admin.build_router(lambda: self.replies),
                admin_nav=AdminNavItem("keyword-reply", "/admin/keyword-reply", "关键词"),
            )

    async def on_unload(self) -> None:
        if self._unregister_web is not None:
            self._unregister_web()
            self._unregister_web = None
