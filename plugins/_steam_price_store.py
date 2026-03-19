"""Steam 价格插件的 SQLite 持久层。"""

from __future__ import annotations

from typing import Optional

from database import cn_now, get_connection
from logger_config import get_logger

logger = get_logger("SteamPriceStore")


def _dict_from_row(row) -> dict:
    if row is None:
        return {}
    return dict(row)


class SteamPriceStore:
    """管理个人关注、频道推送订阅与推送去重记录。"""

    def __init__(self) -> None:
        self._ensure_tables()

    # ------------------------------------------------------------------
    # 建表
    # ------------------------------------------------------------------

    def _ensure_tables(self) -> None:
        conn = get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS steam_watch_personal (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       TEXT    NOT NULL,
                    itad_id       TEXT    NOT NULL DEFAULT '',
                    app_id        INTEGER,
                    game_name     TEXT    NOT NULL DEFAULT '',
                    current_price REAL,
                    lowest_price  REAL,
                    channel       TEXT    NOT NULL DEFAULT '',
                    area          TEXT    NOT NULL DEFAULT '',
                    created_at    TEXT    NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS steam_watch_channel (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel      TEXT    NOT NULL,
                    area         TEXT    NOT NULL,
                    min_discount INTEGER NOT NULL DEFAULT 50,
                    created_at   TEXT    NOT NULL DEFAULT '',
                    UNIQUE(channel, area)
                );

                CREATE TABLE IF NOT EXISTS steam_price_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    itad_id     TEXT    NOT NULL DEFAULT '',
                    price       REAL,
                    discount    INTEGER NOT NULL DEFAULT 0,
                    recorded_at TEXT    NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_steam_personal_user
                    ON steam_watch_personal (user_id);
                CREATE INDEX IF NOT EXISTS idx_steam_personal_itad
                    ON steam_watch_personal (itad_id);
                CREATE INDEX IF NOT EXISTS idx_steam_price_log_itad
                    ON steam_price_log (itad_id, recorded_at);
            """)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 个人关注
    # ------------------------------------------------------------------

    def add_personal_watch(
        self,
        user_id: str,
        itad_id: str,
        app_id: Optional[int],
        game_name: str,
        current_price: Optional[float],
        lowest_price: Optional[float],
        channel: str,
        area: str,
    ) -> int:
        conn = get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO steam_watch_personal
                    (user_id, itad_id, app_id, game_name, current_price, lowest_price, channel, area, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, itad_id, app_id, game_name, current_price, lowest_price, channel, area, cn_now()),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    def remove_personal_watch(self, watch_id: int, user_id: str) -> bool:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM steam_watch_personal WHERE id=? AND user_id=?",
                (watch_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_personal_watches(self, user_id: str) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM steam_watch_personal WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
            return [_dict_from_row(r) for r in rows]
        finally:
            conn.close()

    def get_all_personal_watches(self) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM steam_watch_personal ORDER BY id").fetchall()
            return [_dict_from_row(r) for r in rows]
        finally:
            conn.close()

    def count_personal_watches(self, user_id: str) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM steam_watch_personal WHERE user_id=?",
                (user_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0
        finally:
            conn.close()

    def is_watching(self, user_id: str, itad_id: str) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM steam_watch_personal WHERE user_id=? AND itad_id=?",
                (user_id, itad_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def update_watch_price(self, watch_id: int, current_price: Optional[float], lowest_price: Optional[float]) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE steam_watch_personal SET current_price=?, lowest_price=? WHERE id=?",
                (current_price, lowest_price, watch_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 频道推送订阅
    # ------------------------------------------------------------------

    def subscribe_channel(self, channel: str, area: str, min_discount: int = 50) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """
                INSERT INTO steam_watch_channel (channel, area, min_discount, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel, area) DO UPDATE SET
                    min_discount=excluded.min_discount
                """,
                (channel, area, min_discount, cn_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def unsubscribe_channel(self, channel: str, area: str) -> bool:
        conn = get_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM steam_watch_channel WHERE channel=? AND area=?",
                (channel, area),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_channel_subscribed(self, channel: str, area: str) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM steam_watch_channel WHERE channel=? AND area=?",
                (channel, area),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_channel_subscriptions(self) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute("SELECT * FROM steam_watch_channel ORDER BY id").fetchall()
            return [_dict_from_row(r) for r in rows]
        finally:
            conn.close()

    def any_subscriptions(self) -> bool:
        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT 1 FROM steam_watch_personal
                UNION ALL
                SELECT 1 FROM steam_watch_channel
                LIMIT 1
                """
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 推送去重
    # ------------------------------------------------------------------

    def has_notified(self, itad_id: str, price: float) -> bool:
        """检查同一 itad_id + 价格是否已经推送过。"""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT 1 FROM steam_price_log WHERE itad_id=? AND price=?",
                (itad_id, price),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def mark_notified(self, itad_id: str, price: float, discount: int) -> None:
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO steam_price_log (itad_id, price, discount, recorded_at) VALUES (?, ?, ?, ?)",
                (itad_id, price, discount, cn_now()),
            )
            conn.commit()
        finally:
            conn.close()

    def cleanup_old_logs(self, days: int = 90) -> None:
        """清理超过指定天数的推送记录。"""
        conn = get_connection()
        try:
            conn.execute(
                "DELETE FROM steam_price_log WHERE recorded_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            conn.commit()
        finally:
            conn.close()
