"""基于 SDK 网关的异步 ID 到名称缓存。"""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING

from core.logger_config import get_logger
from core.paths import DATA_DIR

if TYPE_CHECKING:
    from oopz.sdk_gateway import AsyncOopzGateway

logger = get_logger("NameResolver")
NAMES_FILE = os.path.join(DATA_DIR, "names.json")


class NameResolver:
    """名称读取保持纯内存；缺失用户通过注入的 SDK 网关显式异步补全。"""

    _instance: NameResolver | None = None
    _MAX_UNNAMED_USERS = 5000

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._data: dict[str, dict[str, str]] = {
            "users": {},
            "channels": {},
            "areas": {},
        }
        self._pending_uids: set[str] = set()
        self._gateway: AsyncOopzGateway | None = None
        self._dirty = False
        self._revision = 0
        self._loaded = False
        self._save_task: asyncio.Task[None] | None = None
        self._save_delay_seconds = 1.0
        self._initialized = True
        self._load_config_names()

    async def start(self) -> None:
        if self._loaded:
            return
        file_data = await asyncio.to_thread(self._read_names_file)
        for category in ("users", "channels", "areas"):
            values = file_data.get(category)
            if isinstance(values, dict):
                self._data[category].update(
                    {str(key): str(value or "") for key, value in values.items()}
                )
        self._loaded = True
        logger.info(
            "已加载名称映射: %d 个用户, %d 个频道, %d 个区域",
            sum(bool(value) for value in self._data["users"].values()),
            sum(bool(value) for value in self._data["channels"].values()),
            sum(bool(value) for value in self._data["areas"].values()),
        )

    async def bind_gateway(self, gateway: AsyncOopzGateway) -> None:
        self._gateway = gateway
        await self.start()

    def user(self, uid: str) -> str:
        """仅读缓存；网络补全必须显式 ``await ensure_users``。"""
        return self.user_cached(uid)

    def user_cached(self, uid: str, *, fallback: bool = True) -> str:
        if not uid:
            return ""
        return self._data["users"].get(uid) or (self._short_id(uid) if fallback else "")

    def channel(self, channel_id: str) -> str:
        return self._get("channels", channel_id)

    def area(self, area_id: str) -> str:
        return self._get("areas", area_id)

    def set_user(self, uid: str, name: str) -> None:
        self._set("users", uid, name)

    def set_channel(self, channel_id: str, name: str) -> None:
        self._set("channels", channel_id, name)

    def set_area(self, area_id: str, name: str) -> None:
        self._set("areas", area_id, name)

    def find_uid_by_name(self, name: str) -> str | None:
        if not name:
            return None
        expected = name.casefold()
        for uid, current in self._data["users"].items():
            if current and current.casefold() == expected:
                return uid
        return None

    def register_id(self, category: str, id_val: str) -> None:
        if not category or not id_val:
            return
        bucket = self._data.setdefault(category, {})
        if id_val in bucket:
            return
        bucket[id_val] = ""
        if category == "users":
            self._evict_unnamed_users()
        self._mark_dirty()

    def register_ids(self, **categories: str) -> None:
        changed = False
        for category, id_val in categories.items():
            if not id_val:
                continue
            bucket = self._data.setdefault(category, {})
            if id_val not in bucket:
                bucket[id_val] = ""
                changed = True
        self._evict_unnamed_users()
        if changed:
            self._mark_dirty()

    async def batch_resolve_users(self, uids: list[str]) -> dict[str, str]:
        return await self.ensure_users(uids)

    async def ensure_users(self, uids: list[str]) -> dict[str, str]:
        unique = [str(uid) for uid in dict.fromkeys(uids) if str(uid)]
        if not unique:
            return {}
        to_fetch = [
            uid
            for uid in unique
            if not self._data["users"].get(uid) and uid not in self._pending_uids
        ]
        self._pending_uids.update(to_fetch)
        try:
            if to_fetch and self._gateway is not None:
                people = await self._gateway.get_person_infos_batch(to_fetch)
                for uid, person in people.items():
                    name = str(
                        person.get("name")
                        or person.get("nickname")
                        or person.get("displayName")
                        or ""
                    ).strip()
                    if name:
                        self._data["users"][uid] = name
                        self._dirty = True
                        self._revision += 1
                if people:
                    self._schedule_save()
        finally:
            self._pending_uids.difference_update(to_fetch)
        return {uid: self._data["users"].get(uid, "") for uid in unique}

    async def flush(self) -> None:
        task = self._save_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._save_task = None
        if not self._dirty:
            return
        snapshot = {
            category: dict(values)
            for category, values in self._data.items()
        }
        revision = self._revision
        await asyncio.to_thread(self._write_names_file, snapshot)
        self._dirty = revision != self._revision
        if self._dirty:
            self._schedule_save()

    async def close(self) -> None:
        await self.flush()
        self._gateway = None

    def get_stats(self) -> dict[str, int]:
        return {
            "users_total": len(self._data["users"]),
            "users_named": sum(bool(value) for value in self._data["users"].values()),
            "channels_total": len(self._data["channels"]),
            "channels_named": sum(bool(value) for value in self._data["channels"].values()),
            "areas_total": len(self._data["areas"]),
            "areas_named": sum(bool(value) for value in self._data["areas"].values()),
        }

    def _get(self, category: str, id_val: str) -> str:
        if not id_val:
            return ""
        value = self._data.setdefault(category, {}).get(id_val, "")
        if value:
            return value
        self.register_id(category, id_val)
        return self._short_id(id_val)

    def _set(self, category: str, id_val: str, name: str) -> None:
        if not id_val:
            return
        bucket = self._data.setdefault(category, {})
        if bucket.get(id_val) == name:
            return
        bucket[id_val] = name
        self._mark_dirty()

    def _evict_unnamed_users(self) -> None:
        users = self._data["users"]
        unnamed = [uid for uid, name in users.items() if not name]
        for uid in unnamed[: max(0, len(unnamed) - self._MAX_UNNAMED_USERS)]:
            users.pop(uid, None)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._revision += 1
        self._schedule_save()

    def _schedule_save(self) -> None:
        if self._save_task is not None and not self._save_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def delayed_save() -> None:
            await asyncio.sleep(self._save_delay_seconds)
            await self.flush()

        self._save_task = loop.create_task(delayed_save(), name="name-cache-save")

    def _load_config_names(self) -> None:
        try:
            from config import NAME_MAP

            for category in ("users", "channels", "areas"):
                values = NAME_MAP.get(category)
                if isinstance(values, dict):
                    self._data[category].update(values)
        except (ImportError, AttributeError):
            pass

    @staticmethod
    def _read_names_file() -> dict:
        if not os.path.isfile(NAMES_FILE):
            return {}
        try:
            with open(NAMES_FILE, encoding="utf-8") as file:
                payload = json.load(file)
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            logger.warning("加载 names.json 失败: %s", exc)
            return {}

    @staticmethod
    def _write_names_file(payload: dict) -> None:
        os.makedirs(os.path.dirname(NAMES_FILE), exist_ok=True)
        temporary = f"{NAMES_FILE}.tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, NAMES_FILE)

    @staticmethod
    def _short_id(full_id: str) -> str:
        if len(full_id) <= 12:
            return full_id
        return full_id[:6] + ".." + full_id[-4:]


_resolver: NameResolver | None = None


def get_resolver() -> NameResolver:
    global _resolver
    if _resolver is None:
        _resolver = NameResolver()
    return _resolver
