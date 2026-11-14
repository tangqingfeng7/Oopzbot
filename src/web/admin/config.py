import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.redis_keys import WEB_COMMANDS as KEY_WEB_COMMANDS
from core.redis_keys import encode_web_command
from domain.playback import GlobalWebCommand
from web.admin.shared import (
    _BILIBILI_QR_GENERATE_PATH,
    _BILIBILI_QR_POLL_PATH,
    RequestsException,
    _bilibili_account_status,
    _bilibili_api_get,
    _bilibili_cookie_from_poll,
    _bilibili_login_message,
    _bilibili_qr_code,
    _bilibili_response_data,
    _cookie_debug_summary,
    _cookie_from_response,
    _debug_profile_text,
    _make_qr_data_uri,
    _mask_debug_token,
    _music_area_context,
    _netease_account_status,
    _netease_api_get,
    _netease_login_message,
    _netease_qr_code,
    _netease_response_data,
    _netease_timestamp_params,
    _normalize_netease_base_url,
    _oopz_login_lock,
    _refresh_oopz_runtime,
    _set_liked_ids_cache,
    cfg,
    logger,
    read_json_body,
)

router = APIRouter()

@router.get("/admin/api/config")
async def admin_get_config():
    return JSONResponse({
        "ok": True,
        "config": cfg.config_snapshot(),
        "schema": cfg.config_field_schema(),
        "runtime": {
            "music_area": await _music_area_context(),
        },
        "config_source": "config.py",
    })


@router.post("/admin/api/config")
async def admin_update_config(request: Request):
    body = await read_json_body(request)
    updates = body.get("updates", {})
    persist = bool(body.get("persist", True))
    applied, errors, persist_payload = cfg.apply_config_updates(updates)
    persisted = False
    music_runtime = {}

    import web.web_player as web_player
    if "redis" in applied:
        await web_player.reset_redis(force=True)
    if "netease" in applied:
        web_player.reset_netease()
        _set_liked_ids_cache([])
    if {"netease", "qq_music", "bilibili_music"} & set(applied):
        try:
            music_runtime = web_player.refresh_music_platforms()
        except Exception as exc:
            logger.exception("刷新音乐平台运行时失败")
            errors.append(f"音乐平台刷新失败: {exc}")
    if "music" in applied and "default_volume" in applied["music"]:
        try:
            volume = cfg.default_music_volume()
            r = await web_player.get_redis()
            await r.set(web_player.KEY_VOLUME, str(volume))
            # 后台改的是全局默认音量，不归属任何域：留空域即对所有域生效
            await r.rpush(
                KEY_WEB_COMMANDS,
                encode_web_command(GlobalWebCommand("volume", {"value": volume})),
            )
        except Exception as e:
            logger.debug("Apply default music volume failed: %s", e)
    cfg.refresh_runtime_dependents(set(applied))

    if persist and persist_payload:
        try:
            await asyncio.to_thread(cfg.persist_config_updates, persist_payload)
            persisted = True
        except Exception as exc:
            logger.exception("保存配置到 config.py 失败")
            errors.append(f"保存 config.py 失败: {exc}")

    return JSONResponse({
        "ok": len(errors) == 0,
        "applied": applied,
        "errors": errors,
        "persisted": persisted,
        "config_source": "config.py",
        "message": "配置已保存到 config.py 并立即生效" if persisted else "配置已应用到当前进程",
        "config": cfg.config_snapshot(),
        "schema": cfg.config_field_schema(),
        "runtime": {
            "music_area": await _music_area_context(),
            "music_platforms": music_runtime,
        },
    })


