"""定时消息与用户提醒插件。"""

from collections.abc import Callable

from fastapi import APIRouter

from domain.plugins.base import BotModule, PluginCommandCapabilities, PluginMetadata
from domain.plugins.plugin_config import (
    PluginConfigField,
    PluginConfigSpec,
    parse_int,
    validate_range,
)
from plugins._shared.command_mixin import PluginCommandMixin
from web.plugin_routes import AdminNavItem

from . import admin
from .commands import REMIND_USAGE, SchedulerCommands
from .service import ReminderService, ScheduledMessageService

_REMIND_LIST = ("我的提醒", "提醒列表")
_SCHEDULE_LIST = ("定时消息列表", "定时消息")
# 按前缀匹配的 mention 命令：前缀 -> (分组, 动作)；匹配时长前缀优先。
_PREFIX_ACTIONS: dict[str, tuple[str, str]] = {
    "删除提醒": ("remind", "del"),
    "取消提醒": ("remind", "del"),
    "提醒": ("remind", "set"),
    "添加定时消息": ("schedule", "add"),
    "新增定时消息": ("schedule", "add"),
    "删除定时消息": ("schedule", "del"),
    "移除定时消息": ("schedule", "del"),
    "开启定时消息": ("schedule", "on"),
    "启用定时消息": ("schedule", "on"),
    "关闭定时消息": ("schedule", "off"),
    "停用定时消息": ("schedule", "off"),
}
_REMIND_SLASH = ("/remind", "/提醒")
_SCHEDULE_SLASH = ("/schedule",)


def _int_field(name: str, default: int, low: int, high: int, description: str) -> PluginConfigField:
    return PluginConfigField(
        name,
        default=default,
        cast=parse_int,
        validator=validate_range(low, high),
        description=description,
        constraint=f"{low} - {high}",
    )


class SchedulerPlugin(PluginCommandMixin, BotModule):
    command_error_prefix = "定时任务出错"
    command_log_name = "Scheduler"

    def __init__(self):
        self._scheduled: ScheduledMessageService | None = None
        self._reminder: ReminderService | None = None
        self._unregister_web: Callable[[], None] | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("scheduler", "管理员定时消息与用户提醒")

    @property
    def command_capabilities(self) -> PluginCommandCapabilities:
        # 提醒对所有人开放；定时消息在命令内部校验管理员。
        return PluginCommandCapabilities(
            mention_prefixes=(*_REMIND_LIST, *_SCHEDULE_LIST, *_PREFIX_ACTIONS),
            slash_commands=(*_REMIND_SLASH, *_SCHEDULE_SLASH),
        )

    @property
    def config_spec(self) -> PluginConfigSpec:
        return PluginConfigSpec((
            _int_field("scheduled_check_interval_seconds", 30, 10, 3600, "定时消息检查间隔（秒）"),
            _int_field("reminder_check_interval_seconds", 15, 5, 3600, "提醒检查间隔（秒）"),
            _int_field("reminder_max_per_user", 5, 1, 100, "每个用户最多的待执行提醒数"),
            _int_field("reminder_max_delay_hours", 72, 1, 720, "提醒最远可设置到多少小时后"),
        ))

    @property
    def private_modules(self) -> tuple[str, ...]:
        return tuple(f"{__name__}.{name}" for name in ("admin", "commands", "service", "templates"))

    async def handle_mention(self, text, channel, area, user, handler) -> bool:
        stripped = text.strip()
        if stripped in _REMIND_LIST:
            command = "remind list"
        elif stripped in _SCHEDULE_LIST:
            command = "schedule list"
        else:
            prefix = next(
                (p for p in sorted(_PREFIX_ACTIONS, key=len, reverse=True) if stripped.startswith(p)),
                None,
            )
            if prefix is None:
                return False
            group, action = _PREFIX_ACTIONS[prefix]
            command = f"{group} {action} {stripped[len(prefix):].strip()}"
        await self._run_plugin_command(command, channel, area, user, handler)
        return True

    async def handle_slash(self, command, subcommand, arg, channel, area, user, handler) -> bool:
        name = (command or "").strip().lower()
        sub = (subcommand or "").lower()
        if name in _REMIND_SLASH:
            if sub == "list":
                text = "remind list"
            elif sub == "del" and arg:
                text = f"remind del {arg}"
            elif subcommand:
                text = " ".join(("remind set", subcommand, arg or ""))
            else:
                await self._send(handler, REMIND_USAGE, channel, area)
                return True
        elif name in _SCHEDULE_SLASH:
            text = f"schedule {sub or 'list'} {arg or ''}"
        else:
            return False
        await self._run_plugin_command(text, channel, area, user, handler)
        return True

    async def dispatch_command(self, command_text, channel, area, user, handler) -> None:
        group, action, arg = [*command_text.split(None, 2), "", ""][:3]
        if self._reminder is None:
            raise RuntimeError("插件尚未加载完成")
        await SchedulerCommands(handler, self._reminder).run(group, action, arg, channel, area, user)

    async def on_load(self, handler, config=None) -> None:
        await self._stop_workers()
        config = config or {}
        self._scheduled = ScheduledMessageService(
            handler.sender,
            interval=config.get("scheduled_check_interval_seconds", 30),
        )
        self._reminder = ReminderService(
            handler.sender,
            interval=config.get("reminder_check_interval_seconds", 15),
            max_per_user=config.get("reminder_max_per_user", 5),
            max_delay_hours=config.get("reminder_max_delay_hours", 72),
        )
        self._scheduled.start()
        self._reminder.start()
        if self._unregister_web is None:
            router = APIRouter()
            router.include_router(admin.router)
            self._unregister_web = handler.register_web(
                router,
                admin_nav=AdminNavItem("scheduler", "/admin/scheduler", "定时"),
            )

    async def on_unload(self) -> None:
        if self._unregister_web is not None:
            self._unregister_web()
            self._unregister_web = None
        await self._stop_workers()

    async def _stop_workers(self) -> None:
        for worker in (self._scheduled, self._reminder):
            if worker is not None:
                await worker.stop()
