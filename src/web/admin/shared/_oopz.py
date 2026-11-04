"""OOPZ 凭据热更新：统一受控重建SDK 会话。"""

from __future__ import annotations

import asyncio
from typing import Any

import web.web_player_config as cfg
from core.logger_config import get_logger
from oopz.credentials import credentials_payload
from oopz_sdk.auth import OopzLoginCredentials

from ._runtime import _get_sender

logger = get_logger("WebPlayerAdmin")

_oopz_login_lock = asyncio.Lock()
_OOPZ_RUNTIME_FIELDS = ("app_version", "device_id", "person_uid", "jwt_token")


def _oopz_runtime_updates(
    credentials: OopzLoginCredentials | dict[str, Any],
) -> dict[str, Any]:
    """提取可直接同步到 OOPZ_CONFIG 的非敏感字段名集合。"""
    payload = credentials_payload(credentials)
    return {
        key: payload.get(key)
        for key in _OOPZ_RUNTIME_FIELDS
        if payload.get(key)
    }


def _apply_oopz_config_updates(
    credentials: OopzLoginCredentials | dict[str, Any],
) -> bool:
    updates = _oopz_runtime_updates(credentials)
    if not updates:
        return False
    try:
        import config as runtime_config

        runtime_config.OOPZ_CONFIG.update(updates)
        cfg.OOPZ_CONFIG.update(updates)
        return True
    except Exception:
        logger.debug("同步 OOPZ_CONFIG 到运行时失败", exc_info=True)
        return False


async def _refresh_oopz_runtime(
    credentials: OopzLoginCredentials,
) -> dict[str, bool]:
    """应用新凭据，并由稳定网关对象原子切换到底层 SDK 会话。"""
    config_updated = _apply_oopz_config_updates(credentials)
    gateway = _get_sender()
    if gateway is None:
        return {"config": config_updated, "sdk_session": False}
    rebuild = getattr(gateway, "rebuild_credentials", None)
    if rebuild is None:
        raise RuntimeError("当前发送端不是 AsyncOopzGateway，无法热重建 SDK 会话")
    await rebuild(credentials)

    try:
        from oopz.name_resolver import NameResolver

        resolver = NameResolver()
        bind_gateway = getattr(resolver, "bind_gateway", None)
        if bind_gateway is not None:
            result = bind_gateway(gateway)
            if asyncio.iscoroutine(result):
                await result
    except Exception:
        logger.debug("凭据更新后重新绑定名称解析器失败", exc_info=True)

    return {"config": config_updated, "sdk_session": True}


__all__ = [
    "_OOPZ_RUNTIME_FIELDS",
    "_apply_oopz_config_updates",
    "_oopz_login_lock",
    "_oopz_runtime_updates",
    "_refresh_oopz_runtime",
]
