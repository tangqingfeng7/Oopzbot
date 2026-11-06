from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from pathlib import Path

from core.logger_config import get_logger
from oopz.remote_fetch import RemoteFetchError, SafeRemoteFetcher

logger = get_logger("DeltaForceLogin")


class DeltaForceLoginManager:
    """管理扫码登录及其可取消的异步轮询任务。"""

    def __init__(self, config: dict, api_client, store) -> None:
        self._config = config or {}
        self._api = api_client
        self._store = store
        self._lock = asyncio.Lock()
        self._sessions: dict[str, dict] = {}
        self._timeout = max(10, int(self._config.get("login_timeout_sec", 180) or 180))
        self._poll_interval = max(1, int(self._config.get("login_poll_interval_sec", 1) or 1))
        try:
            self._success_notice_delay = max(
                0,
                int(self._config.get("login_success_notice_delay_sec", 10)),
            )
        except (TypeError, ValueError):
            self._success_notice_delay = 10
        self._delivery_mode = self._normalize_delivery_mode(self._config.get("login_delivery_mode"))
        self._temp_dir = Path(str(self._config.get("temp_dir") or "data/delta_force"))
        self._qrs_dir = self._temp_dir / "qrs"
        self._fetcher = SafeRemoteFetcher(proxy_value=self._config.get("proxy"))

    async def setup(self) -> None:
        await asyncio.to_thread(self._qrs_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(self._cleanup_stale_qrs)

    async def start_login(self, user: str, platform: str, channel: str, area: str, handler) -> str:
        if platform not in {"qq", "wechat"}:
            return "首版仅支持 QQ 或微信扫码登录。"

        async with self._lock:
            if user in self._sessions:
                return "已有登录流程进行中，请先完成当前扫码。"
            self._sessions[user] = {"pending": True}

        qr_path: str | None = None
        temp_channel_id = ""
        started = False
        try:
            qr_res = await self._api.get_login_qr(platform)
            qr_image = str(qr_res.get("qr_image") or "")
            framework_token = str(qr_res.get("frameworkToken") or qr_res.get("token") or "")
            if not qr_image or not framework_token:
                return str(qr_res.get("message") or qr_res.get("msg") or "二维码获取失败，请稍后再试。")

            qr_path = await self._write_qr(user, platform, qr_image)
            if not qr_path:
                return "二维码保存失败，请稍后再试。"

            notice = f"请使用{'QQ' if platform == 'qq' else '微信'}扫码登录三角洲账号。二维码有效期约 2 分钟。"
            delivery_message = ""
            delivered = False
            delivery_error = ""
            if self._delivery_mode == "temp_channel":
                try:
                    temp_channel = await handler.sender.create_restricted_text_channel(
                        user,
                        area=area,
                        preferred_channel=channel,
                        name=f"登录-{user[-4:]}-{time.strftime('%H%M%S')}",
                    )
                    temp_channel_id = str(temp_channel.get("channel") or "")
                    if "error" not in temp_channel and temp_channel_id:
                        mention_text, mention_list = self._build_user_mention(user)
                        await handler.sender.upload_and_send_image(
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
                        with contextlib.suppress(Exception):
                            deleted = await handler.sender.bot.channels.delete_channel(area, temp_channel_id)
                            if not deleted.ok:
                                raise RuntimeError(deleted.message or "删除临时频道被拒绝") from None
                        temp_channel_id = ""
            else:
                try:
                    await handler.sender.upload_and_send_private_image(user, qr_path, text=notice)
                    delivered = True
                    delivery_message = "已通过私信发送二维码，请查收并完成扫码确认。"
                except Exception as exc:
                    delivery_error = f"异常: {exc}"
                    logger.warning("DeltaForceLogin: private image send failed: %s", exc)

            if not delivered:
                mode_label = "临时频道" if self._delivery_mode == "temp_channel" else "私信"
                try:
                    await handler.sender.upload_and_send_image(qr_path, text=notice, channel=channel, area=area)
                    suffix = f"（{delivery_error}）" if delivery_error else ""
                    delivery_message = f"{mode_label}发送失败{suffix}，已在当前频道发送二维码。"
                except Exception:
                    await handler.sender.send_message(notice, channel=channel, area=area)
                    suffix = f"（原因：{delivery_error}）" if delivery_error else ""
                    delivery_message = f"{mode_label}和图片发送都失败了{suffix}，已改为文字提示。"

            stop_event = asyncio.Event()
            task = asyncio.create_task(
                self._poll_login(
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
                name=f"DeltaForceLogin:{user}",
            )
            async with self._lock:
                self._sessions[user] = {
                    "event": stop_event,
                    "task": task,
                    "path": qr_path,
                    "sender": handler.sender,
                    "area": area,
                    "temp_channel": temp_channel_id,
                }
            started = True
            return delivery_message
        finally:
            if not started:
                async with self._lock:
                    self._sessions.pop(user, None)
                if temp_channel_id:
                    with contextlib.suppress(Exception):
                        deleted = await handler.sender.bot.channels.delete_channel(area, temp_channel_id)
                        if not deleted.ok:
                            raise RuntimeError(deleted.message or "删除临时频道被拒绝") from None
                await self._cleanup_path(qr_path)

    async def cancel_all(self) -> None:
        async with self._lock:
            sessions = dict(self._sessions)
            self._sessions.clear()
        tasks: list[asyncio.Task] = []
        for item in sessions.values():
            event = item.get("event")
            if isinstance(event, asyncio.Event):
                event.set()
            task = item.get("task")
            if isinstance(task, asyncio.Task):
                task.cancel()
                tasks.append(task)
            temp_channel = str(item.get("temp_channel") or "")
            sender = item.get("sender")
            area = str(item.get("area") or "")
            if temp_channel and sender is not None:
                with contextlib.suppress(Exception):
                    deleted = await sender.bot.channels.delete_channel(area, temp_channel)
                    if not deleted.ok:
                        raise RuntimeError(deleted.message or "删除临时频道被拒绝") from None
            await self._cleanup_path(item.get("path"))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _write_qr(self, user: str, platform: str, qr_image: str) -> str | None:
        path = self._qrs_dir / f"{user}_{platform}_{int(time.time())}.png"
        try:
            if qr_image.startswith("data:image"):
                payload = base64.b64decode(qr_image.split(",", 1)[-1], validate=True)
            elif qr_image.startswith("http://") or qr_image.startswith("https://"):
                payload, _content_type = await asyncio.to_thread(
                    self._fetcher.fetch,
                    qr_image,
                    max_bytes=5 * 1024 * 1024,
                    timeout=(15, 15),
                )
            elif qr_image.startswith("base64://"):
                payload = base64.b64decode(qr_image[len("base64://"):], validate=True)
            else:
                return None
            await asyncio.to_thread(path.write_bytes, payload)
        except (RemoteFetchError, ValueError, OSError) as exc:
            logger.warning("DeltaForceLogin: write qr failed: %s", exc)
            return None
        return str(path)

    async def _send_login_message(
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
        if delivery_mode == "temp_channel" and temp_channel:
            mention_text, mention_list = self._build_user_mention(user)
            try:
                await handler.sender.send_message(
                    f"{mention_text}\n{text}",
                    channel=temp_channel,
                    area=area,
                    mentionList=mention_list,
                )
                return
            except Exception as exc:
                logger.warning("DeltaForceLogin: temp channel send failed: %s", exc)
        elif delivery_mode != "temp_channel":
            try:
                await handler.sender.bot.messages.send_private_message(text, target=user)
                return
            except Exception as exc:
                logger.warning("DeltaForceLogin: private message send failed: %s", exc)
        if allow_public_fallback:
            try:
                await handler.sender.send_message(text, channel=channel, area=area)
            except Exception as exc:
                logger.warning("DeltaForceLogin: DM and fallback send failed: %s", exc)

    async def _poll_login(
        self,
        user: str,
        platform: str,
        framework_token: str,
        channel: str,
        area: str,
        handler,
        stop_event: asyncio.Event,
        qr_path: str,
        temp_channel: str,
        delivery_mode: str,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + self._timeout
        try:
            while not stop_event.is_set() and asyncio.get_running_loop().time() < deadline:
                status = await self._api.get_login_status(platform, framework_token)
                code = status.get("code")
                if code == 0:
                    final_token = str(status.get("frameworkToken") or status.get("token") or "")
                    if not final_token:
                        await self._send_login_message(
                            handler, user, channel, area, "登录成功，但未获取到最终 token。",
                            temp_channel=temp_channel, delivery_mode=delivery_mode,
                        )
                        await self._cleanup_temp_channel_after_notice(
                            handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                        )
                        return
                    bind_res = await self._api.bind_user(final_token, user)
                    if (
                        bind_res.get("success") is False
                        and not bind_res.get("data")
                        and bind_res.get("code") not in {0, "0"}
                    ):
                        await self._send_login_message(
                            handler,
                            user,
                            channel,
                            area,
                            str(bind_res.get("message") or bind_res.get("msg") or "账号绑定失败"),
                            temp_channel=temp_channel,
                            delivery_mode=delivery_mode,
                        )
                        await self._cleanup_temp_channel_after_notice(
                            handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                        )
                        return
                    await self._store.set_active_token(user, final_token)
                    list_res = await self._api.get_user_list(user)
                    accounts = list_res.get("data") if isinstance(list_res.get("data"), list) else []
                    if accounts:
                        await self._store.choose_active_token(user, accounts)
                    await self._send_login_message(
                        handler,
                        user,
                        channel,
                        area,
                        "登录成功，已绑定账号。请继续执行“@bot 三角洲角色绑定”。",
                        temp_channel=temp_channel,
                        delivery_mode=delivery_mode,
                    )
                    await self._cleanup_temp_channel_after_notice(
                        handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                    )
                    return
                if code in {-2, "-2"}:
                    await self._send_login_message(
                        handler, user, channel, area, "二维码已过期，请重新执行三角洲登录。",
                        temp_channel=temp_channel, delivery_mode=delivery_mode,
                    )
                    await self._cleanup_temp_channel_after_notice(
                        handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                    )
                    return
                if code in {-3, "-3"}:
                    await self._send_login_message(
                        handler, user, channel, area, "本次扫码被风控拦截，请稍后重试。",
                        temp_channel=temp_channel, delivery_mode=delivery_mode,
                    )
                    await self._cleanup_temp_channel_after_notice(
                        handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                    )
                    return
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=self._poll_interval)

            if not stop_event.is_set():
                await self._send_login_message(
                    handler, user, channel, area, "登录超时，请重新执行三角洲登录。",
                    temp_channel=temp_channel, delivery_mode=delivery_mode,
                )
                await self._cleanup_temp_channel_after_notice(
                    handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("DeltaForceLogin: polling failed for %s", user)
            await self._send_login_message(
                handler, user, channel, area, f"登录流程异常: {exc}",
                temp_channel=temp_channel, delivery_mode=delivery_mode,
            )
            await self._cleanup_temp_channel_after_notice(
                handler, temp_channel=temp_channel, area=area, stop_event=stop_event,
            )
        finally:
            async with self._lock:
                self._sessions.pop(user, None)
            await self._cleanup_path(qr_path)

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
            [{"person": user, "isBot": False, "botType": "", "offset": -1}],
        )

    async def _cleanup_temp_channel_after_notice(
        self,
        handler,
        *,
        temp_channel: str,
        area: str,
        stop_event: asyncio.Event,
    ) -> None:
        if not temp_channel:
            return
        if self._success_notice_delay > 0:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=self._success_notice_delay)
        try:
            deleted = await handler.sender.bot.channels.delete_channel(area, temp_channel)
            if not deleted.ok:
                raise RuntimeError(deleted.message or "删除临时频道被拒绝") from None
        except Exception as exc:
            logger.warning("DeltaForceLogin: delete temp channel failed: %s", exc)

    @staticmethod
    async def _cleanup_path(path: str | None) -> None:
        if not path:
            return
        try:
            await asyncio.to_thread(Path(path).unlink, missing_ok=True)
        except OSError:
            return

    def _cleanup_stale_qrs(self) -> None:
        ttl_seconds = max(self._timeout * 2, 600)
        now = time.time()
        removed = 0
        try:
            files = list(self._qrs_dir.glob("*.png"))
        except OSError as exc:
            logger.warning("DeltaForceLogin: list qrs dir failed: %s", exc)
            return
        for path in files:
            try:
                if now - path.stat().st_mtime < ttl_seconds:
                    continue
                path.unlink(missing_ok=True)
                removed += 1
            except OSError as exc:
                logger.debug("DeltaForceLogin: skip stale qr cleanup for %s: %s", path, exc)
        if removed:
            logger.info("DeltaForceLogin: 已清理 %s 个过期二维码文件", removed)
