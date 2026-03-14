from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote


PLUGIN_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PLUGIN_DIR / "delta_force_assets"
TEMPLATES_DIR = ASSETS_DIR / "templates"


def decode_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    try:
        return unquote(text)
    except Exception:
        return text


def normalize_mode(token: str) -> str:
    raw = str(token or "").strip().lower()
    if raw in {"烽火", "烽火地带", "sol", "摸金"}:
        return "sol"
    if raw in {"全面", "全面战场", "战场", "mp"}:
        return "mp"
    if raw in {"全部", "all"}:
        return "all"
    return ""


def mode_name(mode: str) -> str:
    if mode == "sol":
        return "烽火地带"
    if mode == "mp":
        return "全面战场"
    return "全部模式"


def pick_avatar_url(personal_info: dict) -> str:
    data = personal_info.get("data") or {}
    user_data = data.get("userData") or {}
    role_info = personal_info.get("roleInfo") or {}
    avatar = decode_text(user_data.get("picurl") or role_info.get("picurl"))
    if avatar.isdigit():
        return f"https://wegame.gtimg.com/g.2001918-r.ea725/helper/df/skin/{avatar}.webp"
    return avatar


def pick_nickname(personal_info: dict, fallback: str = "未知") -> str:
    data = personal_info.get("data") or {}
    user_data = data.get("userData") or {}
    role_info = personal_info.get("roleInfo") or {}
    return decode_text(user_data.get("charac_name") or role_info.get("charac_name") or fallback)


def qq_avatar_url(user_id: str) -> str:
    return f"http://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640&img_type=jpg"
