from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import Project, WorkflowRun
from backend.db.statuses import ACTIVE_RUN_STATUSES, RESUMABLE_RUN_STATUSES, RunStatus
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitManager, project_git_locks
from backend.integrations.gitlab_client import GitLabClient, GitLabError
from backend.services.cleanup_service import CleanupService
from backend.services.crypto import EncryptionError, SecretCipher

logger = logging.getLogger(__name__)


class ReconciliationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        cipher: SecretCipher | None,
        git: GitManager,
        gitlab: GitLabClient,
        processes: ProcessRegistry,
        tasks: TaskRegistry,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cipher = cipher
        self.git = git
        self.gitlab = gitlab
        self.cleanup = CleanupService(
            session,
            git,
            processes,
            tasks,
            settings.PROCESS_TERMINATION_GRACE_SECONDS,
        )

    async def reconcile(self) -> None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(days=self.settings.STALE_FAILED_RUN_DAYS)
        output_before = now - timedelta(days=self.settings.RUN_OUTPUT_RETENTION_DAYS)
        runs = list(
            await self.session.scalars(
                select(WorkflowRun).where(
                    (WorkflowRun.worktree_path.is_not(None))
                    | (WorkflowRun.run_data_path.is_not(None))
                )
            )
        )
        projects = {
            project.id: project
            for project in await self.session.scalars(select(Project))
        }

        for run in runs:
            project = projects.get(run.project_id)
            if project is None:
                continue
            status = RunStatus(run.status)
            worktree_closed = await self._merge_request_is_closed(run, project)
            if worktree_closed:
                await self.cleanup.cleanup_run(run.id)
            elif run.mr_iid is None and status == RunStatus.CANCELLED:
                await self.cleanup.cleanup_run(run.id, remove_output=True)
            elif (
                run.mr_iid is None
                and status in RESUMABLE_RUN_STATUSES
                and (run.finished_at or run.created_at) <= stale_before
            ):
                await self.cleanup.cleanup_worktree(run)
                await self.cleanup.mark_non_resumable(
                    run, "Run worktree expired under the stale-resource policy"
                )

            if (
                run.run_data_path
                and status not in ACTIVE_RUN_STATUSES
                and (run.finished_at or run.created_at) <= output_before
            ):
                await self.cleanup.cleanup_output(run)

            if (
                status in RESUMABLE_RUN_STATUSES
                and run.worktree_path
                and not await asyncio.to_thread(Path(run.worktree_path).is_dir)
            ):
                await self.cleanup.mark_non_resumable(
                    run, "Stored worktree is missing; this run cannot be resumed safely"
                )

        await self.session.commit()
        await self._prune_projects(projects.values())
        self._report_orphan_worktrees(runs)

    async def _merge_request_is_closed(self, run: WorkflowRun, project: Project) -> bool:
        if run.mr_iid is None or run.worktree_path is None:
            return False
        if self.cipher is None:
            logger.warning("Cannot reconcile merge request for run %s without a cipher", run.id)
            return False
        try:
            token = self.cipher.decrypt(project.encrypted_access_token)
            merge_request = await self.gitlab.get_merge_request(
                project.gitlab_project_id, run.mr_iid, token
            )
        except (EncryptionError, GitLabError) as exc:
            logger.warning("Could not reconcile merge request for run %s: %s", run.id, exc)
            return False
        finally:
            token = ""
        return merge_request.get("state") in {"closed", "merged"}

    async def _prune_projects(self, projects: Iterable[Project]) -> None:
        for project in projects:
            repository = Path(project.local_path)
            if not await asyncio.to_thread(repository.is_dir):
                continue
            try:
                async with project_git_locks.for_project(project.id):
                    await self.git.run(["worktree", "prune"], cwd=repository)
            except RuntimeError as exc:
                logger.warning("Could not prune worktrees for project %s: %s", project.id, exc)

    def _report_orphan_worktrees(self, runs: list[WorkflowRun]) -> None:
        root = self.git.worktree_base_path
        if not root.is_dir():
            return
        referenced = {
            Path(run.worktree_path).resolve()
            for run in runs
            if run.worktree_path is not None
        }
        for candidate in root.iterdir():
            if candidate.is_dir() and candidate.resolve() not in referenced:
                logger.warning(
                    "Orphan worktree requires operator review before deletion: %s", candidate
                )
