"""B 站 Web 扫码登录辅助：二维码渲染、Cookie 提取与账号状态查询。"""

from __future__ import annotations

import base64
import io
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlparse

import qrcode  # type: ignore[reportMissingModuleSource]
import requests

from core.constants import USER_AGENT
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger

from ._debug import _cookie_debug_summary, _cookie_pairs_from_response, _debug_profile_text

logger = get_logger("WebPlayerAdmin")

_BILIBILI_LOGIN_BASE = "https://passport.bilibili.com"
_BILIBILI_API_BASE = "https://api.bilibili.com"
_BILIBILI_QR_GENERATE_PATH = "/x/passport-login/web/qrcode/generate"
_BILIBILI_QR_POLL_PATH = "/x/passport-login/web/qrcode/poll"
_BILIBILI_NAV_PATH = "/x/web-interface/nav"
_BILIBILI_COOKIE_NAMES = (
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
)


class _PngImage(Protocol):
    """qrcode Pillow 后端实际提供、但第三方类型声明未完整描述的保存契约。"""

    def save(self, stream: io.BytesIO, format: str = "PNG", **kwargs: object) -> None:
        ...


def _make_qr_data_uri(content: str) -> str:
    """把登录 URL 渲染为前端可直接展示的二维码 PNG。"""
    image = cast(_PngImage, qrcode.make(content))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _bilibili_api_get(path: str, params: dict | None = None) -> tuple[dict, Any]:
    """请求 B 站 Web 扫码登录接口并返回 JSON。"""
    response = requests.get(
        f"{_BILIBILI_LOGIN_BASE}{path}",
        params=params or {},
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bilibili.com/",
            "Cache-Control": "no-cache",
        },
        timeout=HTTP_TIMEOUT_DEFAULT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("B 站 API 返回格式异常")
    return data, response


def _bilibili_account_api_get(path: str, headers: dict | None = None) -> tuple[dict, Any]:
    """请求 B 站 Web API，用于读取已登录账号信息。"""
    request_headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://www.bilibili.com/",
        "Cache-Control": "no-cache",
    }
    if headers:
        request_headers.update(headers)
    response = requests.get(
        f"{_BILIBILI_API_BASE}{path}",
        headers=request_headers,
        timeout=HTTP_TIMEOUT_DEFAULT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("B 站 API 返回格式异常")
    return data, response


def _bilibili_response_data(payload: dict) -> dict:
    """兼容 B 站响应中的 data 包装结构。"""
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _bilibili_login_message(payload: dict, default: str = "") -> str:
    """提取 B 站扫码接口返回的提示。"""
    nested = _bilibili_response_data(payload)
    return str(
        nested.get("message")
        or payload.get("message")
        or payload.get("msg")
        or default
    )


def _bilibili_qr_code(payload: dict) -> int:
    """从 B 站扫码轮询响应中提取状态码。"""
    nested = _bilibili_response_data(payload)
    for value in (nested.get("code"), payload.get("code")):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return -1


def _bilibili_cookie_from_poll(payload: dict, response: Any) -> str:
    """优先取 Set-Cookie，回退到跨域登录 URL 中的 Cookie 参数。"""
    cookie = _cookie_pairs_from_response(response, _BILIBILI_COOKIE_NAMES)
    if cookie:
        logger.debug("B 站扫码登录 Cookie 提取成功: source=response %s", _cookie_debug_summary(cookie))
        return cookie

    login_url = str(_bilibili_response_data(payload).get("url") or "").strip()
    if not login_url:
        logger.debug("B 站扫码登录未拿到跨域登录 URL，无法回退提取 Cookie")
        return ""
    try:
        query = parse_qs(urlparse(login_url).query)
    except Exception:
        logger.debug("B 站扫码登录 URL 解析失败，无法回退提取 Cookie", exc_info=True)
        return ""
    pairs = []
    for name in _BILIBILI_COOKIE_NAMES:
        values = query.get(name)
        if values and values[0]:
            pairs.append(f"{name}={values[0]}")
    cookie = "; ".join(pairs)
    if cookie:
        logger.debug("B 站扫码登录 Cookie 提取成功: source=url %s", _cookie_debug_summary(cookie))
    else:
        logger.debug("B 站扫码登录 URL 中未找到可用 Cookie 字段")
    return cookie


def _extract_bilibili_profile(payload: dict) -> dict | None:
    """从 B 站导航栏接口返回中提取昵称和 UID。"""
    data = _bilibili_response_data(payload)
    if not isinstance(data, dict) or not data.get("isLogin"):
        return None
    user_id = data.get("mid") or data.get("uid")
    if not user_id:
        return None
    return {
        "user_id": str(user_id),
        "nickname": str(data.get("uname") or data.get("name") or ""),
        "avatar_url": str(data.get("face") or ""),
    }


def _bilibili_account_status(cookie: str) -> dict:
    """使用 Cookie 查询当前 B 站登录账号。"""
    cookie = (cookie or "").strip()
    if not cookie:
        logger.debug("B 站账号状态查询跳过: 未配置 Cookie")
        return {"ok": True, "logged_in": False, "message": "未配置 B 站 Cookie"}

    logger.debug("B 站账号状态查询开始: %s", _cookie_debug_summary(cookie))
    payload, _ = _bilibili_account_api_get(
        _BILIBILI_NAV_PATH,
        headers={"Cookie": cookie},
    )
    data = _bilibili_response_data(payload)
    logger.debug(
        "B 站账号状态接口返回: code=%s isLogin=%s message=%s",
        payload.get("code"),
        data.get("isLogin") if isinstance(data, dict) else None,
        _bilibili_login_message(payload, ""),
    )
    profile = _extract_bilibili_profile(payload)
    if profile:
        logger.debug("B 站账号状态查询成功: %s", _debug_profile_text(profile))
        return {
            "ok": True,
            "logged_in": True,
            "profile": profile,
            "message": "B 站账号已登录",
        }

    message = _bilibili_login_message(payload, "Cookie 未登录或已过期")
    logger.debug("B 站账号状态查询未登录: message=%s", message)
    return {"ok": True, "logged_in": False, "message": message}


__all__ = [
    "_BILIBILI_API_BASE",
    "_BILIBILI_COOKIE_NAMES",
    "_BILIBILI_LOGIN_BASE",
    "_BILIBILI_NAV_PATH",
    "_BILIBILI_QR_GENERATE_PATH",
    "_BILIBILI_QR_POLL_PATH",
    "_bilibili_account_api_get",
    "_bilibili_account_status",
    "_bilibili_api_get",
    "_bilibili_cookie_from_poll",
    "_bilibili_login_message",
    "_bilibili_qr_code",
    "_bilibili_response_data",
    "_extract_bilibili_profile",
    "_make_qr_data_uri",
]
