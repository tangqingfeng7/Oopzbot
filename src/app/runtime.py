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
        if redis_host:
            redis_cfg["host"] = redis_host.strip()
        if redis_port:
            try:
                redis_cfg["port"] = int(redis_port)
            except ValueError:
                pass
        if redis_password is not None:
            redis_cfg["password"] = redis_password
        if redis_db:
            try:
                redis_cfg["db"] = int(redis_db)
            except ValueError:
                pass

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
        if web_host:
            web_cfg["host"] = web_host.strip()
        if web_port:
            try:
                web_cfg["port"] = int(web_port)
            except ValueError:
                pass

    oopz_cfg = getattr(runtime_config, "OOPZ_CONFIG", None)
    if isinstance(oopz_cfg, dict):
        proxy = os.environ.get("BOT_OOPZ_PROXY")
        if proxy is not None:
            oopz_cfg["proxy"] = proxy
        if env_flag("BOT_DISABLE_VOICE"):
            oopz_cfg["agora_app_id"] = ""
