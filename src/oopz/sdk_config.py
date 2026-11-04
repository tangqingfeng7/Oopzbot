from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from oopz_sdk import HeartbeatConfig, OopzConfig, ProxyConfig
from oopz_sdk.auth import OopzLoginCredentials, login_with_password
from oopz_sdk.auth.manager import DEFAULT_REFRESH_THRESHOLD_SECONDS
from oopz_sdk.config.settings import (
    OneBotV11Config,
    RateLimitConfig,
    RequestConfig,
    RetryConfig,
)
from oopz_sdk.exceptions import OopzAuthError
from oopz_sdk.utils.jwt import decode_jwt_payload

from config import DEFAULT_HEADERS, OOPZ_CONFIG
from core.logger_config import get_logger
from core.onebot_migration import migrate_onebot_v11_database
from core.paths import PROJECT_ROOT_PATH
from core.proxy_utils import ProxySettings, resolve_proxy_settings_with_env

logger = get_logger("OopzSdkConfig")


def _load_private_key() -> Any:
    try:
        from private_key import get_private_key

        return get_private_key()
    except Exception:
        logger.warning("无法读取 private_key.py，将由 SDK 在校验凭据时报告具体错误")
        return None


def _login_account() -> tuple[str, str]:
    phone = os.environ.get("OOPZ_PHONE") or OOPZ_CONFIG.get("login_phone") or OOPZ_CONFIG.get("phone") or ""
    password = os.environ.get("OOPZ_PASSWORD") or OOPZ_CONFIG.get("login_password") or OOPZ_CONFIG.get("password") or ""
    return str(phone).strip(), str(password or "")


async def _persist_credentials(credentials: OopzLoginCredentials) -> None:
    # SDK 负责登录；项目仅把结果写回既有 config.py/private_key.py 格式。
    from oopz.credentials import persist_credentials

    await persist_credentials(credentials)


def _sdk_proxy(settings: ProxySettings) -> ProxyConfig:
    if not settings.enabled or str(settings.scheme or "").startswith("socks"):
        return ProxyConfig()
    return ProxyConfig(
        http=settings.server,
        https=settings.server,
        websocket=settings.server,
    )


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _resolve_db_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return str(PROJECT_ROOT_PATH / "data" / "onebot_v11.sqlite3")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT_PATH / path
    return str(path)


async def _onebot_v11_config() -> OneBotV11Config:
    try:
        import config as app_config
        raw = getattr(app_config, "ONEBOT_V11_CONFIG", {}) or {}
    except Exception:
        raw = {}

    env_enabled = os.environ.get("ONEBOT_V11_ENABLED")
    enabled = _as_bool(env_enabled, _as_bool(raw.get("enabled"), False))

    db_path = _resolve_db_path(raw.get("db_path"))
    cfg = OneBotV11Config(
        auto_start_server=True,
        platform="oopz",
        enabled=enabled,
        host=str(raw.get("host") or "127.0.0.1"),
        port=int(raw.get("port") or 6700),
        access_token=str(raw.get("access_token") or ""),
        secret=str(raw.get("secret") or ""),
        db_path=db_path,
        enable_http=_as_bool(raw.get("enable_http"), True),
        enable_ws=_as_bool(raw.get("enable_ws"), True),
        enable_http_post=_as_bool(raw.get("enable_http_post"), False),
        enable_ws_reverse=_as_bool(raw.get("enable_ws_reverse"), False),
        http_post_urls=_as_list(raw.get("http_post_urls")),
        http_post_timeout=float(raw.get("http_post_timeout") or 0.0),
        ws_reverse_url=str(raw.get("ws_reverse_url") or ""),
        ws_reverse_api_url=str(raw.get("ws_reverse_api_url") or ""),
        ws_reverse_event_url=str(raw.get("ws_reverse_event_url") or ""),
        ws_reverse_reconnect_interval=float(raw.get("ws_reverse_reconnect_interval") or 3.0),
        send_connect_event=_as_bool(raw.get("send_connect_event"), True),
        enable_area_scoped_group_ban=_as_bool(raw.get("enable_area_scoped_group_ban"), False),
        enable_set_group_kick_as_area_kick=_as_bool(raw.get("enable_set_group_kick_as_area_kick"), False),
        enable_set_group_leave_as_area_leave=_as_bool(raw.get("enable_set_group_leave_as_area_leave"), False),
    )
    cfg.http_post_timeout = max(0.0, cfg.http_post_timeout) or 10.0
    if cfg.enabled:
        await migrate_onebot_v11_database(db_path)
    return cfg


