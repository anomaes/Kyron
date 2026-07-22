from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ExecutionWave,
    GateInstance,
    NodeAttempt,
    NodeExecution,
    RunLog,
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
    wave = (
        await session.scalar(
            select(ExecutionWave).where(
                ExecutionWave.id == run.current_wave_id,
                ExecutionWave.run_id == run.id,
                ExecutionWave.status.in_(wave_statuses),
            )
        )
        if run.current_wave_id is not None
        else None
    )
    if not run.worktree_path or not await asyncio.to_thread(Path(run.worktree_path).exists):
        raise ResumeError("Run worktree is missing")
    if run.pending_operation is not None:
        if not run.current_head_sha:
            raise ResumeError("Pending run operation has no durable Git checkpoint")
        await git.reset_wave(Path(run.worktree_path), run.current_head_sha)
        run.status = RunStatus.RESUMING
        run.status_version += 1
        run.cancel_requested_at = None
        run.finished_at = None
        run.error_type = None
        run.error_message = None
        run.current_wave_id = None
        await session.commit()
        return run
    if wave is not None:
        await git.reset_wave(Path(run.worktree_path), wave.start_commit_sha)
        nodes = list(
            await session.scalars(select(NodeExecution).where(NodeExecution.wave_id == wave.id))
        )
    else:
        if run.current_head_sha:
            await git.reset_wave(Path(run.worktree_path), run.current_head_sha)
        node_statuses = (
            [NodeStatus.CANCELLED]
            if run.status == RunStatus.CANCELLED
            else [NodeStatus.INTERRUPTED, NodeStatus.FAILED]
        )
        nodes = list(
            await session.scalars(
                select(NodeExecution).where(
                    NodeExecution.run_id == run.id,
                    NodeExecution.wave_id.is_(None),
                    NodeExecution.status.in_(node_statuses),
                )
            )
        )
        if not nodes:
            detail = (
                "The cancelled run has no resumable checkpoint"
                if run.status == RunStatus.CANCELLED
                else "No resumable wave or control operation exists"
            )
            raise ResumeError(detail)
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


async def mark_run_interrupted(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    error_type: str,
    error_message: str,
) -> bool:
    """Durably release an active run after its in-process worker loses ownership."""
    run = await session.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    )
    if run is None or run.status not in {RunStatus.RUNNING, RunStatus.RESUMING}:
        return False
    now = datetime.now(UTC)
    run.status = RunStatus.INTERRUPTED
    run.status_version += 1
    run.error_type = error_type
    run.error_message = error_message
    await session.execute(
        update(ExecutionWave)
        .where(ExecutionWave.run_id == run.id, ExecutionWave.status == WaveStatus.RUNNING)
        .values(status=WaveStatus.INTERRUPTED, finished_at=now)
    )
    running_node_ids = select(NodeExecution.id).where(
        NodeExecution.run_id == run.id, NodeExecution.status == NodeStatus.RUNNING
    )
    await session.execute(
        update(NodeAttempt)
        .where(
            NodeAttempt.node_execution_id.in_(running_node_ids),
            NodeAttempt.status == AttemptStatus.RUNNING,
        )
        .values(
            status=AttemptStatus.INTERRUPTED,
            finished_at=now,
            error_type=error_type,
            error_message=error_message,
        )
    )
    await session.execute(
        update(NodeExecution)
        .where(NodeExecution.run_id == run.id, NodeExecution.status == NodeStatus.RUNNING)
        .values(status=NodeStatus.INTERRUPTED, finished_at=now, error_message=error_message)
    )
    session.add(
        RunLog(
            run_id=run.id,
            timestamp=now,
            level="ERROR",
            event_type="RUN_INTERRUPTED",
            message=error_message,
            log_metadata={"error_type": error_type},
        )
    )
    await session.commit()
    return True
