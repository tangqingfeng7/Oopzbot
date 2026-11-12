"""每日一句 / 统计 / 定时任务 / 关键词回复插件的命令与生命周期。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
for root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from oopz_sdk.models.general import DailySpeech  # noqa: E402

from app.infrastructure.plugin_runtime import PluginRegistry  # noqa: E402
from domain.plugins.base import PluginMetadata  # noqa: E402
from domain.plugins.plugin_config import PluginConfig  # noqa: E402
from plugins.daily_speech import DailySpeechPlugin  # noqa: E402
from plugins.keyword_reply import KeywordReplyPlugin, match_reply  # noqa: E402
from plugins.scheduler import SchedulerPlugin  # noqa: E402
from plugins.stats import StatsPlugin  # noqa: E402


def _config(name: str, values: dict[str, Any]) -> PluginConfig:
    return PluginConfig.from_mapping(name, values, f"config/plugins/{name}/config.json", exists=True)


def _host(*, is_admin: bool = True):
    sender = SimpleNamespace(send_message=AsyncMock(), bot=SimpleNamespace(general=SimpleNamespace()))
    return SimpleNamespace(
        sender=sender,
        services=SimpleNamespace(routing=SimpleNamespace(access=SimpleNamespace(is_admin=lambda _uid: is_admin))),
        register_web=Mock(return_value=Mock()),
    )


def _last_text(host) -> str:
    return host.sender.send_message.call_args.args[0]


class DailySpeechPluginTest(unittest.IsolatedAsyncioTestCase):
    async def test_formats_speech_and_reports_failure(self) -> None:
        plugin = DailySpeechPlugin()
        host = _host()
        host.sender.bot.general.get_daily_speech = AsyncMock()
        for payload, expected in [
            ({"words": "一句话", "author": "作者"}, "「一句话」\n—— 作者"),
            ({"words": "一句话"}, "「一句话」"),
            ({}, "暂无内容"),
        ]:
            with self.subTest(payload=payload):
                host.sender.bot.general.get_daily_speech.return_value = DailySpeech.from_api(payload)
                self.assertTrue(await plugin.handle_mention("每日一句", "c", "a", "u", host))
                self.assertEqual(_last_text(host), expected)

        host.sender.bot.general.get_daily_speech.side_effect = RuntimeError("请求失败")
        self.assertTrue(await plugin.handle_slash("/daily", None, None, "c", "a", "u", host))
        self.assertEqual(_last_text(host), "获取每日一句失败: 请求失败")

    async def test_only_exact_aliases_are_handled(self) -> None:
        host = _host()
        self.assertFalse(await DailySpeechPlugin().handle_mention("一句话总结", "c", "a", "u", host))
        host.sender.send_message.assert_not_called()


class StatsPluginTest(unittest.IsolatedAsyncioTestCase):
    async def test_mention_and_slash_aliases_render_the_same_stats(self) -> None:
        plugin = StatsPlugin()
        host = _host()
        songs = [{"song_name": "夜曲", "artist": "周杰伦", "play_count": 3}]
        with patch("plugins.stats.SongCache.get_top_songs", AsyncMock(return_value=songs)):
            self.assertTrue(await plugin.handle_mention("点歌排行", "c", "a", "u", host))
            mention_text = _last_text(host)
            self.assertTrue(await plugin.handle_slash("/播放排行", None, None, "c", "a", "u", host))
        self.assertEqual(_last_text(host), mention_text)
        self.assertIn("1. 夜曲 - 周杰伦  (3次)", mention_text)

    async def test_play_prefixed_text_is_left_to_music(self) -> None:
        host = _host()
        for text in ("播放历史", "播放排行"):
            self.assertFalse(await StatsPlugin().handle_mention(text, "c", "a", "u", host))

    async def test_ranking_uses_current_area(self) -> None:
        ranking = AsyncMock(return_value=[{"user_id": "u1", "total": 5}])
        resolver = Mock()
        resolver.user.return_value = "张三"
        host = _host()
        with (
            patch("plugins.stats.MessageStatsDB.get_user_ranking", ranking),
            patch("plugins.stats.get_resolver", return_value=resolver),
        ):
            await StatsPlugin().handle_mention("活跃排行", "c", "area-1", "u", host)

        ranking.assert_awaited_once_with("area-1", 7, 10)
        self.assertIn("1. 张三  —  5 条消息", _last_text(host))


class SchedulerPluginTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.plugin = SchedulerPlugin()
        self.host = _host()
        await self.plugin.on_load(self.host, _config("scheduler", {"reminder_max_per_user": 2}))
        self.addAsyncCleanup(self.plugin.on_unload)

    async def test_load_starts_workers_and_registers_admin_page(self) -> None:
        assert self.plugin._reminder is not None
        self.assertEqual(self.plugin._reminder._max_per_user, 2)
        self.host.register_web.assert_called_once()
        self.assertEqual(self.host.register_web.call_args.kwargs["admin_nav"].href, "/admin/scheduler")

        await self.plugin.on_unload()
        self.host.register_web.return_value.assert_called_once_with()
        self.assertTrue(self.plugin._reminder.stopping)

    async def test_reminder_commands_are_public(self) -> None:
        host = _host(is_admin=False)
        create = AsyncMock(return_value="已设置提醒")
        with patch.object(self.plugin._reminder, "create_reminder", create):
            self.assertTrue(await self.plugin.handle_mention("提醒 30分钟后 喝水", "c", "a", "u", host))
        create.assert_awaited_once_with("30分钟后 喝水", "c", "a", "u")

        with patch("plugins.scheduler.commands.ReminderDB.get_user_pending", AsyncMock(return_value=[])):
            self.assertTrue(await self.plugin.handle_mention("提醒列表", "c", "a", "u", host))
        self.assertEqual(_last_text(host), "你没有待执行的提醒")

        delete = AsyncMock(return_value=True)
        with patch("plugins.scheduler.commands.ReminderDB.delete_user_reminder", delete):
            self.assertTrue(await self.plugin.handle_slash("/remind", "del", "3", "c", "a", "u", host))
        delete.assert_awaited_once_with(3, "u")

    async def test_scheduled_messages_require_admin(self) -> None:
        host = _host(is_admin=False)
        create = AsyncMock(return_value=1)
        with patch("plugins.scheduler.commands.ScheduledMessageDB.create", create):
            self.assertTrue(await self.plugin.handle_mention("添加定时消息 08:00 早上好", "c", "a", "u", host))
            self.assertTrue(await self.plugin.handle_slash("/schedule", "add", "08:00 早上好", "c", "a", "u", host))
        create.assert_not_awaited()
        self.assertIn("无权限", _last_text(host))

    async def test_admin_can_add_scheduled_message(self) -> None:
        create = AsyncMock(return_value=7)
        with patch("plugins.scheduler.commands.ScheduledMessageDB.create", create):
            await self.plugin.handle_mention("添加定时消息 08:00 [0,1] 早上好", "c", "a", "u", self.host)
        create.assert_awaited_once_with("早上好", 8, 0, "c", "a", "早上好", "0,1")
        self.assertIn("ID: 7", _last_text(self.host))

    async def test_slash_usage_without_arguments(self) -> None:
        await self.plugin.handle_slash("/schedule", "del", None, "c", "a", "u", self.host)
        self.assertEqual(_last_text(self.host), "用法: /schedule del <ID>")
        await self.plugin.handle_slash("/remind", None, None, "c", "a", "u", self.host)
        self.assertIn("/remind list", _last_text(self.host))


class KeywordReplyPluginTest(unittest.IsolatedAsyncioTestCase):
    def test_exact_match_wins_over_substring(self) -> None:
        replies = {"好": "包含", "你好": "整句"}
        self.assertEqual(match_reply(replies, " 你好 "), "整句")
        self.assertEqual(match_reply(replies, "大家好呀"), "包含")
        self.assertEqual(match_reply({"Ping": "pong"}, "PING"), "pong")
        self.assertIsNone(match_reply(replies, "再见"))

    async def test_configured_replies_answer_plain_messages(self) -> None:
        plugin = KeywordReplyPlugin()
        host = _host()
        await plugin.on_load(host, _config("keyword_reply", {"keyword_replies": {"hello": "自动回复"}}))
        self.addAsyncCleanup(plugin.on_unload)

        self.assertTrue(await plugin.handle_message("hello", "c", "a", "u", host))
        host.sender.send_message.assert_awaited_once_with("自动回复", channel="c", area="a")
        self.assertFalse(await plugin.handle_message("你好", "c", "a", "u", host))
        self.assertEqual(plugin.replies, {"hello": "自动回复"})

    async def test_registry_stops_at_first_plugin_that_replies(self) -> None:
        class OtherKeywordReply(KeywordReplyPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata("other_keyword_reply", "测试")

        registry = PluginRegistry()
        first, second = KeywordReplyPlugin(), OtherKeywordReply()
        first._replies = {"hi": "first"}
        second._replies = {"hi": "second"}
        await registry.register(first)
        await registry.register(second)
        host = _host()

        self.assertTrue(await registry.try_dispatch_message("hi", "c", "a", "u", host))
        self.assertFalse(await registry.try_dispatch_message("   ", "c", "a", "u", host))
        host.sender.send_message.assert_awaited_once_with("first", channel="c", area="a")


class FeaturePluginLoadTest(unittest.IsolatedAsyncioTestCase):
    async def test_plugins_load_through_runtime_and_mount_admin_pages(self) -> None:
        import tempfile

        from starlette.testclient import httpx  # pyright: ignore[reportPrivateImportUsage]

        from app.infrastructure.runtime import PluginHost, PluginRuntime
        from web import web_player
        from web.admin.shared import _pages

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runtime = PluginRuntime(state_path=Path(directory.name) / "plugins.json")
        self.addAsyncCleanup(runtime.stop)
        host = PluginHost(cast(Any, SimpleNamespace(sender=_host().sender)), lambda: _host().services)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web_player.app, client=("127.0.0.1", 50000)),
            base_url="http://localhost",
        )
        self.addAsyncCleanup(client.aclose)

        pages = {
            "daily_speech": None,
            "stats": "/admin/activity",
            "scheduler": "/admin/scheduler",
            "keyword_reply": "/admin/keyword-reply",
        }
        # 卸载会从 sys.modules 移除插件模块，退出时恢复，避免影响其他用例的 patch 目标。
        with patch.object(_pages, "_admin_enabled", return_value=True), patch.dict(sys.modules):
            for name, page in pages.items():
                with self.subTest(plugin=name):
                    result = await runtime.load(name, handler=host)
                    self.assertTrue(result.ok, result.message)
                    if page:
                        self.assertEqual((await client.get(page)).status_code, 200)
                        self.assertTrue((await runtime.unload(name, handler=host)).ok)
                        self.assertEqual((await client.get(page)).status_code, 404)


if __name__ == "__main__":
    unittest.main()
