"""管理域服务。"""

from typing import TYPE_CHECKING

from name_resolver import NameResolver, get_resolver


if TYPE_CHECKING:
    from command_handler import CommandHandler


class ModerationService:
    """处理禁言、禁麦、移出域和封禁列表。"""

    def __init__(self, handler: "CommandHandler"):
        self._handler = handler
        self._sender = handler.infrastructure.sender

    def mute_user(self, uid: str, duration: int, channel: str, area: str) -> None:
        """执行禁言。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.mute_user(uid, area=area, duration=duration)
        if "error" in result:
            self._sender.send_message(f"[x] 禁言 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(f"[ok] {result.get('message', f'已禁言 {name}')}", channel=channel, area=area)

    def unmute_user(self, uid: str, channel: str, area: str) -> None:
        """执行解除禁言。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.unmute_user(uid, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 解除禁言 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(
            f"[ok] {result.get('message', f'已解除 {name} 的禁言')}",
            channel=channel,
            area=area,
        )

    def mute_mic(self, uid: str, channel: str, area: str, duration: int = 10) -> None:
        """执行禁麦。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.mute_mic(uid, area=area, duration=duration)
        if "error" in result:
            self._sender.send_message(f"[x] 禁麦 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(f"[ok] {result.get('message', f'已禁麦 {name}')}", channel=channel, area=area)

    def unmute_mic(self, uid: str, channel: str, area: str) -> None:
        """执行解除禁麦。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.unmute_mic(uid, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 解除禁麦 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(
            f"[ok] {result.get('message', f'已解除 {name} 的禁麦')}",
            channel=channel,
            area=area,
        )

    def remove_from_area(self, uid: str, channel: str, area: str) -> None:
        """将用户移出当前域。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.remove_from_area(uid, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 移出域 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(f"[ok] {result.get('message', f'已移出域 {name}')}", channel=channel, area=area)

    def unblock_in_area(self, uid: str, channel: str, area: str) -> None:
        """解除域内封禁。"""
        name = NameResolver().user(uid) or uid[:8]
        result = self._sender.unblock_user_in_area(uid, area=area)
        if "error" in result:
            self._sender.send_message(f"[x] 解除域内封禁 {name} 失败: {result['error']}", channel=channel, area=area)
            return
        self._sender.send_message(
            f"[ok] {result.get('message', f'已解除 {name} 的域内封禁')}",
            channel=channel,
            area=area,
        )

    def show_block_list(self, channel: str, area: str) -> None:
        """展示当前域封禁列表。"""
        resolver = get_resolver()
        data = self._sender.get_area_blocks(area=area)
        if "error" in data:
            self._sender.send_message(f"获取域封禁列表失败: {data['error']}", channel=channel, area=area)
            return

        blocks = data.get("blocks", [])
        area_name = resolver.area(area)
        if not blocks:
            self._sender.send_message(f"{area_name} 当前无封禁用户。", channel=channel, area=area)
            return

        lines = [f"{area_name} - 封禁列表（共 {len(blocks)} 人）", "---"]
        for index, item in enumerate(blocks, 1):
            uid = item.get("uid") or item.get("person") or item.get("target") or str(item)
            if isinstance(uid, dict):
                uid = uid.get("uid") or uid.get("person") or ""
            name = resolver.user(uid) if isinstance(uid, str) else ""
            display = f"{name} ({uid[:8]}...)" if name else uid[:16] + "..."
            lines.append(f"{index}. {display}")

        lines.append("--- 使用 /unblock 用户 或 @bot 解封 用户 解除封禁")
        self._sender.send_message("\n".join(lines), channel=channel, area=area)
