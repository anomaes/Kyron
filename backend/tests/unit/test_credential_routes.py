import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.credential_routes import create_credential, update_credential
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import User
from backend.schemas.credential import CredentialCreate, CredentialUpdate
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


async def test_renaming_credential_to_duplicate_name_returns_conflict(
    db_session: AsyncSession,
) -> None:
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
    existing = await create_credential(
        CredentialCreate(key_name="EXISTING_TOKEN", value="existing"),
        authenticated,
        db_session,
        cipher,
    )
    renamed = await create_credential(
        CredentialCreate(key_name="RENAMED_TOKEN", value="renamed"),
        authenticated,
        db_session,
        cipher,
    )

    with pytest.raises(HTTPException) as failure:
        await update_credential(
            renamed.id,
            CredentialUpdate(key_name=existing.key_name),
            authenticated,
            db_session,
            cipher,
        )

    assert failure.value.status_code == 409
    assert failure.value.detail == 'A credential named "EXISTING_TOKEN" already exists'
