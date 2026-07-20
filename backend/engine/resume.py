from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ExecutionWave,
    GateInstance,
    NodeAttempt,
    NodeExecution,
    RunReport,
    WorkflowInvocation,
    WorkflowRun,
)
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
    await session.execute(delete(RunReport).where(RunReport.run_id == run.id))
    if run.status == RunStatus.CANCELLED and not run.worktree_path:
        if run.started_at is not None:
            raise ResumeError("The cancelled run's retained checkpoint is no longer available")
        run.status = RunStatus.QUEUED
        run.cancel_requested_at = None
        run.finished_at = None
        run.error_type = None
        run.error_message = None
        run.status_version += 1
        await session.commit()
        return run
    if run.status == RunStatus.CANCELLED:
        open_gate = await session.scalar(
            select(GateInstance).where(
                GateInstance.run_id == run.id,
                GateInstance.status == "OPEN",
            )
        )
        if open_gate is not None:
            run.status = RunStatus.AWAITING_FEEDBACK
            run.cancel_requested_at = None
            run.finished_at = None
            run.error_type = None
            run.error_message = None
            run.status_version += 1
            await session.commit()
            return run
    wave_statuses = (
        [WaveStatus.CANCELLED]
        if run.status == RunStatus.CANCELLED
        else [WaveStatus.ROLLED_BACK, WaveStatus.INTERRUPTED, WaveStatus.FAILED]
    )
    wave = await session.scalar(
        select(ExecutionWave)
        .where(
            ExecutionWave.run_id == run.id,
            ExecutionWave.status.in_(wave_statuses),
        )
        .order_by(desc(ExecutionWave.started_at))
        .limit(1)
    )
    if not run.worktree_path or not await asyncio.to_thread(Path(run.worktree_path).exists):
        raise ResumeError("Run worktree is missing")
    if wave is not None:
        await git.reset_wave(Path(run.worktree_path), wave.start_commit_sha)
        nodes = list(
            await session.scalars(select(NodeExecution).where(NodeExecution.wave_id == wave.id))
        )
    elif run.status == RunStatus.CANCELLED:
        if run.current_head_sha:
            await git.reset_wave(Path(run.worktree_path), run.current_head_sha)
        nodes = list(
            await session.scalars(
                select(NodeExecution).where(
                    NodeExecution.run_id == run.id,
                    NodeExecution.status.in_(
                        [NodeStatus.CANCELLED, NodeStatus.INTERRUPTED, NodeStatus.FAILED]
                    ),
                )
            )
        )
        if not nodes:
            raise ResumeError("The cancelled run has no resumable checkpoint")
    else:
        raise ResumeError("No resumable wave exists")
    for node in nodes:
        _reset_node(node)
    await _reset_parent_controls(session, nodes)
    run.status = RunStatus.RESUMING
    run.status_version += 1
    run.cancel_requested_at = None
    run.finished_at = None
    run.error_type = None
    run.error_message = None
    run.current_node_execution_id = None
    run.current_wave_id = None
    await session.commit()
    return run


def _reset_node(node: NodeExecution) -> None:
    node.status = NodeStatus.PENDING
    node.finished_at = None
    node.error_message = None


async def _reset_parent_controls(
    session: AsyncSession, nodes: list[NodeExecution]
) -> None:
    invocation_ids = {node.invocation_id for node in nodes}
    visited: set[uuid.UUID] = set()
    while invocation_ids:
        current_ids = invocation_ids - visited
        if not current_ids:
            break
        visited.update(current_ids)
        invocations = list(
            await session.scalars(
                select(WorkflowInvocation).where(WorkflowInvocation.id.in_(current_ids))
            )
        )
        invocation_ids = set()
        for invocation in invocations:
            invocation.status = "PENDING"
            invocation.finished_at = None
            if invocation.parent_node_execution_id is None:
                continue
            parent = await session.get(NodeExecution, invocation.parent_node_execution_id)
            if parent is None:
                continue
            if parent.status in {
                NodeStatus.RUNNING,
                NodeStatus.FAILED,
                NodeStatus.CANCELLED,
                NodeStatus.INTERRUPTED,
            }:
                _reset_node(parent)
            invocation_ids.add(parent.invocation_id)


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
