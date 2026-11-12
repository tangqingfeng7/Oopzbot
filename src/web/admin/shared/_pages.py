"""后台 Shell 模板渲染：页面元数据、顶栏按钮与整页装配。"""

from __future__ import annotations

import json
import os
import string
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse

from core.paths import WEB_ASSETS_DIR
from web.plugin_routes import admin_navigation

from ._runtime import _admin_enabled

_ADMIN_SHELL_TEMPLATE: string.Template | None = None


def _load_admin_template() -> string.Template:
    global _ADMIN_SHELL_TEMPLATE
    if _ADMIN_SHELL_TEMPLATE is None:
        tpl_path = os.path.join(WEB_ASSETS_DIR, "admin", "admin-shell-template.html")
        with open(tpl_path, encoding="utf-8") as f:
            _ADMIN_SHELL_TEMPLATE = string.Template(f.read())
    return _ADMIN_SHELL_TEMPLATE


_ADMIN_PAGES: dict[str, dict[str, Any]] = {
    "dashboard": {
        "page_title": "后台总览",
        "page_id": "dashboard",
        "brand_title": "后台管理",
        "brand_copy": "顶部主导航、数据优先、专业 SaaS 工作台。",
        "topbar_actions": [
            {"action": "refresh-overview", "label": "刷新概览"},
        ],
        "login_title": "登录后台总览",
        "login_copy": "登录后查看实时状态与关键指标。",
        "login_button": "进入总览",
    },
    "music": {
        "page_title": "音乐管理",
        "page_id": "music",
        "brand_title": "音乐管理",
        "brand_copy": "把播放控制、搜索加歌和队列调度整理成标准运营面板。",
        "topbar_actions": [
            {"action": "refresh-queue", "label": "刷新队列"},
        ],
        "login_title": "登录音乐后台",
        "login_copy": "登录后控制播放、搜索歌曲和调整队列。",
        "login_button": "进入音乐控制台",
    },
    "config": {
        "page_title": "配置中心",
        "page_id": "config",
        "brand_title": "配置中心",
        "brand_copy": "把长表单整理成章节化配置工作台，保留原字段和保存接口。",
        "topbar_actions": [
            {"action": "refresh-config", "label": "刷新配置"},
            {"action": "reset-overrides", "label": "恢复运行配置"},
            {"action": "save-config", "label": "保存并立即生效", "variant": "primary"},
        ],
        "login_title": "登录配置中心",
        "login_copy": "登录后调整后台配置。",
        "login_button": "进入配置中心",
    },
    "stats": {
        "page_title": "统计页",
        "page_id": "stats",
        "brand_title": "统计页",
        "brand_copy": "让摘要、榜单和危险操作形成稳定阅读顺序，而不是只摆一张表。",
        "topbar_actions": [
            {"action": "refresh-stats", "label": "刷新统计"},
            {"action": "clear-history", "label": "清空历史", "variant": "danger"},
        ],
        "login_title": "登录统计页",
        "login_copy": "登录后查看最近 7 天的播放排行。",
        "login_button": "进入统计页",
    },
    "system": {
        "page_title": "系统页",
        "page_id": "system",
        "brand_title": "系统页",
        "brand_copy": "把播放器入口、系统快照和实时日志拆成明确的运维层级。",
        "topbar_actions": [
            {"action": "refresh-system", "label": "刷新系统信息"},
            {"action": "refresh-logs", "label": "刷新日志"},
        ],
        "login_title": "登录系统页",
        "login_copy": "登录后查看链接、系统信息和日志。",
        "login_button": "进入系统页",
    },
    "members": {
        "page_title": "成员管理",
        "page_id": "members",
        "brand_title": "成员管理",
        "brand_copy": "域成员浏览、管理操作与封禁列表。",
        "topbar_actions": [
            {"action": "refresh-members", "label": "刷新成员"},
        ],
        "login_title": "登录成员管理",
        "login_copy": "登录后管理域成员。",
        "login_button": "进入成员管理",
    },
    "areas": {
        "page_title": "域管理",
        "page_id": "areas",
        "brand_title": "域管理",
        "brand_copy": "域配置、频道管理与语音频道监控。",
        "topbar_actions": [
            {"action": "refresh-areas", "label": "刷新"},
        ],
        "login_title": "登录域管理",
        "login_copy": "登录后管理域配置与频道。",
        "login_button": "进入域管理",
    },
    "plugins": {
        "page_title": "插件管理",
        "page_id": "plugins",
        "brand_title": "插件管理",
        "brand_copy": "查看、加载、卸载插件，在线编辑插件配置。",
        "topbar_actions": [
            {"action": "refresh-plugins", "label": "刷新列表"},
        ],
        "login_title": "登录插件管理",
        "login_copy": "登录后管理插件与配置。",
        "login_button": "进入插件管理",
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
    return render_admin_page(_ADMIN_PAGES[page_key], Path(WEB_ASSETS_DIR) / "admin" / "pages")


def render_admin_page(meta: Mapping[str, Any], pages_dir: Path) -> HTMLResponse:
    if not _admin_enabled():
        return HTMLResponse("管理后台未启用，请在 WEB_PLAYER_CONFIG 中开启。", status_code=404)
    page_key = meta["page_id"]
    tpl = _load_admin_template()
    html = tpl.safe_substitute(
        page_title=meta["page_title"],
        page_id=meta["page_id"],
        brand_title=meta["brand_title"],
        brand_copy=meta["brand_copy"],
        topbar_actions=_render_topbar_actions(meta["topbar_actions"]),
        login_title=meta["login_title"],
        login_copy=meta["login_copy"],
        login_button=meta["login_button"],
        page_content=(pages_dir / f"{page_key}_content.html").read_text(encoding="utf-8"),
        page_script=(pages_dir / f"{page_key}_script.js").read_text(encoding="utf-8"),
        plugin_navigation=json.dumps(admin_navigation(), ensure_ascii=False).replace("<", "\\u003c"),
    )
    return HTMLResponse(html)


__all__ = [
    "_ADMIN_PAGES",
    "_ADMIN_SHELL_TEMPLATE",
    "_load_admin_template",
    "_render_admin_page",
    "_render_topbar_actions",
]
