"""后台 Shell 模板渲染：页面元数据、顶栏按钮与整页装配。"""

from __future__ import annotations

import json
import os
import string
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse

import web.web_player_config as cfg
from core.paths import WEB_ASSETS_DIR
from web.plugin_routes import admin_navigation

from ._runtime import _admin_enabled

_ADMIN_SHELL_TEMPLATE: string.Template | None = None
_ADMIN_SHELL_TEMPLATE_MTIME: float | None = None


def _load_admin_template() -> string.Template:
    global _ADMIN_SHELL_TEMPLATE, _ADMIN_SHELL_TEMPLATE_MTIME
    tpl_path = os.path.join(WEB_ASSETS_DIR, "admin", "admin-shell-template.html")
    mtime = os.path.getmtime(tpl_path)
    if _ADMIN_SHELL_TEMPLATE is None or mtime != _ADMIN_SHELL_TEMPLATE_MTIME:
        with open(tpl_path, encoding="utf-8") as f:
            _ADMIN_SHELL_TEMPLATE = string.Template(f.read())
        _ADMIN_SHELL_TEMPLATE_MTIME = mtime
    return _ADMIN_SHELL_TEMPLATE


_ADMIN_PAGES: dict[str, dict[str, Any]] = {
    "dashboard": {
        "page_title": "总览 · Oopz",
        "page_id": "dashboard",
        "brand_title": "总览",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-overview", "label": "刷新"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "music": {
        "page_title": "音乐 · Oopz",
        "page_id": "music",
        "brand_title": "音乐",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-queue", "label": "刷新队列"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "config": {
        "page_title": "配置 · Oopz",
        "page_id": "config",
        "brand_title": "配置",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-config", "label": "刷新"},
            {"action": "reset-overrides", "label": "恢复配置"},
            {"action": "save-config", "label": "保存并生效", "variant": "primary"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "stats": {
        "page_title": "统计 · Oopz",
        "page_id": "stats",
        "brand_title": "统计",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-stats", "label": "刷新"},
            {"action": "clear-history", "label": "清空历史", "variant": "danger"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "system": {
        "page_title": "系统 · Oopz",
        "page_id": "system",
        "brand_title": "系统",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-system", "label": "刷新状态"},
            {"action": "refresh-logs", "label": "刷新日志"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "members": {
        "page_title": "成员 · Oopz",
        "page_id": "members",
        "brand_title": "成员",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-members", "label": "刷新"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "areas": {
        "page_title": "域管理 · Oopz",
        "page_id": "areas",
        "brand_title": "域管理",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-areas", "label": "刷新"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
    "plugins": {
        "page_title": "插件 · Oopz",
        "page_id": "plugins",
        "brand_title": "插件",
        "brand_copy": "",
        "topbar_actions": [
            {"action": "refresh-plugins", "label": "刷新"},
        ],
        "login_title": "验证身份",
        "login_copy": "",
        "login_button": "进入后台",
    },
}


def _render_topbar_actions(actions: list[dict[str, str]]) -> str:
    """把结构化按钮声明渲染成顶栏 HTML，行为通过 data-action 委托到页面脚本。"""
    buttons = [
        '<button class="btn btn-{variant}" type="button" data-action="{action}">{label}</button>'.format(
            variant=action.get("variant", "ghost"),
            action=action["action"],
            label=action["label"],
        )
        for action in actions
    ]
    return "\n          ".join(buttons)


def _render_admin_page(page_key: str) -> HTMLResponse:
    return render_admin_page(_ADMIN_PAGES[page_key])


def _bundle_version() -> str:
    bundle_js = Path(WEB_ASSETS_DIR) / "admin" / "bundle" / "admin-app.js"
    try:
        return str(int(bundle_js.stat().st_mtime))
    except OSError:
        return "1"


def _rewrite_admin_href(href: str, admin_base: str) -> str:
    if admin_base == "/admin":
        return href
    if href == "/admin":
        return admin_base
    if href.startswith("/admin/"):
        return admin_base + href[len("/admin"):]
    return href


def render_admin_page(meta: Mapping[str, Any], pages_dir: Path | None = None) -> HTMLResponse:
    if not _admin_enabled():
        return HTMLResponse("管理后台未启用，请在 WEB_PLAYER_CONFIG 中开启。", status_code=404)
    admin_base = cfg.admin_path()
    assets_base = "/admin-assets" if admin_base == "/admin" else f"{admin_base}/_assets"
    nav_items = [
        {**item, "href": _rewrite_admin_href(str(item.get("href", "")), admin_base)}
        for item in admin_navigation()
    ]
    tpl = _load_admin_template()
    html = tpl.safe_substitute(
        page_title=meta["page_title"],
        page_id=meta["page_id"],
        admin_base=admin_base,
        assets_base=assets_base,
        asset_version=_bundle_version(),
        plugin_navigation=json.dumps(nav_items, ensure_ascii=False).replace("<", "\\u003c"),
    )
    return HTMLResponse(html)


__all__ = [
    "_ADMIN_PAGES",
    "_ADMIN_SHELL_TEMPLATE",
    "_load_admin_template",
    "_render_admin_page",
    "_render_topbar_actions",
]
