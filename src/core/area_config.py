"""多域配置注册表 -- 为每个域提供独立配置，未配置的域回退到全局默认值。"""

from __future__ import annotations

from dataclasses import dataclass

from core.logger_config import get_logger

logger = get_logger("AreaConfig")

_DEFAULT_WELCOME = "欢迎 {name} 加入域～\n请阅读频道规则，祝你玩得开心！"


def _parse_optional_bool(raw: object) -> bool | None:
    """三态 bool 解析：None/空/"inherit" → None，其余按布尔解析。"""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in {"", "inherit", "default", "global", "null", "none"}:
            return None
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
    return None


def _parse_role_ids(raw: object) -> tuple[int, ...]:
    if not isinstance(raw, (list, tuple, set)):
        return ()
    values: set[int] = set()
    for item in raw:
        try:
            role_id = int(item)
        except (TypeError, ValueError):
            continue
        if role_id > 0:
            values.add(role_id)
    return tuple(sorted(values))


@dataclass(frozen=True)
class AreaConfig:
    """单个域的配置快照。"""

    area_id: str
    name: str = ""
    default_channel: str = ""
    welcome_message: str = _DEFAULT_WELCOME
    # 留空继承 AREA_JOIN_NOTIFY.message_template_leave，包括其关闭状态。
    leave_message: str = ""
    auto_assign_role_id: str = ""
    auto_assign_role_name: str = ""
    admin_uids: tuple[str, ...] = ()
    plugins_enabled: tuple[str, ...] = ()
    plugins_disabled: tuple[str, ...] = ()
    screen_share_role_ids: tuple[int, ...] = ()
    # None = 跟随全局 OOPZ_CONFIG.use_announcement_style；True/False = 域级强制
    use_announcement_style: bool | None = None

    @classmethod
    def from_dict(cls, area_id: str, raw: dict) -> AreaConfig:
        return cls(
            area_id=area_id,
            name=str(raw.get("name", "") or ""),
            default_channel=str(raw.get("default_channel", "") or ""),
            welcome_message=str(raw.get("welcome_message", _DEFAULT_WELCOME) or _DEFAULT_WELCOME),
            leave_message=str(raw.get("leave_message") or "").strip(),
            auto_assign_role_id=str(raw.get("auto_assign_role_id", "") or ""),
            auto_assign_role_name=str(raw.get("auto_assign_role_name", "") or ""),
            admin_uids=tuple(str(u) for u in (raw.get("admin_uids") or [])),
            plugins_enabled=tuple(str(p) for p in (raw.get("plugins_enabled") or [])),
            plugins_disabled=tuple(str(p) for p in (raw.get("plugins_disabled") or [])),
            screen_share_role_ids=_parse_role_ids(raw.get("screen_share_role_ids")),
            use_announcement_style=_parse_optional_bool(raw.get("use_announcement_style")),
        )


