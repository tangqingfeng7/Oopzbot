import copy
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
for root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from test_lol_fa8_area_search import GAMES, PROFILE  # noqa: E402

from plugins.lol_fa8 import LolFa8Plugin  # noqa: E402
from plugins.lol_fa8.render import build_card_html, load_card_images  # noqa: E402
from plugins.lol_fa8.service import FA8Handler  # noqa: E402


def query_result():
    return {
        "server_name": "联盟三区", "game_name": "测试玩家", "tag_line": "12345",
        "info": copy.deepcopy(PROFILE["data"]), "games_response": copy.deepcopy(GAMES),
    }


class Fa8CardTest(unittest.TestCase):
    def test_summary_uses_all_games_while_only_five_rows_are_shown(self):
        result = query_result()
        games = []
        for index in range(20):
            game = copy.deepcopy(GAMES["data"]["games"][0])
            game["player"].update(win=index < 14, kills=7, deaths=5, assists=10)
            games.append(game)
        result["games_response"]["data"]["games"] = games

        html = build_card_html(result, generated_at=datetime(2026, 11, 5, 9, 30))

        for text in ("近 20 场对局", "70%", "3.40", "最近 5 场", "流光翡翠 II", "2026-11-05 09:30"):
            self.assertIn(text, html)
        self.assertEqual(html.count('<article class="match '), 5)
        self.assertLess(html.index("李青</div>"), html.index("亚索</div>"))

    def test_player_names_and_upstream_messages_remain_text(self):
        result = query_result()
        result["game_name"] = '玩家<&>"'
        result["info"]["rank_error"] = "段位<暂不可用>"

        html = build_card_html(result)

        self.assertIn("玩家&lt;&amp;&gt;&quot;", html)
        self.assertIn("段位&lt;暂不可用&gt;", html)
        self.assertNotIn("玩家<&>", html)

    def test_missing_data_keeps_error_reasons_without_zero_statistics(self):
        result = query_result()
        result["info"].update(
            rank_error="段位服务不可用", player_assets=None, player_assets_error="资产服务不可用",
            champion_mastery=[], champion_mastery_error="熟练度服务不可用",
        )
        result["games_response"] = {"code": 1, "message": "战绩服务不可用"}

        html = build_card_html(result)

        for reason in ("段位服务不可用", "资产服务不可用", "熟练度服务不可用", "战绩服务不可用"):
            self.assertIn(reason, html)
        self.assertIn("战绩暂不可用", html)
        self.assertNotIn("未定级", html)
        self.assertNotIn('class="metric-value accent">0%', html)

    def test_empty_games_show_an_empty_state(self):
        result = query_result()
        result["games_response"] = {"code": 0, "data": {"games": []}}

        html = build_card_html(result)

        self.assertIn("暂无近期战绩", html)
        self.assertIn('class="metric-value accent">—', html)

    def test_owned_heroes_skins_and_level_are_separate_labeled_statistics(self):
        html = build_card_html(query_result())

        self.assertIn("<span>拥有英雄</span><strong>259</strong>", html)
        self.assertIn("<span>拥有皮肤</span><strong>1381</strong>", html)
        self.assertIn("<span>召唤师等级</span><strong>670</strong>", html)

    def test_hero_portraits_and_matching_rank_emblems_are_embedded(self):
        images = {key: "data:image/png;base64,aW1hZ2U=" for key in (
            "champion:Ambessa", "champion:Briar", "champion:LeeSin", "champion:Yasuo",
            "rank:emerald", "rank:unranked",
        )}

        html = build_card_html(query_result(), images=images)

        self.assertEqual(html.count('<img class="champion-portrait"'), 2)
        self.assertEqual(html.count('<img class="mastery-portrait"'), 2)
        self.assertEqual(html.count('<img class="rank-emblem"'), 2)
        self.assertIn('alt="流光翡翠 II"', html)
        self.assertIn('alt="未定级"', html)
        self.assertNotIn('class="champion-portrait placeholder"', html)


