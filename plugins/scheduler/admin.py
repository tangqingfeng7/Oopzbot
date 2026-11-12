from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.database import ReminderDB, ScheduledMessageDB
from web.admin.shared import read_json_body
from web.admin.shared._pages import render_admin_page

from .templates import get_scheduled_template, list_scheduled_templates

router = APIRouter()
_PAGE = {
    "page_title": "定时任务",
    "page_id": "scheduler",
    "brand_title": "定时任务",
    "brand_copy": "管理定时消息与用户提醒。",
    "topbar_actions": [{"action": "refresh-scheduler", "label": "刷新列表"}],
    "login_title": "登录定时任务",
    "login_copy": "登录后管理定时消息与查看提醒。",
    "login_button": "进入定时任务",
}


def _cron_range_error(hour: int, minute: int):
    """cron 时分越界则返回 400 响应，否则返回 None。避免持久化永不触发的任务。"""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return JSONResponse(
            {"ok": False, "error": "cron_hour 需 0-23, cron_minute 需 0-59"},
            status_code=400,
        )
    return None


@router.get("/admin/scheduler", response_class=HTMLResponse)
def admin_scheduler_page():
    return render_admin_page(_PAGE, Path(__file__).with_name("admin_assets"))


@router.get("/admin/api/scheduled-messages")
async def admin_scheduled_messages_list():
    return JSONResponse({"ok": True, "items": await ScheduledMessageDB.get_all()})


@router.get("/admin/api/scheduled-message-templates")
def admin_scheduled_message_templates():
    return JSONResponse({"ok": True, "items": list_scheduled_templates()})


@router.post("/admin/api/scheduled-message-templates/{template_key}/apply")
async def admin_scheduled_message_template_apply(template_key: str, request: Request):
    template = get_scheduled_template(template_key)
    if not template:
        return JSONResponse({"ok": False, "error": "未找到定时模板"}, status_code=404)
    body = await read_json_body(request)
    channel_id = str(body.get("channel_id") or "").strip()
    area_id = str(body.get("area_id") or "").strip()
    if not channel_id or not area_id:
        return JSONResponse({"ok": False, "error": "channel_id/area_id 不能为空"}, status_code=400)
    name = str(body.get("name") or template["name"]).strip()
    message_text = str(body.get("message_text") or template["message_text"]).strip()
    weekdays = str(body.get("weekdays") or template["weekdays"]).strip()
    try:
        cron_hour = int(body.get("cron_hour", template["cron_hour"]))
        cron_minute = int(body.get("cron_minute", template["cron_minute"]))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "cron_hour/cron_minute 必须为整数"}, status_code=400)
    cron_error = _cron_range_error(cron_hour, cron_minute)
    if cron_error:
        return cron_error
    if not name or not message_text:
        return JSONResponse({"ok": False, "error": "name/message_text 不能为空"}, status_code=400)
    task_id = await ScheduledMessageDB.create(
        name=name,
        cron_hour=cron_hour,
        cron_minute=cron_minute,
        channel_id=channel_id,
        area_id=area_id,
        message_text=message_text,
        weekdays=weekdays,
    )
    return JSONResponse({"ok": True, "id": task_id, "template": template["key"]})


@router.post("/admin/api/scheduled-messages")
async def admin_scheduled_messages_create(request: Request):
    body = await read_json_body(request)
    name = str(body.get("name") or "").strip()
    try:
        hour = int(body.get("cron_hour", 0))
        minute = int(body.get("cron_minute", 0))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "cron_hour/cron_minute 必须为整数"}, status_code=400)
    cron_error = _cron_range_error(hour, minute)
    if cron_error:
        return cron_error
    weekdays = str(body.get("weekdays", "0,1,2,3,4,5,6"))
    channel_id = str(body.get("channel_id") or "").strip()
    area_id = str(body.get("area_id") or "").strip()
    message_text = str(body.get("message_text") or "").strip()
    if not name or not channel_id or not area_id or not message_text:
        return JSONResponse({"ok": False, "error": "name/channel_id/area_id/message_text 不能为空"}, status_code=400)
    task_id = await ScheduledMessageDB.create(
        name=name, cron_hour=hour, cron_minute=minute,
        channel_id=channel_id, area_id=area_id, message_text=message_text,
        weekdays=weekdays,
    )
    return JSONResponse({"ok": True, "id": task_id})


@router.put("/admin/api/scheduled-messages/{task_id}")
async def admin_scheduled_messages_update(task_id: int, request: Request):
    body = await read_json_body(request)
    if "cron_hour" in body or "cron_minute" in body:
        try:
            hour = int(body.get("cron_hour", 0))
            minute = int(body.get("cron_minute", 0))
        except (TypeError, ValueError):
            return JSONResponse({"ok": False, "error": "cron_hour/cron_minute 必须为整数"}, status_code=400)
        cron_error = _cron_range_error(hour, minute)
        if cron_error:
            return cron_error
    updated = await ScheduledMessageDB.update(task_id, **body)
    if not updated:
        return JSONResponse({"ok": False, "error": "未找到或无变更"}, status_code=404)
    return JSONResponse({"ok": True})


@router.delete("/admin/api/scheduled-messages/{task_id}")
async def admin_scheduled_messages_delete(task_id: int):
    if not await ScheduledMessageDB.delete(task_id):
        return JSONResponse({"ok": False, "error": "未找到"}, status_code=404)
    return JSONResponse({"ok": True})


@router.post("/admin/api/scheduled-messages/{task_id}/toggle")
async def admin_scheduled_messages_toggle(task_id: int):
    result = await ScheduledMessageDB.toggle(task_id)
    if result is None:
        return JSONResponse({"ok": False, "error": "未找到"}, status_code=404)
    return JSONResponse({"ok": True, "enabled": result})


@router.get("/admin/api/reminders")
async def admin_reminders_list():
    return JSONResponse({"ok": True, "items": await ReminderDB.get_all_pending()})


__all__ = ["router"]
