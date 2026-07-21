import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api import run_routes
from backend.auth.dependencies import AuthenticatedUser, require_project_provider, upsert_user
from backend.config import Settings
from backend.db.models import WorkflowRun


async def test_auth_identity_upserts_by_provider_identity(db_session: AsyncSession) -> None:
    settings = Settings(AUTH_USER_TOUCH_INTERVAL_SECONDS=0, _env_file=None)
    first = await upsert_user(
        db_session,
        settings,
        email="old@example.com",
        display_name="Old Name",
        avatar_url=None,
        provider="gitlab",
        provider_user_id="555",
        provider_username="actor",
    )
    second = await upsert_user(
        db_session,
        settings,
        email="new@example.com",
        display_name="New Name",
        avatar_url="https://example.com/avatar.png",
        provider="gitlab",
        provider_user_id="555",
        provider_username="actor",
    )
    assert second.id == first.id
    assert second.email == "new@example.com"
    assert second.display_name == "New Name"


async def test_same_email_on_different_providers_creates_distinct_users(
    db_session: AsyncSession,
) -> None:
    settings = Settings(_env_file=None)
    gitlab = await upsert_user(
        db_session,
        settings,
        email="same@example.com",
        display_name="Same",
        avatar_url=None,
        provider="gitlab",
        provider_user_id="7",
        provider_username="same",
    )
    github = await upsert_user(
        db_session,
        settings,
        email="same@example.com",
        display_name="Same",
        avatar_url=None,
        provider="github",
        provider_user_id="7",
        provider_username="same",
    )
    assert github.id != gitlab.id


def test_cross_provider_project_control_is_forbidden() -> None:
    user = AuthenticatedUser(
        id=uuid.uuid4(),
        email="user@example.com",
        display_name="User",
        avatar_url=None,
        provider="github",
        provider_user_id="9",
        provider_username="user",
    )
    with pytest.raises(HTTPException) as captured:
        require_project_provider(user, "gitlab")
    assert captured.value.status_code == 403


async def test_default_gate_triggerer_can_respond_without_a_gate_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = AuthenticatedUser(
        id=uuid.uuid4(),
        email="triggerer@example.com",
        display_name="Triggerer",
        avatar_url=None,
        provider="github",
        provider_user_id="triggerer",
        provider_username="triggerer",
    )
    run = cast(
        WorkflowRun,
        SimpleNamespace(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            triggered_by=user.id,
            current_node_execution_id=uuid.uuid4(),
        ),
    )

    async def no_permissions(*_args: object) -> set[str]:
        return set()

    class DefaultGateSession:
        async def scalar(self, _statement: object) -> uuid.UUID:
            return uuid.uuid4()

    monkeypatch.setattr(run_routes, "project_permissions", no_permissions)
    await run_routes._authorize_gate_response(
        cast(Any, DefaultGateSession()), user, run
    )
