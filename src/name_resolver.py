import os
import atexit
import json
import hashlib
import time
import uuid
import base64
import threading
from typing import Optional, List

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

from logger_config import get_logger

logger = get_logger("NameResolver")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES_FILE = os.path.join(_PROJECT_ROOT, "data", "names.json")

# Oopz API: 获取用户信息的端点
PERSON_INFOS_PATH = "/client/v1/person/v1/personInfos"


class NameResolver:
    """ID → 名称 解析器（自动 API 查询 + 文件持久化）"""

    _instance: Optional["NameResolver"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._lock = threading.RLock()
        self._data = {"users": {}, "channels": {}, "areas": {}}
        self._pending_uids: set = set()  # 待查询的用户 ID
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._save_delay_seconds = 1.0
        self._api_ready = False
        self._initialized = True
        self._load()
        self._init_api()
        atexit.register(self.flush)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def user(self, uid: str) -> str:
        """获取用户显示名称，未知则尝试 API 查询"""
        if not uid:
            return ""
        with self._lock:
            name = self._data.get("users", {}).get(uid, "")
            if name:
                return name
        # 不在锁内调用 API，避免死锁
        self._fetch_user_name(uid)
        with self._lock:
            name = self._data.get("users", {}).get(uid, "")
            return name if name else self._short_id(uid)

    def user_cached(self, uid: str) -> str:
        """仅返回本地缓存名称；未知时返回短 ID，不触发网络请求。"""
        if not uid:
            return ""
        with self._lock:
            name = self._data.get("users", {}).get(uid, "")
            return name if name else self._short_id(uid)

    def channel(self, channel_id: str) -> str:
        """获取频道显示名称，未知则返回短 ID"""
        return self._get("channels", channel_id)

    def area(self, area_id: str) -> str:
        """获取区域显示名称，未知则返回短 ID"""
        return self._get("areas", area_id)

    def set_user(self, uid: str, name: str):
        self._set("users", uid, name)

    def set_channel(self, channel_id: str, name: str):
        self._set("channels", channel_id, name)

    def set_area(self, area_id: str, name: str):
        self._set("areas", area_id, name)

    def find_uid_by_name(self, name: str) -> Optional[str]:
        """通过显示名称反查用户 UID，不区分大小写，返回第一个匹配。"""
        if not name:
            return None
        name_lower = name.lower()
        with self._lock:
            for uid, uname in self._data.get("users", {}).items():
                if uname and uname.lower() == name_lower:
                    return uid
        return None

    def register_id(self, category: str, id_val: str):
        """注册一个新发现的 ID（如果尚未记录）"""
        if not category or not id_val:
            return
        with self._lock:
            bucket = self._data.setdefault(category, {})
            if id_val in bucket:
                return
            bucket[id_val] = ""
            self._mark_dirty_no_lock()

    def batch_resolve_users(self, uids: List[str]):
        """批量解析用户名（后台异步）"""
        to_fetch = self._claim_pending_uids(uids)
        if not to_fetch:
            return
        threading.Thread(
            target=self._fetch_user_names_batch,
            args=(to_fetch,),
            daemon=True,
            name="NameResolverBatchFetch",
        ).start()

    def ensure_users(self, uids: List[str]) -> dict[str, str]:
        """同步确保一批用户名称已进入缓存，并返回当前名称映射。"""
        unique_uids = [uid for uid in dict.fromkeys(uids) if uid]
        if not unique_uids:
            return {}

        to_fetch = self._claim_pending_uids(unique_uids)
        if to_fetch:
            self._fetch_user_names_batch(to_fetch)

        with self._lock:
            users = self._data.get("users", {})
            return {uid: users.get(uid, "") for uid in unique_uids}

    # ------------------------------------------------------------------
    # Oopz API 调用
    # ------------------------------------------------------------------

    def _init_api(self):
        """延迟导入配置和密钥，避免循环依赖"""
        try:
            from config import OOPZ_CONFIG, DEFAULT_HEADERS
            from private_key import get_private_key

            self._config = OOPZ_CONFIG
            self._default_headers = DEFAULT_HEADERS
            self._private_key = get_private_key()
            self._api_ready = True
            logger.info("API 用户名查询已就绪")
        except Exception as e:
            logger.warning(f"API 初始化失败（将使用手动映射）: {e}")
            self._api_ready = False

    def _sign(self, data: str) -> str:
        sig = self._private_key.sign(
            data.encode("utf-8"),
            asym_padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("utf-8")

    def _make_headers(self, url_path: str, body_str: str) -> dict:
        ts = str(int(time.time() * 1000))
        md5 = hashlib.md5((url_path + body_str).encode("utf-8")).hexdigest()
        signature = self._sign(md5 + ts)
        h = dict(self._default_headers)
        h.update({
            "Oopz-Sign": signature,
            "Oopz-Request-Id": str(uuid.uuid4()),
            "Oopz-Time": ts,
            "Oopz-App-Version-Number": self._config["app_version"],
            "Oopz-Channel": self._config["channel"],
            "Oopz-Device-Id": self._config["device_id"],
            "Oopz-Platform": self._config["platform"],
            "Oopz-Web": str(self._config["web"]).lower(),
            "Oopz-Person": self._config["person_uid"],
            "Oopz-Signature": self._config["jwt_token"],
        })
        return h

    def _fetch_user_name(self, uid: str):
        """通过 API 获取单个用户名"""
        if not self._api_ready or not uid:
            return
        to_fetch = self._claim_pending_uids([uid])
        if to_fetch:
            self._fetch_user_names_batch(to_fetch)

    def _fetch_user_names_batch(self, uids: List[str]):
        """通过 API 批量获取用户名"""
        if not self._api_ready or not uids:
            self._release_pending_uids(uids)
            return

        try:
            with self._lock:
                to_fetch = [
                    uid for uid in dict.fromkeys(uids)
                    if uid and not self._data.get("users", {}).get(uid, "")
                ]
            if not to_fetch:
                return

            body = {"persons": to_fetch, "commonIds": []}
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            url = self._config["base_url"] + PERSON_INFOS_PATH
            headers = self._make_headers(PERSON_INFOS_PATH, body_str)

            resp = requests.post(
                url, headers=headers,
                data=body_str.encode("utf-8"),
                timeout=10,
            )
            if resp.status_code != 200:
                logger.debug(f"personInfos 请求失败: {resp.status_code}")
                return

            result = resp.json()
            if not result.get("status"):
                return

            data_list = result.get("data", [])
            updated = 0
            with self._lock:
                for person in data_list:
                    uid = person.get("uid", "")
                    name = person.get("name", "")
                    if uid and name:
                        self._data.setdefault("users", {})[uid] = name
                        updated += 1
                if updated:
                    self._mark_dirty_no_lock()

            if updated:
                names = [p.get("name", "") for p in data_list if p.get("name")]
                logger.info(f"API 自动获取到 {updated} 个用户名: {', '.join(names)}")

        except Exception as e:
            logger.debug(f"API 查询用户名失败: {e}")
        finally:
            self._release_pending_uids(uids)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _get(self, category: str, id_val: str) -> str:
        if not id_val:
            return ""
        with self._lock:
            name = self._data.get(category, {}).get(id_val, "")
            if not name:
                self._data.setdefault(category, {})[id_val] = ""
                self._mark_dirty_no_lock()
                return self._short_id(id_val)
            return name

    def _set(self, category: str, id_val: str, name: str):
        with self._lock:
            bucket = self._data.setdefault(category, {})
            if bucket.get(id_val) == name:
                return
            bucket[id_val] = name
            self._mark_dirty_no_lock()

    def _claim_pending_uids(self, uids: List[str]) -> List[str]:
        unique_uids = list(dict.fromkeys(uid for uid in uids if uid))
        if not unique_uids:
            return []
        to_fetch = []
        with self._lock:
            users = self._data.get("users", {})
            for uid in unique_uids:
                if users.get(uid, "") or uid in self._pending_uids:
                    continue
                self._pending_uids.add(uid)
                to_fetch.append(uid)
        return to_fetch

    def _release_pending_uids(self, uids: List[str]):
        if not uids:
            return
        with self._lock:
            for uid in uids:
                self._pending_uids.discard(uid)

    def _mark_dirty_no_lock(self):
        self._dirty = True
        self._schedule_save_no_lock()

    def _schedule_save_no_lock(self):
        if self._save_timer and self._save_timer.is_alive():
            return
        self._save_timer = threading.Timer(self._save_delay_seconds, self.flush)
        self._save_timer.daemon = True
        self._save_timer.start()

    @staticmethod
    def _short_id(full_id: str) -> str:
        if len(full_id) <= 12:
            return full_id
        return full_id[:6] + ".." + full_id[-4:]

    def _load(self):
        """从 names.json 和 config.py 加载映射"""
        try:
            from config import NAME_MAP
            for cat in ("users", "channels", "areas"):
                if cat in NAME_MAP:
                    self._data[cat].update(NAME_MAP[cat])
        except (ImportError, AttributeError):
            pass

        if os.path.exists(NAMES_FILE):
            try:
                with open(NAMES_FILE, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                for cat in ("users", "channels", "areas"):
                    if cat in file_data:
                        self._data[cat].update(file_data[cat])
                logger.info(
                    f"已加载名称映射: "
                    f"{sum(1 for v in self._data['users'].values() if v)} 个用户, "
                    f"{sum(1 for v in self._data['channels'].values() if v)} 个频道, "
                    f"{sum(1 for v in self._data['areas'].values() if v)} 个区域"
                )
            except Exception as e:
                logger.warning(f"加载 names.json 失败: {e}")
        else:
            logger.info("names.json 不存在，将自动创建")

    def _save_no_lock(self):
        """保存到 names.json（调用时需已持有锁）"""
        try:
            os.makedirs(os.path.dirname(NAMES_FILE), exist_ok=True)
            with open(NAMES_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存 names.json 失败: {e}")

    def flush(self):
        with self._lock:
            self._save_timer = None
            if not self._dirty:
                return
            self._save_no_lock()
            self._dirty = False

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "users_total": len(self._data.get("users", {})),
                "users_named": sum(1 for v in self._data.get("users", {}).values() if v),
                "channels_total": len(self._data.get("channels", {})),
                "channels_named": sum(1 for v in self._data.get("channels", {}).values() if v),
                "areas_total": len(self._data.get("areas", {})),
                "areas_named": sum(1 for v in self._data.get("areas", {}).values() if v),
            }


# 全局单例
_resolver: Optional[NameResolver] = None


def get_resolver() -> NameResolver:
    global _resolver
    if _resolver is None:
        _resolver = NameResolver()
    return _resolver
