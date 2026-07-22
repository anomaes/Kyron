from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ChangeRequestLifecycleEvent,
    EdgeEvaluation,
    ExecutionWave,
    FeedbackEvent,
    GateDecision,
    GateInstance,
    NodeAttempt,
    NodeExecution,
    Project,
    RunLog,
    RunReport,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import ACTIVE_RUN_STATUSES, DELETABLE_RUN_STATUSES, RunStatus
from backend.engine.cancellation import cancel_run
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitManager, project_git_locks


class CleanupService:
    def __init__(
        self,
        session: AsyncSession,
        git: GitManager,
        processes: ProcessRegistry,
        tasks: TaskRegistry,
        termination_grace_seconds: float,
    ) -> None:
        self.session = session
        self.git = git
        self.processes = processes
        self.tasks = tasks
        self.termination_grace_seconds = termination_grace_seconds

    async def cleanup_run(self, run_id: uuid.UUID, *, remove_output: bool = False) -> None:
        run = await self.session.get(WorkflowRun, run_id)
        if run is None:
            raise LookupError("Run does not exist")
        if RunStatus(run.status) in ACTIVE_RUN_STATUSES:
            run = await cancel_run(
                self.session,
                self.tasks,
                self.processes,
                run.id,
                self.termination_grace_seconds,
            )
        await self.cleanup_worktree(run)
        if remove_output:
            await self.cleanup_output(run)
        self.session.add(
            RunLog(
                run_id=run.id,
                level="INFO",
                event_type="RESOURCE_CLEANUP",
                message="Run resources cleaned",
                log_metadata={"output_removed": remove_output},
            )
        )
        await self.session.commit()

    async def delete_run(self, run_id: uuid.UUID) -> WorkflowRun:
        run = await self.session.get(WorkflowRun, run_id)
        if run is None:
            raise LookupError("Run does not exist")
        if RunStatus(run.status) not in DELETABLE_RUN_STATUSES:
            raise ValueError(
                "Only completed, failed, interrupted, or cancelled runs can be deleted"
            )

        # A terminal status is committed just before the worker exits. Wait before taking the
        # row lock so a completing worker can still insert its report without deadlocking.
        await self.tasks.wait(run.id)
        run = cast(
            WorkflowRun | None,
            await self.session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )
        if run is None:
            raise LookupError("Run does not exist")
        if RunStatus(run.status) not in DELETABLE_RUN_STATUSES:
            raise ValueError(
                "Only completed, failed, interrupted, or cancelled runs can be deleted"
        )
        await self.cleanup_worktree(run)
        await self.cleanup_output(run, require_removed=True)
        await self._delete_records(run.id)
        return run

    async def _delete_records(self, run_id: uuid.UUID) -> None:
        gate_ids = select(GateInstance.id).where(GateInstance.run_id == run_id)
        node_ids = select(NodeExecution.id).where(NodeExecution.run_id == run_id)

        await self.session.execute(
            delete(GateDecision).where(GateDecision.gate_instance_id.in_(gate_ids))
        )
        await self.session.execute(delete(GateInstance).where(GateInstance.run_id == run_id))
        await self.session.execute(delete(FeedbackEvent).where(FeedbackEvent.run_id == run_id))
        await self.session.execute(delete(EdgeEvaluation).where(EdgeEvaluation.run_id == run_id))
        await self.session.execute(
            delete(NodeAttempt).where(NodeAttempt.node_execution_id.in_(node_ids))
        )
        await self.session.execute(delete(NodeExecution).where(NodeExecution.run_id == run_id))
        await self.session.execute(delete(ExecutionWave).where(ExecutionWave.run_id == run_id))
        await self.session.execute(
            delete(WorkflowInvocation).where(WorkflowInvocation.run_id == run_id)
        )
        await self.session.execute(delete(RunReport).where(RunReport.run_id == run_id))
        await self.session.execute(
            delete(ChangeRequestLifecycleEvent).where(
                ChangeRequestLifecycleEvent.run_id == run_id
            )
        )
        await self.session.execute(delete(RunLog).where(RunLog.run_id == run_id))
        await self.session.execute(delete(WorkflowRun).where(WorkflowRun.id == run_id))

    async def cleanup_worktree(self, run: WorkflowRun) -> None:
        project = await self.session.get(Project, run.project_id)
        if project and run.worktree_path:
            async with project_git_locks.for_project(project.id):
                await self.git.remove_worktree(
                    Path(project.local_path), Path(run.worktree_path), run.branch_name
                )
            run.worktree_path = None

    async def cleanup_output(
        self, run: WorkflowRun, *, require_removed: bool = False
    ) -> None:
        if run.run_data_path:
            path = self.git.assert_beneath(Path(run.run_data_path), self.git.run_data_base_path)
            if require_removed:
                if await asyncio.to_thread(os.path.lexists, path):
                    await asyncio.to_thread(shutil.rmtree, path)
                if await asyncio.to_thread(os.path.lexists, path):
                    raise OSError(f"Run output still exists after removal: {path}")
            else:
                await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)
            run.run_data_path = None

    async def mark_non_resumable(self, run: WorkflowRun, message: str) -> None:
        run.error_type = "WORKTREE_RECOVERY_FAILED"
        run.error_message = message
        run.finished_at = run.finished_at or datetime.now(UTC)
        self.session.add(
            RunLog(
                run_id=run.id,
                level="ERROR",
                event_type="WORKTREE_RECOVERY_FAILED",
                message=message,
                log_metadata={},
            )
        )