@router.post("/admin/api/netease/login/qr")
async def admin_netease_login_qr(request: Request):
    """创建网易云扫码登录二维码。"""
    body = await read_json_body(request)

    try:
        base_url = _normalize_netease_base_url(body.get("base_url"))
        logger.debug("网易云扫码登录二维码刷新请求开始: base_url=%s", base_url)
        key_payload, _ = await asyncio.to_thread(
            _netease_api_get,
            base_url,
            "/login/qr/key",
            params=_netease_timestamp_params(),
        )
        key_data = _netease_response_data(key_payload)
        unikey = str(key_data.get("unikey") or key_payload.get("unikey") or "").strip()
        if not unikey:
            message = _netease_login_message(key_payload, "二维码 key 获取失败")
            logger.debug(
                "网易云扫码登录二维码 key 获取失败: code=%s message=%s",
                key_payload.get("code"),
                message,
            )
            return JSONResponse({"ok": False, "error": message}, status_code=502)

        qr_payload, _ = await asyncio.to_thread(
            _netease_api_get,
            base_url,
            "/login/qr/create",
            params=_netease_timestamp_params({
                "key": unikey,
                "qrimg": "true",
            }),
        )
        qr_data = _netease_response_data(qr_payload)
        qrimg = str(qr_data.get("qrimg") or qr_payload.get("qrimg") or "").strip()
        qrurl = str(qr_data.get("qrurl") or qr_payload.get("qrurl") or "").strip()
        if qrimg and not qrimg.startswith("data:"):
            qrimg = f"data:image/png;base64,{qrimg}"
        if not qrimg and not qrurl:
            message = _netease_login_message(qr_payload, "二维码生成失败")
            logger.debug(
                "网易云扫码登录二维码响应缺少字段: key=%s qrimg_present=%s qrurl_present=%s message=%s",
                _mask_debug_token(unikey),
                bool(qrimg),
                bool(qrurl),
                message,
            )
            return JSONResponse({"ok": False, "error": message}, status_code=502)

        logger.debug(
            "网易云扫码登录二维码刷新成功: key=%s qrimg_len=%s qrurl_len=%s",
            _mask_debug_token(unikey),
            len(qrimg),
            len(qrurl),
        )
        return JSONResponse({
            "ok": True,
            "base_url": base_url,
            "key": unikey,
            "qrimg": qrimg,
            "qrurl": qrurl,
            "message": "二维码已刷新",
        })
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except RequestsException as exc:
        logger.warning("网易云扫码登录二维码请求失败: %s", exc)
        return JSONResponse({"ok": False, "error": f"网易云 API 请求失败: {exc}"}, status_code=502)
    except Exception as exc:
        logger.exception("创建网易云扫码登录二维码失败")
        return JSONResponse({"ok": False, "error": f"创建二维码失败: {exc}"}, status_code=500)


@router.post("/admin/api/netease/login/qr/check")
async def admin_netease_login_qr_check(request: Request):
    """检查网易云扫码登录状态，成功时返回 Cookie。"""
    body = await read_json_body(request)

    key = str(body.get("key") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "二维码 key 不能为空"}, status_code=400)

    try:
        base_url = _normalize_netease_base_url(body.get("base_url"))
        logger.debug("网易云扫码登录轮询开始: key=%s base_url=%s", _mask_debug_token(key), base_url)
        payload, response = await asyncio.to_thread(
            _netease_api_get,
            base_url,
            "/login/qr/check",
            params=_netease_timestamp_params({"key": key}),
        )
        code = _netease_qr_code(payload)
        message = _netease_login_message(payload)
        status_map = {
            800: "expired",
            801: "waiting",
            802: "scanned",
            803: "success",
        }
        status = status_map.get(code, "unknown")
        logger.debug(
            "网易云扫码登录轮询结果: key=%s code=%s status=%s message=%s",
            _mask_debug_token(key),
            code,
            status,
            message,
        )
        result = {
            "ok": True,
            "base_url": base_url,
            "code": code,
            "status": status,
            "message": message,
        }
        if code == 803:
            cookie = _cookie_from_response(payload, response)
            if not cookie:
                return JSONResponse(
                    {"ok": False, "error": "扫码成功但网易云 API 未返回 Cookie"},
                    status_code=502,
                )
            result["cookie"] = cookie
            try:
                account_status = await asyncio.to_thread(_netease_account_status, base_url, cookie)
                if account_status.get("logged_in"):
                    result["profile"] = account_status.get("profile")
                    logger.debug(
                        "网易云扫码登录成功并识别账号: key=%s %s",
                        _mask_debug_token(key),
                        _debug_profile_text(account_status.get("profile")),
                    )
                else:
                    result["profile_message"] = account_status.get("message", "")
                    logger.debug(
                        "网易云扫码登录成功但账号未识别: key=%s message=%s",
                        _mask_debug_token(key),
                        result["profile_message"],
                    )
            except Exception as exc:
                logger.debug("网易云扫码成功后查询账号信息失败: %s", exc)
                result["profile_message"] = f"账号信息查询失败: {exc}"
            result["message"] = message or "登录成功"
        return JSONResponse(result)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except RequestsException as exc:
        logger.warning("网易云扫码登录状态检查失败: %s", exc)
        return JSONResponse({"ok": False, "error": f"网易云 API 请求失败: {exc}"}, status_code=502)
    except Exception as exc:
        logger.exception("检查网易云扫码登录状态失败")
        return JSONResponse({"ok": False, "error": f"检查登录状态失败: {exc}"}, status_code=500)


