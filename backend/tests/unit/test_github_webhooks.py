import uuid
from pathlib import Path
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Project, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.integrations.github_webhooks import route_github_event
from backend.services.cleanup_service import CleanupService
from backend.services.feedback_service import FeedbackService


class RecordingFeedback:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def accept(self, _run_id: uuid.UUID, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return object()


class RecordingCleanup:
    async def cleanup_run(self, _run_id: uuid.UUID) -> None:
        return None


async def github_run(session: AsyncSession, tmp_path: Path) -> WorkflowRun:
    user = User(
        id=uuid.uuid4(),
        email="reviewer@example.com",
        display_name="Reviewer",
    )
    project = Project(
        id=uuid.uuid4(),
        name="Widget",
        git_url="https://github.test/acme/widget.git",
        provider="github",
        provider_project_id="123",
        provider_project_path="acme/widget",
        encrypted_access_token=b"ciphertext",
        local_path=str(tmp_path / "repo"),
        default_branch="main",
        added_by=user.id,
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        root_workflow_id="build",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.AWAITING_FEEDBACK,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        change_request_number=17,
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="alice",
    )
    session.add_all([user, project, run])
    await session.commit()
    return run


async def test_github_approval_is_normalized_with_review_id(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    await github_run(db_session, tmp_path)
    feedback = RecordingFeedback()
    result = await route_github_event(
        db_session,
        "pull_request_review",
        {
            "action": "submitted",
            "repository": {"id": 123},
            "pull_request": {"number": 17},
            "review": {"id": 99, "state": "approved"},
            "sender": {"id": 7, "login": "alice"},
        },
        cast(FeedbackService, feedback),
        cast(CleanupService, RecordingCleanup()),
    )
    assert result == {"status": "processed", "action": "approval"}
    assert feedback.calls == [
        {
            "event_type": "approval",
            "source": "github",
            "author_provider": "github",
            "author_provider_user_id": "7",
            "author_username": "alice",
            "provider_review_id": "99",
        }
    ]
