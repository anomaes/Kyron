import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser, require_project_provider, upsert_user
from backend.config import Settings


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
