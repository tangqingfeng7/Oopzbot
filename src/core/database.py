from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite

from core.logger_config import get_logger
from core.paths import DATA_DIR

logger = get_logger("Database")

DB_PATH = os.path.join(DATA_DIR, "oopz_cache.db")

CN_TZ = timezone(timedelta(hours=8))


def _safe_json_loads(raw: str | None, fallback=None):
    """json.loads 安全包装，解析失败返回 fallback。"""
    if not raw:
        return fallback if fallback is not None else {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return fallback if fallback is not None else {}


def _required_database_id(value: object, *, operation: str) -> int:
    """校验 SQLite 主键结果，避免把失败的 ``lastrowid=None`` 传到业务层。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"{operation} 未返回有效数据库主键")
    return value


def cn_now() -> str:
    """返回当前中国时间字符串。"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def cn_today() -> str:
    """返回当前中国日期字符串。"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


async def get_connection() -> aiosqlite.Connection:
    """创建已配置的异步 SQLite 连接。

    每个业务事务独占连接，避免共享连接上的事务相互搭车提交；aiosqlite
    自己在受控工作线程中串行执行底层 SQLite 调用，不阻塞应用事件循环。
    WAL 模式持久化在库文件里，由 ``init_database`` 设置一次即可。
    """
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@asynccontextmanager
async def db_connection() -> AsyncIterator[aiosqlite.Connection]:
    """提供提交、回滚和关闭均有保证的异步事务。"""
    conn = await get_connection()
    try:
        yield conn
        await conn.commit()
    except BaseException:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def _fetchone(
    conn: aiosqlite.Connection,
    sql: str,
    parameters: Iterable[Any] = (),
) -> aiosqlite.Row | None:
    cursor = await conn.execute(sql, tuple(parameters))
    try:
        return await cursor.fetchone()
    finally:
        await cursor.close()


async def _fetchall(
    conn: aiosqlite.Connection,
    sql: str,
    parameters: Iterable[Any] = (),
) -> list[aiosqlite.Row]:
    cursor = await conn.execute(sql, tuple(parameters))
    try:
        return list(await cursor.fetchall())
    finally:
        await cursor.close()


async def _query_int(sql: str, parameters: Iterable[Any] = ()) -> int:
    """执行单值聚合查询；不带 GROUP BY 的聚合总会返回一行。"""
    async with db_connection() as conn:
        row = await _fetchone(conn, sql, parameters)
    assert row is not None
    return int(row[0])


async def init_database() -> None:
    """异步创建全部项目数据表和索引。"""
    async with db_connection() as conn:
        # 该 PRAGMA 会返回结果行，游标不关闭时同一连接上的 DROP INDEX 会报 table is locked。
        await _fetchone(conn, "PRAGMA journal_mode=WAL")
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS image_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT,
                file_key TEXT,
                oopz_url TEXT,
                attachment_data TEXT,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                use_count INTEGER DEFAULT 1,
                created_at TEXT,
                last_used_at TEXT,
                UNIQUE(source_id, source_type)
            );

            CREATE TABLE IF NOT EXISTS song_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                song_name TEXT,
                artist TEXT,
                album TEXT,
                play_count INTEGER DEFAULT 1,
                image_cache_id INTEGER,
                created_at TEXT,
                last_played_at TEXT,
                UNIQUE(song_id, platform)
            );

            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_cache_id INTEGER,
                platform TEXT,
                channel_id TEXT,
                user_id TEXT,
                played_at TEXT
            );

            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_plays INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0,
                cache_misses INTEGER DEFAULT 0,
                platform_breakdown TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS delta_force_active_token (
                user_id TEXT PRIMARY KEY,
                account_group TEXT NOT NULL DEFAULT 'qq_wechat',
                framework_token TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS delta_force_place_push (
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                last_snapshot TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, channel_id, area_id)
            );

            CREATE TABLE IF NOT EXISTS delta_force_daily_keyword_push (
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                last_push_date TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, area_id)
            );

            CREATE TABLE IF NOT EXISTS scheduled_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                cron_hour INTEGER NOT NULL,
                cron_minute INTEGER NOT NULL,
                weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_fired_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                fire_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS message_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date, channel_id, area_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS area_invite_requests (
                code TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                message_id TEXT NOT NULL DEFAULT '',
                message_timestamp TEXT NOT NULL DEFAULT '',
                invite_status TEXT NOT NULL DEFAULT '',
                area_id TEXT NOT NULL DEFAULT '',
                area_name TEXT NOT NULL DEFAULT '',
                area_avatar TEXT NOT NULL DEFAULT '',
                banner TEXT NOT NULL DEFAULT '',
                channel_id TEXT NOT NULL DEFAULT '',
                channel_name TEXT NOT NULL DEFAULT '',
                channel_type TEXT NOT NULL DEFAULT '',
                is_area_invite INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'pending',
                received_at TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT ''
            );

            DROP INDEX IF EXISTS idx_message_stats_date;
            DROP INDEX IF EXISTS idx_play_history_played_at;
            DROP INDEX IF EXISTS idx_play_history_user;
            DROP INDEX IF EXISTS idx_reminders_fire_at;
            CREATE INDEX IF NOT EXISTS idx_message_stats_area_date
                ON message_stats (area_id, date);
            CREATE INDEX IF NOT EXISTS idx_reminders_fired_fire_at
                ON reminders (fired, fire_at);
            CREATE INDEX IF NOT EXISTS idx_area_invite_requests_state_received
                ON area_invite_requests (state, received_at DESC);
            """
        )
    logger.info("数据库已初始化: %s", DB_PATH)


