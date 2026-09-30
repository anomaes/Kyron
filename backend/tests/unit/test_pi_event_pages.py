from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import backend.api.run_routes as run_routes
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import (
    NodeAttempt,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.engine.output_paths import node_attempt_directory
from backend.engine.pi.event_pages import PAGE_MAX_SOURCE_BYTES, read_pi_event_page


def _event(text: str) -> bytes:
    return (json.dumps({"type": "message_update", "assistantMessageEvent": {
        "type": "text_delta", "delta": text,
    }}) + "\n").encode()


def test_pages_preserve_indices_and_read_only_a_bounded_prefix(tmp_path: Path) -> None:
    output = tmp_path / "pi_events.jsonl"
    output.write_bytes(_event("first") * 150)
    with output.open("ab") as source:
        source.truncate(200 * 1024 * 1024)
    first = read_pi_event_page(output, None, running=False)
    second = read_pi_event_page(output, first["next_cursor"], running=False)

    assert len(first["events"]) == 100
    assert first["has_more"] is True
    assert first["source_bytes_read"] <= PAGE_MAX_SOURCE_BYTES
    assert first["events"][0]["event_index"] == 1
    assert len(second["events"]) == 50
    assert second["events"][0]["event_index"] == 101
    assert second["source_bytes_read"] <= PAGE_MAX_SOURCE_BYTES


def test_large_record_is_skipped_by_bounded_reads_and_raw_file_remains_intact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "pi_events.jsonl"
    huge = _event("x" * (PAGE_MAX_SOURCE_BYTES * 2))
    output.write_bytes(huge + _event("after"))
    cursor = None
    seen: list[dict[str, object]] = []
    for _ in range(4):
        page = read_pi_event_page(output, cursor, running=False)
        seen.extend(page["events"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break

    assert [item["event_index"] for item in seen] == [1, 2]
    assert seen[0]["pi_event_type"] == "oversized_record"
    assert seen[1]["delta"] == "after"
    assert output.read_bytes() == huge + _event("after")


def test_partial_live_record_waits_for_completion(tmp_path: Path) -> None:
    output = tmp_path / "pi_events.jsonl"
    output.write_bytes(_event("ready") + b'{"type":"message_update"')
    first = read_pi_event_page(output, None, running=True)
    assert [event["event_index"] for event in first["events"]] == [1]
    assert first["has_more"] is False
    with output.open("ab") as source:
        source.write(b',"assistantMessageEvent":{"type":"text_delta","delta":"later"}}\n')
    second = read_pi_event_page(output, first["next_cursor"], running=True)
    assert [event["delta"] for event in second["events"]] == ["later"]


def test_malformed_and_stale_cursor_are_rejected(tmp_path: Path) -> None:
    output = tmp_path / "pi_events.jsonl"
    output.write_bytes(b"broken\n")
    page = read_pi_event_page(output, None, running=False)
    assert page["events"][0]["kind"] == "error"
    with pytest.raises(ValueError, match="cursor"):
        read_pi_event_page(output, "garbage", running=False)
    output.unlink()
    output.write_bytes(_event("replacement"))
    with pytest.raises(ValueError, match="cursor"):
        read_pi_event_page(output, page["next_cursor"], running=False)


def test_large_fields_are_previewed_without_changing_raw_history(tmp_path: Path) -> None:
    output = tmp_path / "pi_events.jsonl"
    raw = json.dumps({
        "type": "tool_execution_end",
        "toolCallId": "call-1",
        "result": {"content": [{"type": "text", "text": "x" * 100_000}]},
    }).encode() + b"\n"
    output.write_bytes(raw)
    page = read_pi_event_page(output, None, running=False)
    assert page["response_bytes"] < 32_000
    assert "preview truncated" in str(page["events"][0]["result"])
    assert output.read_bytes() == raw


async def test_each_pi_page_checks_run_access(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = User(id=uuid.uuid4(), email="owner@example.com", display_name="Owner")
    project = Project(
        id=uuid.uuid4(), name="Pi project", git_url="https://example.invalid/project.git",
        provider="github", provider_project_id="1", provider_project_path="example/project",
        encrypted_access_token=b"ciphertext", local_path=str(tmp_path / "project"),
        default_branch="main", added_by=identity.id,
    )
    root = tmp_path / "run-data"
    run = WorkflowRun(
        id=uuid.uuid4(), root_workflow_id="root", project_id=project.id,
        triggered_by=identity.id, status="COMPLETED", base_ref="main",
        base_commit_sha="a" * 40, workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={}, public_context={}, run_data_path=str(root),
        reviewer_provider="github", reviewer_provider_user_id="7",
        reviewer_provider_username="owner",
    )
    invocation = WorkflowInvocation(
        id=uuid.uuid4(), run_id=run.id, workflow_id="root", invocation_path="root"
    )
    node = NodeExecution(
        id=uuid.uuid4(), run_id=run.id, invocation_id=invocation.id,
        node_id="prompt", node_path="root/prompt", node_type="prompt",
        status="SUCCESS", current_attempt=1,
    )
    attempt = NodeAttempt(
        id=uuid.uuid4(), node_execution_id=node.id, attempt_number=1, status="SUCCESS"
    )
    db_session.add_all([identity, project, run, invocation, node, attempt])
    await db_session.commit()
    output = node_attempt_directory(root, node.node_path, 1)
    output.mkdir(parents=True)
    (output / "pi_events.jsonl").write_bytes(b'{"type":"agent_start"}\n' * 101)
    actor = AuthenticatedUser(
        id=identity.id, email=identity.email, display_name=identity.display_name,
        avatar_url=None, provider="github", provider_user_id="7", provider_username="owner",
    )
    checks = 0

    async def authorize(*_: object) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise HTTPException(403, "Forbidden")

    monkeypatch.setattr(run_routes, "authorize_project", authorize)
    first = await run_routes.node_pi_events(
        run.id, node.id, actor, db_session, attempt=1, cursor=None
    )
    assert first["has_more"]
    with pytest.raises(HTTPException) as rejected:
        await run_routes.node_pi_events(
            run.id, node.id, actor, db_session, attempt=1, cursor=first["next_cursor"]
        )
    assert rejected.value.status_code == 403
    assert checks == 2
