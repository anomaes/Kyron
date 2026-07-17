from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Credential
from backend.schemas.credential import CredentialCreate, CredentialUpdate
from backend.services.crypto import SecretCipher


class CredentialService:
    def __init__(self, session: AsyncSession, cipher: SecretCipher) -> None:
        self.session = session
        self.cipher = cipher

    async def list_for_user(self, user_id: uuid.UUID) -> list[Credential]:
        result = await self.session.scalars(
            select(Credential).where(Credential.user_id == user_id).order_by(Credential.key_name)
        )
        return list(result)

    async def create(self, user_id: uuid.UUID, request: CredentialCreate) -> Credential:
        credential = Credential(
            user_id=user_id,
            key_name=request.key_name,
            encrypted_value=self.cipher.encrypt(request.value),
            key_version=self.cipher.key_version,
            description=request.description,
        )
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def update(
        self, user_id: uuid.UUID, credential_id: uuid.UUID, request: CredentialUpdate
    ) -> Credential:
        credential = await self._owned(user_id, credential_id)
        credential.encrypted_value = self.cipher.encrypt(request.value)
        credential.key_version = self.cipher.key_version
        credential.description = request.description
        await self.session.flush()
        return credential

    async def delete(self, user_id: uuid.UUID, credential_id: uuid.UUID) -> None:
        credential = await self._owned(user_id, credential_id)
        await self.session.delete(credential)
        await self.session.flush()

    async def decrypted_environment(self, user_id: uuid.UUID) -> dict[str, str]:
        credentials = await self.list_for_user(user_id)
        return {
            credential.key_name: self.cipher.decrypt(credential.encrypted_value)
            for credential in credentials
        }

    async def _owned(self, user_id: uuid.UUID, credential_id: uuid.UUID) -> Credential:
        credential = await self.session.scalar(
            select(Credential).where(Credential.id == credential_id, Credential.user_id == user_id)
        )
        if credential is None:
            raise LookupError("Credential does not exist")
        return credential
