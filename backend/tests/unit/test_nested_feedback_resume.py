from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import NodeExecution, Project, User, WorkflowInvocation, WorkflowRun
from backend.db.statuses import InvocationStatus, NodeStatus, RunStatus
from backend.engine.coordinator import RunCoordinator, RunPaused
from backend.engine.waves import WaveExecutor
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition
from backend.services.crypto import SecretCipher
from backend.tests.fixtures.workflows import workflow


async def test_nested_feedback_pause_resumes_child_and_completes_parent(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(email="nested-review@example.com", display_name="Reviewer")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Nested review project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="123",
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "repository"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()

    root_definition = WorkflowDefinition.model_validate(
        workflow(
            nodes=[
                {
                    "id": "implementation",
                    "type": "subworkflow",
                    "label": "Implementation",
                    "config": {"workflow_id": "child"},
                    "position": {"x": 0, "y": 0},
                }
            ]
        )
    )
    child_definition = WorkflowDefinition.model_validate(
        workflow(
            "child",
            nodes=[
                {
                    "id": "review",
                    "type": "human_feedback",
                    "label": "Review",
                    "config": {},
                    "position": {"x": 0, "y": 0},
                }
            ],
        )
    )
    bundle = WorkflowBundle(
        base_commit_sha="a" * 40,
        root_workflow_id="root",
        workflows={"root": root_definition, "child": child_definition},
        reference_graph={"root": ["child"], "child": []},
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.RUNNING,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot=bundle.model_dump(mode="json"),
        public_context={},
        worktree_path=str(worktree),
        reviewer_provider="gitlab",
        reviewer_provider_user_id="7",
        reviewer_provider_username="reviewer",
    )
    db_session.add(run)
    await db_session.flush()
    root_invocation = WorkflowInvocation(
        run_id=run.id,
        workflow_id="root",
        invocation_path="root",
        status=InvocationStatus.PENDING,
    )
    db_session.add(root_invocation)
    await db_session.commit()

    coordinator = RunCoordinator(
        db_session,
        cast(GitManager, object()),
        cast(Any, object()),
        cast(SecretCipher, object()),
        cast(WaveExecutor, object()),
    )

    async def pause_for_feedback(*args: Any, **kwargs: Any) -> None:
        invocation = cast(WorkflowInvocation, args[1])
        definition = cast(WorkflowDefinition, args[2])
        node = args[3]
        execution = await coordinator._node_execution(
            run, invocation, definition, node.id
        )
        execution.status = NodeStatus.AWAITING_FEEDBACK
        run.status = RunStatus.AWAITING_FEEDBACK
        run.current_invocation_id = invocation.id
        run.current_node_execution_id = execution.id
        await db_session.commit()
        raise RunPaused()

    monkeypatch.setattr(coordinator, "_pause_for_feedback", pause_for_feedback)

    with pytest.raises(RunPaused):
        await coordinator.execute_invocation(
            run, root_invocation, bundle, project, user
        )

    parent_execution = await db_session.scalar(
        select(NodeExecution).where(
            NodeExecution.invocation_id == root_invocation.id,
            NodeExecution.node_id == "implementation",
        )
    )
    child_invocation = await db_session.scalar(
        select(WorkflowInvocation).where(
            WorkflowInvocation.invocation_path == "root/implementation"
        )
    )
    assert parent_execution is not None
    assert child_invocation is not None
    child_execution = await db_session.scalar(
        select(NodeExecution).where(
            NodeExecution.invocation_id == child_invocation.id,
            NodeExecution.node_id == "review",
        )
    )
    assert child_execution is not None
    assert run.status == RunStatus.AWAITING_FEEDBACK
    assert parent_execution.status == NodeStatus.RUNNING
    assert child_execution.status == NodeStatus.AWAITING_FEEDBACK

    child_execution.status = NodeStatus.SUCCESS
    run.status = RunStatus.RUNNING
    run.current_node_execution_id = None
    await db_session.commit()

    outputs = await coordinator.execute_invocation(
        run, root_invocation, bundle, project, user
    )

    assert outputs == {}
    assert child_invocation.status == InvocationStatus.SUCCESS
    assert parent_execution.status == NodeStatus.SUCCESS
    assert root_invocation.status == InvocationStatus.SUCCESS
