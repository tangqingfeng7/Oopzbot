import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core import database  # noqa: E402
from core.database import (  # noqa: E402
    ImageCache,
    MessageStatsDB,
    ReminderDB,
    ScheduledMessageDB,
    SongCache,
    Statistics,
    cn_today,
    db_connection,
    init_database,
)


class AsyncDatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    """每个用例独占一个临时库文件，避免污染开发数据。"""

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(
            database, "DB_PATH", os.path.join(self._tmpdir.name, "test_cache.db")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmpdir.cleanup)
        await init_database()

    @staticmethod
    async def _table_names() -> set[str]:
        async with (
            db_connection() as conn,
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor,
        ):
            return {row["name"] for row in await cursor.fetchall()}


class DatabaseSchemaTest(AsyncDatabaseTestCase):
    async def test_init_database_creates_core_tables(self) -> None:
        """启动路径直接 await 建表，不再经线程桥接。"""
        tables = await self._table_names()
        self.assertLessEqual(
            {
                "image_cache",
                "song_cache",
                "play_history",
                "statistics",
                "message_stats",
                "scheduled_messages",
                "reminders",
            },
            tables,
        )

    async def test_init_database_is_idempotent(self) -> None:
        await init_database()
        self.assertIn("statistics", await self._table_names())


class TransactionBoundaryTest(AsyncDatabaseTestCase):
    async def test_connection_commits_on_success(self) -> None:
        async with db_connection() as conn:
            await conn.execute(
                "INSERT INTO reminders "
                "(user_id, channel_id, area_id, message_text, fire_at, fired, created_at) "
                "VALUES ('u1', 'c1', 'a1', 'hi', '2026-01-01 00:00:00', 0, '2026-01-01 00:00:00')"
            )
        rows = await ReminderDB.get_all_pending()
        self.assertEqual(len(rows), 1)

    async def test_connection_rolls_back_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            async with db_connection() as conn:
                await conn.execute(
                    "INSERT INTO reminders "
                    "(user_id, channel_id, area_id, message_text, fire_at, fired, created_at) "
                    "VALUES ('u2', 'c1', 'a1', 'bye', '2026-01-01 00:00:00', 0, '2026-01-01 00:00:00')"
                )
                raise RuntimeError("模拟事务中途失败")
        self.assertEqual(await ReminderDB.get_all_pending(), [])

    async def test_failed_transaction_does_not_leak_to_later_writes(self) -> None:
        with self.assertRaises(RuntimeError):
            async with db_connection() as conn:
                await conn.execute("INSERT INTO statistics (date) VALUES ('2026-01-01')")
                raise RuntimeError("模拟事务中途失败")
        await Statistics.update_today("netease")
        today = await Statistics.get_today()
        self.assertIsNotNone(today)
        assert today is not None
        self.assertEqual(today["total_plays"], 1)


class ScheduledMessageFlowTest(AsyncDatabaseTestCase):
    async def test_crud_round_trip(self) -> None:
        task_id = await ScheduledMessageDB.create(
            "晨间问候", 8, 0, "channel-1", "area-1", "早上好", "0,1,2,3,4,5,6"
        )
        self.assertGreater(task_id, 0)

        tasks = await ScheduledMessageDB.get_all()
        self.assertEqual([t["id"] for t in tasks], [task_id])

        self.assertTrue(await ScheduledMessageDB.update(task_id, message_text="早安"))
        task = await ScheduledMessageDB.get_by_id(task_id)
        assert task is not None
        self.assertEqual(task["message_text"], "早安")

        self.assertIs(await ScheduledMessageDB.toggle(task_id), False)
        self.assertIs(await ScheduledMessageDB.toggle(task_id), True)
        self.assertTrue(await ScheduledMessageDB.delete(task_id))
        self.assertEqual(await ScheduledMessageDB.get_all(), [])

    async def test_due_task_is_returned_once_per_day(self) -> None:
        task_id = await ScheduledMessageDB.create(
            "整点播报", 8, 0, "channel-1", "area-1", "整点了", "0,1,2,3,4,5,6"
        )
        due = await ScheduledMessageDB.get_due_tasks(9, 0, 0, "2026-01-01")
        self.assertEqual([t["id"] for t in due], [task_id])

        await ScheduledMessageDB.mark_fired(task_id, "2026-01-01")
        self.assertEqual(await ScheduledMessageDB.get_due_tasks(9, 0, 0, "2026-01-01"), [])
        self.assertEqual(
            [t["id"] for t in await ScheduledMessageDB.get_due_tasks(9, 0, 1, "2026-01-02")],
            [task_id],
        )

    async def test_weekday_filter_excludes_other_days(self) -> None:
        await ScheduledMessageDB.create(
            "周一提醒", 8, 0, "channel-1", "area-1", "周一了", "0"
        )
        self.assertEqual(await ScheduledMessageDB.get_due_tasks(9, 0, 3, "2026-01-01"), [])


