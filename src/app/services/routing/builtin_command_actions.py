from dataclasses import dataclass

from app.services.runtime import CommandRuntimeView, sender_of


class CommunityCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    def show_members(self, channel: str, area: str) -> None:
        self._services.community.member.show_members(channel, area)

    def show_profile(self, channel: str, area: str, user: str) -> None:
        self._services.community.member.show_profile(channel, area, user)

    def show_myinfo(self, channel: str, area: str, user: str) -> None:
        self._services.community.member.show_myinfo(channel, area, user)

    def show_whois(self, target: str, channel: str, area: str) -> None:
        self._services.community.member.show_whois(target, channel, area)

    def show_user_roles(self, target: str, channel: str, area: str) -> None:
        self._services.community.role.show_user_roles(target, channel, area)

    def show_assignable_roles(self, target: str, channel: str, area: str) -> None:
        self._services.community.role.show_assignable_roles(target, channel, area)

    def give_role(self, target: str, role_name: str, channel: str, area: str) -> None:
        self._services.community.role.give_role(target, role_name, channel, area)

    def remove_role(self, target: str, role_name: str, channel: str, area: str) -> None:
        self._services.community.role.remove_role(target, role_name, channel, area)

    def search_members(self, keyword: str, channel: str, area: str) -> None:
        self._services.community.member.search_members(keyword, channel, area)


class InteractionCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    def show_voice_channels(self, channel: str, area: str) -> None:
        self._services.interaction.common.show_voice_channels(channel, area)

    def enter_channel(self, channel_id: str, channel: str, area: str) -> None:
        self._services.interaction.common.enter_channel(channel_id, channel, area)

    def show_daily_speech(self, channel: str, area: str) -> None:
        self._services.interaction.common.show_daily_speech(channel, area)

    def show_help(self, channel: str, area: str, user: str) -> None:
        self._services.interaction.help.show_help(channel, area, user)

    def generate_image(self, prompt: str, channel: str, area: str, user: str) -> None:
        self._services.interaction.common.generate_image(prompt, channel, area, user)


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

    def _send_target_error(self, raw: str, usage: str, channel: str, area: str) -> None:
        """参数为空时提示用法，参数有值但解析失败时提示找不到用户。"""
        target = self._normalize_target_text(raw)
        if not target:
            self._sender.send_message(usage, channel=channel, area=area)
            return
        self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)

    def mute_user(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, duration = self._services.community.target_resolution.parse_mute_args(raw, area=area)
        if uid:
            self._services.safety.moderation.mute_user(uid, duration, channel, area)
            return
        self._send_target_error(raw, usage, channel, area)

    def unmute_user(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid = self._services.community.target_resolution.resolve_target(raw, area=area)
        if uid:
            self._services.safety.moderation.unmute_user(uid, channel, area)
            return
        self._send_target_error(raw, usage, channel, area)

    def mute_mic(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid, duration = self._services.community.target_resolution.parse_mute_args(raw, area=area)
        if uid:
            self._services.safety.moderation.mute_mic(uid, channel, area, duration)
            return
        self._send_target_error(raw, usage, channel, area)

    def unmute_mic(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid = self._services.community.target_resolution.resolve_target(raw, area=area)
        if uid:
            self._services.safety.moderation.unmute_mic(uid, channel, area)
            return
        self._send_target_error(raw, usage, channel, area)

    def remove_from_area(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid = self._services.community.target_resolution.resolve_target(raw, area=area)
        if uid:
            self._services.safety.moderation.remove_from_area(uid, channel, area)
            return
        self._send_target_error(raw, usage, channel, area)

    def unblock_in_area(self, raw: str, channel: str, area: str, usage: str) -> None:
        uid = self._services.community.target_resolution.resolve_target(raw, area=area)
        if uid:
            self._services.safety.moderation.unblock_in_area(uid, channel, area)
            return
        self._send_target_error(raw, usage, channel, area)

    def show_block_list(self, channel: str, area: str) -> None:
        self._services.safety.moderation.show_block_list(channel, area)


class RecallCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    def recall(self, arg: str | None, channel: str, area: str) -> None:
        if arg and arg.isdigit():
            self._services.safety.recall.recall_multiple(int(arg), channel, area)
            return
        self._services.safety.recall.recall_message(arg, channel, area)

    def recall_multiple(self, count: int, channel: str, area: str) -> None:
        self._services.safety.recall.recall_multiple(count, channel, area)

    def configure_auto_recall(self, arg: str, channel: str, area: str) -> None:
        self._services.safety.recall.configure_auto_recall(arg, channel, area)

    def clear_history(self, channel: str, area: str) -> None:
        self._services.safety.recall.clear_history(channel, area)


class PluginCommandActions:
    def __init__(self, runtime: CommandRuntimeView):
        self._services = runtime.services

    def show_plugin_list(self, channel: str, area: str) -> None:
        self._services.plugins.management.show_plugin_list(channel, area)

    def load_plugin(self, name: str, channel: str, area: str) -> None:
        self._services.plugins.management.load(name, channel, area)

    def unload_plugin(self, name: str, channel: str, area: str) -> None:
        self._services.plugins.management.unload(name, channel, area)


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
