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
from backend.engine.resume import mark_interrupted_runs, mark_run_interrupted
from backend.engine.task_registry import TaskRegistry
from backend.engine.waves import WaveExecutor
from backend.integrations.code_host import create_code_host_client
from backend.integrations.git_manager import GitManager
from backend.services.crypto import SecretCipher
from backend.services.engine_log_service import EngineLogService
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
        logger.info("Initializing workflow runtime")
        async with session_factory() as session:
            interrupted = await mark_interrupted_runs(session)
            queued = list(
                await session.scalars(
                    select(WorkflowRun.id)
                    .where(WorkflowRun.status == RunStatus.QUEUED)
                    .order_by(WorkflowRun.queued_at)
                )
            )
        logger.info(
            "Workflow runtime state restored (interrupted=%s, queued=%s)",
            interrupted,
            len(queued),
        )
        for run_id in queued:
            await self.schedule(run_id)
        self._queue_reconciler_task = asyncio.create_task(
            self._queue_reconciler(), name="queue-reconciler"
        )
        self._resource_reconciler_task = asyncio.create_task(
            self._resource_reconciler(), name="resource-reconciler"
        )
        logger.info("Workflow runtime started")

    async def stop(self) -> None:
        logger.info("Stopping workflow runtime")
        for task in (self._queue_reconciler_task, self._resource_reconciler_task):
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def schedule(self, run_id: uuid.UUID) -> None:
        scheduled = await self.tasks.schedule(run_id, lambda: self._execute(run_id))
        if scheduled:
            logger.info("Workflow run scheduled (run=%s)", run_id)
        else:
            logger.debug("Workflow run is already scheduled (run=%s)", run_id)

    async def reschedule(self, run_id: uuid.UUID) -> None:
        logger.info("Waiting to reschedule workflow run (run=%s)", run_id)
        await self.tasks.wait(run_id)
        if not await self.tasks.schedule(run_id, lambda: self._execute(run_id)):
            raise RuntimeError(f"Could not schedule resumed run {run_id}")
        logger.info("Workflow run rescheduled (run=%s)", run_id)

    async def _execute(self, run_id: uuid.UUID) -> None:
        logger.info("Workflow run worker starting (run=%s)", run_id)
        try:
            await self._execute_owned(run_id)
        except asyncio.CancelledError:
            logger.info("Workflow run worker cancelled (run=%s)", run_id)
            raise
        except Exception as exc:
            exception_type = type(exc).__name__
            logger.error(
                "Workflow run worker crashed (run=%s, exception_type=%s)",
                run_id,
                exception_type,
            )
            try:
                async with session_factory() as recovery_session:
                    await mark_run_interrupted(
                        recovery_session,
                        run_id,
                        error_type="ENGINE_CRASH",
                        error_message=(
                            "Workflow worker stopped unexpectedly "
                            f"({exception_type}); inspect backend logs"
                        ),
                    )
            except Exception as recovery_exc:
                logger.critical(
                    "Could not record workflow worker crash (run=%s, exception_type=%s)",
                    run_id,
                    type(recovery_exc).__name__,
                )
        finally:
            logger.info("Workflow run worker stopped (run=%s)", run_id)

    async def _execute_owned(self, run_id: uuid.UUID) -> None:
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
                logger.warning("Scheduled workflow run no longer exists (run=%s)", run_id)
                return
            project = await session.get(Project, run.project_id)
            if project is None:
                logger.error(
                    "Cannot execute workflow run because its project is missing "
                    "(run=%s, project=%s)",
                    run_id,
                    run.project_id,
                )
                return
            code_host = create_code_host_client(project.provider, settings)
            runner = ProcessRunner(
                process_registry,
                log_broadcaster,
                settings.PROCESS_TERMINATION_GRACE_SECONDS,
            )
            engine_logs = EngineLogService(session, log_broadcaster)
            waves = WaveExecutor(
                session,
                git,
                ProcessNodeExecutor(runner),
                credentials,
                engine_logs,
            )
            try:
                coordinator = RunCoordinator(
                    session,
                    git,
                    code_host,
                    cipher,
                    waves,
                    engine_logs,
                )
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
            logger.debug("Queue reconciliation found %s queued workflow run(s)", len(queued))
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
                logger.debug("Starting stale-resource reconciliation")
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
                logger.debug("Stale-resource reconciliation completed")
            except Exception:
                logger.exception("Stale-resource reconciliation failed")


runtime = EngineRuntime(get_settings())
