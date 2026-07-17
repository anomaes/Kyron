from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ExecutionWave, NodeAttempt, NodeExecution, WorkflowRun
from backend.db.statuses import (
    RESUMABLE_RUN_STATUSES,
    AttemptStatus,
    NodeStatus,
    RunStatus,
    WaveStatus,
)
from backend.integrations.git_manager import GitManager


class ResumeError(RuntimeError):
    pass


async def prepare_resume(session: AsyncSession, git: GitManager, run_id: uuid.UUID) -> WorkflowRun:
    run = await session.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    )
    if run is None:
        raise LookupError("Run does not exist")
    if RunStatus(run.status) not in RESUMABLE_RUN_STATUSES:
        raise ResumeError("Run is not resumable")
    if run.error_type == "WORKTREE_RECOVERY_FAILED":
        raise ResumeError("Worktree must be repaired before resume")
    wave = await session.scalar(
        select(ExecutionWave)
        .where(
            ExecutionWave.run_id == run.id,
            ExecutionWave.status.in_(
                [WaveStatus.ROLLED_BACK, WaveStatus.INTERRUPTED, WaveStatus.FAILED]
            ),
        )
        .order_by(desc(ExecutionWave.started_at))
        .limit(1)
    )
    if wave is None:
        raise ResumeError("No resumable wave exists")
    if not run.worktree_path or not await asyncio.to_thread(Path(run.worktree_path).exists):
        raise ResumeError("Run worktree is missing")
    await git.reset_wave(Path(run.worktree_path), wave.start_commit_sha)
    nodes = list(
        await session.scalars(select(NodeExecution).where(NodeExecution.wave_id == wave.id))
    )
    for node in nodes:
        node.status = NodeStatus.PENDING
        node.finished_at = None
        node.error_message = None
    run.status = RunStatus.RESUMING
    run.status_version += 1
    run.error_type = None
    run.error_message = None
    await session.commit()
    return run


async def mark_interrupted_runs(session: AsyncSession) -> int:
    now = datetime.now(UTC)
    run_ids = list(
        await session.scalars(
            select(WorkflowRun.id).where(
                WorkflowRun.status.in_([RunStatus.RUNNING, RunStatus.RESUMING])
            )
        )
    )
    if not run_ids:
        return 0
    await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id.in_(run_ids))
        .values(
            status=RunStatus.INTERRUPTED,
            status_version=WorkflowRun.status_version + 1,
            error_type="INTERRUPTED",
            error_message="Backend stopped while the run was active",
        )
    )
    await session.execute(
        update(ExecutionWave)
        .where(ExecutionWave.run_id.in_(run_ids), ExecutionWave.status == WaveStatus.RUNNING)
        .values(status=WaveStatus.INTERRUPTED, finished_at=now)
    )
    node_ids = select(NodeExecution.id).where(
        NodeExecution.run_id.in_(run_ids), NodeExecution.status == NodeStatus.RUNNING
    )
    await session.execute(
        update(NodeAttempt)
        .where(
            NodeAttempt.node_execution_id.in_(node_ids),
            NodeAttempt.status == AttemptStatus.RUNNING,
        )
        .values(status=AttemptStatus.INTERRUPTED, finished_at=now)
    )
    await session.execute(
        update(NodeExecution)
        .where(NodeExecution.run_id.in_(run_ids), NodeExecution.status == NodeStatus.RUNNING)
        .values(status=NodeStatus.INTERRUPTED, finished_at=now)
    )
    await session.commit()
    return len(run_ids)
