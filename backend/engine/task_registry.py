from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable


class TaskRegistry:
    def __init__(self, maximum_concurrent_runs: int) -> None:
        self.tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(maximum_concurrent_runs)

    async def schedule(self, run_id: uuid.UUID, operation: Callable[[], Awaitable[None]]) -> bool:
        async with self._lock:
            existing = self.tasks.get(run_id)
            if existing is not None and not existing.done():
                return False

            async def guarded() -> None:
                try:
                    async with self._semaphore:
                        await operation()
                finally:
                    async with self._lock:
                        self.tasks.pop(run_id, None)

            self.tasks[run_id] = asyncio.create_task(guarded(), name=f"workflow-run-{run_id}")
            return True

    async def cancel(self, run_id: uuid.UUID) -> bool:
        async with self._lock:
            task = self.tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def wait(self, run_id: uuid.UUID) -> None:
        async with self._lock:
            task = self.tasks.get(run_id)
        if task is None or task.done() or task is asyncio.current_task():
            return
        await asyncio.gather(task, return_exceptions=True)
