from __future__ import annotations

import uuid
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, RunLog, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitError, GitManager
from backend.services.cleanup_service import CleanupService


async def test_cancelled_run_output_is_removed_and_audited(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    clone_root = tmp_path / "repos"
    worktree_root = tmp_path / "worktrees"
    output_root = tmp_path / "run-data"
    output = output_root / "run-1"
    output.mkdir(parents=True)
    (output / "stdout.log").write_text("safe output", encoding="utf-8")
    user = User(
        id=uuid.uuid4(),
        email="cleanup@example.com",
        display_name="Cleanup",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Cleanup",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="901",
        provider_project_path="901",
        encrypted_access_token=b"ciphertext",
        local_path=str(clone_root / "project"),
        default_branch="main",
        added_by=user.id,
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="cleanup",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.CANCELLED,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        run_data_path=str(output),
        reviewer_provider="gitlab",
        reviewer_provider_user_id="901",
        reviewer_provider_username="cleanup",
    )
    db_session.add_all([user, project, run])
    await db_session.commit()

    await CleanupService(
        db_session,
        GitManager(clone_root, worktree_root, output_root),
        ProcessRegistry(),
        TaskRegistry(1),
        0,
    ).cleanup_run(run.id, remove_output=True)

    assert not output.exists()
    assert run.run_data_path is None
    log = await db_session.scalar(select(RunLog).where(RunLog.run_id == run.id))
    assert log is not None
    assert log.event_type == "RESOURCE_CLEANUP"


async def test_failed_worktree_removal_preserves_database_pointer(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone_root = tmp_path / "repos"
    worktree_root = tmp_path / "worktrees"
    output_root = tmp_path / "run-data"
    worktree = worktree_root / str(uuid.uuid4())
    worktree.mkdir(parents=True)
    user = User(id=uuid.uuid4(), email="failure@example.com", display_name="Failure")
    project = Project(
        id=uuid.uuid4(),
        name="Failure",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="902",
        provider_project_path="902",
        encrypted_access_token=b"ciphertext",
        local_path=str(clone_root / "project"),
        default_branch="main",
        added_by=user.id,
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="failure",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.COMPLETED,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        worktree_path=str(worktree),
        reviewer_provider="gitlab",
        reviewer_provider_user_id="902",
        reviewer_provider_username="failure",
    )
    db_session.add_all([user, project, run])
    await db_session.commit()
    manager = GitManager(clone_root, worktree_root, output_root)

    async def fail_removal(*_: object, **__: object) -> NoReturn:
        raise GitError("simulated removal failure")

    monkeypatch.setattr(manager, "remove_worktree", fail_removal)
    cleanup = CleanupService(
        db_session,
        manager,
        ProcessRegistry(),
        TaskRegistry(1),
        0,
    )

    with pytest.raises(GitError, match="simulated"):
        await cleanup.cleanup_worktree(run)

    assert run.worktree_path == str(worktree)