def _startup_login_needed(config: OopzConfig) -> bool:
    """启动时是否需要用账号密码重登。

    只在凭据缺失或已进入临期窗口时才重登。无条件重登有两个代价：登录端点通常带
    风控/限流，容器重启循环会反复打它；而且每次都要重写 config.py 与 private_key.py，
    白白制造一次原子写事务被打断的窗口。临期判断复用 SDK 的续期阈值，与运行期
    ``AuthManager`` 的口径保持一致。
    """
    if not config.has_credentials():
        return True
    remaining = _seconds_until_jwt_expiry(config.jwt_token)
    if remaining is None:
        # 没有 exp 就无从判断新鲜度，保守地沿用旧行为重登一次。
        return True
    return remaining <= DEFAULT_REFRESH_THRESHOLD_SECONDS


def _seconds_until_jwt_expiry(token: str) -> float | None:
    exp = decode_jwt_payload(token).get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return float(exp) - time.time()


async def build_sdk_config(
    credentials: OopzLoginCredentials | None = None,
) -> tuple[OopzConfig, ProxySettings, object]:
    """构建 SDK 配置，并在配置了账号密码时刷新和原子保存凭据。"""

    raw_proxy = OOPZ_CONFIG.get("proxy")
    proxy = resolve_proxy_settings_with_env(raw_proxy)
    onebot_v11 = await _onebot_v11_config()
    config = OopzConfig(
        device_id=str(OOPZ_CONFIG.get("device_id") or ""),
        person_uid=str(OOPZ_CONFIG.get("person_uid") or ""),
        jwt_token=str(OOPZ_CONFIG.get("jwt_token") or ""),
        private_key=_load_private_key(),
        base_url=str(OOPZ_CONFIG.get("base_url") or "https://gateway.oopz.cn"),
        ws_url=str(OOPZ_CONFIG.get("ws_url") or ""),
        app_version=str(OOPZ_CONFIG.get("app_version") or "69514"),
        channel=str(OOPZ_CONFIG.get("channel") or "Web"),
        platform=str(OOPZ_CONFIG.get("platform") or "windows"),
        web=bool(OOPZ_CONFIG.get("web", True)),
        use_announcement_style=bool(OOPZ_CONFIG.get("use_announcement_style", False)),
        agora_app_id=str(OOPZ_CONFIG.get("agora_app_id") or "358eebceadb94c2a9fd91ecd7b341602"),
        agora_init_timeout=int(OOPZ_CONFIG.get("agora_init_timeout") or 1800),
        voice_browser_executable_path=str(
            os.environ.get("BOT_CHROMIUM_EXECUTABLE_PATH")
            or os.environ.get("CHROME_BIN")
            or ""
        ),
        headers=dict(DEFAULT_HEADERS),
        retry=RetryConfig(max_attempts=3),
        request_config=RequestConfig(timeout=(10, 60)),
        rate_limit=RateLimitConfig(interval=0.35),
        heartbeat=HeartbeatConfig(
            interval=10.0,
            reconnect_interval=2.0,
            max_reconnect_interval=120.0,
        ),
        proxy=_sdk_proxy(proxy),
        auto_subscribe_joined_areas=True,
        ignore_self_messages=True,
        onebot_v11=onebot_v11,
    )

    if credentials is not None:
        config._apply_login_credentials(credentials)

    phone, password = _login_account()
    if phone and password:

        async def _relogin() -> OopzLoginCredentials:
            refreshed = await login_with_password(
                phone,
                password,
                device_id=config.device_id or None,
                timeout=20,
            )
            await _persist_credentials(refreshed)
            return refreshed

        config._auth_relogin = _relogin

        if credentials is None and _startup_login_needed(config):
            try:
                credentials = await _relogin()
            except Exception as exc:
                # 刷新失败时允许仍有效的已有凭据继续启动；凭据本就不可用的话，
                # 下面的 ensure_credentials() 会给出明确的致命错误。
                logger.warning("SDK 账号密码刷新失败，尝试继续使用已有凭据: %s", exc)
            else:
                config._apply_login_credentials(credentials)
                logger.info("已通过 Oopz-SDK 刷新并保存登录凭据")

    try:
        config.ensure_credentials()
    except OopzAuthError:
        # 保留 SDK 的明确异常类型，启动层据此给出致命错误而非无限重连。
        raise
    return config, proxy, raw_proxy
