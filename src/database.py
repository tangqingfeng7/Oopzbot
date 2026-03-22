from __future__ import annotations

import os
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Generator, Optional

from logger_config import get_logger

logger = get_logger("Database")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "oopz_cache.db")

CN_TZ = timezone(timedelta(hours=8))

_thread_local = threading.local()


def _safe_json_loads(raw: str | None, fallback=None):
    """json.loads 安全包装，解析失败返回 fallback。"""
    if not raw:
        return fallback if fallback is not None else {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, TypeError):
        return fallback if fallback is not None else {}


def cn_now() -> str:
    """返回当前中国时间字符串"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def cn_today() -> str:
    """返回当前中国日期字符串"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def get_connection() -> sqlite3.Connection:
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    _thread_local.conn = conn
    return conn


@contextmanager
def db_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def init_database() -> None:
    """创建所有数据表"""
    with db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
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
            )
        """)

        cursor.execute("""
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
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                song_cache_id INTEGER,
                platform TEXT,
                channel_id TEXT,
                user_id TEXT,
                played_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                total_plays INTEGER DEFAULT 0,
                cache_hits INTEGER DEFAULT 0,
                cache_misses INTEGER DEFAULT 0,
                platform_breakdown TEXT DEFAULT '{}'
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS delta_force_active_token (
                user_id TEXT PRIMARY KEY,
                account_group TEXT NOT NULL DEFAULT 'qq_wechat',
                framework_token TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS delta_force_place_push (
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                last_snapshot TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, channel_id, area_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS delta_force_daily_keyword_push (
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                last_push_date TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel_id, area_id)
            )
        """)

        cursor.execute("""
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
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                message_text TEXT NOT NULL,
                fire_at TEXT NOT NULL,
                fired INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                area_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                message_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date, channel_id, area_id, user_id)
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_stats_date ON message_stats (date)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_message_stats_area_date "
            "ON message_stats (area_id, date)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_play_history_played_at "
            "ON play_history (played_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_play_history_user "
            "ON play_history (user_id, played_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_fire_at ON reminders (fire_at, fired)"
        )

    logger.info(f"数据库已初始化: {DB_PATH}")


# ---------------------------------------------------------------------------
# ImageCache
# ---------------------------------------------------------------------------

