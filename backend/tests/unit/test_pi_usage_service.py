from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    NodeAttempt,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.engine.output_paths import node_attempt_directory
from backend.services.pi_usage_service import PiUsageService


def stored_usage(total: int, cost: float) -> dict[str, object]:
    return {
        "input": total - 10,
        "output": 10,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": total,
        "cost": {
            "input": 0,
            "output": cost,
            "cacheRead": 0,
            "cacheWrite": 0,
            "total": cost,
        },
        "requestCount": 1,
    }


async def test_run_usage_includes_persisted_and_historical_attempts(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    user = User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner")
    project = Project(
        id=uuid.uuid4(),
        name="Project",
        git_url="https://example.invalid/project.git",
        provider="github",
        provider_project_id="1",
        provider_project_path="example/project",
        encrypted_access_token=b"ciphertext",
        local_path=str(tmp_path / "project"),
        default_branch="main",
        added_by=user.id,
    )
    run_data = tmp_path / "run-data"
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status="COMPLETED",
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
    node = NodeExecution(
        id=uuid.uuid4(),
        run_id=run.id,
        invocation_id=invocation.id,
        node_id="implement",
        node_path="root/implement",
        node_type="prompt",
        status="SUCCESS",
        current_attempt=2,
    )
    persisted = NodeAttempt(
        id=uuid.uuid4(),
        node_execution_id=node.id,
        attempt_number=1,
        status="FAILED",
        pi_usage=stored_usage(100, 0.1),
    )
    historical = NodeAttempt(
        id=uuid.uuid4(),
        node_execution_id=node.id,
        attempt_number=2,
        status="SUCCESS",
    )
    output = node_attempt_directory(run_data, node.node_path, 2)
    output.mkdir(parents=True)
    (output / "pi_events.jsonl").write_text(
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"usage":{"input":180,"output":20,"cacheRead":50,"cacheWrite":0,'
        '"totalTokens":250,"cost":{"input":0.1,"output":0.1,"cacheRead":0.01,'
        '"cacheWrite":0,"total":0.21}}}}\n',
        encoding="utf-8",
    )
    db_session.add_all([user, project, run, invocation, node, persisted, historical])
    await db_session.commit()

    result = await PiUsageService(db_session).get_run_usage(run)

    assert result["usage"]["totalTokens"] == 350
    assert result["usage"]["requestCount"] == 2
    assert result["attempt_count"] == 2
    assert [item["source"] for item in result["nodes"][0]["attempts"]] == [
        "persisted",
        "events",
    ]
