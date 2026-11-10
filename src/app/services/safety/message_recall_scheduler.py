"""可取消的 asyncio 自动撤回调度器。"""

from __future__ import annotations

import asyncio
import heapq
from dataclasses import dataclass, field

from app.services.runtime import CommandRuntimeView, sender_of
from config import AUTO_RECALL_CONFIG
from core.logger_config import get_logger

logger = get_logger("MessageRecallScheduler")


@dataclass(order=True)
class _ScheduledRecall:
    due_at: float
    sequence: int
    message_id: str = field(compare=False)
    channel: str = field(compare=False)
    area: str = field(compare=False)
    timestamp: str = field(compare=False, default="")


class MessageRecallScheduler:
    """用单个 asyncio task 管理所有延迟撤回。"""

    def __init__(self, runtime: CommandRuntimeView):
        self._sender = sender_of(runtime)
        self._pending: list[_ScheduledRecall] = []
        self._worker: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._sequence = 0
        self._stopped = False

    async def schedule_user_message_recall(
        self,
        message_id: str,
        channel: str,
        area: str,
        timestamp: str = "",
    ) -> bool:
        if not message_id or not AUTO_RECALL_CONFIG.get("enabled"):
            return False
        delay = float(AUTO_RECALL_CONFIG.get("delay", 30) or 0)
        if delay <= 0:
            return False
        return await self.schedule_recall(
            message_id,
            channel,
            area,
            timestamp,
            delay=delay,
        )

    async def schedule_recall(
        self,
        message_id: str,
        channel: str,
        area: str,
        timestamp: str = "",
        *,
        delay: float,
    ) -> bool:
        if not message_id or delay <= 0 or self._stopped:
            return False
        max_pending = self._max_pending()
        if len(self._pending) >= max_pending:
            logger.warning(
                "自动撤回待处理任务已满 (%d)，跳过 message_id=%s",
                max_pending,
                str(message_id)[:16],
            )
            return False

        loop = asyncio.get_running_loop()
        self._sequence += 1
        heapq.heappush(
            self._pending,
            _ScheduledRecall(
                due_at=loop.time() + float(delay),
                sequence=self._sequence,
                message_id=message_id,
                channel=channel,
                area=area,
                timestamp=timestamp,
            ),
        )
        self._ensure_worker()
        self._wake.set()
        return True

    async def cancel_all(self) -> int:
        count = len(self._pending)
        self._pending.clear()
        self._wake.set()
        return count

    async def stop(self, timeout: float = 3.0) -> int:
        count = len(self._pending)
        self._pending.clear()
        self._stopped = True
        self._wake.set()
        worker = self._worker
        if worker is None:
            return count
        try:
            await asyncio.wait_for(worker, timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            logger.warning("服务停止超时: MessageRecallScheduler，任务已取消")
        finally:
            self._worker = None
        return count

    @staticmethod
    def _max_pending() -> int:
        try:
            return max(1, int(AUTO_RECALL_CONFIG.get("max_pending", 1000) or 1000))
        except (TypeError, ValueError):
            return 1000

    def _ensure_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._worker = asyncio.create_task(self._worker_loop(), name="MessageRecallScheduler")

    async def _worker_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            if not self._pending:
                self._wake.clear()
                await self._wake.wait()
                continue

            job = self._pending[0]
            wait_seconds = max(0.0, job.due_at - loop.time())
            if wait_seconds > 0:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=wait_seconds)
                    continue
                except asyncio.TimeoutError:
                    pass

            if self._stopped or not self._pending:
                continue
            job = heapq.heappop(self._pending)
            try:
                result = await self._sender.bot.messages.recall_message(message_id=job.message_id, channel=job.channel, timestamp=job.timestamp, area=job.area)
                if not result.ok:
                    raise RuntimeError(result.message or "撤回被拒绝")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "自动撤回执行失败: message_id=%s",
                    str(job.message_id)[:16],
                    exc_info=True,
                )
