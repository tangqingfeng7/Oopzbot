"""Web 播放器配置管理 — 配置分组、校验、持久化覆盖、运行时辅助函数。"""

from __future__ import annotations

import copy
import json
import os
from typing import Optional

import config as runtime_config
from logger_config import get_logger

logger = get_logger("WebPlayerConfig")

# ---------------------------------------------------------------------------
# 运行时配置引用
# ---------------------------------------------------------------------------

WEB_PLAYER_CONFIG = runtime_config.WEB_PLAYER_CONFIG
OOPZ_CONFIG = getattr(runtime_config, "OOPZ_CONFIG", {})
NETEASE_CLOUD = getattr(runtime_config, "NETEASE_CLOUD", {})
DOUBAO_CONFIG = getattr(runtime_config, "DOUBAO_CONFIG", {})
DOUBAO_IMAGE_CONFIG = getattr(runtime_config, "DOUBAO_IMAGE_CONFIG", {})
AUTO_RECALL_CONFIG = getattr(runtime_config, "AUTO_RECALL_CONFIG", {})
AREA_JOIN_NOTIFY = getattr(runtime_config, "AREA_JOIN_NOTIFY", {})
CHAT_CONFIG = getattr(runtime_config, "CHAT_CONFIG", {})
PROFANITY_CONFIG = getattr(runtime_config, "PROFANITY_CONFIG", {})
REDIS_CONFIG = runtime_config.REDIS_CONFIG
SCHEDULER_CONFIG = getattr(runtime_config, "SCHEDULER_CONFIG", {"enabled": True, "check_interval_seconds": 30})
REMINDER_CONFIG = getattr(runtime_config, "REMINDER_CONFIG", {"enabled": True, "max_per_user": 5, "max_delay_hours": 72, "check_interval_seconds": 15})
MUSIC_CONFIG = getattr(runtime_config, "MUSIC_CONFIG", {"auto_play_enabled": True, "default_volume": 50})
COMMAND_COOLDOWN_CONFIG = getattr(runtime_config, "COMMAND_COOLDOWN_CONFIG", {"enabled": False, "default_seconds": 3, "exempt_admins": True})
QQ_MUSIC_CONFIG = getattr(runtime_config, "QQ_MUSIC_CONFIG", {"enabled": False, "base_url": "http://localhost:3300", "cookie": ""})
BILIBILI_MUSIC_CONFIG = getattr(runtime_config, "BILIBILI_MUSIC_CONFIG", {"enabled": False, "cookie": ""})
MESSAGE_STATS_CONFIG = getattr(runtime_config, "MESSAGE_STATS_CONFIG", {"enabled": True})

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADMIN_OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "data", "admin_runtime_config.json")
KEY_ADMIN_SESSION = "music:admin_session"

# ---------------------------------------------------------------------------
# 配置分组定义
# ---------------------------------------------------------------------------

