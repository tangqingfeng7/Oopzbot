"""
Async QR login manager for Delta Force plugin.
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from logger_config import get_logger

logger = get_logger("DeltaForceLogin")


class DeltaForceLoginManager:
    def __init__(self, config: dict, api_client, store) -> None:
        self._config = config or {}
        self._api = api_client
        self._store = store
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._timeout = max(10, int(self._config.get("login_timeout_sec", 180) or 180))
        self._poll_interval = max(1, int(self._config.get("login_poll_interval_sec", 1) or 1))
        raw_success_notice_delay = self._config.get("login_success_notice_delay_sec", 10)
        try:
            self._success_notice_delay = max(0, int(raw_success_notice_delay))
        except (TypeError, ValueError):
            self._success_notice_delay = 10
        self._delivery_mode = self._normalize_delivery_mode(
            self._config.get("login_delivery_mode")
        )
        self._temp_dir = Path(str(self._config.get("temp_dir") or "data/delta_force"))
        self._qrs_dir = self._temp_dir / "qrs"
        self._qrs_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_qrs()

    def start_login(self, user: str, platform: str, channel: str, area: str, handler) -> str:
        if platform not in {"qq", "wechat"}:
            return "首版仅支持 QQ 或微信扫码登录。"

        with self._lock:
            if user in self._sessions:
                return "已有登录流程进行中，请先完成当前扫码。"

        qr_res = self._api.get_login_qr(platform)
        qr_image = str(qr_res.get("qr_image") or "")
        framework_token = str(qr_res.get("frameworkToken") or qr_res.get("token") or "")
        if not qr_image or not framework_token:
            message = str(qr_res.get("message") or qr_res.get("msg") or "二维码获取失败，请稍后再试。")
            return message

        qr_path = self._write_qr(user, platform, qr_image)
        if not qr_path:
            return "二维码保存失败，请稍后再试。"

        notice = f"请使用{'QQ' if platform == 'qq' else '微信'}扫码登录三角洲账号。二维码有效期约 2 分钟。"
        delivery_message = ""
        delivered = False
        temp_channel_id = ""
        delivery_error = ""
        if self._delivery_mode == "temp_channel":
            try:
                temp_channel = handler.sender.create_restricted_text_channel(
                    user,
                    area=area,
                    preferred_channel=channel,
                    name=f"登录-{user[-4:]}-{time.strftime('%H%M%S')}",
                )
                temp_channel_id = str(temp_channel.get("channel") or "")
                if "error" not in temp_channel and temp_channel_id:
                    mention_text, mention_list = self._build_user_mention(user)
                    handler.sender.upload_and_send_image(
                        qr_path,
                        text=f"{mention_text}\n{notice}",
                        channel=temp_channel_id,
                        area=area,
                        mentionList=mention_list,
                    )
                    delivery_message = "已创建仅你可见的临时频道并发送二维码，请在该频道完成扫码确认。"
                    delivered = True
                else:
                    delivery_error = str(temp_channel.get("error") or "创建临时频道失败")
                    logger.warning("DeltaForceLogin: temp private channel failed: %s", delivery_error)
            except Exception as exc:
                delivery_error = f"异常: {exc}"
                logger.warning("DeltaForceLogin: temp private channel send failed: %s", exc)
                if temp_channel_id:
                    try:
                        handler.sender.delete_channel(temp_channel_id, area=area)
                    except Exception:
                        pass
                    temp_channel_id = ""
        else:
            try:
                dm_result = handler.sender.upload_and_send_private_image(user, qr_path, text=notice)
                delivered = "error" not in dm_result
                if delivered:
                    delivery_message = "已通过私信发送二维码，请查收并完成扫码确认。"
                else:
                    delivery_error = self._format_dm_error(dm_result)
                    logger.warning("DeltaForceLogin: private delivery failed: %s", delivery_error)
            except Exception as exc:
                delivery_error = f"异常: {exc}"
                logger.warning("DeltaForceLogin: private image send failed: %s", exc)

        if not delivered:
            try:
                handler.sender.upload_and_send_image(qr_path, text=notice, channel=channel, area=area)
                mode_label = "临时频道" if self._delivery_mode == "temp_channel" else "私信"
                if delivery_error:
                    delivery_message = f"{mode_label}发送失败（{delivery_error}），已在当前频道发送二维码。"
                else:
                    delivery_message = f"{mode_label}发送失败，已在当前频道发送二维码。"
            except Exception:
                handler.sender.send_message(notice, channel=channel, area=area)
                mode_label = "临时频道" if self._delivery_mode == "temp_channel" else "私信"
                if delivery_error:
                    delivery_message = f"{mode_label}和图片发送都失败了（原因：{delivery_error}），已改为文字提示。"
                else:
                    delivery_message = f"{mode_label}和图片发送都失败了，已改为文字提示。"

        stop_event = threading.Event()
        session = {
            "event": stop_event,
            "path": qr_path,
            "sender": handler.sender,
            "area": area,
            "temp_channel": temp_channel_id,
            "delivery_mode": self._delivery_mode,
        }
        thread = threading.Thread(
            target=self._poll_login,
            args=(
                user,
                platform,
                framework_token,
                channel,
                area,
                handler,
                stop_event,
                qr_path,
                temp_channel_id,
                self._delivery_mode,
            ),
            daemon=True,
        )
        session["thread"] = thread
        with self._lock:
            self._sessions[user] = session
        thread.start()
        return delivery_message

    def cancel_all(self) -> None:
        with self._lock:
            sessions = dict(self._sessions)
            self._sessions.clear()
        for item in sessions.values():
            event = item.get("event")
            if isinstance(event, threading.Event):
                event.set()
            temp_channel = str(item.get("temp_channel") or "")
            sender = item.get("sender")
            area = str(item.get("area") or "")
            if temp_channel and sender is not None:
                try:
                    sender.delete_channel(temp_channel, area=area)
                except Exception:
                    pass
            self._cleanup_path(item.get("path"))

    def _write_qr(self, user: str, platform: str, qr_image: str) -> Optional[str]:
        path = self._qrs_dir / f"{user}_{platform}_{int(time.time())}.png"
        try:
            if qr_image.startswith("data:image"):
                encoded = qr_image.split(",", 1)[-1]
                path.write_bytes(base64.b64decode(encoded))
            elif qr_image.startswith("http://") or qr_image.startswith("https://"):
                resp = requests.get(qr_image, timeout=15)
                resp.raise_for_status()
                path.write_bytes(resp.content)
            elif qr_image.startswith("base64://"):
                path.write_bytes(base64.b64decode(qr_image[len("base64://"):]))
            else:
                return None
        except Exception as exc:
            logger.warning("DeltaForceLogin: write qr failed: %s", exc)
            return None
        return str(path)

    def _send_login_message(
        self,
        handler,
        user: str,
        channel: str,
        area: str,
        text: str,
        *,
        temp_channel: str = "",
        delivery_mode: str = "private_message",
        allow_public_fallback: bool = True,
    ) -> None:
        """按配置的投递方式发送登录相关消息，失败时回退到当前频道。"""
        if delivery_mode == "temp_channel" and temp_channel:
            mention_text, mention_list = self._build_user_mention(user)
            try:
                handler.sender.send_message(
                    f"{mention_text}\n{text}",
                    channel=temp_channel,
                    area=area,
                    mentionList=mention_list,
                )
                return
            except Exception as e:
                logger.warning("DeltaForceLogin: temp channel send failed: %s", e)
        elif delivery_mode != "temp_channel":
            result = handler.sender.send_private_message(user, text)
            if "error" not in result:
                return
        if not allow_public_fallback:
            return
        try:
            handler.sender.send_message(text, channel=channel, area=area)
        except Exception as e:
            logger.warning("DeltaForceLogin: DM and fallback send failed: %s", e)

    def _poll_login(
        self,
        user: str,
        platform: str,
        framework_token: str,
        channel: str,
        area: str,
        handler,
        stop_event: threading.Event,
        qr_path: str,
        temp_channel: str,
        delivery_mode: str,
    ) -> None:
        deadline = time.time() + self._timeout
        try:
            while not stop_event.is_set() and time.time() < deadline:
                status = self._api.get_login_status(platform, framework_token)
                code = status.get("code")
                if code == 0:
                    final_token = str(status.get("frameworkToken") or status.get("token") or "")
                    if not final_token:
                        self._send_login_message(
                            handler,
                            user,
                            channel,
                            area,
                            "登录成功，但未获取到最终 token。",
                            temp_channel=temp_channel,
                            delivery_mode=delivery_mode,
                        )
                        self._cleanup_temp_channel_after_notice(
                            handler,
                            temp_channel=temp_channel,
                            area=area,
                            stop_event=stop_event,
                        )
                        return
                    bind_res = self._api.bind_user(final_token, user)
                    if bind_res.get("success") is False and not bind_res.get("data") and bind_res.get("code") not in {0, "0"}:
                        self._send_login_message(
                            handler,
                            user,
                            channel,
                            area,
                            str(bind_res.get("message") or bind_res.get("msg") or "账号绑定失败"),
                            temp_channel=temp_channel,
                            delivery_mode=delivery_mode,
                        )
                        self._cleanup_temp_channel_after_notice(
                            handler,
                            temp_channel=temp_channel,
                            area=area,
                            stop_event=stop_event,
                        )
                        return
                    self._store.set_active_token(user, final_token)
                    list_res = self._api.get_user_list(user)
                    accounts = list_res.get("data") if isinstance(list_res.get("data"), list) else []
                    if accounts:
                        self._store.choose_active_token(user, accounts)
                    self._send_login_message(
                        handler,
                        user,
                        channel,
                        area,
                        "登录成功，已绑定账号。请继续执行“@bot 三角洲角色绑定”。",
                        temp_channel=temp_channel,
                        delivery_mode=delivery_mode,
                    )
                    self._cleanup_temp_channel_after_notice(
                        handler,
                        temp_channel=temp_channel,
                        area=area,
                        stop_event=stop_event,
                    )
                    return
                if code in {-2, "-2"}:
                    self._send_login_message(
                        handler,
                        user,
                        channel,
                        area,
                        "二维码已过期，请重新执行三角洲登录。",
                        temp_channel=temp_channel,
                        delivery_mode=delivery_mode,
                    )
                    self._cleanup_temp_channel_after_notice(
                        handler,
                        temp_channel=temp_channel,
                        area=area,
                        stop_event=stop_event,
                    )
                    return
                if code in {-3, "-3"}:
                    self._send_login_message(
                        handler,
                        user,
                        channel,
                        area,
                        "本次扫码被风控拦截，请稍后重试。",
                        temp_channel=temp_channel,
                        delivery_mode=delivery_mode,
                    )
                    self._cleanup_temp_channel_after_notice(
                        handler,
                        temp_channel=temp_channel,
                        area=area,
                        stop_event=stop_event,
                    )
                    return
                time.sleep(self._poll_interval)

            if not stop_event.is_set():
                self._send_login_message(
                    handler,
                    user,
                    channel,
                    area,
                    "登录超时，请重新执行三角洲登录。",
                    temp_channel=temp_channel,
                    delivery_mode=delivery_mode,
                )
                self._cleanup_temp_channel_after_notice(
                    handler,
                    temp_channel=temp_channel,
                    area=area,
                    stop_event=stop_event,
                )
        except Exception as exc:
            logger.exception("DeltaForceLogin: polling failed for %s", user)
            self._send_login_message(
                handler,
                user,
                channel,
                area,
                f"登录流程异常: {exc}",
                temp_channel=temp_channel,
                delivery_mode=delivery_mode,
            )
            self._cleanup_temp_channel_after_notice(
                handler,
                temp_channel=temp_channel,
                area=area,
                stop_event=stop_event,
            )
        finally:
            with self._lock:
                self._sessions.pop(user, None)
            self._cleanup_path(qr_path)

    @staticmethod
    def _normalize_delivery_mode(value: object) -> str:
        text = str(value or "").strip().lower()
        if text in {"temp_channel", "temp", "channel", "private_channel"}:
            return "temp_channel"
        return "private_message"

    @staticmethod
    def _build_user_mention(user: str) -> tuple[str, list[dict]]:
        user = str(user or "").strip()
        if not user:
            return "", []
        return (
            f" (met){user}(met)",
            [{
                "person": user,
                "isBot": False,
                "botType": "",
                "offset": -1,
            }],
        )

    def _cleanup_temp_channel_after_notice(
        self,
        handler,
        *,
        temp_channel: str,
        area: str,
        stop_event: threading.Event,
    ) -> None:
        if not temp_channel:
            return
        if self._success_notice_delay > 0:
            stop_event.wait(self._success_notice_delay)
        try:
            handler.sender.delete_channel(temp_channel, area=area)
        except Exception as exc:
            logger.warning("DeltaForceLogin: delete temp channel failed: %s", exc)

    @staticmethod
    def _cleanup_path(path: Optional[str]) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            return

    def _cleanup_stale_qrs(self) -> None:
        """
        在插件加载时清理过期二维码文件，避免遗留临时文件越积越多。
        """
        ttl_seconds = max(self._timeout * 2, 600)
        now = time.time()
        removed = 0

        try:
            files = list(self._qrs_dir.glob("*.png"))
        except Exception as exc:
            logger.warning("DeltaForceLogin: list qrs dir failed: %s", exc)
            return

        for path in files:
            try:
                age = now - path.stat().st_mtime
                if age < ttl_seconds:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except Exception as exc:
                logger.debug("DeltaForceLogin: skip stale qr cleanup for %s: %s", path, exc)

        if removed:
            logger.info("DeltaForceLogin: 已清理 %s 个过期二维码文件", removed)

    @staticmethod
    def _format_dm_error(result: object) -> str:
        if not isinstance(result, dict):
            return "未知错误"
        reason = str(result.get("debug_reason") or "").strip()
        if reason == "open_session_missing_channel":
            return "已打开私信会话，但未解析到会话 channel"
        if reason == "send_dm_http_error":
            return f"私信接口返回错误：{str(result.get('error') or '')[:80]}"
        if reason == "send_dm_unconfirmed":
            return f"私信接口返回了 HTTP 200，但未确认投递成功：{str(result.get('error') or '')[:80]}"
        if reason == "missing_channel":
            return "私信 channel 不可用"
        error = str(result.get("error") or "").strip()
        if error:
            return error[:80]
        return "未知错误"
