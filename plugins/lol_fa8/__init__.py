import contextlib
import re
import sys
import time
from pathlib import Path

from core.constants import Msg
from core.logger_config import get_logger
from domain.plugins.base import (
    BotModule,
    PluginCommandCapabilities,
    PluginConfigField,
    PluginConfigSpec,
    PluginMetadata,
)
from plugins._shared.command_mixin import PluginCommandMixin

logger = get_logger("LolFa8Plugin")

_HELP_TEXT = (
    "请输入召唤师名称\n"
    "格式: @bot 战绩 召唤师名#编号  |  /zj 召唤师名#编号\n"
    "示例: @bot 战绩 艺术就是充钱丶#72269\n"
    "指定大区: @bot 战绩 班德尔城 召唤师名#编号  |  /zj 班德尔城 召唤师名#编号\n"
    "大区核对: @bot 战绩 3 召唤师名#编号 (1-5对应联盟一~五区)\n"
    "未指定大区时自动识别所属大区\n"
    "单局详情: /zj 详情 1 [召唤师名#编号]（省略玩家时使用本频道最近查询）\n"
    "刷新数据: /zj 刷新 召唤师名#编号"
)


class LolFa8Plugin(PluginCommandMixin, BotModule):
    command_error_prefix = "战绩查询出错"
    command_log_name = "LolFa8Plugin"

    def __init__(self):
        self._handler = None
        self._config: dict = {}
        self._recent_queries: dict[tuple[str, str, str], tuple[float, dict]] = {}

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="lol_fa8",
            description="LOL 战绩查询（FA8 召唤师）",
            version="1.1.0",
            author="",
        )

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=("查询战绩", "查战绩", "战绩"),
            slash_commands=("/zj",),
            is_public_command=True,
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (
            "plugins.lol_fa8.service",
            "plugins.lol_fa8.render",
            "plugins.lol_fa8.detail",
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec(
            (
                PluginConfigField("enabled", default=False),
                PluginConfigField("username", default=""),
                PluginConfigField("password", default=""),
                PluginConfigField("session_cookie", default=""),
            )
        )

    async def on_load(self, handler, config=None):
        self._config = (config or {}).copy()
        self._handler = None
        self._recent_queries.clear()

    async def on_unload(self) -> None:
        if self._handler is not None:
            with contextlib.suppress(Exception):
                await self._handler.close()
        self._handler = None
        self._recent_queries.clear()
        render = sys.modules.get(f"{__name__}.render")
        if render is not None:
            await render.close()

    def _service(self):
        if self._handler is None:
            from .service import FA8Handler
            self._handler = FA8Handler(self._config)
        return self._handler

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        text = (command_text or "").strip()
        service = self._service()

        if not text:
            await self._send(handler, _HELP_TEXT, channel, area)
            return
        context = (str(area), str(channel), str(user))
        detail = re.fullmatch(r"详情\s+([0-9]+)(?:\s+(.+))?", text)
        if text.startswith("详情") and detail is None:
            await self._send(handler, "用法: /zj 详情 1 [召唤师名#编号]", channel, area)
            return
        if detail is not None:
            index = int(detail.group(1))
            if index < 1:
                await self._send(handler, "对局序号从 1 开始", channel, area)
                return
            player = detail.group(2)
            if player:
                result = await service.query(player)
            else:
                recent = self._recent_queries.get(context)
                if recent is None or time.monotonic() - recent[0] >= 600:
                    await self._send(handler, "请先查询战绩，或使用 /zj 详情 1 召唤师名#编号", channel, area)
                    return
                result = recent[1]
            if isinstance(result, str):
                await self._send(handler, result, channel, area)
                return
            response = result["games_response"]
            if response.get("code") != 0:
                await self._send(handler, f"战绩读取失败: {response.get('message') or 'FA8 查询失败'}", channel, area)
                return
            games = (response.get("data") or {}).get("games") or []
            if index > len(games):
                await self._send(handler, f"当前查询共 {len(games)} 场，请选择范围内的序号", channel, area)
                return
            result = dict(result, detail_game=games[index - 1], detail_index=index)
        else:
            refresh = text.startswith("刷新 ")
            if refresh:
                text = text[3:].strip()
            await self._send(handler, f"{Msg.SEARCH} 正在查询 {text} 的战绩...", channel, area)
            result = await service.query(text, refresh=True) if refresh else await service.query(text)
        if isinstance(result, str):
            await self._send(handler, result, channel, area)
            return
        if detail is None or detail.group(2):
            now = time.monotonic()
            self._recent_queries = {key: value for key, value in self._recent_queries.items() if now - value[0] < 600}
            if len(self._recent_queries) >= 256:
                self._recent_queries.pop(next(iter(self._recent_queries)))
            self._recent_queries[context] = (now, result)
        image_path: Path | None = None
        try:
            from .render import render_card

            image_path = await render_card(result)
            await handler.sender.upload_and_send_image(str(image_path), channel=channel, area=area)
            return
        except Exception as exc:
            logger.warning("FA8 战绩图片发送失败: %s", exc)
        finally:
            if image_path is not None:
                with contextlib.suppress(OSError):
                    image_path.unlink(missing_ok=True)
        if detail is not None:
            from .detail import format_detail

            reply = format_detail(result)
        else:
            reply = service.format_result(result)
        await self._send(handler, reply, channel, area)
