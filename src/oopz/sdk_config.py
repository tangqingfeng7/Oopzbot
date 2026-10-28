"""把 Oopzbot 的现有配置装配成 Oopz-SDK 配置。"""

from __future__ import annotations

import os
import time
from typing import Any

from config import DEFAULT_HEADERS, OOPZ_CONFIG
from core.logger_config import get_logger
from core.proxy_utils import ProxySettings, resolve_proxy_settings_with_env
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


async def _onebot_v11_config() -> OneBotV11Config:
    from onebot_v11.config import get_onebot_v11_config
    from onebot_v11.sdk_migration import migrate_onebot_v11_database

    current = get_onebot_v11_config()
    if current.enabled:
        # 必须先完成事务迁移再构造 OopzBot；SDK adapter 的构造函数会立刻打开该库。
        await migrate_onebot_v11_database(current.db_path)
    post_timeout = float(current.http_post_timeout or 0.0)
    if post_timeout <= 0:
        post_timeout = 10.0
    return OneBotV11Config(
        enabled=current.enabled,
        auto_start_server=True,
        platform="oopz",
        self_id=str(OOPZ_CONFIG.get("person_uid") or ""),
        db_path=current.db_path,
        host=current.host,
        port=current.port,
        access_token=current.access_token,
        secret=current.secret,
        enable_http=current.enable_http,
        enable_ws=current.enable_ws,
        enable_http_post=current.enable_http_post,
        enable_ws_reverse=current.enable_ws_reverse,
        http_post_urls=list(current.http_post_urls),
        http_post_timeout=post_timeout,
        ws_reverse_url=current.ws_reverse_url,
        ws_reverse_api_url=current.ws_reverse_api_url,
        ws_reverse_event_url=current.ws_reverse_event_url,
        ws_reverse_reconnect_interval=current.ws_reverse_reconnect_interval,
        send_connect_event=current.send_connect_event,
        enable_area_scoped_group_ban=current.enable_area_scoped_group_ban,
        enable_set_group_leave_as_area_leave=current.enable_set_group_leave_as_area_leave,
        enable_set_group_kick_as_area_kick=current.enable_set_group_kick_as_area_kick,
    )


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
