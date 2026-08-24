from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser, upsert_user
from backend.config import Settings
from backend.db.models import VsCodeClientSession, VsCodeDeviceAuthorization
from backend.services.vscode_auth_service import (
    VsCodeAuthorizationError,
    VsCodeAuthService,
    token_hash,
)


async def authenticated_user(db_session: AsyncSession) -> AuthenticatedUser:
    return await upsert_user(
        db_session,
        Settings(_env_file=None),
        email="operator@example.com",
        display_name="Operator",
        avatar_url=None,
        provider="gitlab",
        provider_user_id="123",
        provider_username="operator",
    )


async def test_device_code_is_approved_exchanged_and_never_stored_plaintext(
    db_session: AsyncSession,
) -> None:
    settings = Settings(
        VSCODE_ACCESS_TOKEN_TTL_SECONDS=300,
        VSCODE_REFRESH_TOKEN_TTL_DAYS=7,
        _env_file=None,
    )
    service = VsCodeAuthService(db_session, settings)
    user = await authenticated_user(db_session)

    issued_device = await service.issue_device_code()
    stored_device = await db_session.scalar(select(VsCodeDeviceAuthorization))
    assert stored_device is not None
    assert stored_device.device_code_hash == token_hash(issued_device.device_code)
    assert issued_device.device_code not in stored_device.device_code_hash

    with pytest.raises(VsCodeAuthorizationError) as pending:
        await service.exchange_device_code(issued_device.device_code)
    assert pending.value.code == "authorization_pending"

    await service.approve_device(issued_device.user_code.lower().replace("-", ""), user)
    tokens = await service.exchange_device_code(issued_device.device_code)
    assert tokens.access_token.startswith("kyr_at_")
    assert tokens.refresh_token.startswith("kyr_rt_")

    stored_session = await db_session.scalar(select(VsCodeClientSession))
    assert stored_session is not None
    assert stored_session.access_token_hash == token_hash(tokens.access_token)
    assert stored_session.refresh_token_hash == token_hash(tokens.refresh_token)
    assert tokens.access_token not in stored_session.access_token_hash
    assert tokens.refresh_token not in stored_session.refresh_token_hash

    identity = await service.identity_for_access_token(tokens.access_token)
    assert identity.id == user.id
    assert identity.provider == "gitlab"
    assert identity.provider_user_id == "123"

    with pytest.raises(VsCodeAuthorizationError) as reused:
        await service.exchange_device_code(issued_device.device_code)
    assert reused.value.code == "invalid_grant"


async def test_refresh_rotates_both_credentials_and_revoke_invalidates_session(
    db_session: AsyncSession,
) -> None:
    service = VsCodeAuthService(db_session, Settings(_env_file=None))
    user = await authenticated_user(db_session)
    device = await service.issue_device_code()
    await service.approve_device(device.user_code, user)
    first = await service.exchange_device_code(device.device_code)

    second = await service.refresh(first.refresh_token)
    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token

    with pytest.raises(VsCodeAuthorizationError):
        await service.identity_for_access_token(first.access_token)
    with pytest.raises(VsCodeAuthorizationError):
        await service.refresh(first.refresh_token)

    await service.revoke(second.refresh_token)
    with pytest.raises(VsCodeAuthorizationError):
        await service.identity_for_access_token(second.access_token)


async def test_expired_device_code_cannot_be_approved(db_session: AsyncSession) -> None:
    service = VsCodeAuthService(db_session, Settings(_env_file=None))
    user = await authenticated_user(db_session)
    issued = await service.issue_device_code()
    stored = await db_session.scalar(select(VsCodeDeviceAuthorization))
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    with pytest.raises(VsCodeAuthorizationError) as captured:
        await service.approve_device(issued.user_code, user)
    assert captured.value.code == "expired_token"
