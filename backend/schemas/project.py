import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    git_url: HttpUrl
    gitlab_project_id: int = Field(gt=0)
    access_token: str = Field(min_length=1)
    default_branch: str = Field(default="main", min_length=1, max_length=255)

    @field_validator("git_url")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("Only HTTPS Git URLs are supported")
        return value


class ProjectTokenUpdate(BaseModel):
    access_token: str = Field(min_length=1)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    git_url: str
    gitlab_project_id: int
    local_path: str
    default_branch: str
    added_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    token_configured: bool = True


class ProjectValidationResponse(BaseModel):
    valid: bool
    default_branch: str
    gitlab_path: str