CONFIG_GROUPS: dict[str, dict] = {
    "web_player": {
        "target": WEB_PLAYER_CONFIG,
        "fields": {
            "url": {"type": "str", "max_len": 300},
            "host": {"type": "str", "max_len": 64},
            "port": {"type": "int", "min": 1, "max": 65535},
            "token_ttl_seconds": {"type": "int", "min": 0, "max": 7 * 24 * 3600},
            "cookie_max_age_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "cookie_secure": {"type": "bool"},
            "link_idle_release_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "admin_enabled": {"type": "bool"},
            "admin_password": {"type": "str", "max_len": 128, "sensitive": True},
            "admin_session_ttl_seconds": {"type": "int", "min": 0, "max": 30 * 24 * 3600},
            "admin_cookie_secure": {"type": "bool"},
        },
    },
    "auto_recall": {
        "target": AUTO_RECALL_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "delay": {"type": "int", "min": 1, "max": 3600},
            "exclude_commands": {"type": "str_list", "max_len": 500},
        },
    },
    "area_join_notify": {
        "target": AREA_JOIN_NOTIFY,
        "fields": {
            "enabled": {"type": "bool"},
            "message_template": {"type": "str", "max_len": 200},
            "message_template_leave": {"type": "str", "max_len": 200},
            "poll_interval_seconds": {"type": "int", "min": 2, "max": 3600},
            "auto_assign_role_id": {"type": "str", "max_len": 128},
            "auto_assign_role_name": {"type": "str", "max_len": 128},
        },
    },
    "chat": {
        "target": CHAT_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "keyword_replies": {"type": "json_dict", "max_len": 5000},
        },
    },
    "profanity": {
        "target": PROFANITY_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "mute_duration": {"type": "int", "min": 1, "max": 10080},
            "recall_message": {"type": "bool"},
            "skip_admins": {"type": "bool"},
            "warn_before_mute": {"type": "bool"},
            "context_detection": {"type": "bool"},
            "context_window": {"type": "int", "min": 5, "max": 300},
            "context_max_messages": {"type": "int", "min": 1, "max": 50},
            "ai_detection": {"type": "bool"},
            "ai_min_length": {"type": "int", "min": 1, "max": 50},
        },
    },
    "oopz": {
        "target": OOPZ_CONFIG,
        "fields": {
            "default_area": {"type": "str", "max_len": 128},
            "default_channel": {"type": "str", "max_len": 128},
            "use_announcement_style": {"type": "bool"},
            "proxy": {"type": "str", "max_len": 300},
            "agora_app_id": {"type": "str", "max_len": 128},
            "agora_init_timeout": {"type": "int", "min": 10, "max": 7200},
        },
    },
    "netease": {
        "target": NETEASE_CLOUD,
        "fields": {
            "base_url": {"type": "str", "max_len": 300},
            "cookie": {"type": "str", "max_len": 3000, "sensitive": True, "expose_in_admin": True},
            "audio_download_timeout": {"type": "int", "min": 5, "max": 600},
            "audio_download_retries": {"type": "int", "min": 0, "max": 10},
            "audio_quality": {"type": "str", "max_len": 20},
        },
    },
    "redis": {
        "target": REDIS_CONFIG,
        "fields": {
            "host": {"type": "str", "max_len": 200},
            "port": {"type": "int", "min": 1, "max": 65535},
            "password": {"type": "str", "max_len": 256, "sensitive": True},
            "db": {"type": "int", "min": 0, "max": 15},
            "decode_responses": {"type": "bool"},
        },
    },
    "doubao_chat": {
        "target": DOUBAO_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "api_key": {"type": "str", "max_len": 256, "sensitive": True, "expose_in_admin": True},
            "model": {"type": "str", "max_len": 120},
            "system_prompt": {"type": "str", "max_len": 5000},
            "max_tokens": {"type": "int", "min": 1, "max": 8192},
            "temperature": {"type": "float", "min": 0, "max": 2},
            "context_max_rounds": {"type": "int", "min": 0, "max": 50},
            "context_ttl_seconds": {"type": "int", "min": 0, "max": 86400},
        },
    },
    "doubao_image": {
        "target": DOUBAO_IMAGE_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "api_key": {"type": "str", "max_len": 256, "sensitive": True, "expose_in_admin": True},
            "model": {"type": "str", "max_len": 120},
            "size": {"type": "str", "max_len": 30},
            "watermark": {"type": "bool"},
        },
    },
    "scheduler": {
        "target": SCHEDULER_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "check_interval_seconds": {"type": "int", "min": 10, "max": 3600},
        },
    },
    "reminder": {
        "target": REMINDER_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "max_per_user": {"type": "int", "min": 1, "max": 100},
            "max_delay_hours": {"type": "int", "min": 1, "max": 720},
            "check_interval_seconds": {"type": "int", "min": 5, "max": 3600},
        },
    },
    "music": {
        "target": MUSIC_CONFIG,
        "fields": {
            "auto_play_enabled": {"type": "bool"},
            "default_volume": {"type": "int", "min": 0, "max": 100},
        },
    },
    "command_cooldown": {
        "target": COMMAND_COOLDOWN_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "default_seconds": {"type": "int", "min": 0, "max": 300},
            "exempt_admins": {"type": "bool"},
        },
    },
    "qq_music": {
        "target": QQ_MUSIC_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "base_url": {"type": "str", "max_len": 300},
            "cookie": {"type": "str", "max_len": 3000, "sensitive": True, "expose_in_admin": True},
        },
    },
    "bilibili_music": {
        "target": BILIBILI_MUSIC_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
            "cookie": {"type": "str", "max_len": 3000, "sensitive": True, "expose_in_admin": True},
        },
    },
    "message_stats": {
        "target": MESSAGE_STATS_CONFIG,
        "fields": {
            "enabled": {"type": "bool"},
        },
    },
}

CONFIG_BASELINES: dict[str, dict] = {
    group: copy.deepcopy(CONFIG_GROUPS[group]["target"])
    for group in CONFIG_GROUPS
    if isinstance(CONFIG_GROUPS[group].get("target"), dict)
}

# ---------------------------------------------------------------------------
# 配置辅助函数
# ---------------------------------------------------------------------------

_DEFAULT_COOKIE_MAX_AGE = 7 * 24 * 3600  # 7 days


