from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, RunLog, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitManager
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
        gitlab_user_id=901,
        gitlab_username="cleanup",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Cleanup",
        git_url="https://gitlab.example/group/repo.git",
        gitlab_project_id=901,
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
        reviewer_gitlab_user_id=user.gitlab_user_id,
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