class AreaConfigRegistry:
    """运行时多域配置注册表。"""

    def __init__(self) -> None:
        self._configs: dict[str, AreaConfig] = {}
        self._global_default_area: str = ""
        self._global_default_channel: str = ""
        self._global_admin_uids: tuple[str, ...] = ()
        self._load()

    def _load(self) -> None:
        try:
            import config as _cfg
            self._global_default_area = str(getattr(_cfg, "OOPZ_CONFIG", {}).get("default_area", "") or "")
            self._global_default_channel = str(getattr(_cfg, "OOPZ_CONFIG", {}).get("default_channel", "") or "")
            self._global_admin_uids = tuple(
                str(u) for u in (getattr(_cfg, "ADMIN_UIDS", None) or [])
            )
            raw_configs: dict = getattr(_cfg, "AREA_CONFIGS", None) or {}
        except Exception:
            raw_configs = {}

        for area_id, raw in raw_configs.items():
            area_id = str(area_id).strip()
            if not area_id:
                continue
            if not isinstance(raw, dict):
                continue
            self._configs[area_id] = AreaConfig.from_dict(area_id, raw)

        if self._configs:
            logger.info("已加载 %d 个域配置: %s", len(self._configs), ", ".join(self._configs))
        else:
            logger.info("未配置 AREA_CONFIGS，将使用全局默认域")

    def get(self, area_id: str) -> AreaConfig:
        """返回指定域的配置；未配置时回退到基于全局默认值构建的 AreaConfig。"""
        area_id = str(area_id or "").strip()
        if area_id in self._configs:
            return self._configs[area_id]
        resolved = area_id or self._global_default_area
        return AreaConfig(
            area_id=resolved,
            default_channel=self._global_default_channel if resolved == self._global_default_area else "",
        )

    def get_all_area_ids(self) -> list[str]:
        """返回所有显式配置的域 ID。若无显式配置，返回全局默认域（如果有）。"""
        if self._configs:
            return list(self._configs.keys())
        if self._global_default_area:
            return [self._global_default_area]
        return []

    def get_default_channel(self, area_id: str) -> str:
        """获取域的默认文字频道 ID。"""
        cfg = self.get(area_id)
        return cfg.default_channel or self._global_default_channel

    def get_admin_uids(self, area_id: str) -> tuple[str, ...]:
        """获取域的管理员列表。域级配置为空时继承全局。"""
        cfg = self.get(area_id)
        return cfg.admin_uids if cfg.admin_uids else self._global_admin_uids

    def is_configured(self, area_id: str) -> bool:
        return str(area_id or "").strip() in self._configs

    # ------------------------------------------------------------------
    # 运行时动态修改（后台管理用）
    # ------------------------------------------------------------------

    def update_config(self, area_id: str, raw: dict) -> AreaConfig:
        """创建或更新域配置，返回新的 AreaConfig 实例。"""
        area_id = str(area_id or "").strip()
        if not area_id:
            raise ValueError("area_id 不能为空")
        cfg = AreaConfig.from_dict(area_id, raw)
        self._configs[area_id] = cfg
        logger.info("域配置已更新: %s", area_id)
        return cfg

    def remove_config(self, area_id: str) -> bool:
        """删除域的独立配置，返回是否存在并已删除。"""
        area_id = str(area_id or "").strip()
        removed = self._configs.pop(area_id, None) is not None
        if removed:
            logger.info("域配置已删除: %s", area_id)
        return removed

    def get_all_configs(self) -> dict[str, AreaConfig]:
        """返回所有已配置域的配置副本。"""
        return dict(self._configs)

    @staticmethod
    def config_to_dict(cfg: AreaConfig) -> dict:
        """将 AreaConfig 序列化为可持久化的 dict。"""
        return {
            "name": cfg.name,
            "default_channel": cfg.default_channel,
            "welcome_message": cfg.welcome_message,
            "leave_message": cfg.leave_message,
            "auto_assign_role_id": cfg.auto_assign_role_id,
            "auto_assign_role_name": cfg.auto_assign_role_name,
            "admin_uids": list(cfg.admin_uids),
            "plugins_enabled": list(cfg.plugins_enabled),
            "plugins_disabled": list(cfg.plugins_disabled),
            "screen_share_role_ids": list(cfg.screen_share_role_ids),
            "use_announcement_style": cfg.use_announcement_style,
        }

    def get_announcement_style(self, area_id: str, fallback: bool) -> bool:
        """解析最终的"是否启用公告样式"：域级 None 时回退到 fallback（一般为全局默认）。"""
        cfg = self.get(area_id)
        if cfg.use_announcement_style is None:
            return fallback
        return bool(cfg.use_announcement_style)

    def export_all(self) -> dict[str, dict]:
        """导出所有域配置为可持久化的 dict。"""
        return {aid: self.config_to_dict(c) for aid, c in self._configs.items()}

    @property
    def global_default_area(self) -> str:
        return self._global_default_area

    @property
    def global_default_channel(self) -> str:
        return self._global_default_channel


_registry: AreaConfigRegistry | None = None


def get_area_registry() -> AreaConfigRegistry:
    """获取全局单例。"""
    global _registry
    if _registry is None:
        _registry = AreaConfigRegistry()
    return _registry
