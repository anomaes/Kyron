import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.services.crypto import CREDENTIAL_KEY_PATTERN


class CredentialCreate(BaseModel):
    key_name: str = Field(min_length=1, max_length=255, pattern=CREDENTIAL_KEY_PATTERN.pattern)
    value: str = Field(min_length=1)
    description: str | None = None


class CredentialUpdate(BaseModel):
    value: str = Field(min_length=1)
    description: str | None = None


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    configured: bool = True
