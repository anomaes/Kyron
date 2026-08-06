from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PiModelsConfigRequest(BaseModel):
    document: dict[str, Any]


class PiProviderCatalogResponse(BaseModel):
    id: str
    models: list[str] = Field(default_factory=list)
    required_credentials: list[str] = Field(default_factory=list)


class PiModelsConfigValidationResponse(BaseModel):
    valid: bool = True
    providers: list[PiProviderCatalogResponse]
    required_credentials: list[str]


class PiModelsConfigRevisionResponse(BaseModel):
    id: uuid.UUID
    version: int
    providers: list[PiProviderCatalogResponse]
    required_credentials: list[str]
    created_by: uuid.UUID
    created_at: datetime
    active: bool


class PiModelsConfigAdminResponse(BaseModel):
    source: Literal["database", "file", "builtin"]
    active_revision_id: uuid.UUID | None
    active_version: int | None
    document: dict[str, Any] | None
    providers: list[PiProviderCatalogResponse]
    required_credentials: list[str]
    file_bootstrap_configured: bool
    configuration_error: str | None = None
    revisions: list[PiModelsConfigRevisionResponse]


class PiModelsCatalogResponse(BaseModel):
    source: Literal["database", "file", "builtin"]
    revision_id: uuid.UUID | None
    version: int | None
    providers: list[PiProviderCatalogResponse]
    required_credentials: list[str]
