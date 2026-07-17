from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, WebSocket, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db.database import get_session
from backend.db.models import User

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def upsert_user(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    avatar_url: str | None,
    gitlab_user_id: int,
    gitlab_username: str,
) -> User:
    user = await session.scalar(
        select(User).where(or_(User.email == email, User.gitlab_user_id == gitlab_user_id))
    )
    now = datetime.now(UTC)
    if user is None:
        user = User(
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            gitlab_user_id=gitlab_user_id,
            gitlab_username=gitlab_username,
            last_login_at=now,
        )
        session.add(user)
    else:
        user.email = email
        user.display_name = display_name
        user.avatar_url = avatar_url
        user.gitlab_user_id = gitlab_user_id
        user.gitlab_username = gitlab_username
        last_login = user.last_login_at
        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=UTC)
        if now - last_login >= timedelta(seconds=settings.AUTH_USER_TOUCH_INTERVAL_SECONDS):
            user.last_login_at = now
    await session.commit()
    return user


async def resolve_current_user(
    request: Request,
    session: DbSession,
    x_token_user_email: Annotated[str | None, Header()] = None,
    x_token_user_name: Annotated[str | None, Header()] = None,
    x_token_user_avatar: Annotated[str | None, Header()] = None,
    x_token_gitlab_user_id: Annotated[str | None, Header()] = None,
    x_token_gitlab_username: Annotated[str | None, Header()] = None,
) -> User:
    del request
    if not x_token_user_email or not x_token_gitlab_user_id or not x_token_gitlab_username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing trusted authentication headers")
    try:
        gitlab_user_id = int(x_token_gitlab_user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid GitLab user ID") from exc
    return await upsert_user(
        session,
        get_settings(),
        email=x_token_user_email,
        display_name=x_token_user_name or x_token_gitlab_username,
        avatar_url=x_token_user_avatar,
        gitlab_user_id=gitlab_user_id,
        gitlab_username=x_token_gitlab_username,
    )


CurrentUser = Annotated[User, Depends(resolve_current_user)]


def websocket_identity(websocket: WebSocket) -> tuple[str, int, str]:
    email = websocket.headers.get("X-Token-User-Email")
    gitlab_id_raw = websocket.headers.get("X-Token-GitLab-User-Id")
    username = websocket.headers.get("X-Token-GitLab-Username")
    if not email or not gitlab_id_raw or not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing trusted authentication headers")
    try:
        return email, int(gitlab_id_raw), username
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid GitLab user ID") from exc
