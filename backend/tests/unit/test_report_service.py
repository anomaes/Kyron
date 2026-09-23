from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.api import run_routes
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import (
    ChangeRequestLifecycleEvent,
    ExecutionWave,
    GateDecision,
    GateInstance,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.services.report_service import ReportService


async def test_terminal_report_contains_child_gates_and_lifecycle_addenda(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: Any
) -> None:
    user = User(email="actor@example.com", display_name="Actor")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="42",
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "report-project"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status="COMPLETED",
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="b" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        trigger_actor_snapshot={"display_name": "Actor", "user_id": str(user.id)},
        reviewer_provider="gitlab",
        reviewer_provider_user_id="7",
        reviewer_provider_username="actor",
    )
    db_session.add(run)
    await db_session.flush()
    root = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="SUCCESS"
    )
    db_session.add(root)
    await db_session.flush()
    child = WorkflowInvocation(
        run_id=run.id,
        workflow_id="child",
        invocation_path="root/call",
        parent_invocation_id=root.id,
        status="SUCCESS",
    )
    db_session.add(child)
    await db_session.flush()
    node = NodeExecution(
        run_id=run.id,
        invocation_id=child.id,
        node_id="approval",
        node_path="root/call/approval",
        node_type="human_feedback",
        status="SUCCESS",
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(
        ExecutionWave(
            run_id=run.id,
            invocation_id=child.id,
            wave_index=1,
            status="SUCCESS",
            start_commit_sha="b" * 40,
            end_commit_sha="c" * 40,
        )
    )
    gate = GateInstance(
        run_id=run.id,
        invocation_id=child.id,
        node_execution_id=node.id,
        checkpoint_commit_sha="c" * 40,
        policy_key="review",
        policy_snapshot={"name": "Review", "requirements": []},
        eligible_snapshot={"requirements": []},
        status="APPROVED",
    )
    db_session.add(gate)
    await db_session.flush()
    db_session.add(
        GateDecision(
            gate_instance_id=gate.id,
            event_type="approval",
            source="frontend",
            actor_user_id=user.id,
            actor_snapshot={"display_name": "Actor"},
            requirement_keys=["review"],
        )
    )
    await db_session.commit()

    report = await ReportService(db_session).get(run)
    assert report["schema_version"] == 3
    assert report["frozen"] is True
    assert report["waves"][0]["status"] == "SUCCESS"
    assert report["nodes"][0]["node_path"] == "root/call/approval"
    assert report["gates"][0]["workflow_id"] == "child"
    assert report["gates"][0]["invocation_path"] == "root/call"
    assert report["gates"][0]["decisions"][0]["event_type"] == "approval"

    db_session.add(
        ChangeRequestLifecycleEvent(
            run_id=run.id,
            event_type="merge",
            provider="gitlab",
            actor_provider_user_id="8",
            actor_username="merger",
        )
    )
    await db_session.commit()
    updated = await ReportService(db_session).get(run)
    assert updated["post_run_lifecycle"][0]["actor_username"] == "merger"

    authorized: list[tuple[Any, ...]] = []

    async def allow(*args: Any, **kwargs: Any) -> None:
        authorized.append(args)

    monkeypatch.setattr(run_routes, "authorize_project", allow)
    response = await run_routes.export_run_report(
        run.id,
        AuthenticatedUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=None,
            provider="gitlab",
            provider_user_id="7",
            provider_username="actor",
        ),
        db_session,
    )

    assert authorized
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-disposition"] == (
        f'attachment; filename="kyron-run-{run.id}-traceability-report.html"'
    )
    assert b"Actor" in response.body
    assert b"merger" in response.body
