import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.credential_routes import create_credential
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import User
from backend.schemas.credential import CredentialCreate
from backend.services.crypto import SecretCipher


async def test_duplicate_credential_name_returns_conflict(db_session: AsyncSession) -> None:
    user = User(
        id=uuid.uuid4(),
        email="developer@example.com",
        display_name="Developer",
    )
    db_session.add(user)
    await db_session.flush()
    authenticated = AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=None,
        provider="github",
        provider_user_id="123",
        provider_username="developer",
    )
    cipher = SecretCipher(Fernet.generate_key())
    request = CredentialCreate(
        key_name="SDC_LLM_GATEWAY_TOKEN",
        value="secret",
    )
    await create_credential(request, authenticated, db_session, cipher)

    with pytest.raises(HTTPException) as failure:
        await create_credential(request, authenticated, db_session, cipher)

    assert failure.value.status_code == 409
    assert failure.value.detail == (
        'A credential named "SDC_LLM_GATEWAY_TOKEN" already exists'
    )
