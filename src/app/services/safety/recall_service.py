import os
import time
from typing import Optional

from config import AUTO_RECALL_CONFIG
from database import SongCache
from logger_config import LOG_FILE, get_logger
from app.services.runtime import CommandRuntimeView, sender_of

logger = get_logger("RecallService")


class RecallService:
    """处理消息撤回、自动撤回和历史清理。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._runtime = runtime
        self._sender = sender_of(runtime)

    def recall_message(self, message_id: Optional[str], channel: str, area: str) -> None:
        """撤回指定消息。"""
        content_preview = ""
        recent = None

        if not message_id or message_id.lower() in ("last", "最后", "最后一条", "上一条"):
            if not self._runtime.recent_messages:
                self._sender.send_message(
                    "[x] 没有可撤回的消息记录",
                    channel=channel,
                    area=area,
                )
                return

            for message in reversed(self._runtime.recent_messages):
                if message.get("channel") == channel and message.get("area") == area:
                    recent = message
                    break

            if not recent:
                self._sender.send_message(
                    "[x] 在当前频道没有找到可撤回的消息\n请使用 /recall <消息ID> 或 @bot 撤回 <消息ID>",
                    channel=channel,
                    area=area,
                )
                return

            message_id = recent["messageId"]
            content_preview = recent.get("content", "")[:30]

        timestamp = self._runtime.services.safety.message_lookup.resolve_timestamp(message_id, channel, area)
        result = self._sender.recall_message(
            message_id,
            area=area,
            channel=channel,
            timestamp=timestamp,
        )
        if "error" in result:
            error = result["error"]
            hint = ""
            if "record not found" in (error or "").lower() or "服务异常" in (error or ""):
                hint = "\n提示: 该消息可能已撤回/过期，或消息 ID 无效（请用长按消息复制得到的完整 ID）。"
            mid_preview = (message_id[:24] + "...") if len(str(message_id)) > 24 else str(message_id)
            self._sender.send_message(
                f"[x] 撤回失败: {error}\n消息ID: {mid_preview}{hint}",
                channel=channel,
                area=area,
            )
            return

        preview = f" ({content_preview}...)" if content_preview else ""
        self._sender.send_message(
            f"[ok] 消息已撤回{preview}\n消息ID: {message_id[:20]}...",
            channel=channel,
            area=area,
        )

    def recall_multiple(self, count: int, channel: str, area: str) -> None:
        """批量撤回多条消息。"""
        if count <= 0:
            self._sender.send_message("[x] 撤回数量必须大于 0", channel=channel, area=area)
            return

        if count > 100:
            self._sender.send_message("[x] 最多只能一次撤回 100 条消息", channel=channel, area=area)
            return

        channel_messages = [
            message for message in self._runtime.recent_messages
            if message.get("channel") == channel and message.get("area") == area
        ]

        if len(channel_messages) < count:
            remote_messages = self._sender.get_channel_messages(area=area, channel=channel, size=count)
            known_ids = {message["messageId"] for message in channel_messages}
            for remote in remote_messages:
                if remote["messageId"] in known_ids:
                    continue
                channel_messages.append({
                    "messageId": remote["messageId"],
                    "channel": remote.get("channel", channel),
                    "area": remote.get("area", area),
                    "content": (remote.get("content") or "")[:50],
                    "timestamp": remote.get("timestamp", ""),
                })
            channel_messages.sort(key=lambda message: message.get("timestamp") or "0")

        if not channel_messages:
            self._sender.send_message("[x] 在当前频道没有找到可撤回的消息", channel=channel, area=area)
            return

        to_recall = channel_messages[-count:]
        success_count = 0
        fail_count = 0

        self._sender.send_message(f"[sync] 正在撤回 {len(to_recall)} 条消息...", channel=channel, area=area)

        for message in reversed(to_recall):
            timestamp = message.get("timestamp") or self._runtime.services.safety.message_lookup.resolve_timestamp(
                message["messageId"],
                channel,
                area,
            )
            result = self._sender.recall_message(
                message["messageId"],
                area=area,
                channel=channel,
                timestamp=timestamp,
            )
            if "error" in result:
                fail_count += 1
            else:
                success_count += 1
            time.sleep(0.3)

        result_message = f"[ok] 批量撤回完成:\n成功: {success_count} 条"
        if fail_count > 0:
            result_message += f"\n失败: {fail_count} 条"
        self._sender.send_message(result_message, channel=channel, area=area)

    def configure_auto_recall(self, arg: str, channel: str, area: str) -> None:
        """管理自动撤回功能。"""
        arg = arg.strip()

        if not arg:
            enabled = AUTO_RECALL_CONFIG.get("enabled", False)
            delay = AUTO_RECALL_CONFIG.get("delay", 30)
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            status = "开启" if enabled else "关闭"
            exclude_names = {
                "ai_chat": "AI 聊天",
                "ai_image": "AI 生成图片",
            }
            exclude_display = ", ".join(exclude_names.get(item, item) for item in exclude) or "无"
            self._sender.send_message(
                f"自动撤回状态\n---\n"
                f"  状态: {status}\n"
                f"  延迟: {delay} 秒\n"
                f"  排除: {exclude_display}\n"
                f"---\n"
                f"用法:\n"
                f"  自动撤回 开 [秒数]  开启（可选设置延迟）\n"
                f"  自动撤回 关        关闭\n"
                f"  自动撤回 排除 <类型>  添加排除\n"
                f"  自动撤回 取消排除 <类型>  移除排除\n"
                f"  类型: ai_chat / ai_image",
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
            self._sender.send_message(f"[ok] 自动撤回已开启，延迟 {delay} 秒", channel=channel, area=area)
            return

        if arg in ("关", "关闭", "off"):
            AUTO_RECALL_CONFIG["enabled"] = False
            self._sender.send_message("[ok] 自动撤回已关闭", channel=channel, area=area)
            return

        if arg.startswith("on"):
            rest = arg[2:].strip()
            if rest and rest.isdigit():
                AUTO_RECALL_CONFIG["delay"] = int(rest)
            AUTO_RECALL_CONFIG["enabled"] = True
            delay = AUTO_RECALL_CONFIG["delay"]
            self._sender.send_message(f"[ok] 自动撤回已开启，延迟 {delay} 秒", channel=channel, area=area)
            return

        if arg.isdigit():
            seconds = int(arg)
            if seconds <= 0:
                self._sender.send_message("[x] 延迟秒数必须大于 0", channel=channel, area=area)
                return
            AUTO_RECALL_CONFIG["delay"] = seconds
            self._sender.send_message(f"[ok] 自动撤回延迟已设为 {seconds} 秒", channel=channel, area=area)
            return

        if arg.startswith("排除"):
            command_type = arg[2:].strip()
            if not command_type:
                self._sender.send_message("用法: 自动撤回 排除 ai_chat", channel=channel, area=area)
                return
            exclude = AUTO_RECALL_CONFIG.setdefault("exclude_commands", [])
            if command_type in exclude:
                self._sender.send_message(f"[info] {command_type} 已在排除列表中", channel=channel, area=area)
            else:
                exclude.append(command_type)
                self._sender.send_message(f"[ok] 已将 {command_type} 加入排除列表", channel=channel, area=area)
            return

        if arg.startswith("取消排除"):
            command_type = arg[4:].strip()
            if not command_type:
                self._sender.send_message("用法: 自动撤回 取消排除 ai_chat", channel=channel, area=area)
                return
            exclude = AUTO_RECALL_CONFIG.get("exclude_commands", [])
            if command_type in exclude:
                exclude.remove(command_type)
                self._sender.send_message(f"[ok] 已将 {command_type} 从排除列表移除", channel=channel, area=area)
            else:
                self._sender.send_message(f"[info] {command_type} 不在排除列表中", channel=channel, area=area)
            return

        self._sender.send_message(
            "用法: 自动撤回 开/关/秒数/排除/取消排除",
            channel=channel,
            area=area,
        )

    def clear_history(self, channel: str, area: str) -> None:
        """清理播放历史记录和日志文件。"""
        results = []

        try:
            count = SongCache.clear_play_history()
            results.append(f"[ok] 播放历史记录: 已删除 {count} 条")
        except Exception as exc:
            logger.error("清理播放历史记录失败: %s", exc)
            results.append("[x] 播放历史记录: 清理失败")

        try:
            log_count = 0
            if os.path.exists(LOG_FILE):
                with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as file:
                    log_count = len(file.readlines())
                with open(LOG_FILE, "w", encoding="utf-8") as file:
                    file.write("")
                results.append(f"[ok] 日志文件: 已清空 ({log_count} 行)")
            else:
                results.append("[info] 日志文件: 不存在")
        except Exception as exc:
            logger.error("清理日志文件失败: %s", exc)
            results.append("[x] 日志文件: 清理失败")

        message_count = self._runtime.recent_messages.clear()
        results.append(f"[ok] 消息历史记录: 已清空 ({message_count} 条)")

        message = "清理完成:\n" + "\n".join(results)
        self._sender.send_message(message, channel=channel, area=area)
