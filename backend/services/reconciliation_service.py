from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import Project, ResourceAuditLog, RunLog, WorkflowRun
from backend.db.statuses import (
    ACTIVE_RUN_STATUSES,
    RESUMABLE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    RunStatus,
)
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.code_host import CodeHostError, code_host_client, repository_locator
from backend.integrations.git_manager import GitError, GitManager, project_git_locks
from backend.services.cleanup_service import CleanupService
from backend.services.crypto import EncryptionError, SecretCipher
from backend.services.storage_metrics import (
    StorageRootUsage,
    measure_storage_roots,
    newest_tree_mtime,
)

logger = logging.getLogger(__name__)

_KYRON_WORKTREE_NAME = re.compile(
    r"^(?:definition-|local-)?[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ReconciliationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        cipher: SecretCipher | None,
        git: GitManager,
        processes: ProcessRegistry,
        tasks: TaskRegistry,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cipher = cipher
        self.git = git
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
        terminal_before = now - timedelta(
            days=self.settings.TERMINAL_WORKTREE_RETENTION_DAYS
        )
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
            change_request_state = await self._change_request_state(run, project)
            try:
                if change_request_state in {"closed", "merged"}:
                    await self.cleanup.cleanup_run(run.id)
                elif (
                    run.change_request_number is None
                    and status in TERMINAL_RUN_STATUSES
                    and _as_utc(run.finished_at or run.created_at) <= terminal_before
                ):
                    worktree_path = run.worktree_path
                    await self.cleanup.cleanup_worktree(run)
                    await self._audit(
                        "TERMINAL_WORKTREE_RETENTION_CLEANUP",
                        "INFO",
                        "worktree",
                        worktree_path,
                        run_id=run.id,
                        project_id=run.project_id,
                    )
                elif (
                    run.change_request_number is None
                    and status in RESUMABLE_RUN_STATUSES
                    and _as_utc(run.finished_at or run.created_at) <= stale_before
                ):
                    worktree_path = run.worktree_path
                    await self.cleanup.cleanup_worktree(run)
                    await self._audit(
                        "STALE_RESUMABLE_WORKTREE_CLEANUP",
                        "INFO",
                        "worktree",
                        worktree_path,
                        run_id=run.id,
                        project_id=run.project_id,
                    )
                    await self.cleanup.mark_non_resumable(
                        run, "Run worktree expired under the stale-resource policy"
                    )
            except (GitError, OSError) as exc:
                await self._audit(
                    "WORKTREE_CLEANUP_FAILED",
                    "ERROR",
                    "worktree",
                    run.worktree_path,
                    run_id=run.id,
                    project_id=run.project_id,
                    details={"error": str(exc)},
                )
                logger.exception("Worktree cleanup failed for run %s", run.id)

            if change_request_state in {"open", "opened"}:
                await self._warn_long_open_change_request(run, now)

            if (
                run.run_data_path
                and status not in ACTIVE_RUN_STATUSES
                and _as_utc(run.finished_at or run.created_at) <= output_before
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

        await self._cleanup_orphan_worktrees(runs, projects.values(), now)
        usages = await asyncio.to_thread(measure_storage_roots, self.settings)
        await self._record_storage_alerts(usages)
        await self.session.commit()
        await self._prune_projects(projects.values())

    async def _change_request_state(
        self, run: WorkflowRun, project: Project
    ) -> str | None:
        if run.change_request_number is None or run.worktree_path is None:
            return None
        if self.cipher is None:
            logger.warning("Cannot reconcile change request for run %s without a cipher", run.id)
            return None
        token = ""
        try:
            token = self.cipher.decrypt(project.encrypted_access_token)
            async with code_host_client(project.provider, self.settings) as provider:
                change_request = await provider.get_change_request(
                    repository_locator(
                        project.provider,
                        project.provider_project_id,
                        project.provider_project_path,
                    ),
                    run.change_request_number,
                    token,
                )
        except (EncryptionError, CodeHostError) as exc:
            logger.warning("Could not reconcile change request for run %s: %s", run.id, exc)
            return None
        finally:
            token = ""
        return change_request.state

    async def _warn_long_open_change_request(
        self, run: WorkflowRun, now: datetime
    ) -> None:
        opened_at = _as_utc(
            run.change_request_created_at or run.finished_at or run.created_at
        )
        warning_age = timedelta(days=self.settings.LONG_OPEN_CHANGE_REQUEST_WARNING_DAYS)
        if now - opened_at < warning_age:
            return
        last_warning = await self.session.scalar(
            select(func.max(RunLog.timestamp)).where(
                RunLog.run_id == run.id,
                RunLog.event_type == "LONG_OPEN_CHANGE_REQUEST",
            )
        )
        repeat_after = timedelta(
            days=self.settings.LONG_OPEN_CHANGE_REQUEST_WARNING_REPEAT_DAYS
        )
        if last_warning is not None and now - _as_utc(last_warning) < repeat_after:
            return
        age_days = (now - opened_at).days
        message = (
            f"Change request has remained open for {age_days} days; its worktree is retained"
        )
        self.session.add(
            RunLog(
                run_id=run.id,
                timestamp=now,
                level="WARNING",
                event_type="LONG_OPEN_CHANGE_REQUEST",
                message=message,
                log_metadata={
                    "age_days": age_days,
                    "change_request_number": run.change_request_number,
                },
            )
        )
        logger.warning("Run %s: %s", run.id, message)

    async def _cleanup_orphan_worktrees(
        self,
        runs: list[WorkflowRun],
        projects: Iterable[Project],
        now: datetime,
    ) -> None:
        root = self.git.worktree_base_path
        if not await asyncio.to_thread(root.is_dir):
            return
        resolved_root = root.resolve()
        referenced = await asyncio.to_thread(
            lambda: {
                Path(run.worktree_path).resolve()
                for run in runs
                if run.worktree_path is not None
            }
        )
        registered = await self._registered_worktrees(projects)
        candidates = await asyncio.to_thread(lambda: list(root.iterdir()))
        grace = timedelta(hours=self.settings.ORPHAN_WORKTREE_GRACE_HOURS)
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            resolved = candidate.resolve()
            if (
                resolved.parent != resolved_root
                or resolved in referenced
                or not _KYRON_WORKTREE_NAME.fullmatch(candidate.name)
            ):
                continue
            self.git.assert_beneath(candidate, root)
            newest_mtime = await asyncio.to_thread(newest_tree_mtime, candidate)
            last_activity_at = datetime.fromtimestamp(newest_mtime, UTC)
            latest_event = await self._latest_orphan_event(str(resolved))
            registered_project = registered.get(resolved)
            if latest_event is None or latest_event.event_type in {
                "ORPHAN_WORKTREE_DELETED",
                "ORPHAN_WORKTREE_RESOLVED",
            }:
                detected_at = now
                await self._audit(
                    "ORPHAN_WORKTREE_DETECTED",
                    "WARNING",
                    "worktree",
                    str(resolved),
                    project_id=(registered_project.id if registered_project else None),
                    details={
                        "last_activity_at": last_activity_at.isoformat(),
                    },
                )
                logger.warning("Orphan worktree detected: %s", resolved)
            elif latest_event.event_type == "ORPHAN_WORKTREE_DETECTED":
                detected_at = _as_utc(latest_event.timestamp)
            else:
                # A failed deletion is only emitted after the detection grace elapsed.
                detected_at = now - grace
            eligible_since = max(detected_at, last_activity_at)
            age = now - eligible_since
            if age < grace:
                continue
            project = registered_project
            try:
                self.git.assert_beneath(candidate, root)
                if project is not None:
                    async with project_git_locks.for_project(project.id):
                        await self.git.remove_worktree(
                            Path(project.local_path), candidate, branch=None
                        )
                else:
                    await asyncio.to_thread(shutil.rmtree, candidate)
                if await asyncio.to_thread(os.path.lexists, candidate):
                    raise GitError(f"Orphan worktree still exists after deletion: {candidate}")
            except (GitError, OSError) as exc:
                await self._audit(
                    "ORPHAN_WORKTREE_DELETE_FAILED",
                    "ERROR",
                    "worktree",
                    str(resolved),
                    project_id=project.id if project else None,
                    details={"error": str(exc)},
                )
                logger.exception("Could not delete orphan worktree %s", resolved)
                continue
            await self._audit(
                "ORPHAN_WORKTREE_DELETED",
                "INFO",
                "worktree",
                str(resolved),
                project_id=project.id if project else None,
                details={
                    "detected_at": detected_at.isoformat(),
                    "last_activity_at": last_activity_at.isoformat(),
                },
            )
            logger.info("Deleted orphan worktree after grace period: %s", resolved)

    async def _registered_worktrees(
        self, projects: Iterable[Project]
    ) -> dict[Path, Project]:
        registered: dict[Path, Project] = {}
        for project in projects:
            repository = Path(project.local_path)
            if not await asyncio.to_thread(repository.is_dir):
                continue
            try:
                output = await self.git.run(
                    ["worktree", "list", "--porcelain"], cwd=repository
                )
            except GitError as exc:
                logger.warning("Could not list worktrees for project %s: %s", project.id, exc)
                continue
            for line in output.splitlines():
                if line.startswith("worktree "):
                    path = Path(line.removeprefix("worktree "))
                    registered[await asyncio.to_thread(path.resolve)] = project
        return registered

    async def _latest_orphan_event(
        self, resource_path: str
    ) -> ResourceAuditLog | None:
        return cast(
            ResourceAuditLog | None,
            await self.session.scalar(
                select(ResourceAuditLog)
                .where(
                    ResourceAuditLog.resource_path == resource_path,
                    ResourceAuditLog.event_type.in_(
                        {
                            "ORPHAN_WORKTREE_DETECTED",
                            "ORPHAN_WORKTREE_DELETED",
                            "ORPHAN_WORKTREE_RESOLVED",
                            "ORPHAN_WORKTREE_DELETE_FAILED",
                        }
                    ),
                )
                .order_by(ResourceAuditLog.id.desc())
                .limit(1)
            ),
        )

    async def _record_storage_alerts(self, usages: list[StorageRootUsage]) -> None:
        for usage in usages:
            warning = usage.root_warning or usage.filesystem_warning
            latest = await self.session.scalar(
                select(ResourceAuditLog)
                .where(
                    ResourceAuditLog.resource_path == str(usage.path.resolve()),
                    ResourceAuditLog.event_type.in_(
                        {"STORAGE_USAGE_WARNING", "STORAGE_USAGE_RECOVERED"}
                    ),
                )
                .order_by(ResourceAuditLog.id.desc())
                .limit(1)
            )
            latest_is_warning = latest is not None and latest.event_type == "STORAGE_USAGE_WARNING"
            if warning == latest_is_warning:
                continue
            event_type = "STORAGE_USAGE_WARNING" if warning else "STORAGE_USAGE_RECOVERED"
            level = "WARNING" if warning else "INFO"
            details: dict[str, object] = {
                "root_bytes": usage.bytes,
                "filesystem_used_percent": round(usage.filesystem_used_percent, 2),
                "root_threshold_exceeded": usage.root_warning,
                "filesystem_threshold_exceeded": usage.filesystem_warning,
            }
            await self._audit(
                event_type,
                level,
                "storage_root",
                str(usage.path.resolve()),
                details=details,
            )
            log = logger.warning if warning else logger.info
            log("%s for %s: %s", event_type, usage.name, details)

    async def _audit(
        self,
        event_type: str,
        level: str,
        resource_type: str,
        resource_path: str | None,
        *,
        run_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            ResourceAuditLog(
                event_type=event_type,
                level=level,
                resource_type=resource_type,
                resource_path=resource_path,
                run_id=run_id,
                project_id=project_id,
                details=details or {},
            )
        )
        await self.session.flush()

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


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