def token_ttl_seconds() -> int:
    try:
        ttl = int(WEB_PLAYER_CONFIG.get("token_ttl_seconds", 86400) or 0)
    except (TypeError, ValueError):
        ttl = 86400
    return ttl if ttl > 0 else 0


def cookie_max_age_seconds() -> int:
    configured = WEB_PLAYER_CONFIG.get("cookie_max_age_seconds")
    if configured is not None:
        try:
            v = int(configured)
            return v if v > 0 else _DEFAULT_COOKIE_MAX_AGE
        except (TypeError, ValueError):
            pass
    ttl = token_ttl_seconds()
    return ttl if ttl > 0 else _DEFAULT_COOKIE_MAX_AGE


def cookie_secure() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("cookie_secure", False))


def admin_enabled() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("admin_enabled", False))


def admin_password() -> str:
    value = WEB_PLAYER_CONFIG.get("admin_password", "")
    return str(value).strip() if value is not None else ""


def admin_session_ttl_seconds() -> int:
    try:
        ttl = int(WEB_PLAYER_CONFIG.get("admin_session_ttl_seconds", 43200) or 0)
    except (TypeError, ValueError):
        ttl = 43200
    return ttl if ttl > 0 else 0


def admin_cookie_secure() -> bool:
    return bool(WEB_PLAYER_CONFIG.get("admin_cookie_secure", cookie_secure()))


def admin_cookie_name() -> str:
    return "admin_session"


# ---------------------------------------------------------------------------
# 类型强转 / 校验
# ---------------------------------------------------------------------------

def to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    raise ValueError("布尔值格式无效")


def coerce_config_value(meta: dict, raw: object) -> object:
    value_type = meta.get("type")
    if value_type == "bool":
        return to_bool(raw)
    if value_type == "float":
        try:
            v = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("浮点数格式无效")
        min_v = meta.get("min")
        max_v = meta.get("max")
        if min_v is not None and v < min_v:
            raise ValueError(f"必须 >= {min_v}")
        if max_v is not None and v > max_v:
            raise ValueError(f"必须 <= {max_v}")
        return v
    if value_type == "int":
        try:
            v = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError("整数格式无效")
        min_v = meta.get("min")
        max_v = meta.get("max")
        if min_v is not None and v < min_v:
            raise ValueError(f"必须 >= {min_v}")
        if max_v is not None and v > max_v:
            raise ValueError(f"必须 <= {max_v}")
        return v
    if value_type == "str":
        text = "" if raw is None else str(raw)
        max_len = meta.get("max_len")
        if max_len is not None and len(text) > max_len:
            raise ValueError(f"长度不能超过 {max_len}")
        return text
    if value_type == "str_list":
        if isinstance(raw, str):
            items = [s.strip() for s in raw.split(",") if s.strip()]
        elif isinstance(raw, list):
            items = [str(s).strip() for s in raw if str(s).strip()]
        else:
            raise ValueError("需要字符串列表或逗号分隔的字符串")
        max_len = meta.get("max_len")
        joined = ",".join(items)
        if max_len is not None and len(joined) > max_len:
            raise ValueError(f"总长度不能超过 {max_len}")
        return items
    if value_type == "json_dict":
        if isinstance(raw, dict):
            d = raw
        elif isinstance(raw, str):
            try:
                d = json.loads(raw)
            except Exception:
                raise ValueError("JSON 格式无效")
            if not isinstance(d, dict):
                raise ValueError("必须是 JSON 对象")
        else:
            raise ValueError("需要 JSON 对象或字符串")
        max_len = meta.get("max_len")
        serialized = json.dumps(d, ensure_ascii=False)
        if max_len is not None and len(serialized) > max_len:
            raise ValueError(f"总长度不能超过 {max_len}")
        return d
    raise ValueError(f"未知类型: {value_type}")


# ---------------------------------------------------------------------------
# 管理后台配置覆盖（持久化到 JSON 文件）
# ---------------------------------------------------------------------------

def read_admin_overrides() -> dict:
    if not os.path.exists(ADMIN_OVERRIDES_PATH):
        return {}
    try:
        with open(ADMIN_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"读取后台配置覆盖文件失败: {e}")
        return {}


