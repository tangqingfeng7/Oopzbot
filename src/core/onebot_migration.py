"""OneBot v11 旧数据库迁移。"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import aiosqlite

from core.logger_config import get_logger

logger = get_logger("OneBotV11Migration")

SDK_BACKUP_SUFFIX = ".pre-sdk-v0.15.0.bak"


async def _table_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f'PRAGMA table_info("{table}")')
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return {str(row[1]) for row in rows}


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    try:
        return await cursor.fetchone() is not None
    finally:
        await cursor.close()


async def _needs_migration(db_path: Path) -> bool:
    if not db_path.is_file():
        return False
    async with aiosqlite.connect(db_path) as db:
        id_columns = await _table_columns(db, "onebot_v11_id_map")
        has_legacy_ids = bool(id_columns) and "string" not in id_columns and "source" in id_columns
        has_legacy_messages = await _table_exists(db, "onebot_v11_messages")
        return has_legacy_ids or has_legacy_messages


async def _copy_backup_once(source: Path, backup: Path) -> bool:
    """原子保留首次迁移前快照；已有备份永不覆盖。"""

    def _copy() -> bool:
        try:
            with backup.open("xb") as target, source.open("rb") as origin:
                shutil.copyfileobj(origin, target)
            shutil.copystat(source, backup)
            return True
        except FileExistsError:
            return False
        except BaseException:
            backup.unlink(missing_ok=True)
            raise

    return await asyncio.to_thread(_copy)


async def migrate_onebot_v11_database(db_path: str | Path) -> Path | None:
    """迁移旧 OneBot 表；无旧数据时不创建数据库也不创建备份。"""

    path = Path(db_path).expanduser().resolve()
    if not await _needs_migration(path):
        return None

    backup = path.with_name(path.name + SDK_BACKUP_SUFFIX)
    created = await _copy_backup_once(path, backup)
    if created:
        logger.info("已创建 OneBot v11 迁移前备份: %s", backup)
    else:
        logger.info("OneBot v11 迁移备份已存在，保持不覆盖: %s", backup)

    async with aiosqlite.connect(path) as db:
        await db.execute("PRAGMA foreign_keys=OFF")
        await db.execute("BEGIN IMMEDIATE")
        try:
            id_columns = await _table_columns(db, "onebot_v11_id_map")
            if id_columns and "string" not in id_columns and "source" in id_columns:
                await db.execute(
                    "ALTER TABLE onebot_v11_id_map "
                    "RENAME TO onebot_v11_id_map_pre_sdk"
                )
                await db.execute(
                    """
                    CREATE TABLE onebot_v11_id_map (
                        string TEXT NOT NULL UNIQUE,
                        number INTEGER NOT NULL UNIQUE,
                        source TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                await db.execute(
                    """
                    INSERT INTO onebot_v11_id_map(string, number, source, created_at)
                    SELECT source, number, source, created_at
                    FROM onebot_v11_id_map_pre_sdk
                    """
                )
                await db.execute("DROP TABLE onebot_v11_id_map_pre_sdk")
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_onebot_v11_id_map_number "
                    "ON onebot_v11_id_map(number)"
                )

            if await _table_exists(db, "onebot_v11_messages"):
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS message_map (
                        ob_message_id TEXT PRIMARY KEY,
                        oopz_message_id TEXT NOT NULL,
                        detail_type TEXT NOT NULL,
                        area TEXT NOT NULL DEFAULT '',
                        channel TEXT NOT NULL DEFAULT '',
                        target TEXT NOT NULL DEFAULT '',
                        user_id TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        raw_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """
                )
                await db.execute(
                    """
                    INSERT INTO message_map (
                        ob_message_id, oopz_message_id, detail_type,
                        area, channel, target, user_id, created_at, raw_json
                    )
                    SELECT ob_message_id, oopz_message_id, detail_type,
                           area, channel, target, user_id, created_at, raw
                    FROM onebot_v11_messages
                    WHERE 1
                    ON CONFLICT(ob_message_id) DO UPDATE SET
                        oopz_message_id=excluded.oopz_message_id,
                        detail_type=excluded.detail_type,
                        area=excluded.area,
                        channel=excluded.channel,
                        target=excluded.target,
                        user_id=excluded.user_id,
                        created_at=excluded.created_at,
                        raw_json=excluded.raw_json
                    """
                )
                await db.execute("DROP TABLE onebot_v11_messages")
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_message_map_oopz "
                    "ON message_map(oopz_message_id, detail_type, area, channel, target)"
                )
            await db.commit()
        except BaseException:
            await db.rollback()
            logger.exception("OneBot v11 数据库迁移失败，已回滚；停止 OneBot 启动")
            raise

    logger.info("OneBot v11 数据库已迁移到 Oopz-SDK v0.15.0 结构")
    return backup


__all__ = ["SDK_BACKUP_SUFFIX", "migrate_onebot_v11_database"]
