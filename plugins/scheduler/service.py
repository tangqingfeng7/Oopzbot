"""定时消息调度 + 用户提醒服务。

ScheduledMessageService — 管理员配置的周期性定时消息（每日早安等）
ReminderService         — 用户 @bot 提醒 创建的一次性延迟提醒
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from core.constants import build_mention
from core.database import (
    CN_TZ,
    ReminderDB,
    ScheduledMessageDB,
    cn_now,
)
from plugins._shared.background import IntervalWorker

# 相对时间（N分钟/小时/天后）的量级上限，避免超大数值让 timedelta 抛 OverflowError。
# 取 ~400 天，远超 ReminderService 的 max_delay_hours，故超限值会落到
# create_reminder 的「不能超过 N 小时」校验给出明确提示，而不是静默失败。
_MAX_RELATIVE_MINUTES = 400 * 24 * 60
# 约每小时清理一次已触发的旧提醒。
_REMINDER_CLEANUP_SECONDS = 3600


# ---------------------------------------------------------------------------
# ScheduledMessageService
# ---------------------------------------------------------------------------

class ScheduledMessageService(IntervalWorker):
    """轮询 scheduled_messages 表，到点发送消息。"""

    _NAME = "scheduled-message-service"

    def __init__(self, sender: Any, interval: int = 30) -> None:
        super().__init__(interval=max(10, interval))
        self._sender = sender

    def start(self) -> None:
        if self._start_task():
            self._logger.info("ScheduledMessageService 已启动 (间隔 %ds)", self._interval)

    async def _tick(self) -> None:
        now = datetime.now(CN_TZ)
        today = now.strftime("%Y-%m-%d")
        tasks = await ScheduledMessageDB.get_due_tasks(now.hour, now.minute, now.weekday(), today)
        for task in tasks:
            if self.stopping:
                return
            try:
                await self._sender.send_message(
                    task["message_text"],
                    channel=task["channel_id"],
                    area=task["area_id"],
                )
                self._logger.info("定时消息已发送: [%s] %s", task["name"], task["message_text"][:40])
                await ScheduledMessageDB.mark_fired(task["id"], today)
            except Exception:
                self._logger.exception("定时消息发送失败: id=%s", task["id"])


# ---------------------------------------------------------------------------
# ReminderService
# ---------------------------------------------------------------------------

class ReminderService(IntervalWorker):
    """轮询 reminders 表，到期发送提醒。"""

    _NAME = "reminder-service"

    def __init__(self, sender: Any, interval: int = 15, max_per_user: int = 5, max_delay_hours: int = 72) -> None:
        super().__init__(interval=max(5, interval))
        self._sender = sender
        self._max_per_user = max_per_user
        self._max_delay_hours = max_delay_hours
        self._cleanup_counter = 0

    def start(self) -> None:
        if self._start_task():
            self._logger.info("ReminderService 已启动 (间隔 %ds)", self._interval)

    async def _tick(self) -> None:
        pending = await ReminderDB.get_pending(cn_now())
        for r in pending:
            if self.stopping:
                return
            try:
                uid = r["user_id"]
                await self._sender.send_message(
                    f"{build_mention(uid)} 你设置的提醒到啦：\n{r['message_text']}",
                    channel=r["channel_id"],
                    area=r["area_id"],
                    mentionList=[{"person": uid, "isBot": False, "botType": "", "offset": -1}],
                )
                self._logger.info("提醒已发送: user=%s, text=%s", uid, r["message_text"][:40])
                await ReminderDB.mark_fired(r["id"])
            except Exception:
                self._logger.exception("提醒发送失败: id=%s", r["id"])

        self._cleanup_counter += 1
        if self._cleanup_counter * self._interval >= _REMINDER_CLEANUP_SECONDS:
            self._cleanup_counter = 0
            cleaned = await ReminderDB.cleanup_old(7)
            if cleaned:
                self._logger.info("已清理过期提醒: %d 条", cleaned)

    # ------------------------------------------------------------------
    # 提醒创建（由命令调用）
    # ------------------------------------------------------------------

    async def create_reminder(
        self,
        raw_text: str,
        channel: str,
        area: str,
        user: str,
    ) -> str:
        """解析用户输入并创建提醒，返回提示消息。"""
        fire_at, content = self._parse_reminder_text(raw_text)
        if fire_at is None:
            return (
                "格式不正确，示例：\n"
                "  提醒 30分钟后 开会\n"
                "  提醒 2小时后 喝水\n"
                "  提醒 明天08:00 交作业"
            )

        if not content:
            return "请提供提醒内容"

        now = datetime.now(CN_TZ)
        if fire_at <= now:
            return "提醒时间必须在未来"

        max_future = now + timedelta(hours=self._max_delay_hours)
        if fire_at > max_future:
            return f"提醒时间不能超过 {self._max_delay_hours} 小时"

        pending_count = await ReminderDB.count_user_pending(user)
        if pending_count >= self._max_per_user:
            return f"你最多只能有 {self._max_per_user} 个待执行提醒"

        await ReminderDB.create(user, channel, area, content, fire_at.strftime("%Y-%m-%d %H:%M:%S"))
        return f"已设置提醒\n时间: {fire_at.strftime('%m-%d %H:%M')}\n内容: {content}"

    @staticmethod
    def _parse_reminder_text(raw: str) -> tuple[datetime | None, str]:
        """解析 '30分钟后 内容' / '2小时后 内容' / '明天08:00 内容'。"""
        raw = raw.strip()
        now = datetime.now(CN_TZ)

        m = re.match(r"(\d+)\s*分钟后\s+(.+)", raw, re.DOTALL)
        if m:
            minutes = min(int(m.group(1)), _MAX_RELATIVE_MINUTES)
            return now + timedelta(minutes=minutes), m.group(2).strip()

        m = re.match(r"(\d+)\s*小时后\s+(.+)", raw, re.DOTALL)
        if m:
            hours = min(int(m.group(1)), _MAX_RELATIVE_MINUTES // 60)
            return now + timedelta(hours=hours), m.group(2).strip()

        m = re.match(r"(\d+)\s*天后\s+(.+)", raw, re.DOTALL)
        if m:
            days = min(int(m.group(1)), _MAX_RELATIVE_MINUTES // (24 * 60))
            return now + timedelta(days=days), m.group(2).strip()

        # 形如 “明天08:00 内容” / “后天9：30 内容”，按相对天数 + 绝对时刻解析。
        for keyword, day_offset in (("明天", 1), ("后天", 2)):
            m = re.match(rf"{keyword}\s*(\d{{1,2}})[:\uff1a](\d{{2}})\s+(.+)", raw, re.DOTALL)
            if m:
                fire_at = ReminderService._at_clock(
                    now + timedelta(days=day_offset), int(m.group(1)), int(m.group(2)),
                )
                if fire_at is None:
                    return None, ""
                return fire_at, m.group(3).strip()

        return None, ""

    @staticmethod
    def _at_clock(base: datetime, hour: int, minute: int) -> datetime | None:
        """把 ``base`` 调整到当天的 ``hour:minute``，时分越界则返回 None。"""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)
