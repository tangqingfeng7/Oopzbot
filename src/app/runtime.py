import contextlib
import ipaddress
import math
import os

import config as runtime_config


def env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def apply_runtime_overrides() -> None:
    """使用环境变量覆盖部分运行时配置。"""
    redis_cfg = getattr(runtime_config, "REDIS_CONFIG", None)
    if isinstance(redis_cfg, dict):
        redis_host = os.environ.get("BOT_REDIS_HOST")
        redis_port = os.environ.get("BOT_REDIS_PORT")
        redis_password = os.environ.get("BOT_REDIS_PASSWORD")
        redis_db = os.environ.get("BOT_REDIS_DB")
        redis_connect_timeout = os.environ.get("BOT_REDIS_CONNECT_TIMEOUT")
        redis_socket_timeout = os.environ.get("BOT_REDIS_SOCKET_TIMEOUT")
        redis_health_interval = os.environ.get("BOT_REDIS_HEALTH_CHECK_INTERVAL")
        if redis_host:
            redis_cfg["host"] = redis_host.strip()
        if redis_port:
            with contextlib.suppress(ValueError):
                redis_cfg["port"] = int(redis_port)
        if redis_password is not None:
            redis_cfg["password"] = redis_password
        if redis_db:
            with contextlib.suppress(ValueError):
                redis_cfg["db"] = int(redis_db)
        if redis_connect_timeout:
            try:
                redis_cfg["socket_connect_timeout"] = float(redis_connect_timeout)
            except ValueError as exc:
                raise ValueError("BOT_REDIS_CONNECT_TIMEOUT 必须是数字") from exc
        if redis_socket_timeout:
            try:
                redis_cfg["socket_timeout"] = float(redis_socket_timeout)
            except ValueError as exc:
                raise ValueError("BOT_REDIS_SOCKET_TIMEOUT 必须是数字") from exc
        if redis_health_interval:
            try:
                redis_cfg["health_check_interval"] = int(redis_health_interval)
            except ValueError as exc:
                raise ValueError("BOT_REDIS_HEALTH_CHECK_INTERVAL 必须是整数") from exc

    netease_cfg = getattr(runtime_config, "NETEASE_CLOUD", None)
    if isinstance(netease_cfg, dict):
        netease_base_url = os.environ.get("BOT_NETEASE_BASE_URL")
        if netease_base_url:
            netease_cfg["base_url"] = netease_base_url.strip()
        if env_flag("BOT_DISABLE_AUTO_START_NETEASE"):
            netease_cfg["auto_start_path"] = ""

    web_cfg = getattr(runtime_config, "WEB_PLAYER_CONFIG", None)
    if isinstance(web_cfg, dict):
        web_host = os.environ.get("BOT_WEB_HOST")
        web_port = os.environ.get("BOT_WEB_PORT")
        trusted_proxy_cidrs = os.environ.get("BOT_WEB_TRUSTED_PROXY_CIDRS")
        if web_host:
            web_cfg["host"] = web_host.strip()
        if web_port:
            with contextlib.suppress(ValueError):
                web_cfg["port"] = int(web_port)
        if trusted_proxy_cidrs is not None:
            web_cfg["trusted_proxy_cidrs"] = [
                item.strip()
                for item in trusted_proxy_cidrs.split(",")
                if item.strip()
            ]

    oopz_cfg = getattr(runtime_config, "OOPZ_CONFIG", None)
    if isinstance(oopz_cfg, dict):
        base_url = os.environ.get("BOT_OOPZ_BASE_URL", "").strip()
        if base_url:
            oopz_cfg["base_url"] = base_url.rstrip("/")
        ws_url = os.environ.get("BOT_OOPZ_WS_URL")
        if ws_url is not None:
            # 空值显式恢复自动配对，兼容旧配置中固定的主线路地址。
            oopz_cfg["ws_url"] = ws_url.strip()
        proxy = os.environ.get("BOT_OOPZ_PROXY")
        if proxy is not None:
            oopz_cfg["proxy"] = proxy
        if env_flag("BOT_DISABLE_VOICE"):
            oopz_cfg["agora_app_id"] = ""


def validate_runtime_config() -> None:
    """在启动业务线程前验证不能安全降级的运行时配置。"""
    redis_cfg = getattr(runtime_config, "REDIS_CONFIG", None)
    if isinstance(redis_cfg, dict):
        numeric_fields = {
            "socket_connect_timeout": 3.0,
            "socket_timeout": 5.0,
            "health_check_interval": 30,
        }
        for field, default in numeric_fields.items():
            value = redis_cfg.get(field, default)
            try:
                parsed = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"REDIS_CONFIG.{field} 必须是正数") from exc
            if not math.isfinite(parsed) or parsed <= 0:
                raise ValueError(f"REDIS_CONFIG.{field} 必须是正数")

    web_cfg = getattr(runtime_config, "WEB_PLAYER_CONFIG", None)
    if isinstance(web_cfg, dict):
        if "trust_proxy_header" in web_cfg:
            raise ValueError(
                "WEB_PLAYER_CONFIG.trust_proxy_header 已移除；"
                "请改用 trusted_proxy_cidrs 明确信任的反向代理网段"
            )
        raw_cidrs = web_cfg.get(
            "trusted_proxy_cidrs",
            ["127.0.0.1/32", "::1/128"],
        )
        if not isinstance(raw_cidrs, (list, tuple)):
            raise ValueError("WEB_PLAYER_CONFIG.trusted_proxy_cidrs 必须是字符串列表")
        for raw in raw_cidrs:
            try:
                ipaddress.ip_network(str(raw).strip(), strict=False)
            except ValueError as exc:
                raise ValueError(f"无效的可信代理网段: {raw}") from exc