@router.get("/admin/api/netease/account")
def admin_netease_account():
    """返回当前配置 Cookie 对应的网易云账号信息。"""
    try:
        base_url = _normalize_netease_base_url(cfg.NETEASE_CLOUD.get("base_url"))
        cookie = str(cfg.NETEASE_CLOUD.get("cookie") or "")
        logger.debug("网易云账号状态接口请求: base_url=%s %s", base_url, _cookie_debug_summary(cookie))
        status = _netease_account_status(base_url, cookie)
        if status.get("logged_in"):
            logger.debug("网易云账号状态接口响应: logged_in=True %s", _debug_profile_text(status.get("profile")))
        else:
            logger.debug("网易云账号状态接口响应: logged_in=False message=%s", status.get("message", ""))
        return JSONResponse(status)
    except ValueError as exc:
        return JSONResponse({"ok": True, "logged_in": False, "message": str(exc)})
    except RequestsException as exc:
        logger.warning("网易云账号状态查询失败: %s", exc)
        return JSONResponse({"ok": True, "logged_in": False, "message": f"网易云 API 请求失败: {exc}"})
    except Exception as exc:
        logger.warning("网易云账号状态查询异常: %s", exc, exc_info=True)
        return JSONResponse({"ok": True, "logged_in": False, "message": f"账号状态查询失败: {exc}"})


@router.post("/admin/api/bilibili/login/qr")
async def admin_bilibili_login_qr():
    """创建 B 站扫码登录二维码。"""
    try:
        logger.debug("B 站扫码登录二维码刷新请求开始")
        payload, _ = await asyncio.to_thread(_bilibili_api_get, _BILIBILI_QR_GENERATE_PATH)
        if int(payload.get("code", -1)) != 0:
            message = _bilibili_login_message(payload, "二维码生成失败")
            logger.debug("B 站扫码登录二维码刷新失败: code=%s message=%s", payload.get("code"), message)
            return JSONResponse({"ok": False, "error": message}, status_code=502)

        data = _bilibili_response_data(payload)
        key = str(data.get("qrcode_key") or "").strip()
        qrurl = str(data.get("url") or "").strip()
        if not key or not qrurl:
            message = _bilibili_login_message(payload, "二维码生成失败")
            logger.debug(
                "B 站扫码登录二维码响应缺少字段: key_present=%s qrurl_present=%s message=%s",
                bool(key),
                bool(qrurl),
                message,
            )
            return JSONResponse({"ok": False, "error": message}, status_code=502)

        logger.debug(
            "B 站扫码登录二维码刷新成功: key=%s qrurl_len=%s",
            _mask_debug_token(key),
            len(qrurl),
        )
        return JSONResponse({
            "ok": True,
            "key": key,
            "qrimg": await asyncio.to_thread(_make_qr_data_uri, qrurl),
            "qrurl": qrurl,
            "message": "二维码已刷新",
        })
    except RequestsException as exc:
        logger.warning("B 站扫码登录二维码请求失败: %s", exc)
        return JSONResponse({"ok": False, "error": f"B 站 API 请求失败: {exc}"}, status_code=502)
    except Exception as exc:
        logger.exception("创建 B 站扫码登录二维码失败")
        return JSONResponse({"ok": False, "error": f"创建二维码失败: {exc}"}, status_code=500)


