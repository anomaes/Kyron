from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, RunLog, WorkflowRun
from backend.db.statuses import ACTIVE_RUN_STATUSES, RunStatus
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

    async def cleanup_worktree(self, run: WorkflowRun) -> None:
        project = await self.session.get(Project, run.project_id)
        if project and run.worktree_path:
            async with project_git_locks.for_project(project.id):
                await self.git.remove_worktree(
                    Path(project.local_path), Path(run.worktree_path), run.branch_name
                )
            run.worktree_path = None

    async def cleanup_output(self, run: WorkflowRun) -> None:
        if run.run_data_path:
            path = self.git.assert_beneath(Path(run.run_data_path), self.git.run_data_base_path)
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
