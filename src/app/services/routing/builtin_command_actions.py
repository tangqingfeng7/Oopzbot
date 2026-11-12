from dataclasses import dataclass

from app.services.runtime import CommandRuntimeView, sender_of
from core.database import MessageStatsDB, ReminderDB, ScheduledMessageDB, SongCache
from oopz.name_resolver import get_resolver


class CommunityCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    async def show_members(self, channel: str, area: str) -> None:
        await self._services.community.member.show_members(channel, area)

    async def show_profile(self, channel: str, area: str, user: str) -> None:
        await self._services.community.member.show_profile(channel, area, user)

    async def show_myinfo(self, channel: str, area: str, user: str) -> None:
        await self._services.community.member.show_myinfo(channel, area, user)

    async def show_whois(self, target: str, channel: str, area: str, user: str = "") -> None:
        await self._services.community.member.show_whois(target, channel, area, user)

    async def show_user_roles(self, target: str, channel: str, area: str) -> None:
        await self._services.community.role.show_user_roles(target, channel, area)

    async def show_assignable_roles(self, target: str, channel: str, area: str) -> None:
        await self._services.community.role.show_assignable_roles(target, channel, area)

    async def give_role(self, target: str, role_name: str, channel: str, area: str) -> None:
        await self._services.community.role.give_role(target, role_name, channel, area)

    async def remove_role(self, target: str, role_name: str, channel: str, area: str) -> None:
        await self._services.community.role.remove_role(target, role_name, channel, area)

    async def search_members(self, keyword: str, channel: str, area: str, user: str = "") -> None:
        await self._services.community.member.search_members(keyword, channel, area, user)


class InteractionCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services
        self._sender = sender_of(runtime)

    async def show_voice_channels(self, channel: str, area: str) -> None:
        await self._services.interaction.common.show_voice_channels(channel, area)

    async def enter_channel(self, channel_id: str, channel: str, area: str) -> None:
        await self._services.interaction.common.enter_channel(channel_id, channel, area)

    async def show_daily_speech(self, channel: str, area: str) -> None:
        await self._services.interaction.common.show_daily_speech(channel, area)

    async def show_help(self, channel: str, area: str, user: str, topic: str = "") -> None:
        await self._services.interaction.help.show_help(channel, area, user, topic)

    async def show_health_check(self, channel: str, area: str) -> None:
        await self._services.interaction.setup.show_health_check(channel, area)

    async def show_setup_wizard(self, channel: str, area: str, user: str = "") -> None:
        await self._services.interaction.setup.show_setup_wizard(channel, area, user)

    async def handle_pick(self, raw: str, channel: str, area: str, user: str, usage: str) -> None:
        """选择候选编号：先试点歌候选，再试成员候选（mention/slash 共用）。"""
        token = (raw or "").strip()
        if not token.isdigit():
            await self._sender.send_message(usage, channel=channel, area=area)
            return
        index = int(token)
        if await self._services.interaction.music.handle_pick(index, channel, area, user):
            return
        if await self._services.community.member.handle_pick(index, channel, area, user):
            return
        await self._sender.send_message("当前没有可选择的候选结果，请先搜索或搜歌", channel=channel, area=area)


class ModerationCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services
        self._sender = sender_of(runtime)

    def _normalize_target_text(self, raw: str) -> str:
        """管理命令失败时尽量只回显目标用户部分。"""
        target = raw.strip()
        parts = target.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
        return target

    async def _send_target_error(self, raw: str, usage: str, channel: str, area: str) -> None:
        """参数为空时提示用法，参数有值但解析失败时提示找不到用户。"""
        target = self._normalize_target_text(raw)
        if not target:
            await self._sender.send_message(usage, channel=channel, area=area)
            return
        await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)

    async def _resolve(
        self, raw: str, channel: str, area: str, usage: str, *, with_duration: bool = False,
    ) -> tuple[str | None, int | None]:
        """解析管理命令的目标用户；失败时已回复用户，调用方只需检查 uid。"""
        resolution = self._services.community.target_resolution
        try:
            if with_duration:
                uid, duration = await resolution.parse_mute_args(raw, area=area)
            else:
                uid, duration = await resolution.resolve_target(raw, area=area), None
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return None, None
        if not uid:
            await self._send_target_error(raw, usage, channel, area)
        return uid, duration

    async def mute_user(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, duration = await self._resolve(raw, channel, area, usage, with_duration=True)
        if uid:
            await self._services.safety.moderation.mute_user(uid, duration, channel, area)

    async def unmute_user(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, _ = await self._resolve(raw, channel, area, usage)
        if uid:
            await self._services.safety.moderation.unmute_user(uid, channel, area)

    async def mute_mic(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, duration = await self._resolve(raw, channel, area, usage, with_duration=True)
        if uid:
            await self._services.safety.moderation.mute_mic(uid, channel, area, duration)

    async def unmute_mic(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, _ = await self._resolve(raw, channel, area, usage)
        if uid:
            await self._services.safety.moderation.unmute_mic(uid, channel, area)

    async def remove_from_area(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, _ = await self._resolve(raw, channel, area, usage)
        if uid:
            await self._services.safety.moderation.remove_from_area(uid, channel, area)

    async def unblock_in_area(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, _ = await self._resolve(raw, channel, area, usage)
        if uid:
            await self._services.safety.moderation.unblock_in_area(uid, channel, area)

    async def show_block_list(self, channel: str, area: str) -> None:
        await self._services.safety.moderation.show_block_list(channel, area)


class RecallCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    async def recall(self, arg: str | None, channel: str, area: str) -> None:
        if arg and arg.isdigit():
            await self._services.safety.recall.recall_multiple(int(arg), channel, area)
            return
        await self._services.safety.recall.recall_message(arg, channel, area)

    async def recall_multiple(self, count: int, channel: str, area: str) -> None:
        await self._services.safety.recall.recall_multiple(count, channel, area)

    async def configure_auto_recall(self, arg: str, channel: str, area: str) -> None:
        await self._services.safety.recall.configure_auto_recall(arg, channel, area)

    async def clear_history(self, channel: str, area: str) -> None:
        await self._services.safety.recall.clear_history(channel, area)


class PluginCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    async def show_plugin_list(self, channel: str, area: str) -> None:
        await self._services.plugins.management.show_plugin_list(channel, area)

    async def load_plugin(self, name: str, channel: str, area: str) -> None:
        await self._services.plugins.management.load(name, channel, area)

    async def unload_plugin(self, name: str, channel: str, area: str) -> None:
        await self._services.plugins.management.unload(name, channel, area)

    async def reload_plugin_config(self, name: str, channel: str, area: str) -> None:
        await self._services.plugins.management.reload_config(name, channel, area)



class SchedulerCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services
        self._sender = sender_of(runtime)

    # ------------------------------------------------------------------
    # 用户提醒
    # ------------------------------------------------------------------

    async def set_reminder(self, raw: str, channel: str, area: str, user: str) -> None:
        reminder_svc = self._services.scheduler.reminder
        reply = await reminder_svc.create_reminder(raw, channel, area, user)
        await self._sender.send_message(reply, channel=channel, area=area)

    async def list_reminders(self, channel: str, area: str, user: str) -> None:
        pending = await ReminderDB.get_user_pending(user)
        if not pending:
            await self._sender.send_message("你没有待执行的提醒", channel=channel, area=area)
            return
        lines = ["【我的待执行提醒】"]
        for r in pending:
            lines.append(f"[{r['id']}] {r['fire_at'][:16]}  {r['message_text'][:50]}")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def delete_reminder(self, raw: str, channel: str, area: str, user: str) -> None:
        rid = raw.strip()
        if not rid.isdigit():
            await self._sender.send_message("用法: 删除提醒 <ID>\n先用 \"我的提醒\" 查看 ID", channel=channel, area=area)
            return
        ok = await ReminderDB.delete_user_reminder(int(rid), user)
        if ok:
            await self._sender.send_message(f"已删除提醒 {rid}", channel=channel, area=area)
        else:
            await self._sender.send_message(f"未找到提醒 {rid}（可能已触发或不属于你）", channel=channel, area=area)

    # ------------------------------------------------------------------
    # 管理员定时消息
    # ------------------------------------------------------------------

    async def list_scheduled(self, channel: str, area: str) -> None:
        tasks = await ScheduledMessageDB.get_all()
        if not tasks:
            await self._sender.send_message("暂无定时消息", channel=channel, area=area)
            return
        lines = ["【定时消息列表】"]
        for t in tasks:
            status = "启用" if t["enabled"] else "停用"
            wdays = t["weekdays"]
            lines.append(
                f"[{t['id']}] {t['name']} | {t['cron_hour']:02d}:{t['cron_minute']:02d} "
                f"| 星期 {wdays} | {status}\n  → {t['message_text'][:50]}"
            )
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def add_scheduled(self, raw: str, channel: str, area: str) -> None:
        """格式: HH:MM 内容  或  HH:MM [星期] 内容"""
        import re
        m = re.match(r"(\d{1,2})[:\uff1a](\d{2})\s+(.+)", raw.strip(), re.DOTALL)
        if not m:
            await self._sender.send_message(
                "用法: 添加定时消息 08:00 早上好\n或: 添加定时消息 08:00 [1,2,3,4,5] 工作日快乐",
                channel=channel, area=area,
            )
            return
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await self._sender.send_message(
                "时间不合法，小时需 0-23、分钟需 0-59，例如 08:00",
                channel=channel, area=area,
            )
            return
        rest = m.group(3).strip()

        weekdays = "0,1,2,3,4,5,6"
        wm = re.match(r"\[([0-6,]+)\]\s+(.+)", rest, re.DOTALL)
        if wm:
            weekdays = wm.group(1)
            rest = wm.group(2).strip()

        if not rest:
            await self._sender.send_message("请提供消息内容", channel=channel, area=area)
            return

        name = rest[:20]
        task_id = await ScheduledMessageDB.create(
            name,
            hour,
            minute,
            channel,
            area,
            rest,
            weekdays,
        )
        await self._sender.send_message(
            f"定时消息已创建 (ID: {task_id})\n时间: {hour:02d}:{minute:02d} | 星期: {weekdays}\n内容: {rest[:50]}",
            channel=channel, area=area,
        )

    async def delete_scheduled(self, raw: str, channel: str, area: str) -> None:
        task_id = raw.strip()
        if not task_id.isdigit():
            await self._sender.send_message("用法: 删除定时消息 <ID>", channel=channel, area=area)
            return
        if await ScheduledMessageDB.delete(int(task_id)):
            await self._sender.send_message(f"定时消息 {task_id} 已删除", channel=channel, area=area)
        else:
            await self._sender.send_message(f"未找到定时消息 {task_id}", channel=channel, area=area)

    async def toggle_scheduled(self, raw: str, channel: str, area: str, enable: bool) -> None:
        task_id = raw.strip()
        if not task_id.isdigit():
            await self._sender.send_message("用法: 开启/关闭定时消息 <ID>", channel=channel, area=area)
            return
        task = await ScheduledMessageDB.get_by_id(int(task_id))
        if not task:
            await self._sender.send_message(f"未找到定时消息 {task_id}", channel=channel, area=area)
            return
        await ScheduledMessageDB.update(int(task_id), enabled=1 if enable else 0)
        status = "已启用" if enable else "已停用"
        await self._sender.send_message(f"定时消息 {task_id} {status}", channel=channel, area=area)

    # ------------------------------------------------------------------
    # 活跃排行 & 频道统计
    # ------------------------------------------------------------------

    async def show_ranking(self, channel: str, area: str) -> None:
        ranking = await MessageStatsDB.get_user_ranking(area, 7, 10)
        if not ranking:
            await self._sender.send_message("暂无活跃数据", channel=channel, area=area)
            return
        resolver = get_resolver()
        lines = ["【近 7 天活跃排行】"]
        for i, r in enumerate(ranking):
            prefix = f" {i + 1}."
            display_name = resolver.user(r["user_id"])
            lines.append(f"{prefix} {display_name}  —  {r['total']} 条消息")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_channel_stats(self, channel: str, area: str) -> None:
        daily = await MessageStatsDB.get_channel_daily(channel, area, 7)
        if not daily:
            await self._sender.send_message("暂无频道统计数据", channel=channel, area=area)
            return
        lines = ["【近 7 天频道消息统计】"]
        total = 0
        for d in daily:
            lines.append(f"  {d['date']}  —  {d['total']} 条")
            total += d["total"]
        lines.append(f"合计: {total} 条")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    # ------------------------------------------------------------------
    # 播放排行
    # ------------------------------------------------------------------

    async def show_music_ranking(self, channel: str, area: str) -> None:
        songs = await SongCache.get_top_songs(10)
        if not songs:
            await self._sender.send_message("暂无播放记录", channel=channel, area=area)
            return
        lines = ["【点歌排行榜 Top 10】"]
        for i, s in enumerate(songs):
            artist = s.get("artist", "未知")
            name = s.get("song_name", "未知")
            count = s.get("play_count", 0)
            lines.append(f" {i + 1}. {name} - {artist}  ({count}次)")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_recent_songs(self, channel: str, area: str) -> None:
        songs = await SongCache.get_recent_songs(10)
        if not songs:
            await self._sender.send_message("暂无播放记录", channel=channel, area=area)
            return
        lines = ["【最近播放】"]
        for i, s in enumerate(songs):
            artist = s.get("artist", "未知")
            name = s.get("song_name", "未知")
            played = s.get("last_played_at", "")[:16]
            lines.append(f" {i + 1}. {name} - {artist}  ({played})")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)


@dataclass(frozen=True)
class BuiltinCommandActions:
    community: CommunityCommandActions
    interaction: InteractionCommandActions
    moderation: ModerationCommandActions
    recall: RecallCommandActions
    plugins: PluginCommandActions
    scheduler: SchedulerCommandActions


def build_builtin_command_actions(runtime: CommandRuntimeView) -> BuiltinCommandActions:
    return BuiltinCommandActions(
        community=CommunityCommandActions(runtime),
        interaction=InteractionCommandActions(runtime),
        moderation=ModerationCommandActions(runtime),
        recall=RecallCommandActions(runtime),
        plugins=PluginCommandActions(runtime),
        scheduler=SchedulerCommandActions(runtime),
    )
