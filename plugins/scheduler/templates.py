from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledTemplate:
    key: str
    name: str
    description: str
    cron_hour: int
    cron_minute: int
    weekdays: str
    message_text: str


SCHEDULED_TEMPLATES: tuple[ScheduledTemplate, ...] = (
    ScheduledTemplate(
        key="morning",
        name="早安提醒",
        description="每天早上在频道发送开场消息，适合日常打卡和晨间问候。",
        cron_hour=8,
        cron_minute=0,
        weekdays="0,1,2,3,4,5,6",
        message_text="早上好，各位。今天也别忘了查看频道消息和待办事项。",
    ),
    ScheduledTemplate(
        key="workday_start",
        name="工作日开场",
        description="工作日上午发送简短提醒，适合工作群或项目频道。",
        cron_hour=9,
        cron_minute=0,
        weekdays="0,1,2,3,4",
        message_text="早上好，今天的工作已经开始。请同步进度、查看任务并保持频道消息畅通。",
    ),
    ScheduledTemplate(
        key="lunch_break",
        name="午休提醒",
        description="中午提醒休息和查看未读消息，减少长时间连续在线。",
        cron_hour=12,
        cron_minute=0,
        weekdays="0,1,2,3,4,5,6",
        message_text="中午了，记得休息和吃饭。有未处理消息的同学可以顺手清一下。",
    ),
    ScheduledTemplate(
        key="evening_wrap",
        name="晚间收尾",
        description="晚上提醒总结当天情况，适合活动群和运营频道。",
        cron_hour=21,
        cron_minute=30,
        weekdays="0,1,2,3,4,5,6",
        message_text="今天辛苦了。离线前可以回顾一下今日事项，确认提醒、队列和待处理问题是否已清空。",
    ),
    ScheduledTemplate(
        key="weekend_event",
        name="周末活动预告",
        description="周末固定时间发布活动提醒，适合开黑、聚会或频道活动预热。",
        cron_hour=10,
        cron_minute=0,
        weekdays="5,6",
        message_text="周末活动时间到。看到消息的朋友可以准备集合，有安排变更请及时在频道里同步。",
    ),
)


def list_scheduled_templates() -> list[dict]:
    return [
        {
            "key": item.key,
            "name": item.name,
            "description": item.description,
            "cron_hour": item.cron_hour,
            "cron_minute": item.cron_minute,
            "weekdays": item.weekdays,
            "message_text": item.message_text,
        }
        for item in SCHEDULED_TEMPLATES
    ]


def get_scheduled_template(key: str) -> dict | None:
    raw = (key or "").strip().lower()
    if not raw:
        return None
    for item in list_scheduled_templates():
        if item["key"] == raw or item["name"] == key:
            return dict(item)
    return None
