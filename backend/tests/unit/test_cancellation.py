from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Project, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.engine.cancellation import cancel_run
from backend.engine.process_registry import ProcessRegistry
from backend.engine.task_registry import TaskRegistry


class CompletingTaskRegistry:
    def __init__(self, session: AsyncSession) -> None:
        self.bind = session.bind

    async def cancel(self, run_id: uuid.UUID) -> bool:
        assert self.bind is not None
        factory = async_sessionmaker(self.bind, expire_on_commit=False)
        async with factory() as session:
            run = await session.get(WorkflowRun, run_id)
            assert run is not None
            run.status = RunStatus.COMPLETED
            run.final_commit_sha = "c" * 40
            await session.commit()
        return True


class NoProcesses:
    async def terminate_run(self, run_id: uuid.UUID, grace_seconds: float) -> None:
        return None


async def test_cancellation_does_not_overwrite_concurrent_completion(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="cancel@example.com", display_name="Runner")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Cancel project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="cancel-project",
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "repository"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.RUNNING,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        reviewer_provider="gitlab",
        reviewer_provider_user_id="7",
        reviewer_provider_username="runner",
    )
    db_session.add(run)
    await db_session.commit()

    result = await cancel_run(
        db_session,
        cast(TaskRegistry, CompletingTaskRegistry(db_session)),
        cast(ProcessRegistry, NoProcesses()),
        run.id,
        0,
    )

    assert result.status == RunStatus.COMPLETED
    assert result.final_commit_sha == "c" * 40