class ReminderFlowTest(AsyncDatabaseTestCase):
    async def test_pending_reminder_fires_once(self) -> None:
        reminder_id = await ReminderDB.create(
            "user-1", "channel-1", "area-1", "喝水", "2026-01-01 08:00:00"
        )
        pending = await ReminderDB.get_pending("2026-01-01 09:00:00")
        self.assertEqual([r["id"] for r in pending], [reminder_id])

        await ReminderDB.mark_fired(reminder_id)
        self.assertEqual(await ReminderDB.get_pending("2026-01-01 09:00:00"), [])

    async def test_future_reminder_is_not_pending(self) -> None:
        await ReminderDB.create("user-1", "c", "a", "开会", "2026-12-31 08:00:00")
        self.assertEqual(await ReminderDB.get_pending("2026-01-01 09:00:00"), [])

    async def test_user_scoped_queries(self) -> None:
        rid = await ReminderDB.create("user-1", "c", "a", "任务", "2026-12-31 08:00:00")
        await ReminderDB.create("user-2", "c", "a", "别人的任务", "2026-12-31 08:00:00")

        self.assertEqual(await ReminderDB.count_user_pending("user-1"), 1)
        self.assertEqual([r["id"] for r in await ReminderDB.get_user_pending("user-1")], [rid])
        self.assertFalse(await ReminderDB.delete_user_reminder(rid, "user-2"))
        self.assertTrue(await ReminderDB.delete_user_reminder(rid, "user-1"))
        self.assertEqual(await ReminderDB.count_user_pending("user-1"), 0)


class MessageStatsTest(AsyncDatabaseTestCase):
    async def asyncTearDown(self) -> None:
        await MessageStatsDB.stop(timeout=1.0)

    async def test_increment_is_buffered_until_flush(self) -> None:
        today = cn_today()
        await MessageStatsDB.increment(today, "channel-1", "area-1", "user-1")
        self.assertEqual(await MessageStatsDB.get_today_total(), 0)

        await MessageStatsDB.flush()
        self.assertEqual(await MessageStatsDB.get_today_total(), 1)

    async def test_repeated_increments_accumulate(self) -> None:
        today = cn_today()
        for _ in range(3):
            await MessageStatsDB.increment(today, "channel-1", "area-1", "user-1")
        await MessageStatsDB.increment(today, "channel-1", "area-1", "user-2")
        await MessageStatsDB.flush()

        self.assertEqual(await MessageStatsDB.get_today_total("area-1"), 4)
        self.assertEqual(await MessageStatsDB.get_active_users_today("area-1"), 2)
        ranking = await MessageStatsDB.get_user_ranking("area-1", days=7, limit=10)
        self.assertEqual([(r["user_id"], r["total"]) for r in ranking], [("user-1", 3), ("user-2", 1)])

    async def test_stop_flushes_buffered_rows(self) -> None:
        await MessageStatsDB.increment(cn_today(), "channel-1", "area-1", "user-1")
        await MessageStatsDB.stop(timeout=1.0)
        self.assertEqual(await MessageStatsDB.get_today_total(), 1)


