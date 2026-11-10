import datetime

from app.services.runtime import CommandRuntimeView, sender_of
from core.constants import Msg
from domain.community.role_rules import resolve_role_id
from oopz.name_resolver import get_resolver


class RoleService:
    """处理角色查询、可分配角色和角色增删。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    async def show_user_roles(self, target: str, channel: str, area: str) -> None:
        """查看指定用户在域内的角色和禁言/禁麦状态。"""
        try:
            uid = await self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return
        if not uid:
            await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        resolver = get_resolver()
        name = resolver.user(uid)

        try:
            data = await self._sender.bot.areas.get_area_user_detail(area, uid)
        except Exception as exc:
            await self._sender.send_message(f"查询角色失败: {exc}", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        lines = [f"{name} 在 {area_name} 的角色信息", "---"]

        roles = data.roles
        if roles:
            lines.append("角色列表:")
            for role in roles:
                lines.append(f"  - {role.name or '未知'} (ID={role.role_id})")
        else:
            lines.append("  无角色")

        text_mute = int(data.disable_text_to or 0)
        voice_mute = int(data.disable_voice_to or 0)
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

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def show_assignable_roles(self, target: str, channel: str, area: str) -> None:
        """查看可以分配给目标用户的角色列表。"""
        try:
            uid = await self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return
        if not uid:
            await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        try:
            roles = await self._sender.bot.areas.get_area_can_give_list(area, uid)
        except Exception as exc:
            await self._sender.send_message(f"查询可分配角色失败: {exc}", channel=channel, area=area)
            return
        if not roles:
            await self._sender.send_message(f"没有可分配给 {name} 的角色", channel=channel, area=area)
            return

        lines = [f"可分配给 {name} 的角色", "---"]
        for role in roles:
            owned = " [已拥有]" if role.owned else ""
            lines.append(f"  - {role.name or '未知'} (ID={role.role_id}){owned}")

        await self._sender.send_message("\n".join(lines), channel=channel, area=area)

    async def give_role(self, target: str, role_arg: str, channel: str, area: str) -> None:
        """给目标用户添加身份组。"""
        try:
            uid = await self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return
        if not uid:
            await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        try:
            roles = await self._sender.bot.areas.get_area_can_give_list(area, uid)
        except Exception as exc:
            await self._sender.send_message(f"查询可分配角色失败: {exc}", channel=channel, area=area)
            return
        if not roles:
            await self._sender.send_message(f"没有可分配给 {name} 的身份组", channel=channel, area=area)
            return

        role_id = resolve_role_id(((role.role_id, role.name) for role in roles), role_arg)
        if role_id is None:
            await self._sender.send_message(
                f'未找到身份组 "{role_arg}"。可用 /roles {target} 查看可分配列表',
                channel=channel,
                area=area,
            )
            return

        try:
            result = await self._sender.edit_user_role(uid, role_id, add=True, area=area)
            if not result.ok:
                raise RuntimeError(result.message or "修改身份组被拒绝")
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 给 {name} 添加身份组失败: {exc}", channel=channel, area=area)
            return

        await self._sender.send_message(
            f"{Msg.OK} {result.message or f'已给 {name} 添加身份组'}",
            channel=channel,
            area=area,
        )

    async def remove_role(self, target: str, role_arg: str, channel: str, area: str) -> None:
        """取消目标用户的指定身份组。"""
        try:
            uid = await self._runtime.services.community.target_resolution.resolve_target(target, area=area)
        except Exception as exc:
            await self._sender.send_message(f"查询成员失败: {exc}", channel=channel, area=area)
            return
        if not uid:
            await self._sender.send_message(f"找不到用户: {target}", channel=channel, area=area)
            return

        name = get_resolver().user(uid)
        try:
            detail = await self._sender.bot.areas.get_area_user_detail(area, uid)
        except Exception as exc:
            await self._sender.send_message(f"获取用户角色失败: {exc}", channel=channel, area=area)
            return

        role_list = detail.roles
        if not role_list:
            await self._sender.send_message(f"{name} 当前没有可取消的身份组", channel=channel, area=area)
            return

        role_id = resolve_role_id(((role.role_id, role.name) for role in role_list), role_arg)
        if role_id is None:
            await self._sender.send_message(
                f'未找到身份组 "{role_arg}"。可用 /role {target} 查看当前角色',
                channel=channel,
                area=area,
            )
            return

        try:
            result = await self._sender.edit_user_role(uid, role_id, add=False, area=area)
            if not result.ok:
                raise RuntimeError(result.message or "修改身份组被拒绝")
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 取消 {name} 身份组失败: {exc}", channel=channel, area=area)
            return

        await self._sender.send_message(
            f"{Msg.OK} {result.message or f'已取消 {name} 的该身份组'}",
            channel=channel,
            area=area,
        )