class Fa8CardImagesTest(unittest.IsolatedAsyncioTestCase):
    async def test_cached_images_do_not_need_network_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "data" / "lol_fa8" / "images"
            for name in ("Ambessa", "Briar", "LeeSin", "Yasuo"):
                path = cache / "champions" / "16.22.1" / f"{name}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"portrait")
            for tier in ("emerald", "unranked"):
                path = cache / "ranks" / f"{tier}.png"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"emblem")
            http = SimpleNamespace(session=AsyncMock())
            with (
                patch("plugins.lol_fa8.render.PROJECT_ROOT_PATH", root),
                patch("plugins.lol_fa8.render._HTTP", http),
            ):
                images = await load_card_images(query_result())

            self.assertEqual(len(images), 6)
            self.assertTrue(all(source.startswith("data:image/png;base64,") for source in images.values()))
            http.session.assert_not_awaited()


class Fa8ImageDeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "card.png"
        self.path.write_bytes(b"image")
        self.result = query_result()
        self.plugin = LolFa8Plugin()
        self.service = Mock(spec=FA8Handler)
        self.service.query = AsyncMock(return_value=self.result)
        self.service.format_result = Mock(wraps=FA8Handler.format_result)
        self.plugin._handler = self.service
        self.sender = SimpleNamespace(send_message=AsyncMock(), upload_and_send_image=AsyncMock())
        self.handler = SimpleNamespace(sender=self.sender)

    async def test_success_sends_an_image_and_removes_the_temporary_file(self):
        async def upload(path, **kwargs):
            self.assertTrue(Path(path).is_file())

        self.sender.upload_and_send_image.side_effect = upload
        with patch("plugins.lol_fa8.render.render_card", new_callable=AsyncMock, return_value=self.path):
            await self.plugin.dispatch_command("测试玩家#12345", "channel", "area", "user", self.handler)

        self.sender.upload_and_send_image.assert_awaited_once_with(str(self.path), channel="channel", area="area")
        self.assertEqual(self.sender.send_message.await_count, 1)
        self.assertFalse(self.path.exists())
        self.service.query.assert_awaited_once_with("测试玩家#12345")
        self.service.format_result.assert_not_called()

    async def test_upload_failure_reuses_the_query_for_text_and_removes_the_file(self):
        self.sender.upload_and_send_image.side_effect = RuntimeError("上传失败")
        with patch("plugins.lol_fa8.render.render_card", new_callable=AsyncMock, return_value=self.path):
            await self.plugin.dispatch_command("测试玩家#12345", "channel", "area", "user", self.handler)

        self.assertFalse(self.path.exists())
        self.assertIn("LOL 战绩查询 - 联盟三区", self.sender.send_message.await_args.args[0])
        self.service.query.assert_awaited_once()

    async def test_render_failure_returns_the_same_query_as_text(self):
        with patch("plugins.lol_fa8.render.render_card", new_callable=AsyncMock, side_effect=RuntimeError("渲染失败")):
            await self.plugin.dispatch_command("测试玩家#12345", "channel", "area", "user", self.handler)

        self.sender.upload_and_send_image.assert_not_awaited()
        self.assertIn("测试玩家#12345", self.sender.send_message.await_args.args[0])
        self.service.query.assert_awaited_once()

    async def test_query_errors_are_sent_as_text_without_rendering(self):
        self.service.query.return_value = "未找到玩家 测试玩家#12345"
        with patch("plugins.lol_fa8.render.render_card", new_callable=AsyncMock) as render:
            await self.plugin.dispatch_command("测试玩家#12345", "channel", "area", "user", self.handler)

        render.assert_not_awaited()
        self.sender.upload_and_send_image.assert_not_awaited()
        self.assertIn("未找到玩家", self.sender.send_message.await_args.args[0])
