import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from backend.schemas.pi import PiSettings


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    git_url: HttpUrl
    provider: Literal["gitlab", "github"]
    provider_project: str = Field(min_length=1, max_length=1024)
    access_token: str = Field(min_length=1)
    webhook_secret: str = Field(min_length=16)
    webhook_signing_secret: str | None = Field(default=None, min_length=16)
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

    @model_validator(mode="after")
    def signing_secret_is_gitlab_only(self) -> Self:
        if self.provider != "gitlab" and self.webhook_signing_secret:
            raise ValueError("Webhook signing secrets are supported only for GitLab projects")
        return self


class ProjectTokenUpdate(BaseModel):
    access_token: str = Field(min_length=1)


class ProjectWebhookSecretUpdate(BaseModel):
    webhook_secret: str = Field(min_length=16)
    webhook_signing_secret: str | None = Field(default=None, min_length=16)
    clear_webhook_signing_secret: bool = False

    @model_validator(mode="after")
    def signing_secret_operation_is_unambiguous(self) -> Self:
        if self.webhook_signing_secret and self.clear_webhook_signing_secret:
            raise ValueError("Cannot replace and clear the webhook signing secret together")
        return self


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
    webhook_secret_configured: bool
    webhook_signing_secret_configured: bool
    can_manage: bool = False


class ProjectValidationResponse(BaseModel):
    valid: bool
    default_branch: str
    provider_project_path: str
