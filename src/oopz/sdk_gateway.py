"""基于 oopz-sdk 的项目异步网关。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import mimetypes
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from PIL import Image
from pydantic import BaseModel

from config import AUTO_RECALL_CONFIG, OOPZ_CONFIG
from core.logger_config import get_logger
from oopz.errors import SensitiveContentError, is_sensitive_rejection
from oopz.remote_fetch import SafeRemoteFetcher
from oopz.sdk_config import build_sdk_config
from oopz.sdk_transport import install_project_transports
from oopz_sdk import OopzBot
from oopz_sdk.auth import OopzLoginCredentials
from oopz_sdk.exceptions import OopzApiError, OopzError
from oopz_sdk.models import Attachment, ImageAttachment
from oopz_sdk.models.attachment import AudioAttachment
from oopz_sdk.models.message import MentionInfo

logger = get_logger("AsyncOopzGateway")

MAX_IMAGE_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_AUDIO_DOWNLOAD_BYTES = 100 * 1024 * 1024


@dataclass(slots=True)
class GatewayResponse:
    """异步发送结果的最小 requests.Response 兼容视图。"""

    payload: dict[str, Any]
    status_code: int = 200

    @property
    def text(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)

    @property
    def content(self) -> bytes:
        return self.text.encode("utf-8")

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OopzApiError(
                self.payload.get("message") or f"HTTP {self.status_code}",
                status_code=self.status_code,
                payload=self.payload,
            )


def to_legacy(value: Any) -> Any:
    """SDK Pydantic 模型递归转换成原项目使用的小驼峰字典。"""

    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return {str(key): to_legacy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_legacy(item) for item in value]
    return value


def _operation_payload(result: Any, success_message: str) -> dict[str, Any]:
    ok = bool(getattr(result, "ok", True))
    message = str(getattr(result, "message", "") or success_message)
    if not ok:
        return {"error": message}
    return {"status": True, "message": message}


def _attachment(value: Any) -> Attachment:
    if isinstance(value, Attachment):
        return value
    if isinstance(value, dict):
        return Attachment.parse(value)
    raise TypeError(f"不支持的附件类型: {type(value).__name__}")


class AsyncOopzGateway:
    """当前项目访问 Oopz-SDK 的唯一入口。"""

    def __init__(
        self,
        *,
        on_chat_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_private_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_other_event: Callable[[int, dict[str, Any]], Awaitable[None]] | None = None,
        on_raw_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.bot: OopzBot
        self.raw: OopzBot
        self.signer: Any
        self._on_chat_message = on_chat_message
        self._on_private_message = on_private_message
        self._on_other_event = on_other_event
        self._on_raw_event = on_raw_event
        self._proxy_value: object = None
        self._auto_recall_scheduler: Any = None
        self._ready = asyncio.Event()
        self._run_task: asyncio.Task[None] | None = None
        self._task_supervisor: Any = None
        self._role_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._rebuild_lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        *,
        on_chat_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_private_message: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_other_event: Callable[[int, dict[str, Any]], Awaitable[None]] | None = None,
        on_raw_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> AsyncOopzGateway:
        config, proxy, proxy_value = await build_sdk_config()
        gateway = cls(
            on_chat_message=on_chat_message,
            on_private_message=on_private_message,
            on_other_event=on_other_event,
            on_raw_event=on_raw_event,
        )
        gateway._install_bot(config, proxy, proxy_value)
        return gateway

    async def _handle_sdk_message(self, message, _ctx) -> None:
        if self._on_chat_message is not None:
            await self._on_chat_message(to_legacy(message))

    async def _handle_sdk_private_message(self, message, _ctx) -> None:
        if self._on_private_message is not None:
            await self._on_private_message(to_legacy(message))

    async def _handle_sdk_ready(self, _ctx) -> None:
        self._ready.set()
        logger.info("Oopz-SDK WebSocket ready")

    async def _handle_sdk_raw(self, _ctx, event) -> None:
        raw = dict(getattr(event, "raw", {}) or {})
        if self._on_raw_event is not None:
            await self._on_raw_event(raw)
        if self._on_other_event is not None and getattr(event, "event_name", "") not in {
            "message",
            "message.private",
            "message.edit",
            "message.private.edit",
        }:
            await self._on_other_event(int(getattr(event, "event_type", 0)), raw)

    async def _handle_sdk_error(self, _ctx, error) -> None:
        logger.error("Oopz-SDK 事件错误: %s", error)

    def _install_bot(self, config, proxy, proxy_value: object) -> None:
        bot = OopzBot(
            config,
            on_message=self._handle_sdk_message,
            on_ready=self._handle_sdk_ready,
            on_raw_event=self._handle_sdk_raw,
            on_error=self._handle_sdk_error,
        )
        bot.on_private_message(self._handle_sdk_private_message)
        install_project_transports(bot, proxy, proxy_value)
        self.bot = bot
        self.raw = bot
        self.signer = bot.rest.signer
        self._proxy_value = proxy_value

    async def rebuild_credentials(self, credentials: OopzLoginCredentials) -> None:
        """管理端热更新凭据时受控重建 SDK 会话，并在失败时恢复旧会话。"""
        async with self._rebuild_lock:
            config, proxy, proxy_value = await build_sdk_config(credentials)
            old_bot = self.bot
            old_proxy_value = self._proxy_value
            was_running = self._run_task is not None and not self._run_task.done()
            await self.stop()
            try:
                self._install_bot(config, proxy, proxy_value)
                if was_running:
                    await self.start()
            except BaseException:
                with contextlib.suppress(BaseException):
                    await self.bot.stop()
                self.bot = old_bot
                self.raw = old_bot
                self.signer = old_bot.rest.signer
                self._proxy_value = old_proxy_value
                if was_running:
                    await self.start()
                raise

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def wait_ready(self, timeout: float = 30.0) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout=max(0.1, timeout))

    async def start(self, supervisor: Any = None) -> None:
        if self._run_task is not None and not self._run_task.done():
            return
        if supervisor is not None:
            self._task_supervisor = supervisor
        self._ready.clear()
        if self._task_supervisor is None:
            task = asyncio.create_task(self.bot.start(), name="oopz-sdk")
        else:
            task = self._task_supervisor.create(
                self.bot.start(),
                name="oopz-sdk",
            )
        self._run_task = task
        await asyncio.sleep(0)
        if task.done():
            await task

    async def run(self) -> None:
        await self.start()
        assert self._run_task is not None
        await self._run_task

    async def stop(self) -> None:
        task = self._run_task
        self._run_task = None
        try:
            await self.bot.stop()
        finally:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self._ready.clear()

    def bind_auto_recall_scheduler(self, scheduler: Any) -> None:
        self._auto_recall_scheduler = scheduler

    @staticmethod
    def _default_area(area: str | None) -> str:
        return str(area or OOPZ_CONFIG.get("default_area") or "").strip()

    @staticmethod
    def _default_channel(channel: str | None) -> str:
        return str(channel or OOPZ_CONFIG.get("default_channel") or "").strip()

    @staticmethod
    def _style_tags(area: str, explicit: list | None) -> list:
        if explicit is not None:
            return explicit
        fallback = bool(OOPZ_CONFIG.get("use_announcement_style", False))
        try:
            from core.area_config import get_area_registry

            enabled = get_area_registry().get_announcement_style(area, fallback)
        except Exception:
            enabled = fallback
        return ["IMPORTANT"] if enabled else []

    async def send_message(
        self,
        text: str,
        area: str | None = None,
        channel: str | None = None,
        auto_recall: bool | None = None,
        **kwargs: Any,
    ) -> GatewayResponse:
        area = self._default_area(area)
        channel = self._default_channel(channel)
        try:
            result = await self.bot.messages.send_message(
                str(text),
                area=area,
                channel=channel,
                attachments=[_attachment(item) for item in kwargs.get("attachments", [])],
                mention_list=[MentionInfo.model_validate(item) for item in kwargs.get("mentionList", [])],
                is_mention_all=bool(kwargs.get("isMentionAll", False)),
                style_tags=self._style_tags(area, kwargs.get("styleTags")),
                reference_message_id=kwargs.get("referenceMessageId"),
                animated=bool(kwargs.get("animated", False)),
                display_name=str(kwargs.get("displayName") or ""),
                duration=int(kwargs.get("duration") or 0),
                version=str(kwargs.get("version") or "v1"),
            )
        except OopzError as exc:
            if is_sensitive_rejection(str(exc)):
                raise SensitiveContentError(str(exc)) from exc
            raise

        payload = {
            "status": True,
            "data": {
                "messageId": result.message_id,
                "timestamp": result.timestamp,
            },
        }
        response = GatewayResponse(payload)
        if auto_recall is not False:
            await self._schedule_auto_recall(result.message_id, area, channel, result.timestamp)
        return response

    async def send_to_default(self, text: str, **kwargs: Any) -> GatewayResponse:
        return await self.send_message(text, **kwargs)

    async def send_multiple(self, messages: list[str], interval: float = 1.0) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            try:
                response = await self.send_to_default(message)
                results.append({"message": message, "status_code": response.status_code, "success": True})
            except Exception as exc:
                results.append({"message": message, "status_code": None, "success": False, "error": str(exc)})
            if index + 1 < len(messages):
                await asyncio.sleep(max(0.0, interval))
        return results

    async def _schedule_auto_recall(
        self,
        message_id: str,
        area: str,
        channel: str,
        timestamp: str,
    ) -> None:
        if not AUTO_RECALL_CONFIG.get("enabled") or not message_id:
            return
        delay = float(AUTO_RECALL_CONFIG.get("delay", 30) or 0)
        if delay <= 0 or self._auto_recall_scheduler is None:
            return
        result = self._auto_recall_scheduler.schedule_recall(
            message_id=message_id,
            channel=channel,
            area=area,
            timestamp=timestamp,
            delay=delay,
        )
        if isinstance(result, Awaitable):
            await result

    async def open_private_session(self, target: str) -> dict[str, Any]:
        try:
            session = await self.bot.messages.open_private_session(str(target).strip())
            return {"status": True, "channel": session.session_id, "raw": to_legacy(session)}
        except Exception as exc:
            return {"error": str(exc)}

    async def send_private_message(
        self,
        target: str,
        text: str,
        *,
        attachments: list | None = None,
        style_tags: list | None = None,
        channel: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self.bot.messages.send_private_message(
                str(text),
                target=str(target).strip(),
                channel=channel,
                attachments=[_attachment(item) for item in attachments or []],
                style_tags=style_tags or [],
                version="v2",
            )
            return {"status": True, "channel": channel or "", "result": to_legacy(result)}
        except Exception as exc:
            return {"error": str(exc), "channel": channel or ""}

    async def get_area_operate_logs(
        self, area: str | None = None, offset: int = 0, op_types: list[str] | None = None
    ) -> dict[str, Any]:
        try:
            logs = await self.bot.areas.get_area_operate_logs(
                self._default_area(area), offset=max(0, int(offset)), op_types=op_types
            )
            return {"logs": to_legacy(logs)}
        except Exception as exc:
            return {"error": str(exc)}

    async def get_area_members(
        self,
        area: str | None = None,
        offset_start: int = 0,
        offset_end: int = 49,
        quiet: bool = False,
    ) -> dict[str, Any]:
        try:
            page = await self.bot.areas.get_area_members(
                self._default_area(area),
                int(offset_start),
                int(offset_end),
            )
        except Exception as exc:
            if not quiet:
                logger.error("获取域成员失败: %s", exc)
            return {"error": str(exc)}
        data = to_legacy(page)
        members = data.get("members", [])
        online = sum(1 for member in members if int(member.get("online", 0) or 0) == 1)
        role_count = data.get("roleCount", [])
        online_api = sum(int(item.get("count", 0) or 0) for item in role_count if int(item.get("role", 0) or 0) != -1)
        total = int(data.get("totalCount") or len(members))
        data.update(
            onlineCount=online_api or online,
            totalCount=total,
            userCount=total,
            fetchedCount=len(members),
        )
        data.pop("payload", None)
        return data

    async def get_area_channels(self, area: str | None = None, quiet: bool = False) -> list[dict[str, Any]]:
        try:
            return to_legacy(await self.bot.areas.get_area_channels(self._default_area(area)))
        except Exception as exc:
            if not quiet:
                logger.error("获取频道列表失败: %s", exc)
            return []

    async def get_channel_setting_info(self, channel: str) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.channels.get_channel_setting_info(str(channel).strip()))
        except Exception as exc:
            return {"error": str(exc)}

    async def _pick_channel_group(
        self,
        area: str,
        preferred_channel: str | None = None,
        preferred_group_name: str | None = None,
    ) -> str | None:
        groups = await self.get_area_channels(area, quiet=True)
        preferred_channel = str(preferred_channel or "").strip()
        preferred_group_name = str(preferred_group_name or "").strip().lower()
        fallback = None
        for group in groups:
            group_id = str(group.get("id") or "").strip()
            if not group_id:
                continue
            fallback = fallback or group_id
            if preferred_group_name and str(group.get("name") or "").strip().lower() == preferred_group_name:
                return group_id
            if preferred_channel and any(
                str(channel.get("id") or "") == preferred_channel
                for channel in group.get("channels") or []
            ):
                return group_id
        return None if preferred_group_name else fallback

    async def create_channel(
        self,
        area: str | None = None,
        name: str = "",
        channel_type: str = "text",
        group_id: str = "",
    ) -> dict[str, Any]:
        try:
            result = await self.bot.channels.create_channel(
                self._default_area(area),
                str(name).strip(),
                group_id=group_id,
                channel_type=channel_type,
            )
            data = to_legacy(result)
            return {
                "status": True,
                "channel": str(data.get("channel") or data.get("id") or ""),
                "name": name,
                "message": "频道已创建",
            }
        except Exception as exc:
            return {"error": str(exc)}

    async def update_channel(
        self,
        area: str | None = None,
        channel_id: str = "",
        overrides: dict[str, Any] | None = None,
        *,
        name: str = "",
    ) -> dict[str, Any]:
        values: dict[str, Any] = dict(overrides or {})
        if name:
            values["name"] = name
        mapping = {
            "textGapSecond": "text_gap_second",
            "voiceQuality": "voice_quality",
            "voiceDelay": "voice_delay",
            "maxMember": "max_member",
            "voiceControlEnabled": "voice_control_enabled",
            "textControlEnabled": "text_control_enabled",
            "accessControlEnabled": "access_control_enabled",
            "hasPassword": "has_password",
            "textRoles": "text_roles",
            "voiceRoles": "voice_roles",
            "accessible": "accessible_roles",
            "accessibleMembers": "accessible_members",
        }
        kwargs = {mapping.get(key, key): value for key, value in values.items()}
        try:
            result = await self.bot.channels.update_channel(
                self._default_area(area), str(channel_id).strip(), **kwargs
            )
            return _operation_payload(result, "频道已更新")
        except Exception as exc:
            return {"error": str(exc)}

    async def create_restricted_text_channel(
        self,
        target_uid: str,
        area: str | None = None,
        preferred_channel: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        area = self._default_area(area)
        target_uid = str(target_uid or "").strip()
        if not target_uid:
            return {"error": "缺少 target_uid"}
        group_id = await self._pick_channel_group(area, preferred_channel=preferred_channel)
        if not group_id:
            return {"error": "未找到可用频道分组"}
        channel_name = str(name or f"登录-{target_uid[-4:]}-{time.strftime('%H%M%S')}").strip() or "登录"
        created = await self.create_channel(area, channel_name, "text", group_id)
        channel = str(created.get("channel") or "")
        if "error" in created or not channel:
            return created if "error" in created else {"error": "创建频道成功，但未能提取频道 ID"}
        updated = await self.update_channel(
            area,
            channel,
            {
                "secret": True,
                "accessControlEnabled": True,
                "accessible": [],
                "accessibleMembers": [target_uid, self.bot.config.person_uid],
            },
        )
        if "error" in updated:
            await self.delete_channel(channel, area=area)
            return updated
        return {"status": True, "channel": channel, "group": group_id, "name": channel_name}

    async def delete_channel(self, channel: str, area: str | None = None) -> dict[str, Any]:
        try:
            result = await self.bot.channels.delete_channel(self._default_area(area), str(channel).strip())
            return _operation_payload(result, "已删除频道")
        except Exception as exc:
            return {"error": str(exc)}

    async def get_joined_areas(self, quiet: bool = False) -> list[dict[str, Any]]:
        try:
            return to_legacy(await self.bot.areas.get_joined_areas())
        except Exception as exc:
            if not quiet:
                logger.error("获取已加入域失败: %s", exc)
            return []

    async def get_area_invite_detail(self, code: str) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.areas.get_invite_detail(str(code).strip()))
        except Exception as exc:
            return {"error": str(exc)}

    async def get_area_info(self, area: str | None = None) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.areas.get_area_info(self._default_area(area)))
        except Exception as exc:
            return {"error": str(exc)}

    async def leave_area(self, area: str) -> dict[str, Any]:
        try:
            return _operation_payload(await self.bot.areas.leave_area(str(area).strip()), "已离开域")
        except Exception as exc:
            return {"error": str(exc)}

    async def populate_names(self) -> dict[str, int]:
        from oopz.name_resolver import get_resolver

        resolver = get_resolver()
        result = await self.bot.areas.populate_names(
            set_area=resolver.set_area,
            set_channel=resolver.set_channel,
        )
        return to_legacy(result)

    async def get_person_infos_batch(self, uids: list[str], **_kwargs: Any) -> dict[str, dict]:
        if not uids:
            return {}
        output: dict[str, dict] = {}
        for index in range(0, len(uids), 30):
            try:
                people = await self.bot.person.get_person_infos_batch(uids[index:index + 30])
            except Exception as exc:
                logger.debug("批量获取用户信息部分失败: %s", exc)
                continue
            for person in people:
                data = to_legacy(person)
                uid = str(data.get("uid") or "")
                if uid:
                    output[uid] = data
        return output

    async def get_friendship(self) -> list[dict[str, Any]]:
        try:
            return to_legacy(await self.bot.person.get_friendship())
        except Exception:
            return []

    async def get_friendship_requests(self) -> list[dict[str, Any]]:
        try:
            return to_legacy(await self.bot.person.get_friendship_requests())
        except Exception:
            return []

    async def post_friendship_response(self, target: str, friend_request_id: int, agree: bool) -> dict[str, Any]:
        try:
            result = await self.bot.person.post_friendship_response(target, int(friend_request_id), bool(agree))
            return _operation_payload(result, "好友请求已处理")
        except Exception as exc:
            return {"error": str(exc)}

    async def set_user_remark_name(self, uid: str, remark_name: str = "") -> dict[str, Any]:
        try:
            result = await self.bot.person.set_user_remark_name(uid, remark_name)
            return _operation_payload(result, "备注已更新")
        except Exception as exc:
            return {"error": str(exc)}

    async def get_person_detail(self, uid: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.person.get_person_info(uid or self.bot.config.person_uid))
        except Exception as exc:
            return {"error": str(exc)}

    async def get_person_detail_full(self, uid: str, **_kwargs: Any) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.person.get_person_detail_full(uid))
        except Exception as exc:
            return {"error": str(exc)}

    async def get_self_detail(self) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.person.get_self_detail())
        except Exception as exc:
            return {"error": str(exc)}

    async def get_level_info(self) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.person.get_level_info())
        except Exception as exc:
            return {"error": str(exc)}

    async def get_user_area_detail(self, target: str, area: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.areas.get_area_user_detail(self._default_area(area), target))
        except Exception as exc:
            return {"error": str(exc)}

    async def get_assignable_roles(self, target: str, area: str | None = None, **_kwargs: Any) -> list[dict[str, Any]]:
        try:
            return to_legacy(await self.bot.areas.get_area_can_give_list(self._default_area(area), target))
        except Exception:
            return []

    async def edit_user_role(
        self,
        target_uid: str,
        role_id: int,
        add: bool,
        area: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        area = self._default_area(area)
        key = (area, str(target_uid))
        lock = self._role_locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                result = await self.bot.areas.edit_user_role(area, target_uid, int(role_id), bool(add))
            return _operation_payload(result, "已给身份组" if add else "已取消身份组")
        except Exception as exc:
            return {"error": str(exc)}

    async def search_area_members(self, area: str | None = None, keyword: str = "", **_kwargs: Any) -> list[dict[str, Any]]:
        area = self._default_area(area)
        needle = str(keyword or "").strip().lower()
        try:
            members = await self.bot.areas.get_all_area_members(area, page_size=100)
        except Exception:
            return []
        legacy_members = to_legacy(members)
        if not needle:
            return legacy_members[:50]
        profiles = await self.get_person_infos_batch([str(item.get("uid") or "") for item in legacy_members])
        output = []
        for member in legacy_members:
            uid = str(member.get("uid") or "")
            name = str(profiles.get(uid, {}).get("name") or "")
            if needle in uid.lower() or needle in name.lower():
                output.append({**member, **profiles.get(uid, {})})
            if len(output) >= 50:
                break
        return output

    async def get_voice_channel_members(self, area: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        try:
            data = to_legacy(await self.bot.channels.get_voice_channel_members(self._default_area(area)))
            return data.get("channelMembers", data) if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def get_voice_channel_for_user(self, user_uid: str, area: str | None = None, **_kwargs: Any) -> str | None:
        try:
            return await self.bot.channels.get_voice_channel_for_user(self._default_area(area), user_uid)
        except Exception as exc:
            # 查询失败与「不在任何语音频道」都返回 None，调用方无从区分。残留清理
            # 依赖这个查询，静默失败会让 bot 以重复进入的方式入频道（不广播成员
            # 加入事件，其他客户端看不到它），因此这里必须留下痕迹。
            logger.warning("查询用户语音频道失败 uid=%s: %s", str(user_uid)[:8], exc)
            return None

    async def get_voice_channel_for_user_strict(
        self, user_uid: str, area: str | None = None
    ) -> str | None:
        return await self.bot.channels.get_voice_channel_for_user(
            self._default_area(area), user_uid
        )

    async def drag_member(
        self,
        target: str,
        to_channel: str,
        from_channel: str | None = None,
        area: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        area = self._default_area(area)
        source = str(from_channel or "").strip() or await self.get_voice_channel_for_user(target, area)
        if not source:
            return {"error": "未找到该用户当前所在的语音频道"}
        if source == to_channel:
            return {"error": "用户已在目标语音频道"}
        try:
            result = await self.bot.channels.drag_member(area, target, to_channel, source)
            payload = _operation_payload(result, "已调度")
            if "error" not in payload:
                payload.update(from_channel=source, to_channel=to_channel)
            return payload
        except Exception as exc:
            return {"error": str(exc)}

    async def enter_area(self, area: str | None = None, recover: bool = False) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.areas.enter_area(self._default_area(area), recover))
        except Exception as exc:
            return {"error": str(exc)}

    async def enter_channel(
        self,
        channel: str | None = None,
        area: str | None = None,
        channel_type: str = "TEXT",
        from_channel: str = "",
        from_area: str = "",
        pid: str = "",
    ) -> dict[str, Any]:
        try:
            return to_legacy(
                await self.bot.channels.enter_channel(
                    self._default_area(area),
                    self._default_channel(channel),
                    channel_type,
                    from_channel,
                    from_area,
                    pid,
                )
            )
        except Exception as exc:
            return {"error": str(exc)}

    async def leave_voice_channel(
        self, channel: str, area: str | None = None, target: str | None = None
    ) -> dict[str, Any]:
        try:
            result = await self.bot.channels.leave_voice_channel(
                self._default_area(area), channel, target or self.bot.config.person_uid
            )
            return _operation_payload(result, "已退出语音频道")
        except Exception as exc:
            return {"error": str(exc)}

    async def get_daily_speech(self, **_kwargs: Any) -> dict[str, Any]:
        try:
            return to_legacy(await self.bot.general.get_daily_speech())
        except Exception as exc:
            return {"error": str(exc)}

    async def get_channel_messages(
        self, area: str | None = None, channel: str | None = None, size: int = 50, **_kwargs: Any
    ) -> list[dict[str, Any]]:
        try:
            return to_legacy(
                await self.bot.messages.get_channel_messages(
                    self._default_area(area), self._default_channel(channel), int(size)
                )
            )
        except Exception:
            return []

    async def find_message_timestamp(
        self, message_id: str, area: str | None = None, channel: str | None = None, **_kwargs: Any
    ) -> str | None:
        for message in await self.get_channel_messages(area, channel):
            if str(message.get("messageId") or message.get("id") or "") == str(message_id):
                return str(message.get("timestamp") or "") or None
        return None

    async def _moderation(self, operation: Callable[..., Awaitable[Any]], *args: Any, success: str) -> dict[str, Any]:
        try:
            return _operation_payload(await operation(*args), success)
        except Exception as exc:
            return {"error": str(exc)}

    async def mute_user(self, uid: str, area: str | None = None, channel: str | None = None, duration: int = 10) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.mute_user, self._default_area(area), uid, duration, success="禁言成功")

    async def unmute_user(self, uid: str, area: str | None = None, channel: str | None = None) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.unmute_user, self._default_area(area), uid, success="解除禁言成功")

    async def mute_mic(self, uid: str, area: str | None = None, channel: str | None = None, duration: int = 10) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.mute_mic, self._default_area(area), uid, duration, success="禁麦成功")

    async def unmute_mic(self, uid: str, area: str | None = None, channel: str | None = None) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.unmute_mic, self._default_area(area), uid, success="解除禁麦成功")

    async def remove_from_area(self, uid: str, area: str | None = None) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.remove_from_area, self._default_area(area), uid, success="已移出域")

    async def block_user_in_area(self, uid: str, area: str | None = None) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.block_user_in_area, self._default_area(area), uid, success="已封禁")

    async def get_area_blocks(self, area: str | None = None, name: str = "", **_kwargs: Any) -> dict[str, Any]:
        try:
            return {"blocks": to_legacy(await self.bot.moderation.get_area_blocks(self._default_area(area), name))}
        except Exception as exc:
            return {"error": str(exc)}

    async def unblock_user_in_area(self, uid: str, area: str | None = None) -> dict[str, Any]:
        return await self._moderation(self.bot.moderation.unblock_user_in_area, self._default_area(area), uid, success="解除域内封禁成功")

    async def recall_message(
        self,
        message_id: str,
        area: str | None = None,
        channel: str | None = None,
        timestamp: str | None = None,
        target: str = "",
        **_kwargs: Any,
    ) -> dict[str, Any]:
        try:
            result = await self.bot.messages.recall_message(
                str(message_id), self._default_area(area), self._default_channel(channel), timestamp, target
            )
            return _operation_payload(result, "撤回成功")
        except Exception as exc:
            return {"error": str(exc)}

    async def recall_private_message(
        self,
        message_id: str,
        *,
        channel: str = "",
        target: str = "",
        area: str | None = None,
        timestamp: str | None = None,
    ) -> dict[str, Any]:
        try:
            result = await self.bot.messages.recall_private_message(
                str(message_id), channel, target, area=area, timestamp=timestamp
            )
            return _operation_payload(result, "撤回成功")
        except Exception as exc:
            return {"error": str(exc)}

    async def upload_file(self, file_path: str, file_type: str = "IMAGE", ext: str = ".webp") -> dict[str, Any]:
        result = await self.bot.media.upload_file(file_path, file_type=file_type, ext=ext)
        return to_legacy(result)

    async def upload_file_from_url(self, image_url: str, **_kwargs: Any) -> dict[str, Any]:
        started_at = time.monotonic()
        try:
            image_bytes, _content_type = await asyncio.to_thread(
                SafeRemoteFetcher(proxy_value=self._proxy_value).fetch,
                image_url,
                max_bytes=MAX_IMAGE_DOWNLOAD_BYTES,
                timeout=(10, 60),
            )
            downloaded_at = time.monotonic()
            width, height, image_format = await asyncio.to_thread(self._image_metadata, image_bytes)
            ext = "." + (image_format or "webp").lower()
            uploaded = await self.bot.media.upload_bytes(image_bytes, file_type="IMAGE", ext=ext)
            uploaded_at = time.monotonic()
            logger.info(
                "URL 图片上传完成: %dx%d, %.1f KiB, 下载 %.2fs, Oopz/COS %.2fs, 总计 %.2fs",
                width,
                height,
                len(image_bytes) / 1024,
                downloaded_at - started_at,
                uploaded_at - downloaded_at,
                uploaded_at - started_at,
            )
            attachment = ImageAttachment.from_manually(
                file_key=uploaded.file_key,
                url=uploaded.url,
                width=width,
                height=height,
                file_size=len(image_bytes),
                hash=hashlib.md5(image_bytes).hexdigest(),
                animated=uploaded.animated,
                display_name=uploaded.display_name,
            )
            return {"code": "success", "message": "上传成功", "data": attachment.to_payload()}
        except Exception as exc:
            logger.error("从 URL 上传失败: %s", exc)
            return {"code": "error", "message": str(exc), "data": None}

    @staticmethod
    def _image_metadata(data: bytes) -> tuple[int, int, str]:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height), str(image.format or "webp")

    async def upload_audio_from_url(
        self, audio_url: str, filename: str = "music.mp3", duration_ms: int = 0
    ) -> dict[str, Any]:
        try:
            audio, content_type = await asyncio.to_thread(
                SafeRemoteFetcher(proxy_value=self._proxy_value).fetch,
                audio_url,
                max_bytes=MAX_AUDIO_DOWNLOAD_BYTES,
                timeout=(10, 120),
                headers={"Referer": "https://music.163.com/"},
            )
            guessed = mimetypes.guess_extension(content_type.partition(";")[0].strip()) or os.path.splitext(filename)[1]
            ext = ".m4a" if guessed in {".mp4", ".m4a"} else guessed or ".mp3"
            uploaded = await self.bot.media.upload_bytes(
                audio,
                file_type="AUDIO",
                ext=ext,
                display_name=filename,
            )
            attachment = AudioAttachment.from_manually(
                file_key=uploaded.file_key,
                url=uploaded.url,
                display_name=filename,
                file_size=len(audio),
                duration=int(duration_ms),
                hash=hashlib.md5(audio).hexdigest(),
            )
            return {"code": "success", "message": "上传成功", "data": attachment.to_payload()}
        except Exception as exc:
            return {"code": "error", "message": str(exc), "data": None}

    async def upload_and_send_image(self, file_path: str, text: str = "", **kwargs: Any) -> GatewayResponse:
        uploaded = await self.bot.media.upload_file(file_path, file_type="IMAGE", ext=os.path.splitext(file_path)[1] or ".webp")
        width, height, _format = await asyncio.to_thread(self._image_file_metadata, file_path)
        attachment = ImageAttachment.from_manually(
            file_key=uploaded.file_key,
            url=uploaded.url,
            width=width,
            height=height,
            file_size=os.path.getsize(file_path),
            display_name=os.path.basename(file_path),
        )
        return await self.send_message(text, attachments=[attachment], **kwargs)

    @staticmethod
    def _image_file_metadata(path: str) -> tuple[int, int, str]:
        with Image.open(path) as image:
            return int(image.width), int(image.height), str(image.format or "")

    async def upload_and_send_private_image(self, target: str, file_path: str, text: str = "") -> dict[str, Any]:
        uploaded = await self.bot.media.upload_file(file_path, file_type="IMAGE", ext=os.path.splitext(file_path)[1] or ".webp")
        width, height, _format = await asyncio.to_thread(self._image_file_metadata, file_path)
        attachment = ImageAttachment.from_manually(
            file_key=uploaded.file_key,
            url=uploaded.url,
            width=width,
            height=height,
            file_size=os.path.getsize(file_path),
            display_name=os.path.basename(file_path),
        )
        return await self.send_private_message(target, text, attachments=[attachment])
