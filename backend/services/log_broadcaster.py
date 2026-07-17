from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class Subscription:
    run_id: uuid.UUID
    queue: asyncio.Queue[dict[str, Any]]


class LogBroadcaster:
    def __init__(self, queue_size: int = 500) -> None:
        self.queue_size = queue_size
        self._subscribers: defaultdict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(
            set
        )

    def subscribe(self, run_id: uuid.UUID) -> Subscription:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self.queue_size)
        self._subscribers[run_id].add(queue)
        return Subscription(run_id, queue)

    def unsubscribe(self, subscription: Subscription) -> None:
        subscribers = self._subscribers.get(subscription.run_id)
        if subscribers is None:
            return
        subscribers.discard(subscription.queue)
        if not subscribers:
            self._subscribers.pop(subscription.run_id, None)

    async def publish(self, run_id: uuid.UUID, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", datetime.now(UTC).isoformat())
        for queue in list(self._subscribers.get(run_id, set())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                dropped = {
                    "type": "dropped",
                    "message": "Live output was dropped; load complete output from disk.",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                try:
                    queue.put_nowait(dropped)
                except asyncio.QueueFull:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


log_broadcaster = LogBroadcaster()
