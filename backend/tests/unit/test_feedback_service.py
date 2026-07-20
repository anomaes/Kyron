from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    GateInstance,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import NodeStatus, RunStatus
from backend.integrations.gitlab_client import GitLabClient, GitLabError
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition
from backend.services.crypto import SecretCipher
from backend.services.feedback_service import FeedbackService
from backend.tests.fixtures.workflows import workflow


async def waiting_run(
    session: AsyncSession,
    tmp_path: Path,
    cipher: SecretCipher,
    *,
    review_loop: bool = False,
) -> tuple[WorkflowRun, User, NodeExecution]:
    user = User(
        id=uuid.uuid4(),
        email="reviewer@example.com",
        display_name="Reviewer",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Project",
        git_url="https://gitlab.example/g/r.git",
        provider="gitlab",
        provider_project_id="12",
        provider_project_path="12",
        encrypted_access_token=cipher.encrypt("project-token"),
        local_path=str(tmp_path / "repo"),
        default_branch="main",
        added_by=user.id,
    )
    node = (
        {
            "id": "review",
            "type": "review_loop",
            "label": "review",
            "config": {
                "approval_policy": "review",
                "initial_workflow_id": "child",
                "max_iterations": 3,
            },
        }
        if review_loop
        else {
            "id": "wait",
            "type": "human_feedback",
            "label": "wait",
            "config": {"approval_policy": "review"},
        }
    )
    root_definition = WorkflowDefinition.model_validate(workflow(nodes=[node]))
    definitions = {"root": root_definition}
    graph = {"root": ["child"] if review_loop else []}
    if review_loop:
        child = WorkflowDefinition.model_validate(workflow("child"))
        definitions["child"] = child
        graph["child"] = []
    bundle = WorkflowBundle(
        base_commit_sha="a" * 40,
        root_workflow_id="root",
        workflows=definitions,
        reference_graph=graph,
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.AWAITING_FEEDBACK,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot=bundle.model_dump(mode="json"),
        public_context={},
        worktree_path=str(tmp_path),
        change_request_number=42,
        reviewer_provider="gitlab",
        reviewer_provider_user_id="777",
        reviewer_provider_username="reviewer",
    )
    invocation = WorkflowInvocation(
        id=uuid.uuid4(),
        run_id=run.id,
        workflow_id="root",
        invocation_path="root",
        status="RUNNING",
    )
    execution = NodeExecution(
        id=uuid.uuid4(),
        run_id=run.id,
        invocation_id=invocation.id,
        node_id=node["id"],
        node_path=f"root/{node['id']}",
        node_type=node["type"],
        status=NodeStatus.AWAITING_FEEDBACK,
        output_values={"review_iteration": 1},
    )
    run.current_invocation_id = invocation.id
    run.current_node_execution_id = execution.id
    gate = GateInstance(
        run_id=run.id,
        invocation_id=invocation.id,
        node_execution_id=execution.id,
        iteration=1,
        checkpoint_commit_sha="b" * 40,
        policy_key="review",
        policy_snapshot={
            "key": "review",
            "name": "Review",
            "distinct_approvers_across_requirements": True,
            "eligible_approvers_may_give_feedback": True,
            "requirements": [{"key": "review", "name": "Review", "quorum": 1}],
        },
        eligible_snapshot={
            "requirements": [
                {
                    "key": "review",
                    "name": "Review",
                    "quorum": 1,
                    "users": [
                        {
                            "user_id": str(user.id),
                            "display_name": user.display_name,
                            "email": user.email,
                            "provider": "gitlab",
                            "provider_user_id": "777",
                            "provider_username": "reviewer",
                        }
                    ],
                }
            ]
        },
    )
    session.add_all([user, project, run, invocation, execution, gate])
    await session.commit()
    return run, user, execution


async def test_only_policy_eligible_user_is_accepted(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    run, _, _ = await waiting_run(db_session, tmp_path, cipher)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        service = FeedbackService(
            db_session, cipher, GitLabClient("https://gitlab.example", client), lambda _: _noop()
        )
        with pytest.raises(PermissionError):
            await service.accept(
                run.id,
                event_type="comment",
                source="gitlab",
                author_provider="gitlab",
                author_provider_user_id="999",
                author_username="other",
                message="change it",
            )


async def test_review_comment_creates_next_iteration_and_schedules(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    run, user, execution = await waiting_run(db_session, tmp_path, cipher, review_loop=True)
    scheduled: list[uuid.UUID] = []

    async def schedule(run_id: uuid.UUID) -> None:
        scheduled.append(run_id)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        service = FeedbackService(
            db_session, cipher, GitLabClient("https://gitlab.example", client), schedule
        )
        event = await service.accept(
            run.id,
            event_type="comment",
            source="gitlab",
            author_provider="gitlab",
            author_provider_user_id="777",
            author_username="reviewer",
            message="update docs",
        )
    assert event.event_type == "comment"
    assert execution.status == NodeStatus.PENDING
    assert execution.output_values["review_iteration"] == 2
    assert run.public_context["FEEDBACK"] == "update docs"
    assert scheduled == [run.id]


async def test_approval_reset_failure_leaves_run_waiting(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    cipher = SecretCipher(Fernet.generate_key())
    run, user, _ = await waiting_run(db_session, tmp_path, cipher)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"detailed_merge_status": "mergeable"})
        return httpx.Response(403, json={"message": "forbidden"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = FeedbackService(
            db_session, cipher, GitLabClient("https://gitlab.example", client), lambda _: _noop()
        )
        with pytest.raises(GitLabError):
            await service.accept(
                run.id,
                event_type="approval",
                source="gitlab",
                author_provider="gitlab",
                author_provider_user_id="777",
                author_username="reviewer",
            )
    assert run.status == RunStatus.AWAITING_FEEDBACK


async def _noop() -> None:
    return None
