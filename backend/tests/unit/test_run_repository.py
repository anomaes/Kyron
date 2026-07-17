import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, User, WorkflowRun
from backend.db.repositories.runs import InvalidStateTransition, RunRepository
from backend.db.statuses import RunStatus


async def create_run(session: AsyncSession) -> WorkflowRun:
    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        display_name="Owner",
        gitlab_user_id=123,
        gitlab_username="owner",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Example",
        git_url="https://gitlab.example/group/repo.git",
        gitlab_project_id=10,
        encrypted_access_token=b"ciphertext",
        local_path="/var/workflowengine/repos/project-10",
        default_branch="main",
        added_by=user.id,
    )
    run = WorkflowRun(
        root_workflow_id="build",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.QUEUED,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        reviewer_gitlab_user_id=user.gitlab_user_id,
    )
    session.add_all([user, project, run])
    await session.commit()
    return run


async def test_atomic_state_transition_increments_version(db_session: AsyncSession) -> None:
    run = await create_run(db_session)
    transitioned = await RunRepository(db_session).transition(
        run.id, expected=RunStatus.QUEUED, new=RunStatus.RUNNING, expected_version=1
    )
    await db_session.commit()
    assert transitioned.status == RunStatus.RUNNING
    assert transitioned.status_version == 2
    assert transitioned.started_at is not None


async def test_stale_state_transition_is_rejected(db_session: AsyncSession) -> None:
    run = await create_run(db_session)
    repository = RunRepository(db_session)
    await repository.transition(run.id, expected=RunStatus.QUEUED, new=RunStatus.RUNNING)
    with pytest.raises(InvalidStateTransition, match="concurrently"):
        await repository.transition(run.id, expected=RunStatus.QUEUED, new=RunStatus.RUNNING)


async def test_invalid_transition_is_rejected_before_query(db_session: AsyncSession) -> None:
    with pytest.raises(InvalidStateTransition, match="Invalid transition"):
        await RunRepository(db_session).transition(
            uuid.uuid4(), expected=RunStatus.QUEUED, new=RunStatus.COMPLETED
        )
