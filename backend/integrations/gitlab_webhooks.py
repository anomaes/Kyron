from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ChangeRequestLifecycleEvent,
    GateInstance,
    Project,
    RunChangeRequest,
    WorkflowRun,
)
from backend.db.statuses import RunStatus
from backend.services.cleanup_service import CleanupService
from backend.services.feedback_service import FeedbackError, FeedbackService


async def route_gitlab_event(
    session: AsyncSession,
    payload: dict[str, Any],
    feedback: FeedbackService,
    cleanup: CleanupService,
) -> dict[str, Any]:
    project_data = payload.get("project") or {}
    project_id = project_data.get("id")
    if not isinstance(project_id, int):
        return {"status": "ignored", "reason": "missing_project"}
    project = await session.scalar(
        select(Project).where(
            Project.provider == "gitlab",
            Project.provider_project_id == str(project_id),
        )
    )
    if project is None:
        return {"status": "ignored", "reason": "unknown_project"}
    merge_request = payload.get("merge_request") or payload.get("object_attributes") or {}
    mr_iid = merge_request.get("iid")
    if not isinstance(mr_iid, int):
        return {"status": "ignored", "reason": "missing_merge_request"}
    managed_request = await session.scalar(
        select(RunChangeRequest).where(
            RunChangeRequest.project_id == project.id,
            RunChangeRequest.provider == "gitlab",
            RunChangeRequest.provider_number == mr_iid,
        )
    )
    run = (
        await session.get(WorkflowRun, managed_request.run_id)
        if managed_request is not None
        else await session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project.id,
                WorkflowRun.change_request_number == mr_iid,
            )
        )
    )
    if run is None:
        return {"status": "ignored", "reason": "unknown_run"}
    actor = payload.get("user") or {}
    actor_id = actor.get("id")
    actor_username = str(actor.get("username") or "unknown")
    if not isinstance(actor_id, int):
        return {"status": "ignored", "reason": "missing_actor"}

    object_kind = payload.get("object_kind")
    attributes = payload.get("object_attributes") or {}
    action = attributes.get("action")
    gate = (
        await session.scalar(
            select(GateInstance).where(
                GateInstance.change_request_id == managed_request.id,
                GateInstance.status == "OPEN",
            )
        )
        if managed_request is not None
        else None
    )
    if object_kind == "merge_request" and action in {"approval", "approved"}:
        if action == "approved" and gate is None and run.status != RunStatus.AWAITING_FEEDBACK:
            return {"status": "ignored", "reason": "duplicate_approved_event"}
        try:
            await feedback.accept(
                run.id,
                event_type="approval",
                source="gitlab",
                author_provider="gitlab",
                author_provider_user_id=str(actor_id),
                author_username=actor_username,
                provider_head_sha=(
                    str(attributes["last_commit"]["id"])
                    if isinstance(attributes.get("last_commit"), dict)
                    and attributes["last_commit"].get("id")
                    else None
                ),
                **({"gate_id": gate.id} if gate else {}),
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "approval"}

    if object_kind == "note" and payload.get("merge_request"):
        if attributes.get("system") is True:
            return {"status": "ignored", "reason": "system_note"}
        note = str(attributes.get("note") or "").strip()
        if not note.lower().startswith("@kyron"):
            return {"status": "ignored", "reason": "unrelated_note"}
        message = note[len("@kyron") :].strip()
        if not message:
            return {"status": "ignored", "reason": "empty_feedback"}
        try:
            await feedback.accept(
                run.id,
                event_type="comment",
                source="gitlab",
                author_provider="gitlab",
                author_provider_user_id=str(actor_id),
                author_username=actor_username,
                message=message,
                provider_comment_id=(
                    str(attributes["id"]) if attributes.get("id") is not None else None
                ),
                **({"gate_id": gate.id} if gate else {}),
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "comment"}

    if object_kind == "merge_request" and action in {"merge", "close"}:
        session.add(
            ChangeRequestLifecycleEvent(
                run_id=run.id,
                change_request_id=managed_request.id if managed_request else None,
                event_type=action,
                provider="gitlab",
                actor_provider_user_id=str(actor_id),
                actor_username=actor_username,
                merge_commit_sha=(
                    str(attributes["merge_commit_sha"])
                    if attributes.get("merge_commit_sha")
                    else None
                ),
            )
        )
        if managed_request is not None:
            managed_request.status = "MERGED" if action == "merge" else "CLOSED"
        await session.commit()
        if managed_request is None or managed_request.kind == "FINAL":
            await cleanup.cleanup_run(run.id)
        return {"status": "processed", "action": action}
    return {"status": "ignored", "reason": "unhandled_event"}
