import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.models import OperationResult  # noqa: E402

from core.redis_keys import (  # noqa: E402
    CURRENT,
    PLAY_STATE,
    QUEUE,
    VOLUME,
    WEB_COMMANDS,
    area_key,
)


class AreaKeyTest(unittest.TestCase):
    """area_key 早先硬假设 base 含 ':' 且前缀为 'music'，传别的会 IndexError。"""

    def test_existing_keys_are_unchanged(self) -> None:
        # 这几条是线上实际在用的键，改法必须完全保形
        self.assertEqual(area_key(QUEUE, "A1"), "music:A1:queue")
        self.assertEqual(area_key(CURRENT, "A1"), "music:A1:current")
        self.assertEqual(area_key(PLAY_STATE, "A1"), "music:A1:play_state")
        self.assertEqual(area_key(VOLUME, "A1"), "music:A1:volume")
        self.assertEqual(area_key(WEB_COMMANDS, "A1"), "music:A1:web_commands")

    def test_empty_area_is_rejected_instead_of_using_global_key(self) -> None:
        with self.assertRaises(ValueError):
            area_key(QUEUE, "")

    def test_base_without_colon_does_not_raise(self) -> None:
        self.assertEqual(area_key("volume", "A1"), "volume:A1")

    def test_prefix_is_taken_from_base_not_hardcoded(self) -> None:
        # 早先无论 base 是什么都拼死 "music:" 前缀
        self.assertEqual(area_key("chat:memory", "A1"), "chat:A1:memory")


class StatisticsPlatformCountTest(unittest.IsolatedAsyncioTestCase):
    """每日首条记录曾出现 total_plays=1 但该平台计数为 2。"""

    async def test_first_write_of_the_day_counts_once(self) -> None:
        import core.database as database

        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(database, "DB_PATH", os.path.join(directory, "stats.db")),
        ):
            await database.init_database()
            await database.Statistics.update_today("netease", cache_hit=False)
            today = await database.Statistics.get_today()

        assert today is not None
        self.assertEqual(today["total_plays"], 1)
        self.assertEqual(today["platform_breakdown"], {"netease": 1})


class EditUserRoleLockTest(unittest.IsolatedAsyncioTestCase):
    """editUserRole 是「读-改-写」且服务端全量覆盖，并发会互相覆盖。

    锁已从旧的 `oopz.oopz_api` 模块级字典挪到网关实例的 `_role_locks`，
    按 (域, 目标 uid) 分桶，语义不变。
    """

    def _gateway(self):
        import app.infrastructure.gateways.sender_gateway as module

        gateway = module.SenderGateway.__new__(module.SenderGateway)
        gateway._role_locks = {}
        gateway.bot = AsyncMock()
        gateway.bot.areas.cache = mock.Mock()
        gateway.bot.areas.edit_user_role = AsyncMock(return_value=OperationResult())
        gateway._default_area = lambda area=None: area or "area-default"
        return gateway

    async def _lock_for(self, gateway, area: str, uid: str):
        await gateway.edit_user_role(uid, 1, True, area=area)
        return gateway._role_locks[(area, uid)]

    async def test_same_user_shares_a_lock(self) -> None:
        gateway = self._gateway()
        first = await self._lock_for(gateway, "area-1", "u1")
        second = await self._lock_for(gateway, "area-1", "u1")
        self.assertIs(first, second)

    async def test_different_users_do_not_share_a_lock(self) -> None:
        gateway = self._gateway()
        self.assertIsNot(
            await self._lock_for(gateway, "area-1", "u1"),
            await self._lock_for(gateway, "area-1", "u2"),
        )

    async def test_different_areas_do_not_share_a_lock(self) -> None:
        gateway = self._gateway()
        self.assertIsNot(
            await self._lock_for(gateway, "area-1", "u1"),
            await self._lock_for(gateway, "area-2", "u1"),
        )

    async def test_same_user_edits_are_serialized(self) -> None:
        """同一用户的两次改动必须串行，否则后写会覆盖前写。"""
        gateway = self._gateway()
        inside = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def slow_edit(*_args):
            order.append("enter")
            inside.set()
            await asyncio.wait_for(release.wait(), timeout=2)
            order.append("exit")
            return OperationResult()

        gateway.bot.areas.edit_user_role = AsyncMock(side_effect=slow_edit)

        first = asyncio.create_task(gateway.edit_user_role("u1", 1, True, area="area-1"))
        await asyncio.wait_for(inside.wait(), timeout=1)
        second = asyncio.create_task(gateway.edit_user_role("u1", 2, True, area="area-1"))
        await asyncio.sleep(0.05)

        self.assertEqual(order, ["enter"], "第一次尚未完成，第二次不得进入临界区")
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=2)
        self.assertEqual(order, ["enter", "exit", "enter", "exit"])


if __name__ == "__main__":
    unittest.main()
