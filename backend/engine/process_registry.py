from __future__ import annotations

import asyncio
import os
import signal
import uuid
from collections import defaultdict


class ProcessRegistry:
    def __init__(self) -> None:
        self._process_groups: defaultdict[uuid.UUID, dict[uuid.UUID, int]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def register(self, run_id: uuid.UUID, attempt_id: uuid.UUID, pgid: int) -> None:
        async with self._lock:
            self._process_groups[run_id][attempt_id] = pgid

    async def unregister(self, run_id: uuid.UUID, attempt_id: uuid.UUID) -> None:
        async with self._lock:
            attempts = self._process_groups.get(run_id)
            if attempts is None:
                return
            attempts.pop(attempt_id, None)
            if not attempts:
                self._process_groups.pop(run_id, None)

    async def terminate_run(self, run_id: uuid.UUID, grace_seconds: float) -> None:
        async with self._lock:
            groups = list(self._process_groups.get(run_id, {}).values())
        await asyncio.gather(
            *(terminate_process_group(pgid, grace_seconds) for pgid in groups),
            return_exceptions=True,
        )


async def terminate_process_group(pgid: int, grace_seconds: float = 10) -> None:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = asyncio.get_running_loop().time() + grace_seconds
    while asyncio.get_running_loop().time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return


process_registry = ProcessRegistry()
