from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import RunLog
from backend.services.crypto import SecretRedactor
from backend.services.log_broadcaster import LogBroadcaster


class EngineLogService:
    def __init__(
        self,
        session: AsyncSession,
        broadcaster: LogBroadcaster,
        redactor: SecretRedactor | None = None,
    ) -> None:
        self.session = session
        self.broadcaster = broadcaster
        self.redactor = redactor or SecretRedactor()

    async def write(
        self,
        run_id: uuid.UUID,
        level: str,
        event_type: str,
        message: str,
        *,
        invocation_path: str | None = None,
        node_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunLog:
        safe_message = self.redactor.redact(message)
        log = RunLog(
            run_id=run_id,
            level=level,
            event_type=event_type,
            message=safe_message,
            invocation_path=invocation_path,
            node_path=node_path,
            log_metadata=metadata or {},
        )
        self.session.add(log)
        await self.session.flush()
        await self.broadcaster.publish(
            run_id,
            {
                "type": "log",
                "sequence": log.id,
                "run_id": str(run_id),
                "invocation_path": invocation_path,
                "node_path": node_path,
                "level": level,
                "event_type": event_type,
                "message": safe_message,
            },
        )
        return log
