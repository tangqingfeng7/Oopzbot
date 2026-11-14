"""活跃排行、频道统计与点歌统计插件。"""

from collections.abc import Callable

from fastapi import APIRouter

from core.database import MessageStatsDB, SongCache
from domain.plugins.base import BotModule, PluginCommandCapabilities, PluginMetadata
from oopz.name_resolver import get_resolver
from plugins._shared.command_mixin import PluginCommandMixin
from web.plugin_routes import AdminNavItem

from . import admin

# 「播放排行」「播放历史」会先被音乐的「播放<歌名>」接走，因此不作为 mention 别名。
_COMMANDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "ranking": (("活跃排行", "活跃榜", "排行榜"), ("/ranking", "/活跃", "/活跃排行")),
    "chatstats": (("频道统计", "消息统计"), ("/chatstats", "/频道统计")),
    "topsongs": (("点歌排行", "热歌榜"), ("/topsongs", "/点歌排行", "/播放排行")),
    "recentsongs": (("最近播放",), ("/recentsongs", "/最近播放")),
}
_MENTIONS = {alias: key for key, (mentions, _slash) in _COMMANDS.items() for alias in mentions}
_SLASH = {alias: key for key, (_mentions, slash) in _COMMANDS.items() for alias in slash}


async def _ranking_text(channel: str, area: str) -> str:
    ranking = await MessageStatsDB.get_user_ranking(area, 7, 10)
    if not ranking:
        return "暂无活跃数据"
    resolver = get_resolver()
    lines = ["【近 7 天活跃排行】"]
    for i, r in enumerate(ranking):
        lines.append(f" {i + 1}. {resolver.user(r['user_id'])}  —  {r['total']} 条消息")
    return "\n".join(lines)


async def _channel_stats_text(channel: str, area: str) -> str:
    daily = await MessageStatsDB.get_channel_daily(channel, area, 7)
    if not daily:
        return "暂无频道统计数据"
    lines = ["【近 7 天频道消息统计】"]
    lines.extend(f"  {d['date']}  —  {d['total']} 条" for d in daily)
    lines.append(f"合计: {sum(d['total'] for d in daily)} 条")
    return "\n".join(lines)


async def _top_songs_text(channel: str, area: str) -> str:
    songs = await SongCache.get_top_songs(10)
    if not songs:
        return "暂无播放记录"
    lines = ["【点歌排行榜 Top 10】"]
    for i, s in enumerate(songs):
        lines.append(
            f" {i + 1}. {s.get('song_name', '未知')} - {s.get('artist', '未知')}  ({s.get('play_count', 0)}次)"
        )
    return "\n".join(lines)


async def _recent_songs_text(channel: str, area: str) -> str:
    songs = await SongCache.get_recent_songs(10)
    if not songs:
        return "暂无播放记录"
    lines = ["【最近播放】"]
    for i, s in enumerate(songs):
        played = s.get("last_played_at", "")[:16]
        lines.append(f" {i + 1}. {s.get('song_name', '未知')} - {s.get('artist', '未知')}  ({played})")
    return "\n".join(lines)


_RENDERERS = {
    "ranking": _ranking_text,
    "chatstats": _channel_stats_text,
    "topsongs": _top_songs_text,
    "recentsongs": _recent_songs_text,
}


class StatsPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "统计查询出错"
    command_log_name = "Stats"

    def __init__(self):
        self._unregister_web: Callable[[], None] | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("stats", "活跃排行、频道消息统计、点歌排行与最近播放")

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        return PluginCommandCapabilities(
            mention_prefixes=tuple(_MENTIONS),
            slash_commands=tuple(_SLASH),
        )

    @property
    def private_modules(self) -> tuple[str, ...]:
        return (f"{__name__}.admin",)

    async def handle_mention(self, text, channel, area, user, handler) -> bool:
        command = _MENTIONS.get(text.strip())
        if command is None:
            return False
        await self._run_plugin_command(command, channel, area, user, handler)
        return True

    async def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        key = _SLASH.get((command or "").strip().lower())
        if key is None:
            return False
        await self._run_plugin_command(key, channel, area, user, handler)
        return True

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        text = await _RENDERERS[command_text](channel, area)
        await self._send(handler, text, channel, area)

    async def on_load(self, handler, config=None) -> None:
        if self._unregister_web is not None:
            return
        router = APIRouter()
        router.include_router(admin.router)
        self._unregister_web = handler.register_web(
            router,
            admin_nav=AdminNavItem("activity", "/admin/activity", "活跃"),
        )

    async def on_unload(self) -> None:
        if self._unregister_web is not None:
            self._unregister_web()
            self._unregister_web = None
