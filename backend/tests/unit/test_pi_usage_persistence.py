from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    InvocationWorkspace,
    NodeAttempt,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.engine.nodes.process_nodes import NodeExecutionRequest, ProcessNodeExecutor
from backend.engine.process_runner import ProcessResult
from backend.engine.waves import ProcessWorkflowNode, WaveExecutor
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowDefinition
from backend.tests.fixtures.workflows import workflow


class UsageExecutor:
    async def execute(
        self,
        _: ProcessWorkflowNode,
        request: NodeExecutionRequest,
    ) -> ProcessResult:
        request.secrets.clear()
        request.output_directory.mkdir(parents=True)
        stdout = request.output_directory / "pi_events.jsonl"
        stderr = request.output_directory / "stderr.log"
        stdout.write_text("", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return ProcessResult(
            exit_code=0,
            stdout_path=stdout,
            stderr_path=stderr,
            stdout_preview="",
            stderr_preview="",
            pi_usage={
                "input": 90,
                "output": 10,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 100,
                "cost": {
                    "input": 0.1,
                    "output": 0.1,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0.2,
                },
                "requestCount": 1,
            },
        )


class CleanGit:
    async def ensure_clean(self, _: Path) -> None:
        return None

    async def head_sha(self, _: Path) -> str:
        return "a" * 40

    async def checkpoint(self, _: Path, __: str) -> str:
        return "b" * 40


async def test_wave_persists_pi_usage_on_the_attempt(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner")
    project = Project(
        id=uuid.uuid4(),
        name="Project",
        git_url="https://example.invalid/project.git",
        provider="github",
        provider_project_id="usage",
        provider_project_path="example/project",
        encrypted_access_token=b"ciphertext",
        local_path=str(tmp_path / "project"),
        default_branch="main",
        added_by=user.id,
    )
    run_data = tmp_path / "run-data"
    worktree = tmp_path / "worktree"
    run_data.mkdir()
    worktree.mkdir()
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status="RUNNING",
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        run_data_path=str(run_data),
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="owner",
    )
    invocation = WorkflowInvocation(
        id=uuid.uuid4(),
        run_id=run.id,
        workflow_id="root",
        invocation_path="root",
    )
    workspace = InvocationWorkspace(
        id=uuid.uuid4(),
        run_id=run.id,
        owner_invocation_id=invocation.id,
        mode="ROOT",
        status="RUNNING",
        base_commit_sha="a" * 40,
        current_head_sha="a" * 40,
        branch_name="run/usage",
        worktree_path=str(worktree),
    )
    db_session.add_all([user, project, run, invocation])
    await db_session.commit()
    db_session.add(workspace)
    await db_session.commit()
    invocation.workspace_id = workspace.id
    await db_session.commit()
    definition = WorkflowDefinition.model_validate(
        workflow(
            nodes=[
                {
                    "id": "implement",
                    "type": "prompt",
                    "label": "Implement",
                    "config": {"prompt": "Implement the change"},
                    "position": {"x": 0, "y": 0},
                }
            ]
        )
    )

    async def credentials(_: uuid.UUID) -> dict[str, str]:
        return {}

    await WaveExecutor(
        db_session,
        cast(GitManager, CleanGit()),
        cast(ProcessNodeExecutor, UsageExecutor()),
        credentials,
    ).execute(run, invocation, definition, [cast(ProcessWorkflowNode, definition.nodes[0])])

    attempt = await db_session.scalar(select(NodeAttempt))
    assert attempt is not None
    assert attempt.status == "SUCCESS"
    assert attempt.pi_usage is not None
    assert attempt.pi_usage["totalTokens"] == 100
    assert attempt.pi_usage["requestCount"] == 1
