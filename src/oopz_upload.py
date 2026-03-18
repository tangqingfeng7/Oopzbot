"""Oopz 文件上传 Mixin — 图片、音频上传与发送。"""

from __future__ import annotations

import hashlib
import io
import os
from typing import TYPE_CHECKING, Optional

import requests
from PIL import Image

from config import OOPZ_CONFIG
from logger_config import get_logger

if TYPE_CHECKING:
    from oopz_sender import OopzSender

logger = get_logger("OopzUpload")

UPLOAD_PUT_TIMEOUT = (10, 60)


def get_image_info(file_path: str) -> tuple[int, int, int]:
    """获取本地图片的宽、高、文件大小"""
    with Image.open(file_path) as img:
        width, height = img.size
    file_size = os.path.getsize(file_path)
    return width, height, file_size


class UploadMixin:
    """Oopz 文件上传 Mixin — 图片、音频上传与发送。"""

    def upload_file(self, file_path: str, file_type: str = "IMAGE", ext: str = ".webp") -> dict:
        """上传本地文件，返回 { fileKey, url }"""
        url_path = "/rtc/v1/cos/v1/signedUploadUrl"
        body = {"type": file_type, "ext": ext}

        resp = self._put(url_path, body)
        if resp.status_code != 200:
            raise Exception(f"获取上传 URL 失败: {resp.text}")

        data = resp.json()["data"]
        upload_url = data["signedUrl"]
        file_key = data["file"]
        cdn_url = data["url"]

        with open(file_path, "rb") as f:
            put_resp = requests.put(
                upload_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=UPLOAD_PUT_TIMEOUT,
            )
        if put_resp.status_code not in (200, 201):
            raise Exception(f"文件上传失败: {put_resp.text}")

        return {"fileKey": file_key, "url": cdn_url}

    def upload_file_from_url(self, image_url: str) -> dict:
        """从网络 URL 下载图片并上传到 Oopz（不落地磁盘）"""
        try:
            resp = requests.get(image_url, stream=True, timeout=15)
            resp.raise_for_status()
            image_bytes = resp.content

            img = Image.open(io.BytesIO(image_bytes))
            width, height = img.size
            file_size = len(image_bytes)
            ext = "." + (img.format or "webp").lower()
            md5 = hashlib.md5(image_bytes).hexdigest()

            url_path = "/rtc/v1/cos/v1/signedUploadUrl"
            body = {"type": "IMAGE", "ext": ext}
            resp2 = self._put(url_path, body)
            resp2.raise_for_status()
            data = resp2.json()["data"]

            signed_url = data["signedUrl"]
            file_key = data["file"]
            cdn_url = data["url"]

            put_resp = requests.put(
                signed_url,
                data=image_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=UPLOAD_PUT_TIMEOUT,
            )
            put_resp.raise_for_status()

            attachment = {
                "fileKey": file_key,
                "url": cdn_url,
                "width": width,
                "height": height,
                "fileSize": file_size,
                "hash": md5,
                "animated": False,
                "displayName": "",
                "attachmentType": "IMAGE",
            }
            return {"code": "success", "message": "上传成功", "data": attachment}

        except Exception as e:
            logger.error(f"从 URL 上传失败: {e}")
            return {"code": "error", "message": str(e), "data": None}

    def upload_audio_from_url(
        self, audio_url: str, filename: str = "music.mp3", duration_ms: int = 0
    ) -> dict:
        """从网络 URL 下载音频并上传到 Oopz（AUDIO 类型）"""
        try:
            resp = requests.get(audio_url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/140.0.0.0 Safari/537.36",
                "Referer": "https://music.163.com/",
            })
            resp.raise_for_status()
            audio_bytes = resp.content
            file_size = len(audio_bytes)

            content_type = resp.headers.get("Content-Type", "")
            if "mp4" in content_type or "m4a" in content_type:
                ext = ".m4a"
            elif "flac" in content_type:
                ext = ".flac"
            else:
                ext = ".mp3"

            md5 = hashlib.md5(audio_bytes).hexdigest()

            url_path = "/rtc/v1/cos/v1/signedUploadUrl"
            body = {"type": "AUDIO", "ext": ext}
            resp2 = self._put(url_path, body)
            resp2.raise_for_status()
            data = resp2.json()["data"]

            signed_url = data["signedUrl"]
            file_key = data["file"]
            cdn_url = data["url"]

            put_resp = requests.put(
                signed_url,
                data=audio_bytes,
                headers={"Content-Type": "application/octet-stream"},
                timeout=UPLOAD_PUT_TIMEOUT,
            )
            put_resp.raise_for_status()

            base_name = os.path.splitext(filename or "")[0] or "music"
            display_name = base_name + ext
            duration_sec = duration_ms // 1000 if duration_ms else 0

            attachment = {
                "fileKey": file_key,
                "url": cdn_url,
                "fileSize": file_size,
                "hash": md5,
                "animated": False,
                "displayName": display_name,
                "attachmentType": "AUDIO",
                "duration": duration_sec,
            }
            logger.info(f"音频上传成功: {display_name} ({file_size} bytes, {duration_sec}s)")
            return {"code": "success", "data": attachment}

        except Exception as e:
            logger.error(f"音频上传失败: {e}")
            return {"code": "error", "message": str(e), "data": None}

    def upload_and_send_image(self, file_path: str, text: str = "", **kwargs) -> requests.Response:
        """上传本地图片并作为消息发送"""
        width, height, file_size = get_image_info(file_path)

        url_path = "/rtc/v1/cos/v1/signedUploadUrl"
        body = {"type": "IMAGE", "ext": os.path.splitext(file_path)[1]}
        resp = self._put(url_path, body)
        resp.raise_for_status()
        data = resp.json()["data"]

        signed_url = data["signedUrl"]
        file_key = data["file"]
        cdn_url = data["url"]

        with open(file_path, "rb") as f:
            requests.put(
                signed_url,
                data=f,
                headers={"Content-Type": "application/octet-stream"},
                timeout=UPLOAD_PUT_TIMEOUT,
            ).raise_for_status()

        attachments = [{
            "fileKey": file_key,
            "url": cdn_url,
            "width": width,
            "height": height,
            "fileSize": file_size,
            "hash": "",
            "animated": False,
            "displayName": "",
            "attachmentType": "IMAGE",
        }]

        msg_text = f"![IMAGEw{width}h{height}]({file_key})"
        if text:
            msg_text += f"\n{text}"

        return self.send_message(text=msg_text, attachments=attachments, **kwargs)

    def upload_and_send_private_image(self, target: str, file_path: str, text: str = "") -> dict:
        """上传本地图片并通过私信发送。"""
        width, height, file_size = get_image_info(file_path)

        url_path = "/rtc/v1/cos/v1/signedUploadUrl"
        body = {"type": "IMAGE", "ext": os.path.splitext(file_path)[1]}
        try:
            resp = self._put(url_path, body)
            resp.raise_for_status()
            data = resp.json()["data"]
            signed_url = data["signedUrl"]
            file_key = data["file"]
            cdn_url = data["url"]

            with open(file_path, "rb") as f:
                requests.put(
                    signed_url,
                    data=f,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=UPLOAD_PUT_TIMEOUT,
                ).raise_for_status()
        except Exception as e:
            logger.error(f"上传私信图片失败: {e}")
            return {"error": str(e)}

        attachment = {
            "fileKey": file_key,
            "url": cdn_url,
            "width": width,
            "height": height,
            "fileSize": file_size,
            "hash": "",
            "animated": False,
            "displayName": "",
            "attachmentType": "IMAGE",
        }
        msg_text = f"![IMAGEw{width}h{height}]({file_key})"
        if text:
            msg_text += f"\n{text}"
        result = self.send_private_message(target, msg_text, attachments=[attachment])
        if "error" in result:
            logger.error("私信图片发送失败: %s", result.get("error"))
            return result
        return {"status": True, "channel": result.get("channel"), "attachment": attachment}
