import uuid

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import User
from backend.schemas.credential import CredentialCreate, CredentialResponse, CredentialUpdate
from backend.services.credential_service import CredentialService
from backend.services.crypto import SecretCipher


async def test_credentials_are_write_only_and_user_scoped(db_session: AsyncSession) -> None:
    user = User(
        id=uuid.uuid4(),
        email="developer@example.com",
        display_name="Developer",
        gitlab_user_id=321,
        gitlab_username="developer",
    )
    db_session.add(user)
    await db_session.flush()
    cipher = SecretCipher(Fernet.generate_key())
    service = CredentialService(db_session, cipher)

    credential = await service.create(
        user.id,
        CredentialCreate(key_name="ANTHROPIC_API_KEY", value="plain-secret"),
    )
    assert b"plain-secret" not in credential.encrypted_value
    assert "value" not in CredentialResponse.model_validate(credential).model_dump()
    assert await service.decrypted_environment(user.id) == {"ANTHROPIC_API_KEY": "plain-secret"}

    await service.update(
        user.id,
        credential.id,
        CredentialUpdate(value="replacement", description="Pi provider"),
    )
    assert await service.decrypted_environment(user.id) == {"ANTHROPIC_API_KEY": "replacement"}