class ImageCache:
    """图片缓存管理"""

    @staticmethod
    def get_by_source(source_id: str, source_type: str) -> Optional[dict]:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM image_cache WHERE source_id=? AND source_type=?",
                (str(source_id), source_type),
            ).fetchone()

        if row:
            result = dict(row)
            if result.get("attachment_data"):
                result["attachment_data"] = _safe_json_loads(result["attachment_data"])
            return result
        return None

    @staticmethod
    def save(source_id: str, source_type: str, source_url: str, attachment: dict) -> int:
        now = cn_now()
        with db_connection() as conn:
            cursor = conn.execute(
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
            row_id = cursor.lastrowid or conn.execute(
                "SELECT id FROM image_cache WHERE source_id=? AND source_type=?",
                (str(source_id), source_type),
            ).fetchone()["id"]
        return row_id

    @staticmethod
    def increment_use(source_id: str, source_type: str) -> None:
        now = cn_now()
        with db_connection() as conn:
            conn.execute(
                "UPDATE image_cache SET use_count=use_count+1, last_used_at=? WHERE source_id=? AND source_type=?",
                (now, str(source_id), source_type),
            )


# ---------------------------------------------------------------------------
# SongCache
# ---------------------------------------------------------------------------

class SongCache:
    """歌曲缓存与播放统计"""

    @staticmethod
    def get_or_create(song_id: str, platform: str, data: dict, image_cache_id: Optional[int] = None) -> int:
        now = cn_now()
        with db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM song_cache WHERE song_id=? AND platform=?",
                (str(song_id), platform),
            ).fetchone()

            if row:
                song_cache_id = row["id"]
            else:
                cursor = conn.execute(
                    """INSERT INTO song_cache
                       (song_id, platform, song_name, artist, album, play_count, image_cache_id, created_at, last_played_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
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
                song_cache_id = cursor.lastrowid

        return song_cache_id

    @staticmethod
    def update_play_stats(
        song_id: str, platform: str, channel_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> None:
        now = cn_now()
        with db_connection() as conn:
            conn.execute(
                "UPDATE song_cache SET play_count=play_count+1, last_played_at=? WHERE song_id=? AND platform=?",
                (now, str(song_id), platform),
            )

    @staticmethod
    def add_play_history(
        song_cache_id: int, platform: str, channel_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> None:
        now = cn_now()
        with db_connection() as conn:
            conn.execute(
                "INSERT INTO play_history (song_cache_id, platform, channel_id, user_id, played_at) VALUES (?, ?, ?, ?, ?)",
                (song_cache_id, platform, channel_id, user_id, now),
            )

    @staticmethod
    def record_play(
        song_id: str,
        platform: str,
        data: dict,
        image_cache_id: Optional[int] = None,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        now = cn_now()
        with db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM song_cache WHERE song_id=? AND platform=?",
                (str(song_id), platform),
            ).fetchone()

            if row:
                song_cache_id = row["id"]
                conn.execute(
                    """UPDATE song_cache SET
                       song_name=?,
                       artist=?,
                       album=?,
                       play_count=play_count+1,
                       image_cache_id=COALESCE(?, image_cache_id),
                       last_played_at=?
                       WHERE id=?""",
                    (
                        data.get("name", ""),
                        data.get("artists", ""),
                        data.get("album", ""),
                        image_cache_id,
                        now,
                        song_cache_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """INSERT INTO song_cache
                       (song_id, platform, song_name, artist, album, play_count, image_cache_id, created_at, last_played_at)
                       VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
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
                song_cache_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO play_history (song_cache_id, platform, channel_id, user_id, played_at) VALUES (?, ?, ?, ?, ?)",
                (song_cache_id, platform, channel_id, user_id, now),
            )

        return song_cache_id

    @staticmethod
    def get_top_songs(limit: int = 10) -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM song_cache ORDER BY play_count DESC, last_played_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_recent_songs(limit: int = 10) -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM song_cache ORDER BY last_played_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def clear_play_history() -> int:
        """清空所有播放历史记录，返回删除的记录数"""
        with db_connection() as conn:
            cursor = conn.execute("DELETE FROM play_history")
            count = cursor.rowcount
        logger.info(f"已清理播放历史记录: {count} 条")
        return count


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class Statistics:
    """每日统计"""

    @staticmethod
    def update_today(platform: str, cache_hit: bool = False) -> None:
        today = cn_today()
        with db_connection() as conn:
            conn.execute(
                """INSERT INTO statistics (date, total_plays, cache_hits, cache_misses, platform_breakdown)
                   VALUES (?, 1, ?, ?, ?)
                   ON CONFLICT(date) DO UPDATE SET
                       total_plays=total_plays+1,
                       cache_hits=cache_hits+?,
                       cache_misses=cache_misses+?""",
                (today,
                 1 if cache_hit else 0, 0 if cache_hit else 1,
                 json.dumps({platform: 1}),
                 1 if cache_hit else 0, 0 if cache_hit else 1),
            )
            row = conn.execute(
                "SELECT platform_breakdown FROM statistics WHERE date=?", (today,),
            ).fetchone()
            breakdown = _safe_json_loads(row["platform_breakdown"], {})
            breakdown[platform] = breakdown.get(platform, 0) + 1
            conn.execute(
                "UPDATE statistics SET platform_breakdown=? WHERE date=?",
                (json.dumps(breakdown), today),
            )

    @staticmethod
    def get_today() -> Optional[dict]:
        today = cn_today()
        with db_connection() as conn:
            row = conn.execute("SELECT * FROM statistics WHERE date=?", (today,)).fetchone()
        if row:
            result = dict(row)
            result["platform_breakdown"] = _safe_json_loads(result.get("platform_breakdown"), {})
            return result
        return None

    @staticmethod
    def get_recent(days: int = 7) -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM statistics ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["platform_breakdown"] = _safe_json_loads(d.get("platform_breakdown"), {})
            results.append(d)
        return results

    @staticmethod
    def get_summary() -> dict:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(total_plays),0) as total, COALESCE(SUM(cache_hits),0) as hits, COALESCE(SUM(cache_misses),0) as misses FROM statistics"
            ).fetchone()
        total = row["total"]
        hits = row["hits"]
        return {
            "total_plays": total,
            "cache_hits": hits,
            "cache_misses": row["misses"],
            "cache_hit_rate": round(hits / max(total, 1) * 100, 1),
        }


# ---------------------------------------------------------------------------
# ScheduledMessageDB
# ---------------------------------------------------------------------------