def write_admin_overrides(payload: dict) -> None:
    os.makedirs(os.path.dirname(ADMIN_OVERRIDES_PATH), exist_ok=True)
    with open(ADMIN_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def apply_config_updates(updates: dict) -> tuple[dict, list[str], dict]:
    applied: dict = {}
    errors: list[str] = []
    persist_payload: dict = {}
    for group_name, patch in (updates or {}).items():
        group = CONFIG_GROUPS.get(group_name)
        if not group:
            errors.append(f"未知配置分组: {group_name}")
            continue
        if not isinstance(patch, dict):
            errors.append(f"配置分组 {group_name} 必须是对象")
            continue
        target = group.get("target")
        fields = group.get("fields", {})
        if not isinstance(target, dict):
            errors.append(f"配置分组 {group_name} 不可写")
            continue
        for field, raw in patch.items():
            meta = fields.get(field)
            if not meta:
                errors.append(f"配置项不允许修改: {group_name}.{field}")
                continue
            if meta.get("sensitive") and (raw is None or str(raw).strip() == ""):
                continue
            try:
                value = coerce_config_value(meta, raw)
            except Exception as e:
                errors.append(f"配置项 {group_name}.{field} 校验失败: {e}")
                continue
            target[field] = value
            applied.setdefault(group_name, {})
            persist_payload.setdefault(group_name, {})
            if meta.get("sensitive"):
                applied[group_name][field] = "***"
            else:
                applied[group_name][field] = value
            persist_payload[group_name][field] = value
    return applied, errors, persist_payload


def merge_overrides(base: dict, patch: dict) -> dict:
    out: dict = {}
    for k, v in (base or {}).items():
        out[k] = dict(v) if isinstance(v, dict) else v
    for group, values in (patch or {}).items():
        if isinstance(values, dict):
            if not isinstance(out.get(group), dict):
                out[group] = {}
            out[group].update(values)
        else:
            out[group] = values
    return out


def config_snapshot() -> dict:
    result: dict = {}
    for group_name, group in CONFIG_GROUPS.items():
        target = group.get("target")
        fields = group.get("fields", {})
        if not isinstance(target, dict):
            continue
        section: dict = {}
        for field, meta in fields.items():
            if meta.get("sensitive"):
                value = target.get(field, "")
                section[field] = value if meta.get("expose_in_admin") else ""
                section[f"{field}_configured"] = bool(value)
            else:
                section[field] = target.get(field)
        result[group_name] = section
    return result


_refresh_callbacks: list = []


def on_config_refresh(callback) -> None:
    """注册配置变更后的回调，避免直接导入产生循环依赖。"""
    _refresh_callbacks.append(callback)


def refresh_runtime_dependents(applied_groups: set[str]) -> None:
    if "redis" not in applied_groups and "web_player" not in applied_groups:
        return
    for cb in _refresh_callbacks:
        try:
            cb()
        except Exception as e:
            logger.debug("Config refresh callback failed: %s", e)


def bootstrap_admin_overrides() -> None:
    existing = read_admin_overrides()
    if not existing:
        return
    _, errors, _ = apply_config_updates(existing)
    if errors:
        logger.warning("加载后台配置覆盖时存在问题: %s", " | ".join(errors))


def display_web_base_url() -> str:
    configured = str(WEB_PLAYER_CONFIG.get("url", "") or "").strip()
    if configured:
        return configured.rstrip("/")
    host = str(WEB_PLAYER_CONFIG.get("host", "127.0.0.1") or "127.0.0.1").strip()
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    port = WEB_PLAYER_CONFIG.get("port", 8080)
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# 会话管理辅助
# ---------------------------------------------------------------------------

def admin_session_key(token: str) -> str:
    return f"{KEY_ADMIN_SESSION}:{token}"


# ---------------------------------------------------------------------------
# 域配置持久化 (area_configs)
# ---------------------------------------------------------------------------

AREA_OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "data", "area_configs_override.json")


def read_area_overrides() -> dict:
    if not os.path.exists(AREA_OVERRIDES_PATH):
        return {}
    try:
        with open(AREA_OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("读取域配置覆盖文件失败: %s", e)
        return {}


def write_area_overrides(payload: dict) -> None:
    os.makedirs(os.path.dirname(AREA_OVERRIDES_PATH), exist_ok=True)
    with open(AREA_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def bootstrap_area_overrides() -> None:
    """启动时加载域配置覆盖到 AreaConfigRegistry。"""
    saved = read_area_overrides()
    if not saved:
        return
    try:
        from area_config import get_area_registry
        reg = get_area_registry()
        loaded = 0
        for area_id, raw in saved.items():
            if isinstance(raw, dict):
                reg.update_config(area_id, raw)
                loaded += 1
        if loaded:
            logger.info("从覆盖文件恢复了 %d 个域配置", loaded)
    except Exception as e:
        logger.warning("恢复域配置覆盖失败: %s", e)
