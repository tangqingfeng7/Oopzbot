from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from web.admin.shared._pages import render_admin_page

_PAGE = {
    "page_title": "关键词回复",
    "page_id": "keyword-reply",
    "brand_title": "关键词回复",
    "brand_copy": "普通聊天消息命中关键词时自动回复。",
    "topbar_actions": [
        {"action": "refresh-keywords", "label": "刷新"},
        {"action": "save-keywords", "label": "保存并生效", "variant": "primary"},
    ],
    "login_title": "登录关键词回复",
    "login_copy": "登录后编辑关键词自动回复。",
    "login_button": "进入关键词回复",
}


def build_router(current_replies: Callable[[], dict[str, str]]) -> APIRouter:
    """保存走通用插件配置接口，这里只提供页面和当前生效的关键词。"""
    router = APIRouter()

    @router.get("/admin/keyword-reply", response_class=HTMLResponse)
    def admin_keyword_reply_page():
        return render_admin_page(_PAGE, Path(__file__).with_name("admin_assets"))

    @router.get("/admin/api/keyword-replies")
    def admin_keyword_replies():
        return JSONResponse({"ok": True, "keyword_replies": current_replies()})

    return router