@router.post("/admin/api/bilibili/login/qr/check")
async def admin_bilibili_login_qr_check(request: Request):
    """检查 B 站扫码登录状态，成功时返回 Cookie。"""
    body = await read_json_body(request)

    key = str(body.get("key") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "二维码 key 不能为空"}, status_code=400)

    try:
        logger.debug("B 站扫码登录轮询开始: key=%s", _mask_debug_token(key))
        payload, response = await asyncio.to_thread(
            _bilibili_api_get,
            _BILIBILI_QR_POLL_PATH,
            params={"qrcode_key": key},
        )
        if int(payload.get("code", -1)) != 0:
            message = _bilibili_login_message(payload, "登录状态检查失败")
            logger.debug(
                "B 站扫码登录轮询接口失败: key=%s code=%s message=%s",
                _mask_debug_token(key),
                payload.get("code"),
                message,
            )
            return JSONResponse({"ok": False, "error": message}, status_code=502)

        code = _bilibili_qr_code(payload)
        message = _bilibili_login_message(payload)
        status_map = {
            0: "success",
            86038: "expired",
            86090: "scanned",
            86101: "waiting",
        }
        status = status_map.get(code, "unknown")
        logger.debug(
            "B 站扫码登录轮询结果: key=%s code=%s status=%s message=%s",
            _mask_debug_token(key),
            code,
            status,
            message,
        )
        result = {
            "ok": True,
            "code": code,
            "status": status,
            "message": message,
        }
        if code == 0:
            cookie = _bilibili_cookie_from_poll(payload, response)
            if not cookie:
                return JSONResponse(
                    {"ok": False, "error": "扫码成功但 B 站未返回 Cookie"},
                    status_code=502,
                )
            result["cookie"] = cookie
            try:
                account_status = await asyncio.to_thread(_bilibili_account_status, cookie)
                if account_status.get("logged_in"):
                    result["profile"] = account_status.get("profile")
                    logger.debug(
                        "B 站扫码登录成功并识别账号: key=%s %s",
                        _mask_debug_token(key),
                        _debug_profile_text(account_status.get("profile")),
                    )
                else:
                    result["profile_message"] = account_status.get("message", "")
                    logger.debug(
                        "B 站扫码登录成功但账号未识别: key=%s message=%s",
                        _mask_debug_token(key),
                        result["profile_message"],
                    )
            except Exception as exc:
                logger.debug("B 站扫码成功后查询账号信息失败: %s", exc)
                result["profile_message"] = f"账号信息查询失败: {exc}"
            result["message"] = message or "登录成功"
        return JSONResponse(result)
    except RequestsException as exc:
        logger.warning("B 站扫码登录状态检查失败: %s", exc)
        return JSONResponse({"ok": False, "error": f"B 站 API 请求失败: {exc}"}, status_code=502)
    except Exception as exc:
        logger.exception("检查 B 站扫码登录状态失败")
        return JSONResponse({"ok": False, "error": f"检查登录状态失败: {exc}"}, status_code=500)


