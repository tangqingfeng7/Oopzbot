import datetime

from domain.community.role_rules import resolve_role_id
from name_resolver import get_resolver
from app.services.runtime import CommandRuntimeView, sender_of


class RoleService:
    """处理角色查询、可分配角色和角色增删。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    def show_user_roles(self, target: str, channel: str, area: str) -> None:
        """查看指定用户在域内的角色和禁言/禁麦状态。"""
        uid = self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        if not uid:
            self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        resolver = get_resolver()
        name = resolver.user(uid)

        data = self._sender.get_user_area_detail(uid, area=area)
        if "error" in data:
            self._sender.send_message(f"查询角色失败: {data['error']}", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        lines = [f"{name} 在 {area_name} 的角色信息", "---"]

        roles = data.get("list", [])
        if roles:
            lines.append("角色列表:")
            for role in roles:
                lines.append(f"  - {role.get('name', '未知')} (ID={role.get('roleID', '?')})")
        else:
            lines.append("  无角色")

        text_mute = data.get("disableTextTo", 0)
        voice_mute = data.get("disableVoiceTo", 0)
        if text_mute and text_mute > 0:
            end = datetime.datetime.fromtimestamp(text_mute / 1000).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  禁言至: {end}")
        else:
            lines.append("  禁言: 无")

        if voice_mute and voice_mute > 0:
            end = datetime.datetime.fromtimestamp(voice_mute / 1000).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  禁麦至: {end}")
        else:
            lines.append("  禁麦: 无")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def show_assignable_roles(self, target: str, channel: str, area: str) -> None:
        """查看可以分配给目标用户的角色列表。"""
        uid = self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        if not uid:
            self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        roles = self._sender.get_assignable_roles(uid, area=area)
        if not roles:
            self._sender.send_message(f"没有可分配给 {name} 的角色", channel=channel, area=area)
            return

        lines = [f"可分配给 {name} 的角色", "---"]
        for role in roles:
            owned = " [已拥有]" if role.get("owned") else ""
            lines.append(f"  - {role.get('name', '未知')} (ID={role.get('roleID', '?')}){owned}")

        self._sender.send_message("\n".join(lines), channel=channel, area=area)

    def give_role(self, target: str, role_arg: str, channel: str, area: str) -> None:
        """给目标用户添加身份组。"""
        uid = self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        if not uid:
            self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        roles = self._sender.get_assignable_roles(uid, area=area)
        if not roles:
            self._sender.send_message(f"没有可分配给 {name} 的身份组", channel=channel, area=area)
            return

        role_id = resolve_role_id(roles, role_arg)
        if role_id is None:
            self._sender.send_message(
                f'未找到身份组 "{role_arg}"。可用 /roles {target} 查看可分配列表',
                channel=channel,
                area=area,
            )
            return

        result = self._sender.edit_user_role(uid, role_id, add=True, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 给 {name} 添加身份组失败: {result['error']}", channel=channel, area=area)
            return

        self._sender.send_message(
            f"[ok] {result.get('message', f'已给 {name} 添加身份组')}",
            channel=channel,
            area=area,
        )

    def remove_role(self, target: str, role_arg: str, channel: str, area: str) -> None:
        """取消目标用户的指定身份组。"""
        uid = self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        if not uid:
            self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        detail = self._sender.get_user_area_detail(uid, area=area)
        if "error" in detail:
            self._sender.send_message(f"获取用户角色失败: {detail['error']}", channel=channel, area=area)
            return

        role_list = detail.get("list") or []
        if not role_list:
            self._sender.send_message(f"{name} 当前没有可取消的身份组", channel=channel, area=area)
            return

        role_id = resolve_role_id(role_list, role_arg)
        if role_id is None:
            self._sender.send_message(
                f'未找到身份组 "{role_arg}"。可用 /role {target} 查看当前角色',
                channel=channel,
                area=area,
            )
            return

        result = self._sender.edit_user_role(uid, role_id, add=False, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 取消 {name} 身份组失败: {result['error']}", channel=channel, area=area)
            return

        self._sender.send_message(
            f"[ok] {result.get('message', f'已取消 {name} 的该身份组')}",
            channel=channel,
            area=area,
        )
