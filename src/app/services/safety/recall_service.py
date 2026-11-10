import asyncio
import os

from app.services.runtime import CommandRuntimeView, sender_of
from config import AUTO_RECALL_CONFIG
from core.constants import Msg
from core.database import SongCache
from core.logger_config import LOG_FILE, get_logger

logger = get_logger("RecallService")


class RecallService:
    """处理消息撤回、自动撤回和历史清理。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    async def recall_message(self, message_id: str | None, channel: str, area: str) -> None:
        """撤回指定消息。"""
        content_preview = ""
        recent = None

        if not message_id or message_id.lower() in ("last", "最后", "最后一条", "上一条"):
            if not self._runtime.recent_messages:
                await self._sender.send_message(
                    f"{Msg.ERR} 没有可撤回的消息记录",
                    channel=channel,
                    area=area,
                )
                return

            for message in reversed(self._runtime.recent_messages):
                if message.get("channel") == channel and message.get("area") == area:
                    recent = message
                    break

            if not recent:
                await self._sender.send_message(
                    f"{Msg.ERR} 在当前频道没有找到可撤回的消息\n请使用 /recall <消息ID> 或 @bot 撤回 <消息ID>",
                    channel=channel,
                    area=area,
                )
                return

            message_id = recent["messageId"]
            content_preview = recent.get("content", "")[:30]

        if not isinstance(message_id, str) or not message_id:
            await self._sender.send_message(
                f"{Msg.ERR} 消息记录缺少有效的消息 ID",
                channel=channel,
                area=area,
            )
            return

        try:
            timestamp = await self._runtime.services.safety.message_lookup.resolve_timestamp(message_id, channel, area)
            result = await self._sender.bot.messages.recall_message(message_id, channel=channel, timestamp=timestamp, area=area)
            if not result.ok:
                raise RuntimeError(result.message or "撤回被拒绝")
        except Exception as exc:
            error = str(exc)
            hint = ""
            if "record not found" in (error or "").lower() or "服务异常" in (error or ""):
                hint = "\n提示: 该消息可能已撤回/过期，或消息 ID 无效（请用长按消息复制得到的完整 ID）。"
            mid_preview = (message_id[:24] + "...") if len(str(message_id)) > 24 else str(message_id)
            await self._sender.send_message(
                f"{Msg.ERR} 撤回失败: {error}\n消息ID: {mid_preview}{hint}",
                channel=channel,
                area=area,
            )
            return

        preview = f" ({content_preview}...)" if content_preview else ""
        await self._sender.send_message(
            f"{Msg.OK} 消息已撤回{preview}\n消息ID: {message_id[:20]}...",
            channel=channel,
            area=area,
        )

    async def recall_multiple(self, count: int, channel: str, area: str) -> None:
        """批量撤回多条消息。"""
        if count <= 0:
            await self._sender.send_message(f"{Msg.ERR} 撤回数量必须大于 0", channel=channel, area=area)
            return

        if count > 100:
            await self._sender.send_message(f"{Msg.ERR} 最多只能一次撤回 100 条消息", channel=channel, area=area)
            return

        channel_messages = [
            message for message in self._runtime.recent_messages
            if message.get("channel") == channel and message.get("area") == area
        ]

        if len(channel_messages) < count:
            try:
                remote_messages = await self._sender.bot.messages.get_channel_messages(area, channel, count)
            except Exception as exc:
                await self._sender.send_message(f"{Msg.ERR} 查询历史消息失败: {exc}", channel=channel, area=area)
                return
            known_ids = {message["messageId"] for message in channel_messages}
            for remote in remote_messages:
                if remote.message_id in known_ids:
                    continue
                channel_messages.append({
                    "messageId": remote.message_id,
                    "channel": remote.channel,
                    "area": remote.area,
                    "content": remote.content[:50],
                    "timestamp": remote.timestamp,
                })
            channel_messages.sort(key=lambda message: message.get("timestamp") or "0")

        if not channel_messages:
            await self._sender.send_message(f"{Msg.ERR} 在当前频道没有找到可撤回的消息", channel=channel, area=area)
            return

        to_recall = channel_messages[-count:]
        success_count = 0
        fail_count = 0

        await self._sender.send_message(f"{Msg.SYNC} 正在撤回 {len(to_recall)} 条消息...", channel=channel, area=area)

        for message in reversed(to_recall):
            try:
                timestamp = message.get("timestamp") or await self._runtime.services.safety.message_lookup.resolve_timestamp(
                    message["messageId"], channel, area
                )
                result = await self._sender.bot.messages.recall_message(message["messageId"], channel=channel, timestamp=timestamp, area=area)
                if not result.ok:
                    raise RuntimeError(result.message or "撤回被拒绝")
            except Exception:
                fail_count += 1
            else:
                success_count += 1
            await asyncio.sleep(0.3)

        result_message = f"{Msg.OK} 批量撤回完成:\n成功: {success_count} 条"
        if fail_count > 0:
            result_message += f"\n失败: {fail_count} 条"
        await self._sender.send_message(result_message, channel=channel, area=area)

    async def configure_auto_recall(self, arg: str, channel: str, area: str) -> None:
        """管理自动撤回功能。"""
        arg = arg.strip()

        if not arg:
            enabled = AUTO_RECALL_CONFIG.get("enabled", False)
            delay = AUTO_RECALL_CONFIG.get("delay", 30)
            status = "开启" if enabled else "关闭"
            await self._sender.send_message(
                f"自动撤回状态\n---\n"
                f"  状态: {status}\n"
                f"  延迟: {delay} 秒\n"
                f"---\n"
                f"用法:\n"
                f"  自动撤回 开 [秒数]  开启（可选设置延迟）\n"
                f"  自动撤回 关        关闭",
                channel=channel,
                area=area,
            )
            return

        if arg.startswith("开"):
            rest = arg[1:].strip()
            if rest and rest.isdigit():
                AUTO_RECALL_CONFIG["delay"] = int(rest)
            AUTO_RECALL_CONFIG["enabled"] = True
            delay = AUTO_RECALL_CONFIG["delay"]
            await self._sender.send_message(f"{Msg.OK} 自动撤回已开启，延迟 {delay} 秒", channel=channel, area=area)
            return

        if arg in ("关", "关闭", "off"):
            AUTO_RECALL_CONFIG["enabled"] = False
            await self._sender.send_message(f"{Msg.OK} 自动撤回已关闭", channel=channel, area=area)
            return

        if arg.startswith("on"):
            rest = arg[2:].strip()
            if rest and rest.isdigit():
                AUTO_RECALL_CONFIG["delay"] = int(rest)
            AUTO_RECALL_CONFIG["enabled"] = True
            delay = AUTO_RECALL_CONFIG["delay"]
            await self._sender.send_message(f"{Msg.OK} 自动撤回已开启，延迟 {delay} 秒", channel=channel, area=area)
            return

        if arg.isdigit():
            seconds = int(arg)
            if seconds <= 0:
                await self._sender.send_message(f"{Msg.ERR} 延迟秒数必须大于 0", channel=channel, area=area)
                return
            AUTO_RECALL_CONFIG["delay"] = seconds
            await self._sender.send_message(f"{Msg.OK} 自动撤回延迟已设为 {seconds} 秒", channel=channel, area=area)
            return

        await self._sender.send_message(
            "用法: 自动撤回 开/关/秒数",
            channel=channel,
            area=area,
        )

    async def clear_history(self, channel: str, area: str) -> None:
        """清理播放历史记录和日志文件。"""
        results = []

        try:
            count = await SongCache.clear_play_history()
            results.append(f"{Msg.OK} 播放历史记录: 已删除 {count} 条")
        except Exception as exc:
            logger.error("清理播放历史记录失败: %s", exc)
            results.append(f"{Msg.ERR} 播放历史记录: 清理失败")

        try:
            log_count = await asyncio.to_thread(self._clear_log_file)
            if log_count is not None:
                results.append(f"{Msg.OK} 日志文件: 已清空 ({log_count} 行)")
            else:
                results.append(f"{Msg.INFO} 日志文件: 不存在")
        except Exception as exc:
            logger.error("清理日志文件失败: %s", exc)
            results.append(f"{Msg.ERR} 日志文件: 清理失败")

        message_count = self._runtime.recent_messages.clear()
        results.append(f"{Msg.OK} 消息历史记录: 已清空 ({message_count} 条)")

        message = "清理完成:\n" + "\n".join(results)
        await self._sender.send_message(message, channel=channel, area=area)

    @staticmethod
    def _clear_log_file() -> int | None:
        if not os.path.exists(LOG_FILE):
            return None
        with open(LOG_FILE, encoding="utf-8", errors="replace") as file:
            count = sum(1 for _line in file)
        with open(LOG_FILE, "w", encoding="utf-8"):
            pass
        return count
