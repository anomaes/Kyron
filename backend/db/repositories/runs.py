from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import WorkflowRun
from backend.db.statuses import TERMINAL_RUN_STATUSES, VALID_RUN_TRANSITIONS, RunStatus


class InvalidStateTransition(RuntimeError):
    pass


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, run_id: uuid.UUID, *, for_update: bool = False) -> WorkflowRun:
        query: Select[tuple[WorkflowRun]] = select(WorkflowRun).where(WorkflowRun.id == run_id)
        if for_update:
            query = query.with_for_update()
        run = await self.session.scalar(query)
        if run is None:
            raise LookupError(f"Run {run_id} does not exist")
        return run

    async def transition(
        self,
        run_id: uuid.UUID,
        *,
        expected: RunStatus | Iterable[RunStatus],
        new: RunStatus,
        expected_version: int | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> WorkflowRun:
        expected_set = {expected} if isinstance(expected, RunStatus) else set(expected)
        if not expected_set:
            raise InvalidStateTransition("At least one expected state is required")
        for state in expected_set:
            if new not in VALID_RUN_TRANSITIONS[state]:
                raise InvalidStateTransition(f"Invalid transition {state} -> {new}")

        values: dict[str, object] = {
            "status": new.value,
            "status_version": WorkflowRun.status_version + 1,
            "error_type": error_type,
            "error_message": error_message,
        }
        now = datetime.now(UTC)
        if new == RunStatus.RUNNING:
            values["started_at"] = now
        if new in TERMINAL_RUN_STATUSES:
            values["finished_at"] = now

        statement = (
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.status.in_([s.value for s in expected_set]),
            )
            .values(**values)
            .returning(WorkflowRun)
        )
        if expected_version is not None:
            statement = statement.where(WorkflowRun.status_version == expected_version)
        run = (await self.session.execute(statement)).scalar_one_or_none()
        if run is None:
            raise InvalidStateTransition("Run state or version changed concurrently")
        return run
