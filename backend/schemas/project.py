import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from backend.schemas.pi import PiSettings


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    git_url: HttpUrl
    provider: Literal["gitlab", "github"]
    provider_project: str = Field(min_length=1, max_length=1024)
    access_token: str = Field(min_length=1)
    default_branch: str = Field(default="main", min_length=1, max_length=255)
    pi: PiSettings = Field(default_factory=PiSettings)

    @field_validator("git_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Only HTTPS Git URLs are supported")
        if value.username or value.password:
            raise ValueError("Authenticated Git URLs are not allowed")
        return value


class ProjectTokenUpdate(BaseModel):
    access_token: str = Field(min_length=1)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    provider: str
    provider_project_id: str
    provider_project_path: str
    local_path: str
    default_branch: str
    pi: PiSettings
    added_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    token_configured: bool = True


class ProjectValidationResponse(BaseModel):
    valid: bool
    default_branch: str
    provider_project_path: str
