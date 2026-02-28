"""
SQLite 数据库管理模块
管理图片缓存、歌曲缓存、播放统计
"""

import os
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from logger_config import get_logger

logger = get_logger("Database")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "oopz_cache.db")

# 中国时区 (UTC+8)
CN_TZ = timezone(timedelta(hours=8))


def cn_now() -> str:
    """返回当前中国时间字符串"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def cn_today() -> str:
    """返回当前中国日期字符串"""
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

def init_database():
    """创建所有数据表"""
    conn = get_connection()
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

    conn.commit()
    conn.close()
    logger.info(f"数据库已初始化: {DB_PATH}")


# ---------------------------------------------------------------------------
# ImageCache
# ---------------------------------------------------------------------------

class ImageCache:
    """图片缓存管理"""

    @staticmethod
    def get_by_source(source_id: str, source_type: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM image_cache WHERE source_id=? AND source_type=?",
            (str(source_id), source_type),
        ).fetchone()
        conn.close()

        if row:
            result = dict(row)
            if result.get("attachment_data"):
                result["attachment_data"] = json.loads(result["attachment_data"])
            return result
        return None

    @staticmethod
    def save(source_id: str, source_type: str, source_url: str, attachment: dict) -> int:
        now = cn_now()
        conn = get_connection()
        cursor = conn.execute(
            """INSERT OR REPLACE INTO image_cache
               (source_id, source_type, source_url, file_key, oopz_url,
                attachment_data, width, height, use_count, created_at, last_used_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
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
        conn.commit()
        row_id = cursor.lastrowid
        conn.close()
        return row_id

    @staticmethod
    def increment_use(source_id: str, source_type: str):
        now = cn_now()
        conn = get_connection()
        conn.execute(
            "UPDATE image_cache SET use_count=use_count+1, last_used_at=? WHERE source_id=? AND source_type=?",
            (now, str(source_id), source_type),
        )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# SongCache
# ---------------------------------------------------------------------------

class SongCache:
    """歌曲缓存与播放统计"""

    @staticmethod
    def get_or_create(song_id: str, platform: str, data: dict, image_cache_id: Optional[int] = None) -> int:
        now = cn_now()
        conn = get_connection()

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

        conn.commit()
        conn.close()
        return song_cache_id

    @staticmethod
    def update_play_stats(song_id: str, platform: str, channel_id: str = None, user_id: str = None):
        now = cn_now()
        conn = get_connection()
        conn.execute(
            "UPDATE song_cache SET play_count=play_count+1, last_played_at=? WHERE song_id=? AND platform=?",
            (now, str(song_id), platform),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def add_play_history(song_cache_id: int, platform: str, channel_id: str = None, user_id: str = None):
        now = cn_now()
        conn = get_connection()
        conn.execute(
            "INSERT INTO play_history (song_cache_id, platform, channel_id, user_id, played_at) VALUES (?, ?, ?, ?, ?)",
            (song_cache_id, platform, channel_id, user_id, now),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_top_songs(limit: int = 10) -> list:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM song_cache ORDER BY play_count DESC, last_played_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_recent_songs(limit: int = 10) -> list:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM song_cache ORDER BY last_played_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def clear_play_history() -> int:
        """清空所有播放历史记录，返回删除的记录数"""
        conn = get_connection()
        cursor = conn.execute("DELETE FROM play_history")
        count = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"已清理播放历史记录: {count} 条")
        return count


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class Statistics:
    """每日统计"""

    @staticmethod
    def update_today(platform: str, cache_hit: bool = False):
        today = cn_today()
        conn = get_connection()

        row = conn.execute("SELECT * FROM statistics WHERE date=?", (today,)).fetchone()
        if row:
            breakdown = json.loads(row["platform_breakdown"] or "{}")
            breakdown[platform] = breakdown.get(platform, 0) + 1

            conn.execute(
                """UPDATE statistics SET
                   total_plays=total_plays+1,
                   cache_hits=cache_hits+?,
                   cache_misses=cache_misses+?,
                   platform_breakdown=?
                   WHERE date=?""",
                (1 if cache_hit else 0, 0 if cache_hit else 1, json.dumps(breakdown), today),
            )
        else:
            breakdown = {platform: 1}
            conn.execute(
                """INSERT INTO statistics (date, total_plays, cache_hits, cache_misses, platform_breakdown)
                   VALUES (?, 1, ?, ?, ?)""",
                (today, 1 if cache_hit else 0, 0 if cache_hit else 1, json.dumps(breakdown)),
            )

        conn.commit()
        conn.close()

    @staticmethod
    def get_today() -> Optional[dict]:
        today = cn_today()
        conn = get_connection()
        row = conn.execute("SELECT * FROM statistics WHERE date=?", (today,)).fetchone()
        conn.close()
        if row:
            result = dict(row)
            result["platform_breakdown"] = json.loads(result.get("platform_breakdown") or "{}")
            return result
        return None

    @staticmethod
    def get_recent(days: int = 7) -> list:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM statistics ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            d = dict(r)
            d["platform_breakdown"] = json.loads(d.get("platform_breakdown") or "{}")
            results.append(d)
        return results

    @staticmethod
    def get_summary() -> dict:
        conn = get_connection()
        row = conn.execute(
            "SELECT COALESCE(SUM(total_plays),0) as total, COALESCE(SUM(cache_hits),0) as hits, COALESCE(SUM(cache_misses),0) as misses FROM statistics"
        ).fetchone()
        conn.close()
        total = row["total"]
        hits = row["hits"]
        return {
            "total_plays": total,
            "cache_hits": hits,
            "cache_misses": row["misses"],
            "cache_hit_rate": round(hits / max(total, 1) * 100, 1),
        }
