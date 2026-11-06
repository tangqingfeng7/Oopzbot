from app.infrastructure.member_cache import invalidate_members_cache
from app.services.runtime import CommandRuntimeView, sender_of
from core.constants import Msg
from oopz.name_resolver import NameResolver, get_resolver


class ModerationService:
    """处理禁言、禁麦、移出域和封禁列表。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)

    async def mute_user(self, uid: str, duration: int, channel: str, area: str) -> None:
        """执行禁言。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.mute_user(area, uid, duration=duration)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 禁言 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(f"{Msg.OK} {(result.message or f'已禁言 {name}')}", channel=channel, area=area)

    async def unmute_user(self, uid: str, channel: str, area: str) -> None:
        """执行解除禁言。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.unmute_user(area, uid)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 解除禁言 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(
            f"{Msg.OK} {(result.message or f'已解除 {name} 的禁言')}",
            channel=channel,
            area=area,
        )

    async def mute_mic(self, uid: str, channel: str, area: str, duration: int = 10) -> None:
        """执行禁麦。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.mute_mic(area, uid, duration=duration)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 禁麦 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(f"{Msg.OK} {(result.message or f'已禁麦 {name}')}", channel=channel, area=area)

    async def unmute_mic(self, uid: str, channel: str, area: str) -> None:
        """执行解除禁麦。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.unmute_mic(area, uid)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 解除禁麦 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(
            f"{Msg.OK} {(result.message or f'已解除 {name} 的禁麦')}",
            channel=channel,
            area=area,
        )

    async def remove_from_area(self, uid: str, channel: str, area: str) -> None:
        """将用户移出当前域。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.remove_from_area(area, uid)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 移出域 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(f"{Msg.OK} {(result.message or f'已移出域 {name}')}", channel=channel, area=area)

    async def unblock_in_area(self, uid: str, channel: str, area: str) -> None:
        """解除域内封禁。"""
        name = NameResolver().user(uid) or uid[:8]
        try:
            result = await self._sender.bot.moderation.unblock_user_in_area(area, uid)
            if not result.ok:
                raise RuntimeError(result.message or "操作被拒绝")
            invalidate_members_cache(self._sender.bot, area)
        except Exception as exc:
            await self._sender.send_message(f"{Msg.ERR} 解除域内封禁 {name} 失败: {exc}", channel=channel, area=area)
            return
        await self._sender.send_message(
            f"{Msg.OK} {(result.message or f'已解除 {name} 的域内封禁')}",
            channel=channel,
            area=area,
        )

    async def show_block_list(self, channel: str, area: str) -> None:
        """展示当前域封禁列表。"""
        resolver = get_resolver()
        try:
            blocks = await self._sender.bot.moderation.get_area_blocks(area)
        except Exception as exc:
            await self._sender.send_message(f"获取域封禁列表失败: {exc}", channel=channel, area=area)
            return

        area_name = resolver.area(area)
        if not blocks:
            await self._sender.send_message(f"{area_name} 当前无封禁用户。", channel=channel, area=area)
            return

        lines = [f"{area_name} - 封禁列表（共 {len(blocks)} 人）", "---"]
        for index, item in enumerate(blocks, 1):
            uid = item.uid
            name = resolver.user(uid)
            display = f"{name} ({uid[:8]}...)" if name else uid[:16] + "..."
            lines.append(f"{index}. {display}")

        lines.append("--- 使用 /unblock 用户 或 @bot 解封 用户 解除封禁")
        await self._sender.send_message("\n".join(lines), channel=channel, area=area)
