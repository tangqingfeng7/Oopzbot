"""网易云音乐 API 辅助：扫码登录、Cookie 提取与账号状态查询。"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests

import web.web_player_config as cfg
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger

from ._debug import _cookie_debug_summary, _cookie_pairs_from_header, _debug_profile_text

logger = get_logger("WebPlayerAdmin")


def _normalize_netease_base_url(raw: object = "") -> str:
    """校验并规范化后台传入的网易云 API 地址。"""
    value = str(raw or cfg.NETEASE_CLOUD.get("base_url") or "").strip().rstrip("/")
    if not value:
        raise ValueError("网易云 API 地址为空")
    if len(value) > 300:
        raise ValueError("网易云 API 地址过长")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("网易云 API 地址必须是 http/https URL")
    return value


def _netease_timestamp_params(extra: dict | None = None) -> dict:
    """附加时间戳参数，避免网易云登录接口被缓存。"""
    stamp = str(int(time.time() * 1000))
    params = {
        "timestamp": stamp,
        "timerstamp": stamp,
    }
    if extra:
        params.update(extra)
    return params


def _netease_api_get(
    base_url: str,
    path: str,
    params: dict | None = None,
    headers: dict | None = None,
) -> tuple[dict, Any]:
    """请求本地/远端 NeteaseCloudMusicApi 并返回 JSON。"""
    request_headers = {"Cache-Control": "no-cache"}
    if headers:
        request_headers.update(headers)
    response = requests.get(
        f"{base_url}{path}",
        params=params or {},
        headers=request_headers,
        timeout=HTTP_TIMEOUT_DEFAULT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("网易云 API 返回格式异常")
    return data, response


def _netease_api_post(
    base_url: str,
    path: str,
    data: dict | None = None,
    headers: dict | None = None,
) -> tuple[dict, Any]:
    """POST 请求网易云 API；用于避免把长 Cookie 暴露在查询串里。"""
    request_headers = {"Cache-Control": "no-cache"}
    if headers:
        request_headers.update(headers)
    response = requests.post(
        f"{base_url}{path}",
        data=data or {},
        headers=request_headers,
        timeout=HTTP_TIMEOUT_DEFAULT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("网易云 API 返回格式异常")
    return payload, response


def _netease_response_data(payload: dict) -> dict:
    """兼容不同网易云 API 分支的 data 包装结构。"""
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _netease_qr_code(payload: dict) -> int:
    """从扫码检查响应中提取状态码。"""
    status_codes = {800, 801, 802, 803}
    values = (_netease_response_data(payload).get("code"), payload.get("code"))
    parsed_values = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in status_codes:
            return parsed
        parsed_values.append(parsed)
    if parsed_values:
        return parsed_values[0]
    return 0


def _cookie_from_response(payload: dict, response: Any) -> str:
    """优先取接口 JSON 中的 Cookie，回退到响应 Set-Cookie。"""
    nested = _netease_response_data(payload)
    cookie = str(payload.get("cookie") or nested.get("cookie") or "").strip()
    if cookie:
        logger.debug("网易云扫码登录 Cookie 提取成功: source=json %s", _cookie_debug_summary(cookie))
        return cookie

    jar = getattr(response, "cookies", None)
    if jar:
        try:
            pairs = [f"{item.name}={item.value}" for item in jar]
            cookie = "; ".join(pair for pair in pairs if pair)
            if cookie:
                logger.debug("网易云扫码登录 Cookie 提取成功: source=response %s", _cookie_debug_summary(cookie))
                return cookie
        except Exception:
            logger.debug("解析网易云登录响应 CookieJar 失败", exc_info=True)

    # 回退到 Set-Cookie 头时，只提取 name=value 对，丢弃 Max-Age/Expires/Path 等属性段，
    # 避免把属性写进配置导致 cookie 异常变长（超出 netease.cookie 长度上限）。
    header = response.headers.get("set-cookie", "") if hasattr(response, "headers") else ""
    cookie = _cookie_pairs_from_header(header)
    if cookie:
        logger.debug("网易云扫码登录 Cookie 提取成功: source=set-cookie %s", _cookie_debug_summary(cookie))
    else:
        logger.debug("网易云扫码登录响应中未找到可用 Cookie")
    return cookie


def _netease_login_message(payload: dict, default: str = "") -> str:
    """兼容 message/msg/nested message 三种提示字段。"""
    nested = _netease_response_data(payload)
    return str(
        payload.get("message")
        or payload.get("msg")
        or nested.get("message")
        or nested.get("msg")
        or default
    )


def _netease_account_status(base_url: str, cookie: str) -> dict:
    """通过项目约定的 ``POST /login/status`` 查询当前网易云账号。"""
    cookie = (cookie or "").strip()
    if not cookie:
        logger.debug("网易云账号状态查询跳过: 未配置 Cookie")
        return {"ok": True, "logged_in": False, "message": "未配置网易云 Cookie"}

    logger.debug("网易云账号状态查询开始: base_url=%s %s", base_url, _cookie_debug_summary(cookie))
    try:
        payload, _ = _netease_api_post(
            base_url,
            "/login/status",
            data=_netease_timestamp_params({"cookie": cookie}),
            headers={"Cookie": cookie},
        )
    except Exception as exc:
        logger.debug("网易云账号状态请求失败: path=/login/status error=%s", exc)
        return {"ok": False, "logged_in": False, "message": str(exc)}

    nested = _netease_response_data(payload)
    message = _netease_login_message(payload, "")
    logger.debug(
        "网易云账号状态接口返回: path=/login/status code=%s data_code=%s message=%s",
        payload.get("code"),
        nested.get("code"),
        message,
    )
    raw_profile = nested.get("profile")
    if isinstance(raw_profile, dict) and raw_profile.get("userId"):
        profile = {
            "user_id": str(raw_profile["userId"]),
            "nickname": str(raw_profile.get("nickname") or ""),
            "avatar_url": str(raw_profile.get("avatarUrl") or ""),
        }
        logger.debug("网易云账号状态查询成功: path=/login/status %s", _debug_profile_text(profile))
        return {
            "ok": True,
            "logged_in": True,
            "profile": profile,
            "message": "网易云账号已登录",
        }

    logger.debug("网易云账号状态未解析到 profile: path=/login/status message=%s", message)
    return {
        "ok": True,
        "logged_in": False,
        "message": message or "Cookie 未登录或已过期",
    }


__all__ = [
    "_cookie_from_response",
    "_netease_account_status",
    "_netease_api_get",
    "_netease_api_post",
    "_netease_login_message",
    "_netease_qr_code",
    "_netease_response_data",
    "_netease_timestamp_params",
    "_normalize_netease_base_url",
]