class MusicCacheTest(AsyncDatabaseTestCase):
    async def test_record_play_updates_song_and_history(self) -> None:
        song = {"name": "夜曲", "artists": "周杰伦", "album": "十一月的萧邦"}
        await SongCache.record_play("1001", "netease", song, None, "channel-1", "user-1")
        await SongCache.record_play("1001", "netease", song, None, "channel-1", "user-1")

        top = await SongCache.get_top_songs(10)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0]["song_name"], "夜曲")
        self.assertEqual(top[0]["play_count"], 2)
        self.assertEqual(len(await SongCache.get_recent_songs(10)), 1)
        today = await Statistics.get_today()
        assert today is not None
        self.assertEqual(today["total_plays"], 2)
        self.assertEqual(today["platform_breakdown"], {"netease": 2})

        # 清理只删播放流水，歌曲缓存本身保留。
        self.assertEqual(await SongCache.clear_play_history(), 2)
        async with (
            db_connection() as conn,
            conn.execute("SELECT COUNT(1) AS c FROM play_history") as cursor,
        ):
            row = await cursor.fetchone()
        assert row is not None
        self.assertEqual(row["c"], 0)
        self.assertEqual(len(await SongCache.get_recent_songs(10)), 1)

    async def test_image_cache_round_trip(self) -> None:
        attachment = {"fileKey": "k1", "url": "https://example.com/a.webp", "width": 300, "height": 300}
        cache_id = await ImageCache.save("1001", "netease", "https://example.com/src.jpg", attachment)
        self.assertGreater(cache_id, 0)

        cached = await ImageCache.get_by_source("1001", "netease")
        assert cached is not None
        self.assertEqual(cached["attachment_data"], attachment)
        self.assertEqual(cached["use_count"], 1)

        await ImageCache.increment_use("1001", "netease")
        refreshed = await ImageCache.get_by_source("1001", "netease")
        assert refreshed is not None
        self.assertEqual(refreshed["use_count"], 2)

    async def test_statistics_track_platform_and_cache_hits(self) -> None:
        await Statistics.update_today("netease")
        await Statistics.update_today("netease", cache_hit=True)
        await Statistics.update_today("qq")

        today = await Statistics.get_today()
        assert today is not None
        self.assertEqual(today["total_plays"], 3)
        self.assertEqual(today["cache_hits"], 1)
        self.assertEqual(today["cache_misses"], 2)
        self.assertEqual(today["platform_breakdown"], {"netease": 2, "qq": 1})
        self.assertEqual(len(await Statistics.get_recent(days=7)), 1)
        self.assertEqual((await Statistics.get_summary())["total_plays"], 3)


class MigratedCallSiteTest(AsyncDatabaseTestCase):
    """曾用 ``asyncio.to_thread`` 包装 async 函数的调用点，回归到真正落库。"""

    async def test_scheduler_service_tick_marks_task_fired(self) -> None:
        from services.scheduler_service import ScheduledMessageService

        task_id = await ScheduledMessageDB.create(
            "整点播报", 0, 0, "channel-1", "area-1", "整点了", "0,1,2,3,4,5,6"
        )
        sender = mock.AsyncMock()
        await ScheduledMessageService(sender)._tick()

        sender.send_message.assert_awaited_once()
        task = await ScheduledMessageDB.get_by_id(task_id)
        assert task is not None
        self.assertEqual(task["last_fired_date"], database.cn_today())

    async def test_reminder_service_tick_sends_and_marks_fired(self) -> None:
        from services.scheduler_service import ReminderService

        await ReminderDB.create("user-1", "channel-1", "area-1", "喝水", "2020-01-01 08:00:00")
        sender = mock.AsyncMock()
        await ReminderService(sender)._tick()

        sender.send_message.assert_awaited_once()
        self.assertEqual(await ReminderDB.get_all_pending(), [])

    async def test_reminder_service_create_persists_reminder(self) -> None:
        from services.scheduler_service import ReminderService

        service = ReminderService(mock.AsyncMock())
        reply = await service.create_reminder("30分钟后 喝水", "channel-1", "area-1", "user-1")

        self.assertIn("已设置提醒", reply)
        self.assertEqual(await ReminderDB.count_user_pending("user-1"), 1)

    async def test_reminder_service_enforces_per_user_quota(self) -> None:
        from services.scheduler_service import ReminderService

        service = ReminderService(mock.AsyncMock(), max_per_user=1)
        await service.create_reminder("30分钟后 第一件事", "channel-1", "area-1", "user-1")
        reply = await service.create_reminder("40分钟后 第二件事", "channel-1", "area-1", "user-1")

        self.assertIn("最多只能有", reply)
        self.assertEqual(await ReminderDB.count_user_pending("user-1"), 1)

    async def test_admin_top_songs_snapshot_reads_play_history(self) -> None:
        from web.admin.shared._snapshots import _top_songs_from_play_history

        song = {"name": "夜曲", "artists": "周杰伦", "album": "十一月的萧邦"}
        await SongCache.record_play("1001", "netease", song, None, "channel-1", "user-1")
        await SongCache.record_play("1002", "netease", {"name": "晴天"}, None, "channel-1", "user-1")

        items, total = await _top_songs_from_play_history(page=1, page_size=10)
        self.assertEqual(total, 2)
        self.assertEqual({item["song_id"] for item in items}, {"1001", "1002"})


if __name__ == "__main__":
    unittest.main()