class ImageCache:
    """图片缓存管理。"""

    @staticmethod
    async def get_by_source(source_id: str, source_type: str) -> dict | None:
        async with db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT * FROM image_cache WHERE source_id=? AND source_type=?",
                (str(source_id), source_type),
            )
        if row:
            result = dict(row)
            if result.get("attachment_data"):
                result["attachment_data"] = _safe_json_loads(result["attachment_data"])
            return result
        return None

    @staticmethod
    async def save(
        source_id: str,
        source_type: str,
        source_url: str,
        attachment: dict,
    ) -> int:
        now = cn_now()
        async with db_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO image_cache
                   (source_id, source_type, source_url, file_key, oopz_url,
                    attachment_data, width, height, use_count, created_at, last_used_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                   ON CONFLICT(source_id, source_type) DO UPDATE SET
                       source_url=excluded.source_url,
                       file_key=excluded.file_key,
                       oopz_url=excluded.oopz_url,
                       attachment_data=excluded.attachment_data,
                       width=excluded.width,
                       height=excluded.height,
                       use_count=use_count+1,
                       last_used_at=excluded.last_used_at""",
                (
                    str(source_id),
                    source_type,
                    source_url,
                    attachment.get("fileKey", ""),
                    attachment.get("url", ""),
                    json.dumps(attachment, ensure_ascii=False),
                    attachment.get("width", 0),
                    attachment.get("height", 0),
                    now,
                    now,
                ),
            )
            row_id = cursor.lastrowid
            await cursor.close()
            if not row_id:
                row = await _fetchone(
                    conn,
                    "SELECT id FROM image_cache WHERE source_id=? AND source_type=?",
                    (str(source_id), source_type),
                )
                row_id = row["id"] if row else None
        return _required_database_id(row_id, operation="保存图片缓存")

    @staticmethod
    async def increment_use(source_id: str, source_type: str) -> None:
        async with db_connection() as conn:
            await conn.execute(
                "UPDATE image_cache SET use_count=use_count+1, last_used_at=? "
                "WHERE source_id=? AND source_type=?",
                (cn_now(), str(source_id), source_type),
            )


async def _bump_statistics(conn: aiosqlite.Connection, platform: str, cache_hit: bool) -> None:
    hit = 1 if cache_hit else 0
    platform_path = json.dumps(platform, ensure_ascii=False)
    await conn.execute(
        """INSERT INTO statistics
           (date, total_plays, cache_hits, cache_misses, platform_breakdown)
           VALUES (?, 1, ?, ?, json_object(?, 1))
           ON CONFLICT(date) DO UPDATE SET
               total_plays=total_plays+1,
               cache_hits=cache_hits+excluded.cache_hits,
               cache_misses=cache_misses+excluded.cache_misses,
               platform_breakdown=json_set(
                   platform_breakdown, '$.' || ?,
                   COALESCE(json_extract(platform_breakdown, '$.' || ?), 0) + 1
               )""",
        (cn_today(), hit, 1 - hit, platform, platform_path, platform_path),
    )


class SongCache:
    """歌曲缓存与播放统计。"""

    @staticmethod
    async def record_play(
        song_id: str,
        platform: str,
        data: dict,
        image_cache_id: int | None = None,
        channel_id: str | None = None,
        user_id: str | None = None,
        *,
        cache_hit: bool = False,
    ) -> int:
        """记录一次播放：歌曲缓存、播放流水和当日统计在同一事务内落库。"""
        now = cn_now()
        async with db_connection() as conn:
            await conn.execute(
                """INSERT INTO song_cache
                   (song_id, platform, song_name, artist, album, play_count,
                    image_cache_id, created_at, last_played_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(song_id, platform) DO UPDATE SET
                       song_name=excluded.song_name,
                       artist=excluded.artist,
                       album=excluded.album,
                       play_count=play_count+1,
                       image_cache_id=COALESCE(excluded.image_cache_id, image_cache_id),
                       last_played_at=excluded.last_played_at""",
                (
                    str(song_id),
                    platform,
                    data.get("name", ""),
                    data.get("artists", ""),
                    data.get("album", ""),
                    image_cache_id,
                    now,
                    now,
                ),
            )
            row = await _fetchone(
                conn,
                "SELECT id FROM song_cache WHERE song_id=? AND platform=?",
                (str(song_id), platform),
            )
            song_cache_id = _required_database_id(row["id"] if row else None, operation="记录歌曲缓存")
            await conn.execute(
                "INSERT INTO play_history "
                "(song_cache_id, platform, channel_id, user_id, played_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (song_cache_id, platform, channel_id, user_id, now),
            )
            await _bump_statistics(conn, platform, cache_hit)
        return song_cache_id

    @staticmethod
    async def get_top_songs(limit: int = 10) -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM song_cache "
                "ORDER BY play_count DESC, last_played_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_recent_songs(limit: int = 10) -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM song_cache ORDER BY last_played_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def clear_play_history() -> int:
        async with db_connection() as conn:
            cursor = await conn.execute("DELETE FROM play_history")
            count = cursor.rowcount
            await cursor.close()
        logger.info("已清理播放历史记录: %d 条", count)
        return count


class Statistics:
    """每日统计。"""

    @staticmethod
    async def update_today(platform: str, cache_hit: bool = False) -> None:
        async with db_connection() as conn:
            await _bump_statistics(conn, platform, cache_hit)

    @staticmethod
    async def get_today() -> dict | None:
        async with db_connection() as conn:
            row = await _fetchone(
                conn, "SELECT * FROM statistics WHERE date=?", (cn_today(),)
            )
        if not row:
            return None
        result = dict(row)
        result["platform_breakdown"] = _safe_json_loads(
            result.get("platform_breakdown"), {}
        )
        return result

    @staticmethod
    async def get_recent(days: int = 7) -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM statistics ORDER BY date DESC LIMIT ?",
                (days,),
            )
        results: list[dict] = []
        for row in rows:
            item = dict(row)
            item["platform_breakdown"] = _safe_json_loads(
                item.get("platform_breakdown"), {}
            )
            results.append(item)
        return results

    @staticmethod
    async def get_summary() -> dict:
        async with db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT COALESCE(SUM(total_plays),0) AS total, "
                "COALESCE(SUM(cache_hits),0) AS hits, "
                "COALESCE(SUM(cache_misses),0) AS misses FROM statistics",
            )
        assert row is not None
        total, hits, misses = int(row["total"]), int(row["hits"]), int(row["misses"])
        return {
            "total_plays": total,
            "cache_hits": hits,
            "cache_misses": misses,
            "cache_hit_rate": round(hits / max(total, 1) * 100, 1),
        }


class AreaInviteRequestDB:
    """私信中识别出的域邀请待审批记录。"""

    @staticmethod
    async def upsert_pending(
        *,
        code: str,
        sender_id: str,
        sender_name: str,
        message_id: str,
        message_timestamp: str,
        detail: dict[str, Any],
    ) -> None:
        now = cn_now()
        async with db_connection() as conn:
            await conn.execute(
                """INSERT INTO area_invite_requests (
                       code, sender_id, sender_name, message_id, message_timestamp,
                       invite_status, area_id, area_name, area_avatar, banner,
                       channel_id, channel_name, channel_type, is_area_invite,
                       state, received_at, processed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, '')
                   ON CONFLICT(code) DO UPDATE SET
                       sender_id=excluded.sender_id,
                       sender_name=excluded.sender_name,
                       message_id=excluded.message_id,
                       message_timestamp=excluded.message_timestamp,
                       invite_status=excluded.invite_status,
                       area_id=excluded.area_id,
                       area_name=excluded.area_name,
                       area_avatar=excluded.area_avatar,
                       banner=excluded.banner,
                       channel_id=excluded.channel_id,
                       channel_name=excluded.channel_name,
                       channel_type=excluded.channel_type,
                       is_area_invite=excluded.is_area_invite,
                       state='pending',
                       received_at=excluded.received_at,
                       processed_at=''""",
                (
                    code,
                    sender_id,
                    sender_name,
                    message_id,
                    message_timestamp,
                    str(detail.get("status") or ""),
                    str(detail.get("area") or ""),
                    str(detail.get("areaName") or ""),
                    str(detail.get("areaAvatar") or ""),
                    str(detail.get("banner") or ""),
                    str(detail.get("channel") or ""),
                    str(detail.get("channelName") or ""),
                    str(detail.get("channelType") or ""),
                    int(bool(detail.get("isAreaInvite"))),
                    now,
                ),
            )

    @staticmethod
    async def list_pending() -> list[dict[str, Any]]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM area_invite_requests "
                "WHERE state='pending' ORDER BY received_at DESC, code ASC",
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_pending(code: str) -> dict[str, Any] | None:
        async with db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT * FROM area_invite_requests WHERE code=? AND state='pending'",
                (code,),
            )
        return dict(row) if row else None

    @staticmethod
    async def mark_processed(code: str, state: str) -> bool:
        if state not in {"accepted", "rejected"}:
            raise ValueError("invalid area invite state")
        async with db_connection() as conn:
            cursor = await conn.execute(
                "UPDATE area_invite_requests SET state=?, processed_at=? "
                "WHERE code=? AND state='pending'",
                (state, cn_now(), code),
            )
            updated = cursor.rowcount > 0
            await cursor.close()
        return updated


class ScheduledMessageDB:
    """管理员定时消息 CRUD。"""

    @staticmethod
    async def create(
        name: str,
        cron_hour: int,
        cron_minute: int,
        channel_id: str,
        area_id: str,
        message_text: str,
        weekdays: str = "0,1,2,3,4,5,6",
    ) -> int:
        now = cn_now()
        async with db_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO scheduled_messages
                   (name, cron_hour, cron_minute, weekdays, channel_id, area_id,
                    message_text, enabled, last_fired_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, ?)""",
                (
                    name,
                    cron_hour,
                    cron_minute,
                    weekdays,
                    channel_id,
                    area_id,
                    message_text,
                    now,
                    now,
                ),
            )
            row_id = cursor.lastrowid
            await cursor.close()
        return _required_database_id(row_id, operation="创建定时消息")

    @staticmethod
    async def update(task_id: int, **kwargs) -> bool:
        allowed = {
            "name",
            "cron_hour",
            "cron_minute",
            "weekdays",
            "channel_id",
            "area_id",
            "message_text",
            "enabled",
        }
        fields = {key: value for key, value in kwargs.items() if key in allowed}
        if not fields:
            return False
        fields["updated_at"] = cn_now()
        set_clause = ", ".join(f"{key}=?" for key in fields)
        values = [*fields.values(), task_id]
        async with db_connection() as conn:
            cursor = await conn.execute(
                f"UPDATE scheduled_messages SET {set_clause} WHERE id=?",
                values,
            )
            updated = cursor.rowcount > 0
            await cursor.close()
        return updated

    @staticmethod
    async def delete(task_id: int) -> bool:
        async with db_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM scheduled_messages WHERE id=?", (task_id,)
            )
            deleted = cursor.rowcount > 0
            await cursor.close()
        return deleted

    @staticmethod
    async def toggle(task_id: int) -> bool | None:
        async with db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT enabled FROM scheduled_messages WHERE id=?",
                (task_id,),
            )
            if not row:
                return None
            new_value = 0 if row["enabled"] else 1
            await conn.execute(
                "UPDATE scheduled_messages SET enabled=?, updated_at=? WHERE id=?",
                (new_value, cn_now(), task_id),
            )
        return bool(new_value)

    @staticmethod
    async def get_all() -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM scheduled_messages ORDER BY cron_hour, cron_minute",
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_by_id(task_id: int) -> dict | None:
        async with db_connection() as conn:
            row = await _fetchone(
                conn, "SELECT * FROM scheduled_messages WHERE id=?", (task_id,)
            )
        return dict(row) if row else None

    @staticmethod
    async def get_due_tasks(
        hour: int,
        minute: int,
        weekday: int,
        today_str: str,
    ) -> list[dict]:
        current_minutes = hour * 60 + minute
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                """SELECT * FROM scheduled_messages
                   WHERE enabled=1
                     AND (cron_hour * 60 + cron_minute) <= ?
                     AND last_fired_date != ?""",
                (current_minutes, today_str),
            )
        weekday_text = str(weekday)
        return [
            task
            for task in (dict(row) for row in rows)
            if weekday_text in task["weekdays"].split(",")
        ]

    @staticmethod
    async def mark_fired(task_id: int, date_str: str) -> None:
        async with db_connection() as conn:
            await conn.execute(
                "UPDATE scheduled_messages SET last_fired_date=?, updated_at=? "
                "WHERE id=?",
                (date_str, cn_now(), task_id),
            )