class ScheduledMessageDB:
    """管理员定时消息 CRUD"""

    @staticmethod
    def create(
        name: str,
        cron_hour: int,
        cron_minute: int,
        channel_id: str,
        area_id: str,
        message_text: str,
        weekdays: str = "0,1,2,3,4,5,6",
    ) -> int:
        now = cn_now()
        with db_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO scheduled_messages
                   (name, cron_hour, cron_minute, weekdays, channel_id, area_id,
                    message_text, enabled, last_fired_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, '', ?, ?)""",
                (name, cron_hour, cron_minute, weekdays, channel_id, area_id,
                 message_text, now, now),
            )
            return cursor.lastrowid

    @staticmethod
    def update(task_id: int, **kwargs) -> bool:
        allowed = {"name", "cron_hour", "cron_minute", "weekdays",
                   "channel_id", "area_id", "message_text", "enabled"}
        fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not fields:
            return False
        fields["updated_at"] = cn_now()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [task_id]
        with db_connection() as conn:
            cursor = conn.execute(
                f"UPDATE scheduled_messages SET {set_clause} WHERE id=?", values,
            )
            return cursor.rowcount > 0

    @staticmethod
    def delete(task_id: int) -> bool:
        with db_connection() as conn:
            cursor = conn.execute("DELETE FROM scheduled_messages WHERE id=?", (task_id,))
            return cursor.rowcount > 0

    @staticmethod
    def toggle(task_id: int) -> Optional[bool]:
        with db_connection() as conn:
            row = conn.execute("SELECT enabled FROM scheduled_messages WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            new_val = 0 if row["enabled"] else 1
            conn.execute(
                "UPDATE scheduled_messages SET enabled=?, updated_at=? WHERE id=?",
                (new_val, cn_now(), task_id),
            )
            return bool(new_val)

    @staticmethod
    def get_all() -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_messages ORDER BY cron_hour, cron_minute"
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(task_id: int) -> Optional[dict]:
        with db_connection() as conn:
            row = conn.execute("SELECT * FROM scheduled_messages WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_due_tasks(hour: int, minute: int, weekday: int, today_str: str) -> list[dict]:
        """返回当前时刻（含之前已错过的分钟）应触发且今日尚未触发的任务。"""
        current_minutes = hour * 60 + minute
        with db_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM scheduled_messages
                   WHERE enabled=1
                     AND (cron_hour * 60 + cron_minute) <= ?
                     AND last_fired_date != ?""",
                (current_minutes, today_str),
            ).fetchall()
        results = []
        wd_str = str(weekday)
        for r in rows:
            task = dict(r)
            if wd_str in task["weekdays"].split(","):
                results.append(task)
        return results

    @staticmethod
    def mark_fired(task_id: int, date_str: str) -> None:
        with db_connection() as conn:
            conn.execute(
                "UPDATE scheduled_messages SET last_fired_date=?, updated_at=? WHERE id=?",
                (date_str, cn_now(), task_id),
            )


# ---------------------------------------------------------------------------
# ReminderDB
# ---------------------------------------------------------------------------

class ReminderDB:
    """用户定时提醒"""

    @staticmethod
    def create(user_id: str, channel_id: str, area_id: str, message_text: str, fire_at: str) -> int:
        now = cn_now()
        with db_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO reminders (user_id, channel_id, area_id, message_text, fire_at, fired, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (user_id, channel_id, area_id, message_text, fire_at, now),
            )
            return cursor.lastrowid

    @staticmethod
    def get_pending(now_str: str) -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 AND fire_at <= ? ORDER BY fire_at",
                (now_str,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def mark_fired(reminder_id: int) -> None:
        with db_connection() as conn:
            conn.execute("UPDATE reminders SET fired=1 WHERE id=?", (reminder_id,))

    @staticmethod
    def get_user_pending(user_id: str) -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id=? AND fired=0 ORDER BY fire_at",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def count_user_pending(user_id: str) -> int:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM reminders WHERE user_id=? AND fired=0",
                (user_id,),
            ).fetchone()
        return row["cnt"]

    @staticmethod
    def delete_user_reminder(reminder_id: int, user_id: str) -> bool:
        with db_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id=? AND user_id=? AND fired=0",
                (reminder_id, user_id),
            )
            return cursor.rowcount > 0

    @staticmethod
    def cleanup_old(days: int = 7) -> int:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with db_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE fired=1 AND fire_at < ?", (cutoff,),
            )
            return cursor.rowcount

    @staticmethod
    def get_all_pending() -> list[dict]:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE fired=0 ORDER BY fire_at"
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# MessageStatsDB
# ---------------------------------------------------------------------------

