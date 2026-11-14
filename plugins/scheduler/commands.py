"""提醒与定时消息命令。"""

from __future__ import annotations

import re
from typing import Any

from core.constants import Msg
from core.database import ReminderDB, ScheduledMessageDB

from .service import ReminderService

REMIND_USAGE = "用法:\n/remind 30分钟后 提醒内容\n/remind list  查看我的提醒\n/remind del <ID>  删除提醒"
SCHEDULE_USAGE = "用法: /schedule list | add | del | on | off"
_SCHEDULE_ARG_USAGE = {
    "add": "用法: /schedule add 08:00 早上好",
    "del": "用法: /schedule del <ID>",
    "on": "用法: /schedule on <ID>",
    "off": "用法: /schedule off <ID>",
}


class SchedulerCommands:
    def __init__(self, handler: Any, reminder: ReminderService):
        self._handler = handler
        self._sender = handler.sender
        self._reminder = reminder

    async def _reply(self, text: str, channel: str, area: str) -> None:
        await self._sender.send_message(text, channel=channel, area=area)

    async def run(self, group: str, action: str, arg: str, channel: str, area: str, user: str) -> None:
        if group == "remind":
            await self._run_remind(action, arg, channel, area, user)
            return
        if not self._handler.services.routing.access.is_admin(user):
            await self._reply(f"{Msg.ERR} 无权限，仅管理员可使用该指令", channel, area)
            return
        await self._run_schedule(action, arg, channel, area)

    async def _run_remind(self, action: str, arg: str, channel: str, area: str, user: str) -> None:
        if action == "list":
            await self.list_reminders(channel, area, user)
        elif action == "del":
            await self.delete_reminder(arg, channel, area, user)
        elif arg:
            await self._reply(await self._reminder.create_reminder(arg, channel, area, user), channel, area)
        else:
            await self._reply(REMIND_USAGE, channel, area)

    async def _run_schedule(self, action: str, arg: str, channel: str, area: str) -> None:
        if action == "list":
            await self.list_scheduled(channel, area)
        elif action not in _SCHEDULE_ARG_USAGE:
            await self._reply(SCHEDULE_USAGE, channel, area)
        elif not arg:
            await self._reply(_SCHEDULE_ARG_USAGE[action], channel, area)
        elif action == "add":
            await self.add_scheduled(arg, channel, area)
        elif action == "del":
            await self.delete_scheduled(arg, channel, area)
        else:
            await self.toggle_scheduled(arg, channel, area, action == "on")

    # ------------------------------------------------------------------
    # 用户提醒
    # ------------------------------------------------------------------

    async def list_reminders(self, channel: str, area: str, user: str) -> None:
        pending = await ReminderDB.get_user_pending(user)
        if not pending:
            await self._reply("你没有待执行的提醒", channel, area)
            return
        lines = ["【我的待执行提醒】"]
        lines.extend(f"[{r['id']}] {r['fire_at'][:16]}  {r['message_text'][:50]}" for r in pending)
        await self._reply("\n".join(lines), channel, area)

    async def delete_reminder(self, raw: str, channel: str, area: str, user: str) -> None:
        rid = raw.strip()
        if not rid.isdigit():
            await self._reply("用法: 删除提醒 <ID>\n先用 \"我的提醒\" 查看 ID", channel, area)
            return
        if await ReminderDB.delete_user_reminder(int(rid), user):
            await self._reply(f"已删除提醒 {rid}", channel, area)
        else:
            await self._reply(f"未找到提醒 {rid}（可能已触发或不属于你）", channel, area)

    # ------------------------------------------------------------------
    # 管理员定时消息
    # ------------------------------------------------------------------

    async def list_scheduled(self, channel: str, area: str) -> None:
        tasks = await ScheduledMessageDB.get_all()
        if not tasks:
            await self._reply("暂无定时消息", channel, area)
            return
        lines = ["【定时消息列表】"]
        for t in tasks:
            status = "启用" if t["enabled"] else "停用"
            lines.append(
                f"[{t['id']}] {t['name']} | {t['cron_hour']:02d}:{t['cron_minute']:02d} "
                f"| 星期 {t['weekdays']} | {status}\n  → {t['message_text'][:50]}"
            )
        await self._reply("\n".join(lines), channel, area)

    async def add_scheduled(self, raw: str, channel: str, area: str) -> None:
        """格式: HH:MM 内容  或  HH:MM [星期] 内容"""
        m = re.match(r"(\d{1,2})[:\uff1a](\d{2})\s+(.+)", raw.strip(), re.DOTALL)
        if not m:
            await self._reply(
                "用法: 添加定时消息 08:00 早上好\n或: 添加定时消息 08:00 [1,2,3,4,5] 工作日快乐",
                channel, area,
            )
            return
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await self._reply("时间不合法，小时需 0-23、分钟需 0-59，例如 08:00", channel, area)
            return
        rest = m.group(3).strip()

        weekdays = "0,1,2,3,4,5,6"
        wm = re.match(r"\[([0-6,]+)\]\s+(.+)", rest, re.DOTALL)
        if wm:
            weekdays = wm.group(1)
            rest = wm.group(2).strip()

        if not rest:
            await self._reply("请提供消息内容", channel, area)
            return

        task_id = await ScheduledMessageDB.create(rest[:20], hour, minute, channel, area, rest, weekdays)
        await self._reply(
            f"定时消息已创建 (ID: {task_id})\n时间: {hour:02d}:{minute:02d} | 星期: {weekdays}\n内容: {rest[:50]}",
            channel, area,
        )

    async def delete_scheduled(self, raw: str, channel: str, area: str) -> None:
        task_id = raw.strip()
        if not task_id.isdigit():
            await self._reply("用法: 删除定时消息 <ID>", channel, area)
            return
        if await ScheduledMessageDB.delete(int(task_id)):
            await self._reply(f"定时消息 {task_id} 已删除", channel, area)
        else:
            await self._reply(f"未找到定时消息 {task_id}", channel, area)

    async def toggle_scheduled(self, raw: str, channel: str, area: str, enable: bool) -> None:
        task_id = raw.strip()
        if not task_id.isdigit():
            await self._reply("用法: 开启/关闭定时消息 <ID>", channel, area)
            return
        if not await ScheduledMessageDB.get_by_id(int(task_id)):
            await self._reply(f"未找到定时消息 {task_id}", channel, area)
            return
        await ScheduledMessageDB.update(int(task_id), enabled=1 if enable else 0)
        await self._reply(f"定时消息 {task_id} {'已启用' if enable else '已停用'}", channel, area)
