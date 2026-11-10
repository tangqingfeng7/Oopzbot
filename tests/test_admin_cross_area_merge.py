"""跨域成员聚合：同一个人属于多个域时的合并
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from oopz_sdk.models import (  # noqa: E402
    AreaMembersPage,
    UserInfo,
)

from web.admin.members import _members  # noqa: E402


def _member(uid: str, *, role_sort: int = 0, online: int = 0, playing: str = "") -> dict:
    return {
        "uid": uid,
        "online": online,
        "role": role_sort,
        "roleSort": role_sort,
        "playingState": playing,
        "displayType": "MUSIC" if playing else "",
    }


class CrossAreaMergeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _members._members_resp_cache.invalidate()

    async def _run(self, per_area: dict[str, list[dict]], *, keyword: str = "") -> dict:
        names = {aid: f"{aid}域" for aid in per_area}

        sender: Any = AsyncMock()

        async def get_area_members(*, area: str, **_: Any) -> AreaMembersPage:
            return AreaMembersPage.from_api({"members": per_area[area]})

        sender.bot.areas.get_area_members = AsyncMock(side_effect=get_area_members)
        sender.bot.person.get_person_infos_batch = AsyncMock(
            side_effect=lambda uids: [UserInfo(uid=u, name=f"名字-{u}", pid=u) for u in uids]
        )

        with (
            patch.object(_members, "_get_sender", return_value=sender),
            patch.object(_members, "_area_name_map", AsyncMock(return_value=names)),
        ):
            resp = await _members._members_across_all_areas(offset=0, limit=100, keyword=keyword)
        return json.loads(bytes(resp.body))

    async def test_person_in_two_areas_becomes_one_row_with_both_areas(self) -> None:
        data = await self._run({"A": [_member("u1")], "B": [_member("u1")]})

        self.assertEqual(data["total"], 1, "同一个人不该在合并列表里出现两次")
        (row,) = data["members"]
        self.assertEqual(
            sorted(a["areaId"] for a in row["areas"]),
            ["A", "B"],
            "必须列出该成员所属的全部域，只保留一个会误导操作者",
        )

    async def test_highest_role_wins_and_becomes_primary(self) -> None:
        data = await self._run(
            {"A": [_member("u1", role_sort=1)], "B": [_member("u1", role_sort=9)]}
        )

        (row,) = data["members"]
        self.assertEqual(row["roleSort"], 9, "合并后权限应取各域中最高的，不能被低权限域盖掉")
        self.assertEqual(row["areas"][0]["areaId"], "B", "主域取权限最高的那个")
        self.assertEqual(row["areaId"], "B", "兼容字段跟随主域")

    async def test_online_in_any_area_counts_as_online(self) -> None:
        data = await self._run(
            {
                "A": [_member("u1", online=0)],
                "B": [_member("u1", online=1, playing="听歌中")],
            }
        )

        (row,) = data["members"]
        self.assertTrue(row["online"], "任一域在线即视为在线")
        self.assertEqual(row["playingState"], "听歌中", "动态取自其在线的那个域")
        self.assertEqual(data["online"], 1, "在线数按人计，不按域重复计数")

    async def test_distinct_people_are_kept_apart(self) -> None:
        data = await self._run({"A": [_member("u1"), _member("u2")], "B": [_member("u1")]})

        self.assertEqual(data["total"], 2)
        by_uid = {m["uid"]: m for m in data["members"]}
        self.assertEqual(len(by_uid["u1"]["areas"]), 2)
        self.assertEqual(len(by_uid["u2"]["areas"]), 1)

    async def test_failed_area_is_reported_not_silently_dropped(self) -> None:
        names = {"A": "A域", "B": "B域"}
        sender: Any = AsyncMock()

        async def get_area_members(*, area: str, **_: Any) -> AreaMembersPage:
            if area == "B":
                raise RuntimeError("查询数量超过限制")
            return AreaMembersPage.from_api({"members": [_member("u1")]})

        sender.bot.areas.get_area_members = AsyncMock(side_effect=get_area_members)
        sender.bot.person.get_person_infos_batch = AsyncMock(return_value=[UserInfo(uid="u1", name="甲")])

        with (
            patch.object(_members, "_get_sender", return_value=sender),
            patch.object(_members, "_area_name_map", AsyncMock(return_value=names)),
        ):
            resp = await _members._members_across_all_areas(offset=0, limit=100, keyword="")
        data = json.loads(bytes(resp.body))

        self.assertEqual(data["partial"], ["B域"], "取数失败的域要显式告知，避免看起来人变少了")
        self.assertEqual(data["total"], 1)


if __name__ == "__main__":
    unittest.main()
