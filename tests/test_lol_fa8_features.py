import asyncio
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for root in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(root))

from test_lol_fa8_area_search import CHECK, GAMES, PROFILE  # noqa: E402

from plugins.lol_fa8 import LolFa8Plugin  # noqa: E402
from plugins.lol_fa8.detail import build_detail_html, format_detail  # noqa: E402
from plugins.lol_fa8.service import FA8Handler  # noqa: E402


def result():
    return {"game_name": "测试玩家", "tag_line": "12345", "server_name": "联盟三区",
            "info": copy.deepcopy(PROFILE["data"]), "games_response": copy.deepcopy(GAMES)}


class QueryCacheTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service: Any = FA8Handler({"enabled": True})
        self.service._client = SimpleNamespace(
            find_player=AsyncMock(return_value=copy.deepcopy(CHECK)),
            query_summoner=AsyncMock(return_value=copy.deepcopy(PROFILE)),
            query_games=AsyncMock(return_value=copy.deepcopy(GAMES)), stop=AsyncMock(),
        )
        self.addAsyncCleanup(self.service.close)

    async def test_concurrent_queries_and_cached_results_use_one_request_chain(self):
        replies = await asyncio.gather(*(self.service.query("测试玩家 # 12345") for _ in range(8)))
        replies[0]["info"]["summoner"]["level"] = -1
        cached = await self.service.query("测试玩家#12345")
        self.assertEqual(cached["info"]["summoner"]["level"], 670)
        self.service._client.find_player.assert_awaited_once()
        self.service._client.query_games.assert_awaited_once()
        self.assertIn("queried_at", cached)

    async def test_refresh_expiry_and_area_validation(self):
        await self.service.query("测试玩家#12345")
        await self.service.query("测试玩家#12345", refresh=True)
        self.assertEqual(self.service._client.find_player.await_count, 2)
        self.service._query_cache = {key: (0, value[1]) for key, value in self.service._query_cache.items()}
        await self.service.query("测试玩家#12345")
        self.assertEqual(self.service._client.find_player.await_count, 3)
        self.assertIn("与指定大区", await self.service.query("艾欧尼亚 测试玩家#12345"))

    async def test_errors_and_partial_results_are_not_cached(self):
        self.service._client.query_games.return_value = {"code": 1, "message": "暂不可用"}
        await self.service.query("测试玩家#12345")
        self.service._client.query_games.return_value = copy.deepcopy(GAMES)
        self.assertEqual((await self.service.query("测试玩家#12345"))["games_response"]["code"], 0)
        self.assertEqual(self.service._client.query_games.await_count, 2)

    async def test_cancelled_waiter_does_not_cancel_shared_query(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def find(*args):
            entered.set()
            await release.wait()
            return copy.deepcopy(CHECK)

        self.service._client.find_player.side_effect = find
        first = asyncio.create_task(self.service.query("测试玩家#12345"))
        await entered.wait()
        second = asyncio.create_task(self.service.query("测试玩家#12345"))
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        release.set()
        self.assertIsInstance(await second, dict)
        self.service._client.find_player.assert_awaited_once()

    async def test_close_cancels_inflight_queries(self):
        entered = asyncio.Event()

        async def find(*args):
            entered.set()
            await asyncio.Event().wait()

        self.service._client.find_player.side_effect = find
        waiter = asyncio.create_task(self.service.query("测试玩家#12345"))
        await entered.wait()
        await self.service.close()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertFalse(self.service._pending_queries)


class DetailCommandsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.plugin: Any = LolFa8Plugin()
        self.plugin._handler = Mock(spec=FA8Handler)
        self.plugin._handler.query = AsyncMock(return_value=result())
        self.plugin._handler.format_result.return_value = "summary"
        self.sender = SimpleNamespace(send_message=AsyncMock(), upload_and_send_image=AsyncMock())
        self.handler = SimpleNamespace(sender=self.sender)

    async def send(self, text, user="user", channel="channel"):
        await self.plugin.dispatch_command(text, channel, "area", user, self.handler)

    async def test_detail_uses_own_recent_query_and_text_fallback(self):
        with patch("plugins.lol_fa8.render.render_card", side_effect=RuntimeError("渲染不可用")):
            await self.send("测试玩家#12345")
            await self.send("详情 1")
            self.assertIn("第 1 场", self.sender.send_message.await_args.args[0])
            self.plugin._handler.query.assert_awaited_once()
            await self.send("详情 1", user="other")
            self.assertIn("请先查询", self.sender.send_message.await_args.args[0])
            await self.send("详情 1", channel="other")
            self.assertIn("请先查询", self.sender.send_message.await_args.args[0])
            await self.send("详情 99")
            self.assertIn("当前查询共 2 场", self.sender.send_message.await_args.args[0])

    async def test_explicit_player_image_and_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "card.png"
            path.write_bytes(b"image")
            with patch("plugins.lol_fa8.render.render_card", new_callable=AsyncMock, return_value=path) as render:
                await self.send("详情 2 测试玩家#12345")
                assert render.await_args is not None
                self.assertEqual(render.await_args.args[0]["detail_index"], 2)
                self.sender.upload_and_send_image.assert_awaited_once()
                self.assertFalse(path.exists())
            with patch("plugins.lol_fa8.render.render_card", side_effect=RuntimeError("渲染不可用")):
                await self.send("刷新 测试玩家#12345")
            self.plugin._handler.query.assert_awaited_with("测试玩家#12345", refresh=True)

    async def test_invalid_expired_context_and_failed_games(self):
        await self.send("详情 0")
        self.assertIn("从 1 开始", self.sender.send_message.await_args.args[0])
        await self.send("详情 abc")
        self.assertIn("用法", self.sender.send_message.await_args.args[0])
        self.plugin._recent_queries[("area", "channel", "user")] = (0, result())
        await self.send("详情 1")
        self.assertIn("请先查询", self.sender.send_message.await_args.args[0])
        self.plugin._handler.query.return_value["games_response"] = {"code": 1, "message": "战绩不可用"}
        await self.send("详情 1 测试玩家#12345")
        self.assertIn("战绩不可用", self.sender.send_message.await_args.args[0])


class DetailCardTest(unittest.TestCase):
    def test_real_field_names_equipment_and_missing_statistics(self):
        data = result()
        game = data["games_response"]["data"]["games"][0]
        player = dict(game["player"], display_name="玩家<甲>", is_current=True,
                      damage_dealt=12345, gold=9000, vision_score=0, items=[{"id": 1001}])
        game["teams"] = [{"label": "蓝方", "win": True, "kills": 12, "participants": [player]}]
        data.update(detail_game=game, detail_index=1)
        html = build_detail_html(data, images={"item:1001": "data:image/png;base64,aW1hZ2U="})
        for text in ("12,345", "玩家&lt;甲&gt;", "装备 1001", "本人", "视野", "承伤"):
            self.assertIn(text, html)
        self.assertNotIn("玩家<甲>", html)
        self.assertIn("承伤: —", format_detail(data))
        self.assertIn("视野: —", format_detail(data))
