from __future__ import annotations

import hashlib
import logging
from contextlib import suppress
from functools import wraps
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from web.web_player_config import trusted_proxy_cidrs
from web.web_rate_limit import DEFAULT_LIMITER, RateLimiter, client_ip

from .labels import presenter_label
from .messages import recall_viewer_link, sent_message_reference
from .service import ScreenShareError, get_screen_share_service

logger = logging.getLogger(__name__)

router = APIRouter()
PRESENTER_COOKIE_NAME = "oopz_screen_presenter"
_ASSETS = Path(__file__).with_name("assets")
_PRESENTER_STOP_REASONS = {
    "capture_ended",
    "page_closed",
    "presenter_stop",
    "start_failed",
}


def _error(exc: ScreenShareError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": str(exc), "code": exc.code},
        status_code=exc.status_code,
    )


def _unavailable(action: str) -> JSONResponse:
    logger.warning("屏幕共享接口异常: action=%s", action, exc_info=True)
    return JSONResponse(
        {
            "ok": False,
            "error": "屏幕共享服务暂时不可用",
            "code": "screen_share_unavailable",
        },
        status_code=503,
    )


async def _json(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _auth(request: Request) -> str:
    return str(request.cookies.get(PRESENTER_COOKIE_NAME) or "")


def _api_handler(handle, *, heartbeat=False, creates_share=False):
    per_presenter = RateLimiter(max_requests=30, window_seconds=60) if heartbeat else None
    heartbeat_ip = RateLimiter(max_requests=1200, window_seconds=60) if heartbeat else None

    @wraps(handle)
    async def dispatch(request: Request):
        ip = client_ip(request, trusted_proxy_cidrs())
        if per_presenter is not None and heartbeat_ip is not None:
            auth = _auth(request)
            key = f"presenter:{hashlib.sha256(auth.encode('utf-8')).hexdigest()}" if auth else ip
            allowed = heartbeat_ip.is_allowed(ip) and per_presenter.is_allowed(key)
        else:
            allowed = DEFAULT_LIMITER.is_allowed(ip)
        if not allowed:
            return JSONResponse(
                {"ok": False, "error": "请求过于频繁，请稍后再试"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        if creates_share:
            try:
                async with get_screen_share_service().creation():
                    return await handle(request)
            except ScreenShareError as exc:
                return _error(exc)
        return await handle(request)

    return dispatch


def _secure_cookie(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    from web.web_player_config import display_web_base_url
    return display_web_base_url().lower().startswith("https://")


def _page_response() -> FileResponse:
    return FileResponse(
        _ASSETS / "index.html",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Permissions-Policy": "camera=(), microphone=(), display-capture=(self)",
        },
    )


@router.get("/screen-share/p/{presenter_token}")
async def presenter_page(presenter_token: str):
    del presenter_token
    return _page_response()


@router.get("/screen-share/p")
async def presenter_page_without_path_token():
    return _page_response()


@router.get("/screen-share/w/{viewer_token}")
async def viewer_page(viewer_token: str):
    del viewer_token
    return _page_response()


@router.get("/screen-share/w")
async def viewer_page_without_path_token():
    return _page_response()


@router.api_route("/screen-share/assets/{filename}", methods=["GET", "HEAD"], include_in_schema=False)
async def share_asset(filename: str):
    if filename not in {"app.js", "style.css"}:
        raise HTTPException(status_code=404)
    return FileResponse(
        _ASSETS / filename,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


async def presenter_claim(request: Request):
    body = await _json(request)
    try:
        payload, auth_token = await get_screen_share_service().claim(str(body.get("token") or ""))
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("presenter_claim")
    response = JSONResponse({"ok": True, **payload})
    response.set_cookie(
        PRESENTER_COOKIE_NAME,
        auth_token,
        max_age=86400,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="strict",
        path="/screen-share",
    )
    return response


async def presenter_ready(request: Request):
    service = get_screen_share_service()
    try:
        result = await service.mark_ready(_auth(request))
        session = result["session"]
        viewer_url = ""
        if result["first_ready"]:
            from web.web_player import get_sender
            from web.web_player_config import display_web_base_url

            sender = get_sender()
            if sender is None:
                await service.stop(session, reason="sender_unavailable")
                raise ScreenShareError("Bot 消息服务尚未就绪", code="sender_unavailable", status_code=503)
            viewer_url = (
                f"{display_web_base_url().rstrip('/')}/screen-share/w#"
                f"{result['viewer_token']}"
            )
            reference_session: dict | None = None
            try:
                presenter_name = await presenter_label(session)
                sent = await sender.send_message(
                    f"{presenter_name} 的屏幕共享已开始，点击观看：{viewer_url}",
                    channel=str(session["channel"]),
                    area=str(session["area"]),
                    auto_recall=False,
                )
                message_id, timestamp = sent_message_reference(sent)
                if not message_id:
                    raise ScreenShareError(
                        "观看链接发送结果缺少消息标识",
                        code="message_reference_missing",
                        status_code=502,
                    )
                reference_session = {
                    **session,
                    "viewer_message_id": message_id,
                    "viewer_message_timestamp": timestamp,
                }
                recorded = await service.record_viewer_message(
                    str(session["id"]),
                    message_id=message_id,
                    timestamp=timestamp,
                )
                if not recorded:
                    raise ScreenShareError(
                        "屏幕共享已结束",
                        code="session_ended",
                        status_code=410,
                    )
            except Exception as exc:
                if reference_session is not None:
                    await recall_viewer_link(sender, reference_session)
                with suppress(Exception):
                    await service.stop(session, reason="viewer_link_send_failed")
                if isinstance(exc, ScreenShareError):
                    raise exc
                raise ScreenShareError(
                    "观看链接发送失败，共享已停止",
                    code="send_failed",
                    status_code=502,
                ) from exc
        return JSONResponse({"ok": True, "viewer_url": viewer_url})
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("presenter_ready")


async def presenter_heartbeat(request: Request):
    try:
        await get_screen_share_service().heartbeat(_auth(request))
        return JSONResponse({"ok": True})
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("presenter_heartbeat")


async def presenter_renew(request: Request):
    try:
        payload = await get_screen_share_service().renew_presenter(_auth(request))
        return JSONResponse({"ok": True, **payload})
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("presenter_renew")


async def announce_ended(session: dict) -> None:
    if session.get("status") != "active":
        return
    from web.web_player import get_sender
    sender = get_sender()
    if sender is None:
        return
    try:
        await recall_viewer_link(sender, session)
        presenter_name = await presenter_label(session)
        await sender.send_message(
            f"{presenter_name} 的屏幕共享已结束",
            channel=str(session["channel"]),
            area=str(session["area"]),
        )
    except Exception:
        logger.warning("发送屏幕共享结束通知失败", exc_info=True)


async def presenter_stop(request: Request):
    body = await _json(request)
    requested_reason = str(body.get("reason") or "")
    reason = requested_reason if requested_reason in _PRESENTER_STOP_REASONS else "presenter_request"
    try:
        session = await get_screen_share_service().stop_by_auth(_auth(request), reason=reason)
        if session is not None:
            await announce_ended(session)
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("presenter_stop")
    response = JSONResponse({"ok": True})
    response.delete_cookie(PRESENTER_COOKIE_NAME, path="/screen-share")
    return response


async def viewer_token(request: Request):
    body = await _json(request)
    try:
        payload = await get_screen_share_service().viewer_credentials(
            str(body.get("token") or ""),
            viewer_instance=str(body.get("viewer_instance") or ""),
        )
        return JSONResponse({"ok": True, **payload})
    except ScreenShareError as exc:
        return _error(exc)
    except Exception:
        return _unavailable("viewer_token")


router.post("/screen-share/api/presenter/claim")(_api_handler(presenter_claim, creates_share=True))
router.post("/screen-share/api/presenter/ready")(_api_handler(presenter_ready, creates_share=True))
router.post("/screen-share/api/presenter/heartbeat")(_api_handler(presenter_heartbeat, heartbeat=True))
router.post("/screen-share/api/presenter/renew")(_api_handler(presenter_renew))
router.post("/screen-share/api/presenter/stop")(_api_handler(presenter_stop))
router.post("/screen-share/api/viewer/token")(_api_handler(viewer_token))
