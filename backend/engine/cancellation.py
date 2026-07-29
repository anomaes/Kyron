from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ExecutionWave,
    GateInstance,
    InvocationWorkspace,
    NodeAttempt,
    NodeExecution,
    SubworkflowBatch,
    WorkflowRun,
)
from backend.db.statuses import AttemptStatus, NodeStatus, RunStatus, WaveStatus
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry


async def cancel_run(
    session: AsyncSession,
    tasks: TaskRegistry,
    processes: ProcessRegistry,
    run_id: uuid.UUID,
    grace_seconds: float,
) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise LookupError("Run does not exist")
    if run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
        return run
    run.cancel_requested_at = datetime.now(UTC)
    await session.commit()
    await processes.terminate_run(run.id, grace_seconds)
    await tasks.cancel(run.id)
    now = datetime.now(UTC)
    await session.execute(
        update(NodeAttempt)
        .where(
            NodeAttempt.node_execution_id.in_(
                select(NodeExecution.id).where(NodeExecution.run_id == run.id)
            ),
            NodeAttempt.status == AttemptStatus.RUNNING,
        )
        .values(status=AttemptStatus.CANCELLED, finished_at=now)
    )
    await session.execute(
        update(NodeExecution)
        .where(NodeExecution.run_id == run.id, NodeExecution.status == NodeStatus.RUNNING)
        .values(status=NodeStatus.CANCELLED, finished_at=now)
    )
    await session.execute(
        update(ExecutionWave)
        .where(ExecutionWave.run_id == run.id, ExecutionWave.status == WaveStatus.RUNNING)
        .values(status=WaveStatus.CANCELLED, finished_at=now)
    )
    await session.execute(
        update(InvocationWorkspace)
        .where(
            InvocationWorkspace.run_id == run.id,
            InvocationWorkspace.status.in_(
                ["CREATING", "READY", "RUNNING", "AWAITING_FEEDBACK", "INTEGRATING"]
            ),
        )
        .values(status="CANCELLED", finished_at=now)
    )
    await session.execute(
        update(SubworkflowBatch)
        .where(
            SubworkflowBatch.run_id == run.id,
            SubworkflowBatch.status.in_(
                ["CREATING", "RUNNING", "BLOCKED", "INTEGRATING"]
            ),
        )
        .values(status="CANCELLED", finished_at=now)
    )
    await session.execute(
        update(GateInstance)
        .where(GateInstance.run_id == run.id, GateInstance.status == "OPEN")
        .values(status="CANCELLED", resolved_at=now)
    )
    run.status = RunStatus.CANCELLED
    if run.delivery_mode == "REPORT_ONLY":
        run.verification_conclusion = "CANCELLED"
    run.finished_at = now
    await session.commit()
    return run
