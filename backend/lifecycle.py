from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress

from sqlalchemy import select

from backend.config import Settings, get_settings
from backend.db.database import session_factory
from backend.db.models import Credential, Project, WorkflowRun
from backend.db.statuses import RunStatus
from backend.engine.coordinator import RunCoordinator
from backend.engine.nodes.process_nodes import ProcessNodeExecutor
from backend.engine.process_registry import process_registry
from backend.engine.process_runner import ProcessRunner
from backend.engine.resume import mark_interrupted_runs
from backend.engine.task_registry import TaskRegistry
from backend.engine.waves import WaveExecutor
from backend.integrations.code_host import create_code_host_client
from backend.integrations.git_manager import GitManager
from backend.services.crypto import SecretCipher
from backend.services.log_broadcaster import log_broadcaster
from backend.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)


class EngineRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tasks = TaskRegistry(settings.MAX_CONCURRENT_RUNS)
        self._queue_reconciler_task: asyncio.Task[None] | None = None
        self._resource_reconciler_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        async with session_factory() as session:
            await mark_interrupted_runs(session)
            queued = list(
                await session.scalars(
                    select(WorkflowRun.id)
                    .where(WorkflowRun.status == RunStatus.QUEUED)
                    .order_by(WorkflowRun.queued_at)
                )
            )
        for run_id in queued:
            await self.schedule(run_id)
        self._queue_reconciler_task = asyncio.create_task(
            self._queue_reconciler(), name="queue-reconciler"
        )
        self._resource_reconciler_task = asyncio.create_task(
            self._resource_reconciler(), name="resource-reconciler"
        )

    async def stop(self) -> None:
        for task in (self._queue_reconciler_task, self._resource_reconciler_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def schedule(self, run_id: uuid.UUID) -> None:
        await self.tasks.schedule(run_id, lambda: self._execute(run_id))

    async def reschedule(self, run_id: uuid.UUID) -> None:
        await self.tasks.wait(run_id)
        if not await self.tasks.schedule(run_id, lambda: self._execute(run_id)):
            raise RuntimeError(f"Could not schedule resumed run {run_id}")

    async def _execute(self, run_id: uuid.UUID) -> None:
        settings = self.settings
        cipher = SecretCipher(
            settings.CREDENTIALS_ENCRYPTION_KEY,
            settings.CREDENTIALS_ENCRYPTION_KEY_VERSION,
        )
        git = GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        )

        async def credentials(user_id: uuid.UUID) -> dict[str, str]:
            async with session_factory() as credential_session:
                rows = list(
                    await credential_session.scalars(
                        select(Credential).where(Credential.user_id == user_id)
                    )
                )
                return {row.key_name: cipher.decrypt(row.encrypted_value) for row in rows}

        async with session_factory() as session:
            run = await session.get(WorkflowRun, run_id)
            if run is None:
                return
            project = await session.get(Project, run.project_id)
            if project is None:
                return
            code_host = create_code_host_client(project.provider, settings)
            runner = ProcessRunner(
                process_registry,
                log_broadcaster,
                settings.PROCESS_TERMINATION_GRACE_SECONDS,
            )
            waves = WaveExecutor(session, git, ProcessNodeExecutor(runner), credentials)
            try:
                coordinator = RunCoordinator(session, git, code_host, cipher, waves)
                await coordinator.execute_run(run_id)
            finally:
                await code_host.close()

    async def _queue_reconciler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.QUEUE_RECONCILIATION_INTERVAL_SECONDS)
            async with session_factory() as session:
                queued = list(
                    await session.scalars(
                        select(WorkflowRun.id)
                        .where(WorkflowRun.status == RunStatus.QUEUED)
                        .order_by(WorkflowRun.queued_at)
                    )
                )
            for run_id in queued:
                await self.schedule(run_id)

    async def _resource_reconciler(self) -> None:
        while True:
            await asyncio.sleep(self.settings.STALE_RESOURCE_RECONCILIATION_INTERVAL_SECONDS)
            cipher = (
                SecretCipher(
                    self.settings.CREDENTIALS_ENCRYPTION_KEY,
                    self.settings.CREDENTIALS_ENCRYPTION_KEY_VERSION,
                )
                if self.settings.CREDENTIALS_ENCRYPTION_KEY
                else None
            )
            try:
                async with session_factory() as session:
                    await ReconciliationService(
                        session,
                        self.settings,
                        cipher,
                        GitManager(
                            self.settings.PROJECT_CLONE_BASE_PATH,
                            self.settings.WORKTREE_BASE_PATH,
                            self.settings.RUN_DATA_BASE_PATH,
                        ),
                        process_registry,
                        self.tasks,
                    ).reconcile()
            except Exception:
                logger.exception("Stale-resource reconciliation failed")


runtime = EngineRuntime(get_settings())
