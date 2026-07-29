from __future__ import annotations

import asyncio
import uuid

from backend.engine.task_registry import TaskRegistry


async def test_schedule_while_active_latches_one_more_worker_pass() -> None:
    registry = TaskRegistry(1)
    run_id = uuid.uuid4()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    calls: list[str] = []

    async def operation() -> None:
        calls.append("run")
        if len(calls) == 1:
            first_started.set()
            await release_first.wait()

    assert await registry.schedule(run_id, operation)
    await first_started.wait()
    assert not await registry.schedule(run_id, operation)
    release_first.set()
    await registry.wait(run_id)

    assert calls == ["run", "run"]