class ReminderDB:
    """用户定时提醒。"""

    @staticmethod
    async def create(
        user_id: str,
        channel_id: str,
        area_id: str,
        message_text: str,
        fire_at: str,
    ) -> int:
        async with db_connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO reminders
                   (user_id, channel_id, area_id, message_text, fire_at, fired, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (user_id, channel_id, area_id, message_text, fire_at, cn_now()),
            )
            row_id = cursor.lastrowid
            await cursor.close()
        return _required_database_id(row_id, operation="创建提醒")

    @staticmethod
    async def get_pending(now_str: str) -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM reminders WHERE fired=0 AND fire_at <= ? "
                "ORDER BY fire_at",
                (now_str,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def mark_fired(reminder_id: int) -> None:
        async with db_connection() as conn:
            await conn.execute(
                "UPDATE reminders SET fired=1 WHERE id=?", (reminder_id,)
            )

    @staticmethod
    async def get_user_pending(user_id: str) -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM reminders WHERE user_id=? AND fired=0 ORDER BY fire_at",
                (user_id,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def count_user_pending(user_id: str) -> int:
        return await _query_int(
            "SELECT COUNT(*) FROM reminders WHERE user_id=? AND fired=0", (user_id,),
        )

    @staticmethod
    async def delete_user_reminder(reminder_id: int, user_id: str) -> bool:
        async with db_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM reminders WHERE id=? AND user_id=? AND fired=0",
                (reminder_id, user_id),
            )
            deleted = cursor.rowcount > 0
            await cursor.close()
        return deleted

    @staticmethod
    async def cleanup_old(days: int = 7) -> int:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        async with db_connection() as conn:
            cursor = await conn.execute(
                "DELETE FROM reminders WHERE fired=1 AND fire_at < ?", (cutoff,)
            )
            deleted = cursor.rowcount
            await cursor.close()
        return deleted

    @staticmethod
    async def get_all_pending() -> list[dict]:
        async with db_connection() as conn:
            rows = await _fetchall(
                conn, "SELECT * FROM reminders WHERE fired=0 ORDER BY fire_at"
            )
        return [dict(row) for row in rows]


class _MessageStatsBatcher:
    """在事件循环内缓冲并异步批量写入高频消息统计。"""

    _FLUSH_INTERVAL = 30.0
    _MAX_BUFFER_SIZE = 500

    def __init__(self) -> None:
        self._buffer: dict[tuple[str, str, str, str], int] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def _ensure_started(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._flush_loop(), name="message-stats-batcher"
        )

    async def increment(
        self,
        date: str,
        channel_id: str,
        area_id: str,
        user_id: str,
    ) -> None:
        key = (date, channel_id, area_id, user_id)
        self._buffer[key] = self._buffer.get(key, 0) + 1
        self._ensure_started()
        if len(self._buffer) >= self._MAX_BUFFER_SIZE:
            await self.flush()

    async def flush(self) -> None:
        if not self._buffer:
            return
        snapshot = self._buffer
        self._buffer = {}
        try:
            async with db_connection() as conn:
                await conn.executemany(
                    """INSERT INTO message_stats
                       (date, channel_id, area_id, user_id, message_count)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(date, channel_id, area_id, user_id)
                       DO UPDATE SET message_count = message_count + ?""",
                    [
                        (date, channel, area, user, count, count)
                        for (date, channel, area, user), count in snapshot.items()
                    ],
                )
        except BaseException as exc:
            for key, count in snapshot.items():
                self._buffer[key] = self._buffer.get(key, 0) + count
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.exception("MessageStats 批量刷入失败，数据已回填缓冲区")

    async def _flush_loop(self) -> None:
        try:
            while True:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._FLUSH_INTERVAL
                    )
                except asyncio.TimeoutError:
                    await self.flush()
                    continue
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("MessageStats 异步批处理任务异常")
        finally:
            await self.flush()

    async def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            await asyncio.wait_for(self.flush(), timeout=max(0.001, timeout))
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=max(0.001, timeout))
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            logger.warning("服务停止超时: MessageStatsBatcher，任务已取消")