class _MessageStatsBatcher:
    """将高频的 increment 调用缓冲到内存，定时批量刷入 SQLite，减少磁盘 I/O。"""

    _FLUSH_INTERVAL = 30
    _MAX_BUFFER_SIZE = 500

    def __init__(self) -> None:
        self._buffer: dict[tuple[str, str, str, str], int] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _ensure_started_locked(self) -> None:
        """在持有 self._lock 的情况下调用，确保后台 flush 线程已启动。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._flush_loop, name="MsgStatsBatcher", daemon=True,
        )
        self._thread.start()

    def increment(self, date: str, channel_id: str, area_id: str, user_id: str) -> None:
        with self._lock:
            key = (date, channel_id, area_id, user_id)
            self._buffer[key] = self._buffer.get(key, 0) + 1
            need_flush = len(self._buffer) >= self._MAX_BUFFER_SIZE
            self._ensure_started_locked()
        if need_flush:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            snapshot = self._buffer
            self._buffer = {}
        try:
            with db_connection() as conn:
                conn.executemany(
                    """INSERT INTO message_stats (date, channel_id, area_id, user_id, message_count)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(date, channel_id, area_id, user_id)
                       DO UPDATE SET message_count = message_count + ?""",
                    [
                        (date, ch, area, user, count, count)
                        for (date, ch, area, user), count in snapshot.items()
                    ],
                )
        except Exception:
            logger.exception("MessageStats 批量刷入失败，数据回填缓冲区")
            with self._lock:
                for key, count in snapshot.items():
                    self._buffer[key] = self._buffer.get(key, 0) + count

    def _flush_loop(self) -> None:
        while not self._stop.wait(self._FLUSH_INTERVAL):
            try:
                self.flush()
            except Exception:
                logger.exception("MessageStats flush_loop 异常")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self.flush()


_msg_stats_batcher = _MessageStatsBatcher()


class MessageStatsDB:
    """频道消息统计（按日、频道、用户聚合）"""

    @staticmethod
    def increment(date: str, channel_id: str, area_id: str, user_id: str) -> None:
        _msg_stats_batcher.increment(date, channel_id, area_id, user_id)

    @staticmethod
    def flush() -> None:
        """手动刷入缓冲区。"""
        _msg_stats_batcher.flush()

    @staticmethod
    def stop() -> None:
        """停止后台线程并刷入缓冲区（关闭时调用）。"""
        _msg_stats_batcher.stop()

    @staticmethod
    def get_channel_daily(channel_id: str, area_id: str, days: int = 14) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        with db_connection() as conn:
            rows = conn.execute(
                """SELECT date, SUM(message_count) as total
                   FROM message_stats
                   WHERE channel_id=? AND area_id=? AND date >= ?
                   GROUP BY date ORDER BY date""",
                (channel_id, area_id, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_area_daily(area_id: str, days: int = 14) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        with db_connection() as conn:
            rows = conn.execute(
                """SELECT date, SUM(message_count) as total
                   FROM message_stats
                   WHERE area_id=? AND date >= ?
                   GROUP BY date ORDER BY date""",
                (area_id, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_all_daily(days: int = 14) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        with db_connection() as conn:
            rows = conn.execute(
                """SELECT date, SUM(message_count) as total
                   FROM message_stats
                   WHERE date >= ?
                   GROUP BY date ORDER BY date""",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_user_ranking(area_id: str, days: int = 7, limit: int = 10) -> list[dict]:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
        with db_connection() as conn:
            rows = conn.execute(
                """SELECT user_id, SUM(message_count) as total
                   FROM message_stats
                   WHERE area_id=? AND date >= ?
                   GROUP BY user_id
                   ORDER BY total DESC
                   LIMIT ?""",
                (area_id, cutoff, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_today_total(area_id: str | None = None) -> int:
        today = cn_today()
        with db_connection() as conn:
            if area_id:
                row = conn.execute(
                    "SELECT COALESCE(SUM(message_count), 0) as total FROM message_stats WHERE date=? AND area_id=?",
                    (today, area_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(message_count), 0) as total FROM message_stats WHERE date=?",
                    (today,),
                ).fetchone()
        return row["total"]

    @staticmethod
    def get_active_users_today(area_id: str | None = None) -> int:
        today = cn_today()
        with db_connection() as conn:
            if area_id:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM message_stats WHERE date=? AND area_id=?",
                    (today, area_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT user_id) as cnt FROM message_stats WHERE date=?",
                    (today,),
                ).fetchone()
        return row["cnt"]

    @staticmethod
    def get_week_total(area_id: str | None = None) -> int:
        cutoff = (datetime.now(CN_TZ) - timedelta(days=7)).strftime("%Y-%m-%d")
        with db_connection() as conn:
            if area_id:
                row = conn.execute(
                    "SELECT COALESCE(SUM(message_count), 0) as total FROM message_stats WHERE date >= ? AND area_id=?",
                    (cutoff, area_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(message_count), 0) as total FROM message_stats WHERE date >= ?",
                    (cutoff,),
                ).fetchone()
        return row["total"]