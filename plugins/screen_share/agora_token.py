from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
import zlib
from hashlib import sha256


def _u16(value: int) -> bytes:
    return struct.pack("<H", int(value))


def _u32(value: int) -> bytes:
    return struct.pack("<I", int(value))


def _packed(value: str | bytes) -> bytes:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return _u16(len(data)) + data


def _validate_hex_id(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if len(normalized) != 32:
        raise ValueError(f"{label} 必须是 32 位十六进制字符串")
    try:
        bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError(f"{label} 必须是 32 位十六进制字符串") from exc
    return normalized


def build_rtc_token(
    *,
    app_id: str,
    app_certificate: str,
    channel_name: str,
    uid: int,
    expires_in: int,
    publish: bool,
    now: int | None = None,
) -> str:
    """生成绑定数字 UID 的 AccessToken2 RTC Token。

    ``publish=False`` 只包含 join 权限；发布者额外获得音频、视频和数据流权限。
    """

    app_id = _validate_hex_id(app_id, "Agora App ID")
    app_certificate = _validate_hex_id(app_certificate, "Agora App Certificate")
    channel_name = str(channel_name or "").strip()
    if not channel_name or len(channel_name.encode("utf-8")) >= 64:
        raise ValueError("Agora channel_name 必须为 1-63 字节")
    if not 1 <= int(uid) <= 0xFFFFFFFF:
        raise ValueError("Agora UID 必须在 1 到 2^32-1 之间")
    expires_in = int(expires_in)
    if not 1 <= expires_in <= 86400:
        raise ValueError("Agora Token 有效期必须在 1-86400 秒之间")

    issue_ts = int(time.time() if now is None else now)
    salt = secrets.SystemRandom().randint(1, 99_999_999)

    # ServiceRtc: type(1), privilege map, channel name, uid string.
    privileges = [(1, expires_in)]
    if publish:
        privileges.extend(((2, expires_in), (3, expires_in), (4, expires_in)))
    privilege_map = _u16(len(privileges)) + b"".join(
        _u16(privilege) + _u32(expire)
        for privilege, expire in privileges
    )
    rtc_service = (
        _u16(1)
        + privilege_map
        + _packed(channel_name)
        + _packed(str(int(uid)))
    )
    signing_info = (
        _packed(app_id)
        + _u32(issue_ts)
        + _u32(expires_in)
        + _u32(salt)
        + _u16(1)
        + rtc_service
    )

    signing_key = hmac.new(_u32(issue_ts), app_certificate.encode("utf-8"), sha256).digest()
    signing_key = hmac.new(_u32(salt), signing_key, sha256).digest()
    signature = hmac.new(signing_key, signing_info, sha256).digest()
    return "007" + base64.b64encode(zlib.compress(_packed(signature) + signing_info)).decode("ascii")
