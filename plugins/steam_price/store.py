"""Steam 价格插件的异步 SQLite 持久层。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

from core.database import DB_PATH, cn_now


class SteamPriceStore:
    """管理个人关注、频道推送订阅与推送去重记录。"""

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        connection = await aiosqlite.connect(DB_PATH, timeout=5)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA journal_mode=WAL")
        await connection.execute("PRAGMA busy_timeout=5000")
        await connection.execute("PRAGMA synchronous=NORMAL")
        try:
            yield connection
        except BaseException:
            await connection.rollback()
            raise
        finally:
            await connection.close()

    async def setup(self) -> None:
        async with self._connect() as connection:
            await connection.executescript(
                """
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
                """
            )
            cursor = await connection.execute("PRAGMA table_info(steam_price_log)")
            if not any(row["name"] == "kind" for row in await cursor.fetchall()):
                await connection.execute(
                    "ALTER TABLE steam_price_log ADD COLUMN kind TEXT NOT NULL DEFAULT ''"
                )
            await connection.commit()

    async def add_personal_watch(
        self,
        user_id: str,
        itad_id: str,
        app_id: int | None,
        game_name: str,
        current_price: float | None,
        lowest_price: float | None,
        channel: str,
        area: str,
    ) -> int:
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO steam_watch_personal
                    (user_id, itad_id, app_id, game_name, current_price, lowest_price, channel, area, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, itad_id, app_id, game_name, current_price, lowest_price, channel, area, cn_now()),
            )
            await connection.commit()
            return int(cursor.lastrowid or 0)

    async def remove_personal_watch(self, watch_id: int, user_id: str) -> bool:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "DELETE FROM steam_watch_personal WHERE id=? AND user_id=?",
                (watch_id, user_id),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def get_personal_watches(self, user_id: str) -> list[dict]:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM steam_watch_personal WHERE user_id=? ORDER BY id",
                (user_id,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def get_all_personal_watches(self) -> list[dict]:
        async with self._connect() as connection:
            cursor = await connection.execute("SELECT * FROM steam_watch_personal ORDER BY id")
            return [dict(row) for row in await cursor.fetchall()]

    async def count_personal_watches(self, user_id: str) -> int:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) AS cnt FROM steam_watch_personal WHERE user_id=?",
                (user_id,),
            )
            row = await cursor.fetchone()
            return int(row["cnt"]) if row else 0

    async def is_watching(self, user_id: str, itad_id: str) -> bool:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM steam_watch_personal WHERE user_id=? AND itad_id=?",
                (user_id, itad_id),
            )
            return await cursor.fetchone() is not None

    async def update_watch_price(
        self,
        watch_id: int,
        current_price: float | None,
        lowest_price: float | None,
    ) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "UPDATE steam_watch_personal SET current_price=?, lowest_price=? WHERE id=?",
                (current_price, lowest_price, watch_id),
            )
            await connection.commit()

    async def subscribe_channel(self, channel: str, area: str, min_discount: int = 50) -> None:
        async with self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO steam_watch_channel (channel, area, min_discount, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel, area) DO UPDATE SET
                    min_discount=excluded.min_discount
                """,
                (channel, area, min_discount, cn_now()),
            )
            await connection.commit()

    async def unsubscribe_channel(self, channel: str, area: str) -> bool:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "DELETE FROM steam_watch_channel WHERE channel=? AND area=?",
                (channel, area),
            )
            await connection.commit()
            return cursor.rowcount > 0

    async def is_channel_subscribed(self, channel: str, area: str) -> bool:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM steam_watch_channel WHERE channel=? AND area=?",
                (channel, area),
            )
            return await cursor.fetchone() is not None

    async def get_channel_subscriptions(self) -> list[dict]:
        async with self._connect() as connection:
            cursor = await connection.execute("SELECT * FROM steam_watch_channel ORDER BY id")
            return [dict(row) for row in await cursor.fetchall()]

    async def any_subscriptions(self) -> bool:
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT 1 FROM steam_watch_personal
                UNION ALL
                SELECT 1 FROM steam_watch_channel
                LIMIT 1
                """
            )
            return await cursor.fetchone() is not None

    async def has_notified(self, itad_id: str, price: float, kind: str) -> bool:
        # kind='' 是加列前的旧记录，对两类推送都视为已推送。
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM steam_price_log WHERE itad_id=? AND price=? AND kind IN (?, '')",
                (itad_id, price, kind),
            )
            return await cursor.fetchone() is not None

    async def mark_notified(self, itad_id: str, price: float, discount: int, kind: str) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "INSERT INTO steam_price_log (itad_id, price, discount, kind, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (itad_id, price, discount, kind, cn_now()),
            )
            await connection.commit()

    async def cleanup_old_logs(self, days: int = 90) -> None:
        async with self._connect() as connection:
            await connection.execute(
                "DELETE FROM steam_price_log WHERE recorded_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            await connection.commit()
