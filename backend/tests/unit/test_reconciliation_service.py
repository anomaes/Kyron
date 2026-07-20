from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import Project, ResourceAuditLog, RunLog, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitManager
from backend.services.reconciliation_service import ReconciliationService
from backend.services.storage_metrics import measure_storage_roots


async def git(*args: str, cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip()


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "PROJECT_CLONE_BASE_PATH": tmp_path / "repos",
        "WORKTREE_BASE_PATH": tmp_path / "worktrees",
        "RUN_DATA_BASE_PATH": tmp_path / "run-data",
        "TERMINAL_WORKTREE_RETENTION_DAYS": 1,
        "ORPHAN_WORKTREE_GRACE_HOURS": 1,
        "WORKTREE_USAGE_WARNING_BYTES": 0,
        "RUN_DATA_USAGE_WARNING_BYTES": 0,
        "FILESYSTEM_USAGE_WARNING_PERCENT": 100,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def user_and_project(tmp_path: Path) -> tuple[User, Project]:
    user = User(
        id=uuid.uuid4(),
        email="retention@example.com",
        display_name="Retention",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Retention",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="901",
        provider_project_path="901",
        encrypted_access_token=b"ciphertext",
        local_path=str(tmp_path / "repos" / "project"),
        default_branch="main",
        added_by=user.id,
    )
    return user, project


def service(
    session: AsyncSession, configured: Settings, manager: GitManager
) -> ReconciliationService:
    return ReconciliationService(
        session,
        configured,
        None,
        manager,
        ProcessRegistry(),
        TaskRegistry(1),
    )


async def test_completed_local_run_worktree_expires(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    configured = settings(tmp_path)
    repository = configured.PROJECT_CLONE_BASE_PATH / "project"
    repository.mkdir(parents=True)
    await git("init", "-b", "main", cwd=repository)
    await git("config", "user.email", "test@example.com", cwd=repository)
    await git("config", "user.name", "Test", cwd=repository)
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    await git("add", "tracked.txt", cwd=repository)
    await git("commit", "-m", "base", cwd=repository)
    base_sha = await git("rev-parse", "HEAD", cwd=repository)
    manager = GitManager(
        configured.PROJECT_CLONE_BASE_PATH,
        configured.WORKTREE_BASE_PATH,
        configured.RUN_DATA_BASE_PATH,
    )
    run_id = uuid.uuid4()
    branch, worktree, run_data = await manager.create_run_worktree(
        repository, run_id, "local-test", base_sha
    )
    user, project = user_and_project(tmp_path)
    run = WorkflowRun(
        id=run_id,
        root_workflow_id="local-test",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.COMPLETED,
        base_ref="main",
        base_commit_sha=base_sha,
        workflow_definition_commit_sha=base_sha,
        workflow_bundle_snapshot={},
        local_definition_test=True,
        public_context={},
        branch_name=branch,
        worktree_path=str(worktree),
        run_data_path=str(run_data),
        reviewer_provider="gitlab",
        reviewer_provider_user_id="901",
        reviewer_provider_username="retention",
        finished_at=datetime.now(UTC) - timedelta(days=2),
    )
    db_session.add_all([user, project, run])
    await db_session.commit()

    await service(db_session, configured, manager).reconcile()

    assert run.worktree_path is None
    assert not worktree.exists()
    assert run_data.exists()
    audit = await db_session.scalar(
        select(ResourceAuditLog).where(
            ResourceAuditLog.event_type == "TERMINAL_WORKTREE_RETENTION_CLEANUP"
        )
    )
    assert audit is not None
    assert audit.run_id == run.id


async def test_old_safe_orphan_is_deleted_and_audited(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    configured = settings(tmp_path)
    configured.WORKTREE_BASE_PATH.mkdir(parents=True)
    orphan = configured.WORKTREE_BASE_PATH / str(uuid.uuid4())
    orphan.mkdir()
    payload = orphan / "artifact.bin"
    payload.write_bytes(b"orphan")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(payload, (old, old))
    os.utime(orphan, (old, old))
    unsafe = configured.WORKTREE_BASE_PATH / "operator-notes"
    unsafe.mkdir()
    user, project = user_and_project(tmp_path)
    db_session.add_all([user, project])
    await db_session.commit()
    manager = GitManager(
        configured.PROJECT_CLONE_BASE_PATH,
        configured.WORKTREE_BASE_PATH,
        configured.RUN_DATA_BASE_PATH,
    )

    reconciler = service(db_session, configured, manager)
    await reconciler.reconcile()

    assert orphan.exists()
    detected = await db_session.scalar(
        select(ResourceAuditLog).where(
            ResourceAuditLog.resource_path == str(orphan.resolve()),
            ResourceAuditLog.event_type == "ORPHAN_WORKTREE_DETECTED",
        )
    )
    assert detected is not None
    detected.timestamp = datetime.now(UTC) - timedelta(hours=2)
    await db_session.commit()

    await reconciler.reconcile()

    assert not orphan.exists()
    assert unsafe.exists()
    event_types = set(
        await db_session.scalars(
            select(ResourceAuditLog.event_type).where(
                ResourceAuditLog.resource_path == str(orphan.resolve())
            )
        )
    )
    assert event_types == {"ORPHAN_WORKTREE_DETECTED", "ORPHAN_WORKTREE_DELETED"}


async def test_long_open_change_request_warning_is_deduplicated(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    configured = settings(tmp_path)
    manager = GitManager(
        configured.PROJECT_CLONE_BASE_PATH,
        configured.WORKTREE_BASE_PATH,
        configured.RUN_DATA_BASE_PATH,
    )
    user, project = user_and_project(tmp_path)
    now = datetime.now(UTC)
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="review",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.COMPLETED,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        worktree_path=str(configured.WORKTREE_BASE_PATH / str(uuid.uuid4())),
        change_request_number=42,
        change_request_created_at=now - timedelta(days=15),
        reviewer_provider="gitlab",
        reviewer_provider_user_id="901",
        reviewer_provider_username="retention",
    )
    db_session.add_all([user, project, run])
    await db_session.commit()
    reconciler = service(db_session, configured, manager)

    await reconciler._warn_long_open_change_request(run, now)
    await db_session.commit()
    await reconciler._warn_long_open_change_request(run, now + timedelta(hours=1))
    await db_session.commit()

    count = await db_session.scalar(
        select(func.count()).select_from(RunLog).where(
            RunLog.run_id == run.id,
            RunLog.event_type == "LONG_OPEN_CHANGE_REQUEST",
        )
    )
    assert count == 1


async def test_storage_threshold_records_warning_and_recovery_once(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    configured = settings(tmp_path, WORKTREE_USAGE_WARNING_BYTES=1)
    configured.WORKTREE_BASE_PATH.mkdir(parents=True)
    payload = configured.WORKTREE_BASE_PATH / "usage.bin"
    payload.write_bytes(b"over threshold")
    manager = GitManager(
        configured.PROJECT_CLONE_BASE_PATH,
        configured.WORKTREE_BASE_PATH,
        configured.RUN_DATA_BASE_PATH,
    )
    reconciler = service(db_session, configured, manager)

    usages = measure_storage_roots(configured)
    await reconciler._record_storage_alerts(usages)
    await db_session.commit()
    await reconciler._record_storage_alerts(usages)
    await db_session.commit()
    payload.unlink()
    await reconciler._record_storage_alerts(measure_storage_roots(configured))
    await db_session.commit()

    events = list(
        await db_session.scalars(
            select(ResourceAuditLog.event_type)
            .where(ResourceAuditLog.resource_type == "storage_root")
            .order_by(ResourceAuditLog.id)
        )
    )
    assert events == ["STORAGE_USAGE_WARNING", "STORAGE_USAGE_RECOVERED"]
