from dataclasses import dataclass

from app.services.runtime import CommandRuntimeView, sender_of


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


@dataclass(frozen=True)
class BuiltinCommandActions:
    community: CommunityCommandActions
    interaction: InteractionCommandActions
    moderation: ModerationCommandActions
    recall: RecallCommandActions
    plugins: PluginCommandActions


def build_builtin_command_actions(runtime: CommandRuntimeView) -> BuiltinCommandActions:
    return BuiltinCommandActions(
        community=CommunityCommandActions(runtime),
        interaction=InteractionCommandActions(runtime),
        moderation=ModerationCommandActions(runtime),
        recall=RecallCommandActions(runtime),
        plugins=PluginCommandActions(runtime),
    )
