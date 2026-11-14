"""FA8 全服搜索、大区核对与消息格式。"""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
for root in (REPO_ROOT, REPO_ROOT / "src"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from plugins.lol_fa8.service import FA8Handler  # noqa: E402

CHECK = {"code": 0, "data": {
    "exists": True, "puuid": "player-id", "re": "CQ100",
    "game_name": "测试玩家", "tag_line": "12345", "region_name": "联盟三区",
}}
PROFILE = {"code": 0, "data": {
    "region": {"name": "联盟三区", "re": "CQ100"},
    "summoner": {"level": 670, "lastGameDate": 1793793660000},
    "alias": {"game_name": "测试玩家", "tag_line": "12345"},
    "player_assets": {"heroes": 259, "skins": 1381},
    "ranked_stats": {"queues": [{
        "queueType": "RANKED_SOLO_5X5", "tier_label": "流光翡翠", "rank_label": "II",
        "wins": 32, "losses": 0, "leaguePoints": 45,
        "highest_tier_label": "流光翡翠", "highest_rank_label": "II",
    }]},
    "champion_mastery": [
        {"name": "亚索", "level": 27, "points": 272261},
        {"name": "李青", "level": 33, "points": 374950},
    ],
}}
GAMES = {"code": 0, "data": {"games": [
    {"mode": "海克斯乱斗", "created_at": 1793792761473, "duration": 927,
     "result": "胜利", "win": True, "player": {
         "champion_name": "Ambessa", "champion_title": "安蓓萨",
         "kills": 11, "deaths": 12, "assists": 25, "win": True,
     }},
    {"mode": "海克斯乱斗", "created_at": 1793790285000, "duration": 149,
     "result": "失败", "win": False, "player": {
         "champion_name": "Briar", "champion_title": "贝蕾亚",
         "kills": 0, "deaths": 0, "assists": 1, "win": False,
     }},
]}}


class Fa8QueryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.handler = FA8Handler({"enabled": True, "default_area": "1"})
        self.client = AsyncMock()
        self.client.find_player.return_value = copy.deepcopy(CHECK)
        self.client.query_summoner.return_value = copy.deepcopy(PROFILE)
        self.client.query_games.return_value = copy.deepcopy(GAMES)
        self.handler._client = self.client

    async def test_global_search_uses_returned_region(self):
        reply = await self.handler.query_and_format("测试玩家 # 12345")
        self.client.find_player.assert_awaited_once_with("测试玩家", "12345")
        self.client.query_summoner.assert_awaited_once_with("player-id", "CQ100")
        self.client.query_games.assert_awaited_once_with("player-id", "CQ100")
        self.assertIn("LOL 战绩查询 - 联盟三区", reply)
        self.assertIn("等级: 670", reply)
        self.assertIn("最近游戏: 2026-11-04 20:01", reply)
        self.assertIn("英雄: 259 个 | 皮肤: 1381 个", reply)
        self.assertIn("单双排位: 流光翡翠 II (32胜0负) 胜点45", reply)
        self.assertIn("灵活排位: 未定级 / 无段位", reply)
        self.assertIn("1. 李青 - 33级英雄成就 (374,950)", reply)
        self.assertIn("近期战绩: 1胜 1负 (胜率50%)", reply)
        self.assertIn("胜利 海克斯乱斗 安蓓萨 11/12/25 [15:27] 2026-11-04 19:46", reply)
        self.assertIn("失败 海克斯乱斗 贝蕾亚 0/0/1 [2:29]", reply)

    async def test_merged_region_accepts_group_and_original_server(self):
        for prefix in ("3", "三区", "联盟三区", "班德尔城", "5"):
            with self.subTest(prefix=prefix):
                # 数字 5 表示联盟五区，不是原服务器 ID 5。
                reply = await self.handler.query_and_format(f"{prefix} 测试玩家#12345")
                if prefix == "5":
                    self.assertIn("与指定大区（联盟五区）不符", reply)
                else:
                    self.assertIn("LOL 战绩查询 - 联盟三区", reply)

    async def test_wrong_region_does_not_query_games(self):
        reply = await self.handler.query_and_format("艾欧尼亚 测试玩家#12345")
        self.assertIn("该玩家位于联盟三区", reply)
        self.assertIn("与指定大区（艾欧尼亚）不符", reply)
        self.client.query_games.assert_not_awaited()

    async def test_errors_are_not_reported_as_missing_players(self):
        for message, detail in (
            ("请先登录", {"login_required": True}),
            ("需要赞助会员", {"vip_required": True}),
            ("查询次数不足", {}),
            ("服务暂不可用", {"service_unavailable": True}),
        ):
            with self.subTest(message=message):
                self.client.find_player.return_value = {"code": 1, "message": message, "data": detail}
                reply = await self.handler.query_and_format("测试玩家#12345")
                self.assertIn(message, reply)
                self.assertNotIn("未找到", reply)
        self.client.query_summoner.assert_not_awaited()

    async def test_nonexistent_player(self):
        self.client.find_player.return_value = {"code": 0, "data": {"exists": False}}
        reply = await self.handler.query_and_format("测试玩家#12345")
        self.assertIn("未找到玩家 测试玩家#12345", reply)
        self.client.query_summoner.assert_not_awaited()

    async def test_missing_player_identifier(self):
        self.client.find_player.return_value = {"code": 0, "data": {"exists": True}}
        self.assertIn("未返回玩家标识或大区", await self.handler.query_and_format("测试玩家#12345"))

    async def test_profile_error(self):
        self.client.query_summoner.return_value = {"code": 1, "message": "资料服务暂不可用"}
        self.assertIn("资料查询失败: 资料服务暂不可用", await self.handler.query_and_format("测试玩家#12345"))
        self.client.query_games.assert_not_awaited()

    async def test_partial_failures_keep_profile_and_error_messages(self):
        data = self.client.query_summoner.return_value["data"]
        data.update({"rank_error": "段位服务不可用", "player_assets": None,
                     "player_assets_error": "资产服务不可用", "champion_mastery": [],
                     "champion_mastery_error": "熟练度服务不可用"})
        self.client.query_games.return_value = {"code": 1, "message": "战绩需要赞助会员"}
        reply = await self.handler.query_and_format("测试玩家#12345")
        for text in ("等级: 670", "段位读取失败: 段位服务不可用", "玩家资产读取失败: 资产服务不可用",
                     "英雄熟练度读取失败: 熟练度服务不可用", "战绩读取失败: 战绩需要赞助会员"):
            self.assertIn(text, reply)
        self.assertNotIn("未定级", reply)
        self.assertNotIn("0胜 0负", reply)

    async def test_empty_games(self):
        self.client.query_games.return_value = {"code": 0, "data": {"games": []}}
        self.assertIn("暂无近期战绩", await self.handler.query_and_format("测试玩家#12345"))

    async def test_invalid_input_never_calls_api(self):
        for name in ("", "测试玩家", "测试玩家#abc", "#12345", "测试玩家#123#45"):
            self.assertIn("请输入召唤师名#数字编号", await self.handler.query_and_format(name))
        self.client.find_player.assert_not_awaited()

    async def test_unload_closes_client(self):
        await self.handler.close()
        self.client.stop.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
