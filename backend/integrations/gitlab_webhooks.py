from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, WorkflowRun
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
    project = await session.scalar(select(Project).where(Project.gitlab_project_id == project_id))
    if project is None:
        return {"status": "ignored", "reason": "unknown_project"}
    merge_request = payload.get("merge_request") or payload.get("object_attributes") or {}
    mr_iid = merge_request.get("iid")
    if not isinstance(mr_iid, int):
        return {"status": "ignored", "reason": "missing_merge_request"}
    run = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == project.id, WorkflowRun.mr_iid == mr_iid
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
    if object_kind == "merge_request" and action in {"approval", "approved"}:
        if action == "approved" and run.status != RunStatus.AWAITING_FEEDBACK:
            return {"status": "ignored", "reason": "duplicate_approved_event"}
        try:
            await feedback.accept(
                run.id,
                event_type="approval",
                source="gitlab",
                author_gitlab_user_id=actor_id,
                author_username=actor_username,
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "approval"}

    if object_kind == "note" and payload.get("merge_request"):
        if attributes.get("system") is True:
            return {"status": "ignored", "reason": "system_note"}
        note = str(attributes.get("note") or "").strip()
        if not note.lower().startswith("@yoke"):
            return {"status": "ignored", "reason": "unrelated_note"}
        message = note[len("@yoke") :].strip()
        if not message:
            return {"status": "ignored", "reason": "empty_feedback"}
        try:
            await feedback.accept(
                run.id,
                event_type="comment",
                source="gitlab",
                author_gitlab_user_id=actor_id,
                author_username=actor_username,
                message=message,
                gitlab_note_id=(
                    int(attributes["id"]) if attributes.get("id") is not None else None
                ),
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "comment"}

    if object_kind == "merge_request" and action in {"merge", "close"}:
        await cleanup.cleanup_run(run.id)
        return {"status": "processed", "action": action}
    return {"status": "ignored", "reason": "unhandled_event"}