_msg_stats_batcher = _MessageStatsBatcher()


async def _query_message_stats(aggregate: str, date_clause: str, date: str, area_id: str | None) -> int:
    sql = f"SELECT {aggregate} FROM message_stats WHERE {date_clause}"
    if area_id:
        return await _query_int(sql + " AND area_id=?", (date, area_id))
    return await _query_int(sql, (date,))


class MessageStatsDB:
    """频道消息统计（按日、频道、用户聚合）。"""

    @staticmethod
    async def increment(date: str, channel_id: str, area_id: str, user_id: str) -> None:
        await _msg_stats_batcher.increment(date, channel_id, area_id, user_id)

    @staticmethod
    async def flush() -> None:
        await _msg_stats_batcher.flush()

    @staticmethod
    async def stop(timeout: float = 3.0) -> None:
        await _msg_stats_batcher.stop(timeout=timeout)

    @staticmethod
    async def get_channel_daily(
        channel_id: str, area_id: str, days: int = 14
    ) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                """SELECT date, SUM(message_count) AS total
                   FROM message_stats
                   WHERE channel_id=? AND area_id=? AND date >= ?
                   GROUP BY date ORDER BY date""",
                (channel_id, area_id, cutoff),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_area_daily(area_id: str, days: int = 14) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                """SELECT date, SUM(message_count) AS total
                   FROM message_stats
                   WHERE area_id=? AND date >= ?
                   GROUP BY date ORDER BY date""",
                (area_id, cutoff),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_all_daily(days: int = 14) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        async with db_connection() as conn:
            rows = await _fetchall(
                conn,
                """SELECT date, SUM(message_count) AS total
                   FROM message_stats
                   WHERE date >= ?
                   GROUP BY date ORDER BY date""",
                (cutoff,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_user_ranking(
        area_id: str, days: int = 7, limit: int = 10
    ) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        async with db_connection() as conn:
            if area_id:
                rows = await _fetchall(
                    conn,
                    """SELECT user_id, SUM(message_count) AS total
                       FROM message_stats
                       WHERE area_id=? AND date >= ?
                       GROUP BY user_id ORDER BY total DESC LIMIT ?""",
                    (area_id, cutoff, limit),
                )
            else:
                rows = await _fetchall(
                    conn,
                    """SELECT user_id, SUM(message_count) AS total
                       FROM message_stats
                       WHERE date >= ?
                       GROUP BY user_id ORDER BY total DESC LIMIT ?""",
                    (cutoff, limit),
                )
        return [dict(row) for row in rows]

    @staticmethod
    async def get_user_total(area_id: str, user_id: str, days: int = 7) -> int:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        return await _query_int(
            "SELECT COALESCE(SUM(message_count), 0) FROM message_stats "
            "WHERE area_id=? AND user_id=? AND date >= ?",
            (area_id, user_id, cutoff),
        )

    @staticmethod
    async def get_today_total(area_id: str | None = None) -> int:
        return await _query_message_stats("COALESCE(SUM(message_count), 0)", "date=?", cn_today(), area_id)

    @staticmethod
    async def get_active_users_today(area_id: str | None = None) -> int:
        return await _query_message_stats("COUNT(DISTINCT user_id)", "date=?", cn_today(), area_id)

    @staticmethod
    async def get_week_total(area_id: str | None = None) -> int:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
        return await _query_message_stats("COALESCE(SUM(message_count), 0)", "date >= ?", cutoff, area_id)
