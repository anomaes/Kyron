from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

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
from backend.engine.coordinator import RunCoordinator
from backend.engine.waves import WaveExecutor
from backend.integrations.code_host import ChangeRequest, CodeHostError, ProviderUser
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowDefinition
from backend.services.crypto import SecretCipher
from backend.tests.fixtures.workflows import workflow


class AmbiguousCreateCodeHost:
    provider = "github"

    def __init__(self, run: WorkflowRun) -> None:
        self.run = run
        self.created = False
        self.calls: list[str] = []

    async def find_change_request(self, *args: Any, **kwargs: Any) -> ChangeRequest | None:
        self.calls.append("find")
        if not self.created:
            return None
        return ChangeRequest(
            number=17,
            url="https://github.test/acme/widget/pull/17",
            state="open",
        )

    async def create_change_request(self, *args: Any, **kwargs: Any) -> ChangeRequest:
        self.calls.append("create")
        self.created = True
        raise CodeHostError("github", "pull request creation")

    async def update_change_request_reviewers(
        self,
        repository: str,
        number: int,
        token: str,
        reviewers: list[ProviderUser],
    ) -> None:
        self.calls.append("reviewers")
        assert self.run.change_request_number == number


class CheckpointGit:
    def __init__(self, sha: str) -> None:
        self.sha = sha
        self.messages: list[str] = []

    async def checkpoint(self, worktree: Path, message: str) -> str:
        self.messages.append(message)
        return self.sha


async def test_ambiguous_change_request_creation_is_reconciled_before_retry(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="runner@example.com", display_name="Runner")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Project",
        git_url="https://github.test/acme/widget.git",
        provider="github",
        provider_project_id="123",
        provider_project_path="acme/widget",
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
        branch_name=f"workflow/root_{uuid.uuid4().hex[:8]}",
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="alice",
    )
    db_session.add(run)
    await db_session.commit()
    definition_data = workflow()
    definition_data["settings"] = {
        "mr_title_template": "Workflow run",
        "mr_description_template": "Review this run",
    }
    definition = WorkflowDefinition.model_validate(definition_data)
    code_host = AmbiguousCreateCodeHost(run)
    run_id = run.id
    coordinator = RunCoordinator(
        db_session,
        cast(GitManager, object()),
        cast(Any, code_host),
        cast(SecretCipher, object()),
        cast(WaveExecutor, object()),
    )

    await coordinator._ensure_merge_request(run, project, definition, "token")

    db_session.expire_all()
    stored = await db_session.get(WorkflowRun, run_id)
    assert stored is not None
    assert stored.change_request_number == 17
    assert stored.change_request_url == "https://github.test/acme/widget/pull/17"
    assert code_host.calls == ["find", "create", "find", "reviewers"]


async def test_pending_local_finalization_completes_without_replaying_workflow(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="local@example.com", display_name="Local runner")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Local project",
        git_url="https://github.test/acme/local.git",
        provider="github",
        provider_project_id="456",
        provider_project_path="acme/local",
        encrypted_access_token=b"unused",
        local_path=str(tmp_path / "repository-local"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    worktree = tmp_path / "worktree-local"
    worktree.mkdir()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.RUNNING,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        local_definition_test=True,
        public_context={},
        branch_name="workflow/local_run",
        worktree_path=str(worktree),
        current_head_sha="b" * 40,
        pending_operation="FINAL_PUBLICATION",
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="alice",
    )
    db_session.add(run)
    await db_session.commit()
    definition_data = workflow()
    definition_data["settings"] = {"final_commit_message_template": "Finish run"}
    definition = WorkflowDefinition.model_validate(definition_data)
    git = CheckpointGit("c" * 40)
    coordinator = RunCoordinator(
        db_session,
        cast(Any, git),
        cast(Any, object()),
        cast(SecretCipher, object()),
        cast(WaveExecutor, object()),
    )

    await coordinator._finish_final_publication(run, project, definition)

    assert run.status == RunStatus.COMPLETED
    assert run.pending_operation is None
    assert run.final_commit_sha == "c" * 40
    assert run.current_head_sha == "c" * 40
    assert git.messages == ["Finish run"]


async def test_pending_feedback_publication_opens_existing_gate(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = User(email="review@example.com", display_name="Reviewer")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Review project",
        git_url="https://github.test/acme/review.git",
        provider="github",
        provider_project_id="789",
        provider_project_path="acme/review",
        encrypted_access_token=b"unused",
        local_path=str(tmp_path / "repository-review"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    worktree = tmp_path / "worktree-review"
    worktree.mkdir()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.RUNNING,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        local_definition_test=True,
        public_context={},
        branch_name="workflow/review_run",
        worktree_path=str(worktree),
        current_head_sha="b" * 40,
        pending_operation="FEEDBACK_PUBLICATION",
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="alice",
    )
    db_session.add(run)
    await db_session.flush()
    invocation = WorkflowInvocation(
        run_id=run.id,
        workflow_id="root",
        invocation_path="root",
        status="RUNNING",
    )
    db_session.add(invocation)
    await db_session.flush()
    execution = NodeExecution(
        run_id=run.id,
        invocation_id=invocation.id,
        node_id="review",
        node_path="root/review",
        node_type="human_feedback",
        status=NodeStatus.INTERRUPTED,
        output_values={"review_iteration": 1},
    )
    db_session.add(execution)
    await db_session.flush()
    gate = GateInstance(
        run_id=run.id,
        invocation_id=invocation.id,
        node_execution_id=execution.id,
        iteration=1,
        checkpoint_commit_sha="b" * 40,
        policy_key="default_review",
        policy_snapshot={},
        eligible_snapshot={},
        status="PUBLISHING",
    )
    db_session.add(gate)
    run.current_invocation_id = invocation.id
    run.current_node_execution_id = execution.id
    await db_session.commit()
    definition = WorkflowDefinition.model_validate(
        workflow(
            nodes=[
                {
                    "id": "review",
                    "type": "human_feedback",
                    "label": "Review",
                    "config": {},
                    "position": {"x": 0, "y": 0},
                }
            ]
        )
    )
    coordinator = RunCoordinator(
        db_session,
        cast(GitManager, object()),
        cast(Any, object()),
        cast(SecretCipher, object()),
        cast(WaveExecutor, object()),
    )

    await coordinator._publish_feedback_checkpoint(
        run,
        invocation,
        definition,
        cast(Any, definition.nodes[0]),
        execution,
        project,
        iteration=1,
    )

    assert run.status == RunStatus.AWAITING_FEEDBACK
    assert run.pending_operation is None
    assert execution.status == NodeStatus.AWAITING_FEEDBACK
    assert gate.status == "OPEN"
