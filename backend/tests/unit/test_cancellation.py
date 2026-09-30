from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import (
    NodeAttempt,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import RunStatus
from backend.engine.cancellation import cancel_run
from backend.engine.output_paths import node_attempt_directory
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


async def test_cancellation_persists_partial_pi_summary(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="cancel-pi@example.com", display_name="Runner")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Cancel Pi", git_url="https://gitlab.example/group/repo.git",
        provider="gitlab", provider_project_id="cancel-pi",
        provider_project_path="group/repo", encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "repository"), default_branch="main", added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    root = tmp_path / "run-data"
    run = WorkflowRun(
        root_workflow_id="root", project_id=project.id, triggered_by=user.id,
        status=RunStatus.RUNNING, base_ref="main", base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40, workflow_bundle_snapshot={},
        public_context={}, run_data_path=str(root), reviewer_provider="gitlab",
        reviewer_provider_user_id="7", reviewer_provider_username="runner",
    )
    db_session.add(run)
    await db_session.flush()
    invocation = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root"
    )
    db_session.add(invocation)
    await db_session.flush()
    node = NodeExecution(
        run_id=run.id, invocation_id=invocation.id, node_id="prompt",
        node_path="root/prompt", node_type="prompt", status="RUNNING",
    )
    db_session.add(node)
    await db_session.flush()
    attempt = NodeAttempt(node_execution_id=node.id, attempt_number=1, status="RUNNING")
    db_session.add(attempt)
    output = node_attempt_directory(root, node.node_path, 1)
    output.mkdir(parents=True)
    (output / "pi_events.jsonl").write_text(
        '{"type":"message_end","message":{"role":"assistant",'
        '"provider":"anthropic","model":"sonnet","content":[],"usage":'
        '{"input":7,"output":2,"totalTokens":9}}}\n', encoding="utf-8"
    )
    await db_session.commit()

    result = await cancel_run(
        db_session, TaskRegistry(1), cast(ProcessRegistry, NoProcesses()), run.id, 0
    )
    await db_session.refresh(attempt)
    assert result.status == RunStatus.CANCELLED
    assert attempt.pi_usage is not None and attempt.pi_usage["totalTokens"] == 9
    assert attempt.pi_models == [
        {"provider": "anthropic", "model": "sonnet", "response_models": []}
    ]
