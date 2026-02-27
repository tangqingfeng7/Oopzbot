"""
Oopz 消息发送器
负责 HTTP API 通信：RSA 签名、发送消息、上传文件
"""

import io
import os
import hashlib
import base64
import uuid
import time
import json
import random
import threading
from typing import Dict, Optional

import requests
from PIL import Image
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

from config import OOPZ_CONFIG, DEFAULT_HEADERS
try:
    from config import AUTO_RECALL_CONFIG
except ImportError:
    AUTO_RECALL_CONFIG = {"enabled": False}
from logger_config import get_logger

logger = get_logger("OopzSender")


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------

def get_image_info(file_path: str):
    """获取本地图片的宽、高、文件大小"""
    with Image.open(file_path) as img:
        width, height = img.size
    file_size = os.path.getsize(file_path)
    return width, height, file_size


class ClientMessageIdGenerator:
    """生成 15 位客户端消息 ID（模拟真实格式）"""

    def generate(self) -> str:
        timestamp_us = int(time.time() * 1_000_000)
        base_id = timestamp_us % 10_000_000_000_000
        suffix = random.randint(10, 99)
        return str(base_id * 100 + suffix)


# ---------------------------------------------------------------------------
# RSA 签名器
# ---------------------------------------------------------------------------

class Signer:
    """Oopz API 请求签名器"""

    def __init__(self):
        self.private_key = self._load_key()
        self.id_gen = ClientMessageIdGenerator()

    # -- 密钥加载 --

    @staticmethod
    def _load_key():
        try:
            from private_key import get_private_key
            return get_private_key()
        except (ImportError, Exception):
            logger.warning("private_key.py 不可用，使用临时生成的测试密钥")
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend(),
            )

    # -- ID / 时间戳 --

    @staticmethod
    def request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def timestamp_ms() -> str:
        return str(int(time.time() * 1000))

    @staticmethod
    def timestamp_us() -> str:
        return str(int(time.time() * 1_000_000))

    def client_message_id(self) -> str:
        return self.id_gen.generate()

    # -- 签名 --

    def sign(self, data: str) -> str:
        """RSA PKCS1v15 + SHA256 签名，返回 Base64"""
        sig = self.private_key.sign(
            data.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode("utf-8")

    def oopz_headers(self, url_path: str, body_str: str) -> Dict[str, str]:
        """
        构造 Oopz 专用签名请求头。
        签名流程: MD5(url_path + body_json) + timestamp → RSA 签名
        """
        ts = self.timestamp_ms()
        md5 = hashlib.md5((url_path + body_str).encode("utf-8")).hexdigest()
        signature = self.sign(md5 + ts)

        return {
            "Oopz-Sign": signature,
            "Oopz-Request-Id": self.request_id(),
            "Oopz-Time": ts,
            "Oopz-App-Version-Number": OOPZ_CONFIG["app_version"],
            "Oopz-Channel": OOPZ_CONFIG["channel"],
            "Oopz-Device-Id": OOPZ_CONFIG["device_id"],
            "Oopz-Platform": OOPZ_CONFIG["platform"],
            "Oopz-Web": str(OOPZ_CONFIG["web"]).lower(),
            "Oopz-Person": OOPZ_CONFIG["person_uid"],
            "Oopz-Signature": OOPZ_CONFIG["jwt_token"],
        }


# ---------------------------------------------------------------------------
# 消息发送器
# ---------------------------------------------------------------------------

class OopzSender:
    """Oopz 平台消息发送 & 文件上传"""

    def __init__(self):
        self.signer = Signer()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        # 代理：留空/不设=使用系统代理(HTTP_PROXY/HTTPS_PROXY)；False 或 "direct"=直连；或 "http://ip:port"
        proxy_cfg = OOPZ_CONFIG.get("proxy")
        if proxy_cfg is False or (isinstance(proxy_cfg, str) and proxy_cfg.strip().lower() == "direct"):
            self.session.trust_env = False
            logger.info("OopzSender: 已禁用代理（直连）")
        elif isinstance(proxy_cfg, str) and proxy_cfg.strip():
            self.session.proxies = {"http": proxy_cfg.strip(), "https": proxy_cfg.strip()}
            logger.info(f"OopzSender: 使用代理 {proxy_cfg.strip()}")
        # 否则使用 requests 默认行为（读取环境变量）

        logger.info("OopzSender 已初始化")
        logger.info(f"  用户: {OOPZ_CONFIG['person_uid']}")
        logger.info(f"  设备: {OOPZ_CONFIG['device_id']}")

    # ---- 内部 ----

    def _post(self, url_path: str, body: dict) -> requests.Response:
        body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = {**self.session.headers, **self.signer.oopz_headers(url_path, body_str)}
        url = OOPZ_CONFIG["base_url"] + url_path
        return self.session.post(url, headers=headers, data=body_str.encode("utf-8"))

    def _put(self, url_path: str, body: dict) -> requests.Response:
        body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        headers = {**self.session.headers, **self.signer.oopz_headers(url_path, body_str)}
        url = OOPZ_CONFIG["base_url"] + url_path
        return self.session.put(url, headers=headers, data=body_str.encode("utf-8"))

    def _delete(self, url_path: str, body: Optional[dict] = None) -> requests.Response:
        """DELETE 请求，部分撤回接口可能用 DELETE 方法"""
        body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else "{}"
        headers = {**self.session.headers, **self.signer.oopz_headers(url_path, body_str)}
        url = OOPZ_CONFIG["base_url"] + url_path
        return self.session.request("DELETE", url, headers=headers, data=body_str.encode("utf-8") if body else None)

    def _get(self, url_path: str, params: Optional[dict] = None, use_api: bool = False) -> requests.Response:
        """
        GET 请求（签名包含查询参数），支持自动回退。

        优先使用指定的 base_url；若返回 404 或连接失败，自动尝试另一个。
        """
        if params:
            from urllib.parse import urlencode
            query_string = urlencode(params)
            sign_path = url_path + "?" + query_string
        else:
            sign_path = url_path

        bases = [OOPZ_CONFIG["api_url"], OOPZ_CONFIG["base_url"]] if use_api \
            else [OOPZ_CONFIG["base_url"], OOPZ_CONFIG["api_url"]]

        last_error = None
        resp = None
        for base in bases:
            try:
                headers = {**self.session.headers, **self.signer.oopz_headers(sign_path, "")}
                url = base + url_path
                resp = self.session.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code == 404:
                    logger.debug(f"GET {url} → 404，尝试回退")
                    continue
                return resp
            except Exception as e:
                logger.debug(f"GET {base}{url_path} 连接失败: {e}，尝试回退")
                last_error = e
                continue

        if resp is not None:
            return resp
        if last_error:
            raise last_error
        raise RuntimeError("GET 请求未得到任何响应")

    # ---- 发送消息 ----

    def send_message(
        self,
        text: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        auto_recall: Optional[bool] = None,
        **kwargs,
    ) -> requests.Response:
        """
        发送聊天消息。

        Args:
            text:    消息文本
            area:    区域 ID（默认取配置）
            channel: 频道 ID（默认取配置）
            auto_recall: 是否自动撤回。None=按配置决定，False=不撤回，True=强制撤回
            **kwargs: attachments, mentionList, referenceMessageId, styleTags 等。styleTags 默认由配置 use_announcement_style 决定（公告样式=["IMPORTANT"]）
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        default_style = ["IMPORTANT"] if OOPZ_CONFIG.get("use_announcement_style", True) else []

        body = {
            "area": area,
            "channel": channel,
            "target": kwargs.get("target", ""),
            "clientMessageId": self.signer.client_message_id(),
            "timestamp": self.signer.timestamp_us(),
            "isMentionAll": kwargs.get("isMentionAll", False),
            "mentionList": kwargs.get("mentionList", []),
            "styleTags": kwargs.get("styleTags", default_style),
            "referenceMessageId": kwargs.get("referenceMessageId", None),
            "animated": kwargs.get("animated", False),
            "displayName": kwargs.get("displayName", ""),
            "duration": kwargs.get("duration", 0),
            "text": text,
            "attachments": kwargs.get("attachments", []),
        }

        url_path = "/im/session/v1/sendGimMessage"
        logger.info(f"发送消息: {text[:80]}{'...' if len(text) > 80 else ''}")

        try:
            resp = self._post(url_path, body)
            logger.info(f"响应状态: {resp.status_code}")
            if resp.text:
                logger.debug(f"响应内容: {resp.text[:200]}")
            if auto_recall is not False:
                self._schedule_auto_recall(resp, area, channel)
            return resp
        except Exception as e:
            logger.error(f"发送失败: {e}")
            raise

    def send_to_default(self, text: str, **kwargs) -> requests.Response:
        """发送到默认频道"""
        return self.send_message(text, **kwargs)

    # ---- 自动撤回 ----

    def _schedule_auto_recall(self, resp: requests.Response, area: str, channel: str):
        """根据配置，在延迟后自动撤回刚发送的消息。"""
        if not AUTO_RECALL_CONFIG.get("enabled"):
            return
        delay = AUTO_RECALL_CONFIG.get("delay", 30)
        if delay <= 0:
            return

        try:
            result = resp.json()
            data = result.get("data", {})
            msg_id = None
            if isinstance(data, dict):
                msg_id = data.get("messageId")
            if not msg_id:
                msg_id = result.get("messageId")
            if not msg_id:
                logger.debug("自动撤回: 无法从响应中提取 messageId，跳过")
                return
            msg_id = str(msg_id)

            timer = threading.Timer(
                delay, self._do_auto_recall, args=[msg_id, area, channel],
            )
            timer.daemon = True
            timer.start()
            logger.debug(f"已安排 {delay}s 后自动撤回: {msg_id[:16]}...")
        except Exception as e:
            logger.debug(f"安排自动撤回失败: {e}")

    def _do_auto_recall(self, message_id: str, area: str, channel: str):
        """定时器回调：执行自动撤回。"""
        try:
            result = self.recall_message(message_id, area=area, channel=channel)
            if "error" in result:
                logger.warning(f"自动撤回失败: {result['error']} (msgId={message_id[:16]}...)")
            else:
                logger.info(f"自动撤回成功: {message_id[:16]}...")
        except Exception as e:
            logger.error(f"自动撤回异常: {e}")

    # ---- 文件上传 ----

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
            put_resp = requests.put(upload_url, data=f, headers={"Content-Type": "application/octet-stream"})
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

            put_resp = requests.put(signed_url, data=image_bytes, headers={"Content-Type": "application/octet-stream"})
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

    def upload_audio_from_url(self, audio_url: str, filename: str = "music.mp3", duration_ms: int = 0) -> dict:
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

            put_resp = requests.put(signed_url, data=audio_bytes, headers={"Content-Type": "application/octet-stream"})
            put_resp.raise_for_status()

            display_name = filename + ext
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
            requests.put(signed_url, data=f, headers={"Content-Type": "application/octet-stream"}).raise_for_status()

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

    # ---- 批量 ----

    def send_multiple(self, messages: list, interval: float = 1.0) -> list:
        """批量发送消息"""
        results = []
        for i, msg in enumerate(messages, 1):
            try:
                resp = self.send_to_default(msg)
                results.append({"message": msg, "status_code": resp.status_code, "success": resp.status_code == 200})
                if i < len(messages):
                    time.sleep(interval)
            except Exception as e:
                results.append({"message": msg, "status_code": None, "success": False, "error": str(e)})
        return results

    # ---- 域成员查询 ----

    def get_area_members(self, area: Optional[str] = None, offset_start: int = 0, offset_end: int = 49, quiet: bool = False) -> dict:
        """
        获取域内成员列表及在线状态。

        API: GET /area/v3/members?area={area}&offsetStart={start}&offsetEnd={end}

        Args:
            quiet: 为 True 时不向控制台打成功日志（用于轮询等后台调用）。

        Returns:
            {"members": [...], "userCount": int, "onlineCount": int, ...}
            或 {"error": "..."} 表示失败
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/members"
        params = {"area": area, "offsetStart": str(offset_start), "offsetEnd": str(offset_end)}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取域成员失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取域成员失败: {msg}")
                return {"error": msg}

            data = result.get("data", {})
            members = data.get("members", [])
            online = sum(1 for m in members if m.get("online") == 1)
            total = len(members)
            if not quiet:
                logger.info(f"获取域成员成功: {total} 人, 在线 {online} 人")
            data["onlineCount"] = online
            data["userCount"] = total
            return data
        except Exception as e:
            logger.error(f"获取域成员异常: {e}")
            return {"error": str(e)}

    # ---- 频道列表 ----

    def get_area_channels(self, area: Optional[str] = None, quiet: bool = False) -> list:
        """
        获取域内完整频道列表（含分组）。

        API: GET /client/v1/area/v1/detail/v1/channels?area={area}

        Args:
            quiet: 为 True 时不打成功日志（用于轮询等后台调用）。

        Returns:
            频道分组列表，每组含 channels 子列表。失败时返回空列表。
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/detail/v1/channels"
        params = {"area": area}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取频道列表失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取频道列表失败: {result.get('message') or result.get('error')}")
                return []
            groups = result.get("data") or []
            if not quiet:
                total = sum(len(g.get("channels") or []) for g in groups)
                logger.info(f"获取频道列表: {total} 个频道, {len(groups)} 个分组")
            return groups
        except Exception as e:
            logger.error(f"获取频道列表异常: {e}")
            return []

    # ---- 已加入的域列表 ----

    def get_joined_areas(self, quiet: bool = False) -> list:
        """
        获取当前用户已加入（订阅）的域列表。

        API: GET /userSubscribeArea/v1/list

        Args:
            quiet: 为 True 时不打成功日志（用于轮询等后台调用）。

        Returns:
            域信息列表，每个元素包含 id / code / name / avatar / owner 等字段。
            失败时返回空列表。
        """
        url_path = "/userSubscribeArea/v1/list"
        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                logger.error(f"获取已加入域列表失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取已加入域列表失败: {result.get('message') or result.get('error')}")
                return []
            areas = result.get("data", [])
            if not quiet:
                logger.info(f"获取已加入域列表: {len(areas)} 个域")
                for a in areas:
                    logger.info(f"  域: {a.get('name')} (ID={a.get('id')}, code={a.get('code')})")
            return areas
        except Exception as e:
            logger.error(f"获取已加入域列表异常: {e}")
            return []

    # ---- 域详情（含频道） ----

    def get_area_info(self, area: Optional[str] = None) -> dict:
        """
        获取域详细信息（含角色列表、主页频道 ID/名称等）。

        API: GET /area/v2/info?area={area}

        Returns:
            域信息字典，或 {"error": "..."} 表示失败。
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v2/info"
        params = {"area": area}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取域详情失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or result.get("error") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取域详情异常: {e}")
            return {"error": str(e)}

    # ---- 启动时自动填充域/频道名称 ----

    def populate_names(self):
        """
        从 API 获取已加入的域列表及各域频道列表，
        自动填充 NameResolver 中的域名称和频道名称。
        """
        from name_resolver import get_resolver
        resolver = get_resolver()

        areas = self.get_joined_areas()
        for a in areas:
            area_id = a.get("id", "")
            area_name = a.get("name", "")
            if area_id and area_name:
                resolver.set_area(area_id, area_name)

            groups = self.get_area_channels(area_id) or []
            for group in groups:
                for ch in (group.get("channels") or []):
                    ch_id = ch.get("id", "")
                    ch_name = ch.get("name", "")
                    if ch_id and ch_name:
                        resolver.set_channel(ch_id, ch_name)

        stats = resolver.get_stats()
        logger.info(
            f"名称自动填充完成: "
            f"{stats['areas_named']} 个域, "
            f"{stats['channels_named']} 个频道"
        )

    # ---- 个人详细信息 ----

    def get_person_detail(self, uid: Optional[str] = None) -> dict:
        """
        通过 personInfos 接口获取用户信息（可查询任意用户）。

        Args:
            uid: 用户 UID（默认取当前 Bot 自身的 UID）

        Returns:
            包含用户信息的字典，或 {"error": "..."} 表示失败
        """
        uid = uid or OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/person/v1/personInfos"
        body = {"persons": [uid], "commonIds": []}

        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"获取个人信息失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取个人信息失败: {msg}")
                return {"error": msg}

            data_list = result.get("data", [])
            if not data_list:
                return {"error": "未找到该用户"}

            person = data_list[0]
            logger.info(f"获取个人信息成功: {person.get('name', '未知')}")
            return person
        except Exception as e:
            logger.error(f"获取个人信息异常: {e}")
            return {"error": str(e)}

    # ---- 他人详细资料 ----

    def get_person_detail_full(self, uid: str) -> dict:
        """
        获取他人完整详细资料（比 personInfos 更详细，含 VIP、IP 属地等）。

        API: GET /client/v1/person/v1/personDetail?uid={uid}
        """
        url_path = "/client/v1/person/v1/personDetail"
        params = {"uid": uid}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取他人详细资料异常: {e}")
            return {"error": str(e)}

    # ---- 自身详细资料 ----

    def get_self_detail(self) -> dict:
        """
        获取当前登录用户的完整详细资料。

        API: GET /client/v1/person/v2/selfDetail?uid={uid}
        """
        uid = OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/person/v2/selfDetail"
        params = {"uid": uid}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取自身详细资料异常: {e}")
            return {"error": str(e)}

    # ---- 用户等级信息 ----

    def get_level_info(self) -> dict:
        """
        获取当前用户等级、积分信息。

        API: GET /user_points/v1/level_info

        Returns:
            {"currentLevel": int, "nextLevel": int, "nextLevelDistance": int, ...}
        """
        url_path = "/user_points/v1/level_info"
        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取等级信息异常: {e}")
            return {"error": str(e)}

    # ---- 用户在域内的角色 / 禁言状态 ----

    def get_user_area_detail(self, target: str, area: Optional[str] = None) -> dict:
        """
        获取指定用户在域内的角色列表和禁言/禁麦状态。

        API: GET /area/v3/userDetail?area={area}&target={uid}

        Returns:
            {"list": [{"roleID":..., "name":...}], "disableTextTo":..., "disableVoiceTo":..., "higherUid":...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/userDetail"
        params = {"area": area, "target": target}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"获取用户域内详情异常: {e}")
            return {"error": str(e)}

    # ---- 可分配的角色列表 ----

    def get_assignable_roles(self, target: str, area: Optional[str] = None) -> list:
        """
        获取当前用户可以分配给目标用户的角色列表。

        API: GET /area/v3/role/canGiveList?area={area}&target={uid}

        Returns:
            [{"roleID": int, "name": str, "owned": bool, "sort": int}, ...]
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/role/canGiveList"
        params = {"area": area, "target": target}
        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取可分配角色失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                return []
            data = result.get("data")
            if not isinstance(data, dict):
                return []
            return data.get("roles", [])
        except Exception as e:
            logger.error(f"获取可分配角色异常: {e}")
            return []

    # ---- 给/取消身份组 ----

    def edit_user_role(
        self,
        target_uid: str,
        role_id: int,
        add: bool,
        area: Optional[str] = None,
    ) -> dict:
        """
        给目标用户添加或取消指定身份组。

        真实 API（与 Web 端一致）:
        POST /area/v3/role/editUserRole
        Body: {"area": area, "target": target_uid, "targetRoleIDs": [id1, id2, ...]}
        语义：将目标用户在该域内的身份组设置为 targetRoleIDs 列表（全量覆盖）。

        Args:
            target_uid: 目标用户 UID
            role_id: 身份组 ID（来自 canGiveList 或 userDetail.list）
            add: True=给身份组，False=取消身份组
            area: 域 ID，默认取配置

        Returns:
            {"status": True, "message": "..."} 或 {"error": "..."}
        """
        area = area or OOPZ_CONFIG["default_area"]
        detail = self.get_user_area_detail(target_uid, area=area)
        if "error" in detail:
            return {"error": detail["error"]}
        current_list = detail.get("list") or []
        current_ids = [int(r["roleID"]) for r in current_list if r.get("roleID") is not None]
        role_id = int(role_id)
        if add:
            if role_id not in current_ids:
                current_ids.append(role_id)
        else:
            current_ids = [x for x in current_ids if x != role_id]
        url_path = "/area/v3/role/editUserRole"
        body = {"area": area, "target": target_uid, "targetRoleIDs": current_ids}
        try:
            resp = self._post(url_path, body)
            raw = resp.text or ""
            logger.info(f"editUserRole POST {url_path} add={add} -> {resp.status_code}, body: {raw[:200]}")
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:150]}" if raw else "")}
            result = resp.json()
            if result.get("status") is True:
                return {"status": True, "message": result.get("message") or ("已给身份组" if add else "已取消身份组")}
            return {"error": result.get("message") or result.get("error") or str(result)}
        except Exception as e:
            logger.error(f"editUserRole 异常: {e}")
            return {"error": str(e)}

    # ---- 搜索域成员 ----

    def search_area_members(self, area: Optional[str] = None, keyword: str = "") -> list:
        """
        搜索域内成员（含角色信息、加入时间）。

        API: POST /area/v3/search/areaSettingMembers

        Returns:
            [{"uid": str, "roleInfos": [...], "enterTime": int}, ...]
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/search/areaSettingMembers"
        body = {"area": area, "name": keyword, "offset": 0, "limit": 50}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"搜索域成员失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                return []
            return result.get("data", {}).get("members", [])
        except Exception as e:
            logger.error(f"搜索域成员异常: {e}")
            return []

    # ---- 各语音频道在线成员 ----

    def get_voice_channel_members(self, area: Optional[str] = None) -> dict:
        """
        获取域内各语音频道的在线成员列表。

        API: POST /area/v3/channel/membersByChannels

        Returns:
            {"channelId1": [uid1, uid2, ...], "channelId2": [...], ...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        groups = self.get_area_channels(area)
        voice_ids = []
        for g in groups:
            for ch in g.get("channels", []):
                if ch.get("type") == "VOICE":
                    voice_ids.append(ch["id"])
        if not voice_ids:
            return {}

        url_path = "/area/v3/channel/membersByChannels"
        body = {"area": area, "channels": voice_ids}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                logger.error(f"获取语音频道成员失败: HTTP {resp.status_code}")
                return {}
            result = resp.json()
            if not result.get("status"):
                return {}
            return result.get("data", {}).get("channelMembers", {})
        except Exception as e:
            logger.error(f"获取语音频道成员异常: {e}")
            return {}

    def get_voice_channel_for_user(self, user_uid: str, area: Optional[str] = None) -> Optional[str]:
        """
        获取用户当前所在的语音频道 ID。
        若用户不在任何语音频道，返回 None。
        """
        members = self.get_voice_channel_members(area=area)
        for ch_id, ch_members in members.items():
            if not ch_members:
                continue
            for m in ch_members:
                uid = m.get("uid", m.get("id", "")) if isinstance(m, dict) else str(m)
                if uid == user_uid:
                    return ch_id
        return None

    # ---- 进入域 / 进入频道 ----

    def enter_area(self, area: Optional[str] = None, recover: bool = False) -> dict:
        """
        进入指定域（前置步骤，进入语音频道前需先进入域）。

        API: POST /client/v1/area/v1/enter?area={area}&recover={recover}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = f"/client/v1/area/v1/enter?area={area}&recover={str(recover).lower()}"
        body = {"area": area, "recover": recover}
        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or result.get("error") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"进入域异常: {e}")
            return {"error": str(e)}

    def enter_channel(self, channel: Optional[str] = None, area: Optional[str] = None,
                      channel_type: str = "TEXT", from_channel: str = "",
                      from_area: str = "", pid: str = "") -> dict:
        """
        进入指定频道（获取频道配置、语音参数、禁言状态等）。

        API: POST /area/v2/channel/enter

        Args:
            channel:      频道 ID
            area:         域 ID
            channel_type: 频道类型，"TEXT" 或 "VOICE"
            from_channel: 切换语音频道时，来源频道 ID
            from_area:    切换语音频道时，来源域 ID
            pid:          语音频道 Agora uid，服务端据此生成 Token

        Returns:
            {"voiceQuality": str, "voiceDelay": str, "disableTextTo": ..., "roleSort": int, ...}
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        url_path = "/area/v2/channel/enter"

        body: dict = {"type": channel_type, "area": area, "channel": channel}
        if channel_type == "VOICE":
            body.update({
                "fromChannel": from_channel,
                "fromArea": from_area,
                "password": "",
                "sign": 1,
                "pid": pid,
            })

        try:
            resp = self._post(url_path, body)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}"}
            result = resp.json()
            if not result.get("status"):
                return {"error": result.get("message") or "未知错误"}
            return result.get("data", {})
        except Exception as e:
            logger.error(f"进入频道异常: {e}")
            return {"error": str(e)}

    def leave_voice_channel(self, channel: str, area: Optional[str] = None,
                            target: Optional[str] = None) -> dict:
        """
        退出语音频道。

        API: DELETE /client/v1/area/v1/member/v1/removeFromChannel
             ?area={area}&channel={channel}&target={uid}

        Args:
            channel: 语音频道 ID
            area:    域 ID（默认取配置）
            target:  要移出的用户 UID（默认为 Bot 自身）
        """
        area = area or OOPZ_CONFIG["default_area"]
        target = target or OOPZ_CONFIG["person_uid"]
        url_path = "/client/v1/area/v1/member/v1/removeFromChannel"
        query = f"?area={area}&channel={channel}&target={target}"
        full_path = url_path + query

        try:
            body_str = ""
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.delete(url, headers=headers)
        except Exception as e:
            logger.error(f"退出语音频道异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"退出语音频道 DELETE {full_path} -> HTTP {resp.status_code}")

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            logger.info("已退出语音频道")
            return {"status": True, "message": "已退出语音频道"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"退出语音频道失败: {err}")
        return {"error": err}

    # ---- 每日一句 ----

    def get_daily_speech(self) -> dict:
        """
        获取开屏每日一句（名言）。

        Returns:
            {"words": "文本内容", "author": "作者"}
            或 {"error": "..."} 表示失败
        """
        url_path = "/general/v1/speech"

        try:
            resp = self._get(url_path)
            if resp.status_code != 200:
                logger.error(f"获取每日一句失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取每日一句失败: {msg}")
                return {"error": msg}

            data = result["data"]
            logger.info(f"每日一句: {data.get('words', '')[:30]}...")
            return data
        except Exception as e:
            logger.error(f"获取每日一句异常: {e}")
            return {"error": str(e)}

    # ---- 获取频道消息 ----

    def get_channel_messages(
        self,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        size: int = 50,
    ) -> list:
        """
        获取频道最近的消息列表（含 messageId / timestamp / person / content 等）。

        API: GET /im/session/v2/messageBefore?area={area}&channel={channel}&size={size}

        Returns:
            消息列表（按时间倒序，最新在前），失败时返回空列表。
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        url_path = "/im/session/v2/messageBefore"
        params = {"area": area, "channel": channel, "size": str(size)}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取频道消息失败: HTTP {resp.status_code}")
                return []
            result = resp.json()
            if not result.get("status"):
                logger.error(f"获取频道消息失败: {result.get('message') or result.get('error')}")
                return []
            raw_list = result.get("data", {}).get("messages", [])
            messages = []
            for m in raw_list:
                mid = m.get("messageId") or m.get("id")
                if mid is not None:
                    m = {**m, "messageId": str(mid)}
                messages.append(m)
            logger.info(f"获取频道消息: {len(messages)} 条 (area={area[:8]}… channel={channel[:8]}…)")
            return messages
        except Exception as e:
            logger.error(f"获取频道消息异常: {e}")
            return []

    def find_message_timestamp(
        self,
        message_id: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> Optional[str]:
        """
        从频道最近消息中查找指定 messageId 的 timestamp。
        找不到则返回 None。
        """
        messages = self.get_channel_messages(area=area, channel=channel)
        for msg in messages:
            if msg.get("messageId") == message_id:
                return msg.get("timestamp")
        return None

    # ---- 禁言 / 禁麦 ----
    #
    # 禁言时长 intervalId 映射:
    #   禁言(text): 1=60秒, 2=5分钟, 3=1小时, 4=1天, 5=3天, 6=7天
    #   禁麦(voice): 7=60秒, 8=5分钟, 9=1小时, 10=1天, 11=3天, 12=7天

    _TEXT_INTERVALS = {1: "60秒", 2: "5分钟", 3: "1小时", 4: "1天", 5: "3天", 6: "7天"}
    _VOICE_INTERVALS = {7: "60秒", 8: "5分钟", 9: "1小时", 10: "1天", 11: "3天", 12: "7天"}

    @staticmethod
    def _minutes_to_interval_id(minutes: int, voice: bool = False) -> str:
        """将分钟数映射到最接近的 intervalId。"""
        thresholds = [(1, 7), (5, 8), (60, 9), (1440, 10), (4320, 11), (10080, 12)] if voice \
            else [(1, 1), (5, 2), (60, 3), (1440, 4), (4320, 5), (10080, 6)]
        for limit, iid in thresholds:
            if minutes <= limit:
                return str(iid)
        return str(thresholds[-1][1])

    def mute_user(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        duration: int = 10,
    ) -> dict:
        """
        禁言用户（PATCH disableText）。

        Args:
            uid:      目标用户 UID
            area:     区域 ID
            duration: 禁言时长（分钟），自动映射到最近的 intervalId
        """
        area = area or OOPZ_CONFIG["default_area"]
        interval_id = self._minutes_to_interval_id(duration, voice=False)
        url_path = "/client/v1/area/v1/member/v1/disableText"
        query = f"?area={area}&target={uid}&intervalId={interval_id}"
        body = {"area": area, "target": uid, "intervalId": interval_id}
        return self._manage_patch("禁言", url_path, query, body)

    def unmute_user(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict:
        """解除禁言（PATCH recoverText）。"""
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/member/v1/recoverText"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除禁言", url_path, query, body)

    def mute_mic(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        duration: int = 10,
    ) -> dict:
        """禁麦用户（PATCH disableVoice）。"""
        area = area or OOPZ_CONFIG["default_area"]
        interval_id = self._minutes_to_interval_id(duration, voice=True)
        url_path = "/client/v1/area/v1/member/v1/disableVoice"
        query = f"?area={area}&target={uid}&intervalId={interval_id}"
        body = {"area": area, "target": uid, "intervalId": interval_id}
        return self._manage_patch("禁麦", url_path, query, body)

    def unmute_mic(
        self,
        uid: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> dict:
        """解除禁麦（PATCH recoverVoice）。"""
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/member/v1/recoverVoice"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除禁麦", url_path, query, body)

    def remove_from_area(
        self,
        uid: str,
        area: Optional[str] = None,
    ) -> dict:
        """
        将用户移出当前域（踢出域）。

        API: POST /area/v3/remove?area={area}&target={uid}

        Args:
            uid:  目标用户 UID
            area: 域 ID（默认取配置）
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/area/v3/remove"
        query = f"?area={area}&target={uid}"
        full_path = url_path + query
        body = {"area": area, "target": uid}

        try:
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.post(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"移出域请求异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"移出域 POST {full_path} -> HTTP {resp.status_code}, body: {raw[:300]}")

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            logger.info("移出域成功")
            return {"status": True, "message": "已移出域"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"移出域失败: {err}")
        return {"error": err}

    def get_area_blocks(self, area: Optional[str] = None, name: str = "") -> dict:
        """
        获取域内封禁列表。

        API: GET /client/v1/area/v1/areaSettings/v1/blocks?area={area}&name={name}

        Returns:
            {"blocks": [{"uid": "...", ...}, ...]} 或 {"error": "..."}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/areaSettings/v1/blocks"
        params = {"area": area, "name": name}

        try:
            resp = self._get(url_path, params=params)
            if resp.status_code != 200:
                logger.error(f"获取域封禁列表失败: HTTP {resp.status_code}")
                return {"error": f"HTTP {resp.status_code}"}

            result = resp.json()
            if not result.get("status"):
                msg = result.get("message") or result.get("error") or "未知错误"
                logger.error(f"获取域封禁列表失败: {msg}")
                return {"error": msg}

            data = result.get("data", {})
            blocks = data if isinstance(data, list) else data.get("blocks", data.get("list", []))
            if not isinstance(blocks, list):
                blocks = []
            logger.info(f"获取域封禁列表: {len(blocks)} 人")
            return {"blocks": blocks}
        except Exception as e:
            logger.error(f"获取域封禁列表异常: {e}")
            return {"error": str(e)}

    def unblock_user_in_area(
        self,
        uid: str,
        area: Optional[str] = None,
    ) -> dict:
        """
        解除域内封禁（从域封禁列表移除）。

        API: PATCH /client/v1/area/v1/unblock?area={area}&target={uid}
        """
        area = area or OOPZ_CONFIG["default_area"]
        url_path = "/client/v1/area/v1/unblock"
        query = f"?area={area}&target={uid}"
        body = {"area": area, "target": uid}
        return self._manage_patch("解除域内封禁", url_path, query, body)

    def _manage_patch(self, action: str, url_path: str, query: str, body: dict) -> dict:
        """通用 PATCH 管理操作（禁言/禁麦等），参数同时放 query string 和 body。"""
        full_path = url_path + query
        try:
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.patch(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"{action}请求异常: {e}")
            return {"error": str(e)}

        raw = resp.text or ""
        logger.info(f"{action} PATCH {full_path} -> HTTP {resp.status_code}, body: {raw[:300]}")

        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}" + (f" | {raw[:200]}" if raw else "")
            return {"error": err}

        try:
            result = resp.json()
        except Exception:
            return {"error": f"响应非 JSON: {raw[:200]}"}

        if result.get("status") is True:
            msg = result.get("message") or f"{action}成功"
            logger.info(f"{action}成功: {msg}")
            return {"status": True, "message": msg}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"{action}失败: {err}")
        return {"error": err}

    # ---- 撤回消息 ----

    def recall_message(
        self,
        message_id: str,
        area: Optional[str] = None,
        channel: Optional[str] = None,
        timestamp: Optional[str] = None,
        target: str = "",
    ) -> dict:
        """
        撤回指定消息（需要管理员权限）。

        API: POST /im/session/v1/recallGim
        参数同时放在 query string 和 JSON body 中。

        Args:
            message_id: 消息 ID
            area:       区域 ID（默认取配置）
            channel:    频道 ID（默认取配置）
            timestamp:  消息原始时间戳（微秒），为空则用当前时间
            target:     目标用户 UID（撤回他人消息时填写，默认空）
        """
        area = area or OOPZ_CONFIG["default_area"]
        channel = channel or OOPZ_CONFIG["default_channel"]
        timestamp = timestamp or self.signer.timestamp_us()
        message_id = str(message_id).strip() if message_id is not None else ""

        url_path = "/im/session/v1/recallGim"
        query = (
            f"?area={area}&channel={channel}"
            f"&messageId={message_id}&timestamp={timestamp}&target={target}"
        )
        full_path = url_path + query

        body = {
            "area": area,
            "channel": channel,
            "messageId": message_id,
            "timestamp": timestamp,
            "target": target,
        }

        try:
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
            headers = {**self.session.headers, **self.signer.oopz_headers(full_path, body_str)}
            url = OOPZ_CONFIG["base_url"] + full_path
            resp = self.session.post(url, headers=headers, data=body_str.encode("utf-8"))
        except Exception as e:
            logger.error(f"撤回请求异常: {e}")
            return {"error": str(e)}

        raw_text = resp.text or ""
        logger.info(f"撤回 POST {full_path} → HTTP {resp.status_code}, body: {raw_text[:300]}")

        if resp.status_code != 200:
            err = f"HTTP {resp.status_code}" + (f" | {raw_text[:200]}" if raw_text else "")
            logger.error(f"撤回消息失败: {err}")
            return {"error": err}

        try:
            result = resp.json()
        except Exception:
            logger.error(f"撤回响应非 JSON: {raw_text[:200]}")
            return {"error": f"响应非 JSON: {raw_text[:200]}"}

        if result.get("status") is True or result.get("code") in (0, "0", "success", 200):
            logger.info(f"撤回消息成功: {message_id}")
            return {"status": True, "message": "撤回成功"}

        err = result.get("message") or result.get("error") or str(result)
        logger.error(f"撤回消息失败: {err}")
        return {"error": err}
