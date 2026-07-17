from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import upsert_user
from backend.config import Settings


async def test_auth_identity_upserts_by_gitlab_id(db_session: AsyncSession) -> None:
    settings = Settings(AUTH_USER_TOUCH_INTERVAL_SECONDS=0, _env_file=None)
    first = await upsert_user(
        db_session,
        settings,
        email="old@example.com",
        display_name="Old Name",
        avatar_url=None,
        gitlab_user_id=555,
        gitlab_username="actor",
    )
    user_id = first.id
    second = await upsert_user(
        db_session,
        settings,
        email="new@example.com",
        display_name="New Name",
        avatar_url="https://example.com/avatar.png",
        gitlab_user_id=555,
        gitlab_username="actor",
    )
    assert second.id == user_id
    assert second.email == "new@example.com"
    assert second.display_name == "New Name"