@router.get("/admin/api/bilibili/account")
def admin_bilibili_account():
    """返回当前配置 Cookie 对应的 B 站账号信息。"""
    try:
        cookie = str(cfg.BILIBILI_MUSIC_CONFIG.get("cookie") or "")
        logger.debug("B 站账号状态接口请求: %s", _cookie_debug_summary(cookie))
        result = _bilibili_account_status(cookie)
        if result.get("logged_in"):
            logger.debug("B 站账号状态接口响应: logged_in=True %s", _debug_profile_text(result.get("profile")))
        else:
            logger.debug("B 站账号状态接口响应: logged_in=False message=%s", result.get("message", ""))
        return JSONResponse(result)
    except RequestsException as exc:
        logger.warning("B 站账号状态查询失败: %s", exc)
        return JSONResponse({"ok": True, "logged_in": False, "message": f"B 站 API 请求失败: {exc}"})
    except Exception as exc:
        logger.warning("B 站账号状态查询异常: %s", exc, exc_info=True)
        return JSONResponse({"ok": True, "logged_in": False, "message": f"账号状态查询失败: {exc}"})


@router.post("/admin/api/config/reset")
async def admin_reset_config_overrides():
    try:
        cfg.reload_config_from_file()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"重新加载 config.py 失败: {exc}"}, status_code=500)

    import web.web_player as web_player
    await web_player.reset_redis(force=True)
    web_player.reset_netease()
    _set_liked_ids_cache([])
    try:
        music_runtime = web_player.refresh_music_platforms()
    except Exception as exc:
        logger.debug("重置配置后刷新音乐平台失败: %s", exc)
        music_runtime = {"available": False, "error": str(exc)}
    cfg.refresh_runtime_dependents({"redis", "web_player"})
    return JSONResponse({
        "ok": True,
        "config_source": "config.py",
        "message": "已从 config.py 重新加载并立即生效",
        "music_platforms": music_runtime,
    })


def _parse_oopz_login_payload(body: dict[str, Any]) -> tuple[str, str, float]:
    if not isinstance(body, dict):
        body = {}
    phone = str(body.get("phone", "") or "").strip()
    password = str(body.get("password", "") or "")
    oopz_config = getattr(cfg, "OOPZ_CONFIG", {}) or {}
    if not phone:
        phone = str(oopz_config.get("login_phone") or "").strip()
    if not password:
        password = str(oopz_config.get("login_password") or "")
    try:
        timeout = float(body.get("timeout", 90) or 90)
    except (TypeError, ValueError):
        timeout = 90.0
    return phone, password, max(30.0, min(timeout, 180.0))


def _mask_oopz_credential(value: object, *, keep: int = 4) -> str:
    text = str(value or "")
    if len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}***{text[-keep:]}"


@router.post("/admin/api/oopz/login")
async def admin_oopz_login(request: Request):
    if _oopz_login_lock.locked():
        return JSONResponse({"ok": False, "error": "OOPZ 登录任务正在执行"}, status_code=409)

    phone, password, timeout = _parse_oopz_login_payload(await read_json_body(request))

    from oopz_sdk.auth import login_with_password
    from oopz_sdk.exceptions import OopzPasswordLoginError

    from oopz.credentials import persist_credentials

    async with _oopz_login_lock:
        try:
            credentials = await login_with_password(phone, password, timeout=timeout)
            saved = await persist_credentials(credentials)
            runtime = await _refresh_oopz_runtime(credentials)
            return JSONResponse({
                "ok": True,
                "saved": saved,
                "credentials": {
                    "person_uid": _mask_oopz_credential(credentials.person_uid),
                    "device_id": _mask_oopz_credential(credentials.device_id),
                    "jwt_token": _mask_oopz_credential(credentials.jwt_token, keep=10),
                    "private_key": bool(credentials.private_key_pem),
                    "app_version": credentials.app_version,
                    "expires_at": credentials.expires_at,
                    "expires_in_seconds": credentials.expires_in_seconds,
                },
                "restart_required": False,
                "runtime": runtime,
                "message": "OOPZ 登录成功，已保存到: " + ("、".join(saved) if saved else "运行时"),
            })
        except OopzPasswordLoginError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            logger.exception("后台 OOPZ 账号密码登录失败")
            return JSONResponse({"ok": False, "error": f"OOPZ 登录失败: {exc}"}, status_code=500)

__all__ = ["router"]
