import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.logger_config import get_logger
from web.admin.shared import (
    _admin_enabled,
    _clear_admin_session_token,
    _set_admin_session_token,
    cfg,
    read_json_body,
)
from web.web_rate_limit import client_ip, login_guard
from web.web_request_context import cookie_secure_for

logger = get_logger("WebPlayerAdmin")

router = APIRouter()

# ---------------------------------------------------------------------------
# 管理后台 API 路由
# ---------------------------------------------------------------------------

@router.post("/admin/api/login")
async def admin_login(request: Request):
    if not _admin_enabled():
        return JSONResponse({"ok": False, "error": "管理后台未启用"}, status_code=404)
    password = cfg.admin_password()
    if not password:
        return JSONResponse({"ok": False, "error": "未配置 admin_password"}, status_code=503)

    ip = client_ip(request, cfg.trusted_proxy_cidrs())
    lock_seconds = cfg.admin_login_lock_seconds()
    remaining = login_guard.locked_seconds(ip, lock_seconds)
    if remaining:
        logger.warning("后台登录已锁定，来源 %s，剩余 %ds", ip, remaining)
        return JSONResponse(
            {"ok": False, "error": f"失败次数过多，请 {remaining} 秒后再试"},
            status_code=429,
            headers={"Retry-After": str(remaining)},
        )

    body = await read_json_body(request)
    submitted = str(body.get("password", ""))
    # compare_digest 对含非 ASCII 的 str 会抛 TypeError，先编码成字节再比
    if not secrets.compare_digest(submitted.encode("utf-8"), password.encode("utf-8")):
        locked = login_guard.record_failure(ip, cfg.admin_login_max_failures(), lock_seconds)
        if locked:
            logger.warning("后台登录失败次数达上限，已锁定 %s %ds", ip, lock_seconds)
        else:
            logger.info("后台登录密码错误，来源 %s", ip)
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)

    login_guard.record_success(ip)
    token = secrets.token_urlsafe(24)
    await _set_admin_session_token(token)
    ttl = cfg.admin_session_ttl_seconds()
    response = JSONResponse({"ok": True, "ttl": ttl})
    response.set_cookie(
        key=cfg.admin_cookie_name(),
        value=token,
        path="/admin",
        httponly=True,
        samesite="lax",
        secure=cookie_secure_for(
            request,
            cfg.admin_cookie_secure(),
            cfg.trusted_proxy_cidrs(),
        ),
        max_age=ttl if ttl > 0 else None,
    )
    return response


@router.post("/admin/api/logout")
async def admin_logout(request: Request):
    await _clear_admin_session_token(request.cookies.get(cfg.admin_cookie_name(), ""))
    response = JSONResponse({"ok": True})
    response.delete_cookie(cfg.admin_cookie_name(), path="/admin")
    return response


@router.get("/admin/api/me")
def admin_me():
    return JSONResponse({"ok": True, "role": "admin"})

__all__ = ["router"]
