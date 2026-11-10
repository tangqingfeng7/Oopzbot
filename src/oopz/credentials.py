from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
from collections.abc import Mapping
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from oopz_sdk.auth import OopzLoginCredentials
from oopz_sdk.exceptions import OopzPasswordLoginError

from core.config_file_store import config_file_write_lock, replace_text_files_atomically
from core.paths import PROJECT_ROOT

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.py")
CONFIG_EXAMPLE_PATH = os.path.join(PROJECT_ROOT, "config.example.py")
PRIVATE_KEY_PATH = os.path.join(PROJECT_ROOT, "private_key.py")
OOPZ_CONFIG_CREDENTIAL_FIELDS = ("app_version", "device_id", "person_uid", "jwt_token")


def credentials_payload(credentials: OopzLoginCredentials | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(credentials, OopzLoginCredentials):
        return {
            "device_id": credentials.device_id,
            "person_uid": credentials.person_uid,
            "jwt_token": credentials.jwt_token,
            "private_key_pem": credentials.private_key_pem,
            "app_version": credentials.app_version,
        }
    return dict(credentials)


def _read_config_template() -> str:
    for path in (CONFIG_PATH, CONFIG_EXAMPLE_PATH):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as file:
                return file.read()
    raise OopzPasswordLoginError("config.py 不存在，且未找到 config.example.py")


def _replace_config_value(content: str, key: str, value: Any) -> tuple[str, bool]:
    if value is None or str(value) == "":
        return content, False
    pattern = re.compile(rf'("{re.escape(key)}"\s*:\s*)"[^"]*"')
    replacement = json.dumps(str(value), ensure_ascii=False)
    content, count = pattern.subn(lambda match: f"{match.group(1)}{replacement}", content, count=1)
    return content, count > 0


def _updated_config_content(credentials: Mapping[str, Any]) -> str:
    content = _read_config_template()
    replaced = False
    for key in OOPZ_CONFIG_CREDENTIAL_FIELDS:
        content, changed = _replace_config_value(content, key, credentials.get(key))
        replaced = replaced or changed
    if not replaced:
        raise OopzPasswordLoginError("未能在 config.py 中定位 OOPZ_CONFIG 凭据字段")
    return content


def _private_key_module_content(pem: str) -> str:
    normalized = pem.strip().replace("\r\n", "\n")
    return (
        '"""RSA 私钥（由 Oopz-SDK 登录自动生成）"""\n\n'
        "from cryptography.hazmat.primitives import serialization\n"
        "from cryptography.hazmat.backends import default_backend\n\n"
        f'PRIVATE_KEY_PEM = b"""{normalized}"""\n\n\n'
        "def get_private_key():\n"
        '    """加载并返回 RSA 私钥对象。"""\n'
        "    return serialization.load_pem_private_key(\n"
        "        PRIVATE_KEY_PEM, password=None, backend=default_backend()\n"
        "    )\n"
    )


def _apply_runtime(credentials: Mapping[str, Any]) -> None:
    updates = {
        key: credentials.get(key)
        for key in OOPZ_CONFIG_CREDENTIAL_FIELDS
        if credentials.get(key)
    }
    for module_name in ("config", "web.web_player_config"):
        try:
            module = importlib.import_module(module_name)
            target = getattr(module, "OOPZ_CONFIG", None)
            if isinstance(target, dict):
                target.update(updates)
        except Exception:
            continue


def save_credentials(
    credentials: OopzLoginCredentials | Mapping[str, Any], *, require_private_key: bool = True,
) -> list[str]:
    """成对原子保存登录凭据；手动捕获允许只更新已取得的字段。"""
    payload = credentials_payload(credentials)
    pem = str(payload.get("private_key_pem") or payload.get("private_key") or "").strip()
    if require_private_key and not pem:
        raise OopzPasswordLoginError("缺少 RSA 私钥，无法写入 private_key.py")
    with config_file_write_lock():
        updates = []
        if any(payload.get(key) for key in OOPZ_CONFIG_CREDENTIAL_FIELDS):
            updates.append((CONFIG_PATH, _updated_config_content(payload)))
        if pem:
            updates.append((PRIVATE_KEY_PATH, _private_key_module_content(pem)))
        if updates:
            replace_text_files_atomically(updates)
    _apply_runtime(payload)
    return [os.path.basename(path) for path, _content in updates]


async def persist_credentials(
    credentials: OopzLoginCredentials | Mapping[str, Any],
) -> list[str]:
    return await asyncio.to_thread(save_credentials, credentials)


def load_private_key_from_pem(pem: str):
    return serialization.load_pem_private_key(
        pem.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )


__all__ = [
    "credentials_payload",
    "load_private_key_from_pem",
    "persist_credentials",
    "save_credentials",
]
