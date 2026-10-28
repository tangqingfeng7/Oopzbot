from __future__ import annotations

from contextlib import suppress

from app.services.runtime import CommandRuntimeView, sender_of
from screen_share import ScreenShareError, get_screen_share_service
from screen_share.labels import presenter_label
from screen_share.messages import recall_viewer_link


class ScreenShareCommandService:
    """频道命令入口；媒体与浏览器会话由 screen_share 包负责。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    def _is_bot_admin(self, user: str) -> bool:
        return self._runtime.services.routing.access.is_admin(user)

    async def start(self, channel: str, area: str, user: str) -> None:
        service = get_screen_share_service()
        try:
            links = await service.create_session(
                sender=self._sender,
                user=user,
                area=area,
                channel=channel,
                is_bot_admin=self._is_bot_admin(user),
            )
        except ScreenShareError as exc:
            await self._sender.send_message(f"屏幕共享创建失败：{exc}", channel=channel, area=area)
            return
        except Exception:
            await self._sender.send_message(
                "屏幕共享创建失败：服务暂时不可用",
                channel=channel,
                area=area,
            )
            return

        try:
            dm = await self._sender.send_private_message(
                user,
                "屏幕共享【发起端专用链接】（不是观看链接，单次使用）：\n"
                f"{links.presenter_url}\n"
                "请由你本人打开并选择要共享的窗口；共享成功后 Bot 才会在原频道发送观看链接。",
            )
        except Exception:
            dm = {"error": "private_message_failed"}
        if not isinstance(dm, dict) or dm.get("error"):
            with suppress(ScreenShareError):
                await service.stop_by_id(
                    links.session_id,
                    reason="private_message_failed",
                )
            await self._sender.send_message(
                "屏幕共享创建失败：无法私信发送发起链接，链接未在频道公开",
                channel=channel,
                area=area,
            )
            return

        await self._sender.send_message(
            "屏幕共享发起链接已通过私信发送；共享成功后这里会出现观看链接。",
            channel=channel,
            area=area,
        )

    async def stop(self, channel: str, area: str, user: str) -> None:
        service = get_screen_share_service()
        try:
            sessions = await service.list_by_channel(area=area, channel=channel)
            if not sessions:
                await self._sender.send_message("当前频道没有屏幕共享", channel=channel, area=area)
                return

            own_session = next(
                (
                    session
                    for session in sessions
                    if str(session.get("presenter_uid") or "") == str(user)
                ),
                None,
            )
            if own_session is not None:
                stopped = [await service.stop(own_session, reason="command_stop_self")]
            elif not await service.authorize(
                self._sender,
                user=user,
                area=area,
                is_bot_admin=self._is_bot_admin(user),
            ):
                await self._sender.send_message("你的域角色没有停止该共享的权限", channel=channel, area=area)
                return
            else:
                stopped = [
                    await service.stop(session, reason="command_stop_channel")
                    for session in sessions
                ]
        except ScreenShareError as exc:
            await self._sender.send_message(f"停止屏幕共享失败：{exc}", channel=channel, area=area)
            return
        except Exception:
            await self._sender.send_message(
                "停止屏幕共享失败：服务暂时不可用",
                channel=channel,
                area=area,
            )
            return
        for stopped_session in stopped:
            await recall_viewer_link(self._sender, stopped_session)
        if len(stopped) > 1:
            await self._sender.send_message(
                f"已结束当前频道的 {len(stopped)} 个屏幕共享",
                channel=channel,
                area=area,
            )
        elif stopped[0].get("status") == "active":
            presenter_name = await presenter_label(stopped[0])
            await self._sender.send_message(
                f"{presenter_name} 的屏幕共享已结束",
                channel=channel,
                area=area,
            )
        else:
            await self._sender.send_message("屏幕共享会话已取消", channel=channel, area=area)
