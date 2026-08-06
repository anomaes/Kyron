from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    InvocationWorkspace,
    Project,
    RunLog,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.engine.nodes.process_nodes import NodeExecutionRequest, ProcessNodeExecutor
from backend.engine.process_runner import ProcessResult
from backend.engine.waves import ProcessWorkflowNode, WaveExecutor
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowDefinition
from backend.services.engine_log_service import EngineLogService
from backend.services.log_broadcaster import LogBroadcaster
from backend.tests.fixtures.workflows import workflow

SKILL_WARNING = "Pi skill '.agents/skills/release' declares no description"


class SkippedSkillExecutor:
    """Stands in for a prompt node whose configured skill Pi would not have loaded."""

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
            pi_skill_warning=SKILL_WARNING,
        )


class CleanGit:
    async def ensure_clean(self, _: Path) -> None:
        return None

    async def head_sha(self, _: Path) -> str:
        return "a" * 40

    async def checkpoint(self, _: Path, __: str) -> str:
        return "b" * 40


async def test_skipped_pi_skill_is_recorded_on_the_run_log(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner")
    project = Project(
        id=uuid.uuid4(),
        name="Project",
        git_url="https://example.invalid/project.git",
        provider="github",
        provider_project_id="skill",
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
        branch_name="run/skill",
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
                    "config": {
                        "prompt": "Implement the change",
                        "skill": ".agents/skills/release",
                    },
                    "position": {"x": 0, "y": 0},
                }
            ]
        )
    )

    async def credentials(_: uuid.UUID) -> dict[str, str]:
        return {}

    broadcaster = LogBroadcaster()
    subscription = broadcaster.subscribe(run.id)
    await WaveExecutor(
        db_session,
        cast(GitManager, CleanGit()),
        cast(ProcessNodeExecutor, SkippedSkillExecutor()),
        credentials,
        EngineLogService(db_session, broadcaster),
    ).execute(run, invocation, definition, [cast(ProcessWorkflowNode, definition.nodes[0])])

    logs = list(await db_session.scalars(select(RunLog).order_by(RunLog.id)))
    skipped = [log for log in logs if log.event_type == "PI_SKILL_SKIPPED"]
    assert len(skipped) == 1
    assert skipped[0].level == "WARNING"
    assert SKILL_WARNING in skipped[0].message
    assert "The prompt ran without it." in skipped[0].message
    assert skipped[0].node_path is not None
    assert skipped[0].invocation_path == "root"

    # The node still succeeds, so the warning is the only signal the skill was skipped.
    assert [log.event_type for log in logs].index("PI_SKILL_SKIPPED") < [
        log.event_type for log in logs
    ].index("NODE_SUCCESS")

    streamed = []
    while not subscription.queue.empty():
        streamed.append(subscription.queue.get_nowait())
    warnings = [event for event in streamed if event.get("event_type") == "PI_SKILL_SKIPPED"]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "WARNING"
    assert warnings[0]["type"] == "log"
    assert warnings[0]["sequence"] == skipped[0].id
