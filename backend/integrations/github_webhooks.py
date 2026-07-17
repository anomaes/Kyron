from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, WorkflowRun
from backend.services.cleanup_service import CleanupService
from backend.services.feedback_service import FeedbackError, FeedbackService


async def route_github_event(
    session: AsyncSession,
    event_name: str,
    payload: dict[str, Any],
    feedback: FeedbackService,
    cleanup: CleanupService,
) -> dict[str, Any]:
    repository = payload.get("repository") or {}
    repository_id = repository.get("id")
    if not isinstance(repository_id, int):
        return {"status": "ignored", "reason": "missing_repository"}
    project = await session.scalar(
        select(Project).where(
            Project.provider == "github",
            Project.provider_project_id == str(repository_id),
        )
    )
    if project is None:
        return {"status": "ignored", "reason": "unknown_project"}
    pull_request = payload.get("pull_request") or {}
    number = pull_request.get("number") or (payload.get("issue") or {}).get("number")
    if not isinstance(number, int):
        return {"status": "ignored", "reason": "missing_pull_request"}
    run = await session.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == project.id,
            WorkflowRun.change_request_number == number,
        )
    )
    if run is None:
        return {"status": "ignored", "reason": "unknown_run"}
    sender = payload.get("sender") or {}
    actor_id = sender.get("id")
    actor_username = str(sender.get("login") or "unknown")
    if not isinstance(actor_id, int):
        return {"status": "ignored", "reason": "missing_actor"}

    action = str(payload.get("action") or "")
    if event_name == "pull_request_review" and action == "submitted":
        review = payload.get("review") or {}
        if str(review.get("state") or "").lower() != "approved":
            return {"status": "ignored", "reason": "review_not_approved"}
        try:
            await feedback.accept(
                run.id,
                event_type="approval",
                source="github",
                author_provider="github",
                author_provider_user_id=str(actor_id),
                author_username=actor_username,
                provider_review_id=(str(review["id"]) if review.get("id") else None),
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "approval"}

    if event_name == "issue_comment" and action == "created":
        issue = payload.get("issue") or {}
        if not issue.get("pull_request"):
            return {"status": "ignored", "reason": "not_pull_request"}
        comment = payload.get("comment") or {}
        note = str(comment.get("body") or "").strip()
        if not note.lower().startswith("@kyron"):
            return {"status": "ignored", "reason": "unrelated_comment"}
        message = note[len("@kyron") :].strip()
        if not message:
            return {"status": "ignored", "reason": "empty_feedback"}
        try:
            await feedback.accept(
                run.id,
                event_type="comment",
                source="github",
                author_provider="github",
                author_provider_user_id=str(actor_id),
                author_username=actor_username,
                message=message,
                provider_comment_id=(str(comment["id"]) if comment.get("id") else None),
            )
        except (PermissionError, FeedbackError) as exc:
            return {"status": "ignored", "reason": str(exc)}
        return {"status": "processed", "action": "comment"}

    if event_name == "pull_request" and action == "closed":
        await cleanup.cleanup_run(run.id)
        return {
            "status": "processed",
            "action": "merge" if pull_request.get("merged") is True else "close",
        }
    return {"status": "ignored", "reason": "unhandled_event"}
