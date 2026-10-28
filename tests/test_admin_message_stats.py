"""消息排行榜在名称缓存缺失时应补全昵称，并保留接口失败时的统计。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz.name_resolver import NameResolver  # noqa: E402
from web.admin.scheduler import admin_message_stats_ranking  # noqa: E402


class MessageStatsRankingNameTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(patch("oopz.name_resolver.NAMES_FILE", str(
            Path(self.directory.name) / "names.json",
        )))
        self.enterContext(patch.object(NameResolver, "_instance", None))
        self.enterContext(patch.object(NameResolver, "_load_config_names"))
        self.resolver = NameResolver()
        self.gateway = Mock()
        self.gateway.get_person_infos_batch = AsyncMock(return_value={})
        await self.resolver.bind_gateway(self.gateway)
        self.addAsyncCleanup(self.resolver.close)
        self.enterContext(patch("web.admin.scheduler.get_resolver", return_value=self.resolver))
        self.ranking = self.enterContext(patch(
            "web.admin.scheduler.MessageStatsDB.get_user_ranking", new_callable=AsyncMock,
        ))

    async def test_new_member_name_is_fetched_and_reused(self) -> None:
        uid = "981599abcdef7056"
        self.ranking.return_value = [{"user_id": uid, "total": 2}]
        self.gateway.get_person_infos_batch.return_value = {uid: {"name": "新成员昵称"}}

        for _ in range(2):
            response = await admin_message_stats_ranking(days=7, limit=10, area_id="area-1")
            payload = json.loads(response.body)
            self.assertEqual(payload["ranking"][0]["display_name"], "新成员昵称")
            self.assertEqual(payload["ranking"][0]["total"], 2)

        self.gateway.get_person_infos_batch.assert_awaited_once_with([uid])
        self.ranking.assert_awaited_with("area-1", days=7, limit=10)

    async def test_failed_name_lookup_keeps_statistics_and_can_retry(self) -> None:
        uid = "981599abcdef7056"
        self.ranking.return_value = [{"user_id": uid, "total": 2}]
        self.gateway.get_person_infos_batch.side_effect = [
            RuntimeError("temporary failure"), {uid: {"nickname": "恢复后的昵称"}},
        ]

        with self.assertLogs("WebPlayerAdmin", level="WARNING"):
            response = await admin_message_stats_ranking(days=7, limit=10, area_id="")
        payload = json.loads(response.body)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ranking"][0]["display_name"], "981599..7056")
        self.assertEqual(payload["ranking"][0]["total"], 2)

        response = await admin_message_stats_ranking(days=7, limit=10, area_id="")
        self.assertEqual(json.loads(response.body)["ranking"][0]["display_name"], "恢复后的昵称")


if __name__ == "__main__":
    unittest.main()
