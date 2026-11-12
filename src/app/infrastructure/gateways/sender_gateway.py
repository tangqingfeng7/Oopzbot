"""应用消息、媒体和平台操作。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import time
from collections.abc import Awaitable, Container
from pathlib import Path
from typing import Any

from oopz_sdk import OopzBot
from oopz_sdk.exceptions import OopzError
from oopz_sdk.models import AreaMemberInfo, Attachment, ImageAttachment, OperationResult
from oopz_sdk.models.message import MentionInfo, MessageSendResult
from oopz_sdk.models.segment import Image as ImageSegment
from PIL import Image

from app.infrastructure.member_cache import invalidate_members_cache
from config import AUTO_RECALL_CONFIG, OOPZ_CONFIG
from core.logger_config import get_logger
from oopz.errors import SensitiveContentError, is_sensitive_rejection
from oopz.remote_fetch import SafeRemoteFetcher

logger = get_logger("SenderGateway")

MAX_IMAGE_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _attachment(value: Any) -> Attachment:
    if isinstance(value, Attachment):
        return value
    if isinstance(value, dict):
        return Attachment.parse(value)
    raise TypeError(f"不支持的附件类型: {type(value).__name__}")


class SenderGateway:
    """直接调用 SDK 服务，提供应用的消息与媒体操作。"""

    def __init__(self, bot: OopzBot, *, proxy_value=None, rebuild_credentials=None):
        self.bot = bot
        self._proxy_value = proxy_value
        self.rebuild_credentials = rebuild_credentials
        self._auto_recall_scheduler: Any = None
        self._role_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.voice_channels: Container[str] = frozenset()

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
    ) -> MessageSendResult:
        area = self._default_area(area)
        channel = self._default_channel(channel)
        version = kwargs.get("version") or ("v2" if channel in self.voice_channels else "v1")
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
                version=str(version),
            )
        except OopzError as exc:
            if is_sensitive_rejection(str(exc)):
                raise SensitiveContentError(str(exc)) from exc
            raise

        if auto_recall is not False:
            await self._schedule_auto_recall(result.message_id, area, channel, result.timestamp)
        return result


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


    async def _pick_channel_group(
        self,
        area: str,
        preferred_channel: str | None = None,
    ) -> str | None:
        groups = await self.bot.areas.get_area_channels(area)
        preferred_channel = str(preferred_channel or "").strip()
        fallback = None
        for group in groups:
            group_id = group.group_id.strip()
            if not group_id:
                continue
            fallback = fallback or group_id
            if preferred_channel and any(
                channel.channel_id == preferred_channel
                for channel in group.channels
            ):
                return group_id
        return fallback


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
        created = await self.bot.channels.create_channel(area, channel_name, group_id=group_id, channel_type="text")
        channel = created.channel_id
        try:
            updated = await self.bot.channels.update_channel(
                area, channel, secret=True, access_control_enabled=True,
                accessible_roles=[], accessible_members=[target_uid, self.bot.config.person_uid],
            )
            if not updated.ok:
                raise RuntimeError(updated.message or "设置私密频道失败")
        except Exception:
            try:
                deleted = await self.bot.channels.delete_channel(area, channel)
                if not deleted.ok:
                    raise RuntimeError(deleted.message or "删除频道被拒绝")
            except Exception:
                logger.warning("清理未完成配置的临时频道失败 channel=%s", channel, exc_info=True)
            raise
        return {"status": True, "channel": channel, "group": group_id, "name": channel_name}


    async def get_area_invite_detail(self, code: str) -> dict[str, Any]:
        try:
            code = str(code or "").strip()
            if not code:
                raise ValueError("code is required for get_area_invite_detail")
            return await self.bot.rest.transport.request_data(
                "GET", "/invite/v1/codeDetail", params={"code": code},
            )
        except Exception as exc:
            return {"error": str(exc)}


    async def edit_user_role(
        self,
        target_uid: str,
        role_id: int,
        add: bool,
        area: str | None = None,
    ) -> OperationResult:
        """串行修改同一用户的身份组，成功后刷新成员展示缓存。"""
        area = self._default_area(area)
        key = (area, target_uid)
        lock = self._role_locks.setdefault(key, asyncio.Lock())
        async with lock:
            result = await self.bot.areas.edit_user_role(area, target_uid, role_id, add)
            if result.ok:
                invalidate_members_cache(self.bot, area)
        return result

    async def search_area_members(self, area: str | None = None, keyword: str = "") -> list[AreaMemberInfo]:
        area = self._default_area(area)
        needle = str(keyword or "").strip().lower()
        members = await self.bot.areas.get_all_area_members(area, page_size=100)
        if not needle:
            return members[:50]
        profiles = {person.uid: person for person in await self.bot.person.get_person_infos_batch([item.uid for item in members])}
        output = []
        for member in members:
            profile = profiles.get(member.uid)
            name = profile.name if profile else ""
            if needle in member.uid.lower() or needle in name.lower():
                output.append(member)
            if len(output) >= 50:
                break
        return output


    async def upload_image_from_url(self, image_url: str) -> ImageAttachment:
        started_at = time.monotonic()
        image_bytes, _content_type = await asyncio.to_thread(
            SafeRemoteFetcher(proxy_value=self._proxy_value).fetch,
            image_url,
            max_bytes=MAX_IMAGE_DOWNLOAD_BYTES,
            timeout=(10, 60),
        )
        downloaded_at = time.monotonic()
        attachment = await self._upload_image_bytes(image_bytes)
        uploaded_at = time.monotonic()
        logger.info(
            "URL 图片上传完成: %dx%d, %.1f KiB, 下载 %.2fs, 图片处理及上传 %.2fs, 总计 %.2fs",
            attachment.width, attachment.height, len(image_bytes) / 1024,
            downloaded_at - started_at, uploaded_at - downloaded_at, uploaded_at - started_at,
        )
        return attachment

    @staticmethod
    def _image_metadata(data: bytes) -> tuple[int, int, str]:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height), str(image.format or "webp")

    async def _upload_image_bytes(self, image_bytes: bytes, filename: str = "") -> ImageAttachment:
        """上传图片并补齐原生图片消息需要的尺寸和 hash。"""
        width, height, image_format = await asyncio.to_thread(self._image_metadata, image_bytes)
        ext = os.path.splitext(filename)[1] or "." + image_format.lower()
        uploaded = await self.bot.media.upload_bytes(
            image_bytes, file_type="IMAGE", ext=ext, display_name=filename,
        )
        return ImageAttachment.from_manually(
            file_key=uploaded.file_key,
            url=uploaded.url,
            width=width,
            height=height,
            file_size=len(image_bytes),
            hash=hashlib.md5(image_bytes).hexdigest(),
            animated=uploaded.animated,
            display_name=uploaded.display_name,
        )

    async def _send_native_image(
        self, image: ImageAttachment, *, area: str = "", channel: str = "",
        target: str = "", style_tags: list | None = None,
    ) -> MessageSendResult:
        """发送按图片比例展示的原生图片消息。"""
        if target:
            session = await self.bot.messages.open_private_session(target)
            channel = session.session_id
            endpoint = "/rtc/v1/im/v1/sendImage"
        else:
            if not area.strip() or not channel.strip():
                raise ValueError("area and channel are required for a channel image")
            endpoint = "/rtc/v1/gim/v1/sendImage"
        body = {
            "area": area, "channel": channel, "target": target,
            "clientMessageId": self.bot.rest.signer.client_message_id(),
            "timestamp": self.bot.rest.signer.timestamp_us(),
            "rawImage": image.to_payload(),
            "displayName": image.display_name,
            "animated": image.animated,
            "styleTags": style_tags or [],
            "isMentionAll": False, "mentionList": [],
        }
        result = await self.bot.rest.transport.request_data("POST", endpoint, body=body)
        return MessageSendResult.from_api(result)

    async def upload_and_send_image(self, file_path: str, text: str = "", **kwargs: Any) -> MessageSendResult:
        image_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
        attachment = await self._upload_image_bytes(image_bytes, os.path.basename(file_path))
        if not text:
            area = self._default_area(kwargs.get("area"))
            channel = self._default_channel(kwargs.get("channel"))
            result = await self._send_native_image(
                attachment, area=area, channel=channel,
                style_tags=self._style_tags(area, kwargs.get("styleTags")),
            )
            if kwargs.get("auto_recall") is not False:
                await self._schedule_auto_recall(result.message_id, area, channel, result.timestamp)
            return result
        image_text = ImageSegment.from_attachment(attachment).to_message_text() + text
        return await self.send_message(image_text, attachments=[attachment], **kwargs)

    async def upload_and_send_private_image(self, target: str, file_path: str, text: str = "") -> MessageSendResult:
        image_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
        attachment = await self._upload_image_bytes(image_bytes, os.path.basename(file_path))
        if not text:
            return await self._send_native_image(attachment, target=str(target).strip())
        image_text = ImageSegment.from_attachment(attachment).to_message_text() + text
        return await self.bot.messages.send_private_message(image_text, attachments=[attachment], target=target)
