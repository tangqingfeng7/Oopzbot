"""应用级 asyncio 任务托管、异常收集与有界关停。"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from core.logger_config import get_logger

logger = get_logger("TaskSupervisor")


class TaskSupervisor:
    """持有应用创建的长期任务，并集中报告未处理异常。"""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._failures: asyncio.Queue[BaseException] = asyncio.Queue()
        self._closing = False

    @property
    def tasks(self) -> tuple[asyncio.Task[Any], ...]:
        return tuple(self._tasks)

    @property
    def closing(self) -> bool:
        return self._closing

    def create(self, coroutine: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        if self._closing:
            # 关停期拒绝新任务时主动关闭协程，避免 "never awaited" 告警。
            coroutine.close()
            raise RuntimeError("任务托管器正在关闭")
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("后台任务异常退出: %s: %s", task.get_name(), error)
            self._failures.put_nowait(error)

    async def wait_failure(self) -> BaseException:
        return await self._failures.get()

    async def close(self, timeout: float = 20.0) -> bool:
        self._closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if not tasks:
            return True
        done, pending = await asyncio.wait(tasks, timeout=max(0.0, timeout))
        if pending:
            logger.warning(
                "后台任务关停超时: %s",
                ", ".join(sorted(task.get_name() for task in pending)),
            )
        await asyncio.gather(*done, return_exceptions=True)
        return not pending
