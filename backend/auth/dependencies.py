from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db.database import get_session
from backend.db.models import ProviderIdentity, User
from backend.integrations.code_host import SUPPORTED_PROVIDERS, provider_display_name

DbSession = Annotated[AsyncSession, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None
    provider: str
    provider_user_id: str
    provider_username: str


async def upsert_user(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    avatar_url: str | None,
    provider: str,
    provider_user_id: str,
    provider_username: str,
) -> AuthenticatedUser:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported authentication provider")
    identity = await session.scalar(
        select(ProviderIdentity).where(
            ProviderIdentity.provider == provider,
            ProviderIdentity.provider_user_id == provider_user_id,
        )
    )
    now = datetime.now(UTC)
    if identity is None:
        user = User(
            email=email,
            display_name=display_name,
            avatar_url=avatar_url,
            last_login_at=now,
        )
        session.add(user)
        await session.flush()
        identity = ProviderIdentity(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            username=provider_username,
        )
        session.add(identity)
    else:
        existing_user = await session.get(User, identity.user_id)
        if existing_user is None:
            raise RuntimeError("Provider identity has no user")
        user = existing_user
        user.email = email
        user.display_name = display_name
        user.avatar_url = avatar_url
        identity.username = provider_username
        last_login = user.last_login_at
        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=UTC)
        if now - last_login >= timedelta(seconds=settings.AUTH_USER_TOUCH_INTERVAL_SECONDS):
            user.last_login_at = now
    await session.commit()
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        provider=identity.provider,
        provider_user_id=identity.provider_user_id,
        provider_username=identity.username,
    )


async def resolve_current_user(
    request: Request,
    session: DbSession,
    x_token_user_email: Annotated[str | None, Header()] = None,
    x_token_user_name: Annotated[str | None, Header()] = None,
    x_token_user_avatar: Annotated[str | None, Header()] = None,
    x_token_provider: Annotated[str | None, Header()] = None,
    x_token_provider_user_id: Annotated[str | None, Header()] = None,
    x_token_provider_username: Annotated[str | None, Header()] = None,
) -> AuthenticatedUser:
    del request
    if (
        not x_token_user_email
        or not x_token_provider
        or not x_token_provider_user_id
        or not x_token_provider_username
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing trusted authentication headers")
    try:
        return await upsert_user(
            session,
            get_settings(),
            email=x_token_user_email,
            display_name=x_token_user_name or x_token_provider_username,
            avatar_url=x_token_user_avatar,
            provider=x_token_provider,
            provider_user_id=x_token_provider_user_id,
            provider_username=x_token_provider_username,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


CurrentUser = Annotated[AuthenticatedUser, Depends(resolve_current_user)]


def websocket_identity(websocket: WebSocket) -> tuple[str, str, str, str]:
    email = websocket.headers.get("X-Token-User-Email")
    provider = websocket.headers.get("X-Token-Provider")
    provider_user_id = websocket.headers.get("X-Token-Provider-User-Id")
    username = websocket.headers.get("X-Token-Provider-Username")
    if not email or not provider or not provider_user_id or not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing trusted authentication headers")
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unsupported authentication provider")
    return email, provider, provider_user_id, username


def require_project_provider(user: AuthenticatedUser, project_provider: str) -> None:
    if user.provider != project_provider:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Sign in with {provider_display_name(project_provider)} to control this project",
        )
