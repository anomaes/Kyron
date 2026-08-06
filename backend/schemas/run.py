from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BranchRunSubject(BaseModel):
    type: Literal["branch"]
    ref: str = Field(min_length=1, max_length=255)


class ChangeRequestRunSubject(BaseModel):
    type: Literal["change_request"]
    number: int = Field(gt=0)


RunSubject = Annotated[
    BranchRunSubject | ChangeRequestRunSubject,
    Field(discriminator="type"),
]


class RunTriggerRequest(BaseModel):
    subject: RunSubject | None = None
    base_ref: str | None = Field(default=None, min_length=1, max_length=255)
    inputs: dict[str, Any] = Field(default_factory=dict)
    use_local_definitions: bool = False

    @model_validator(mode="after")
    def one_subject_source(self) -> RunTriggerRequest:
        if self.subject is not None and self.base_ref is not None:
            raise ValueError("subject and base_ref cannot be supplied together")
        return self


class RunTriggerResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    base_commit_sha: str
    delivery_mode: str
    subject_commit_sha: str
    workflow_definition_commit_sha: str


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    root_workflow_id: str
    project_id: uuid.UUID
    triggered_by: uuid.UUID
    status: str
    status_version: int
    base_ref: str
    base_commit_sha: str
    subject_type: str
    subject_ref: str
    subject_change_request_number: int | None
    subject_change_request_url: str | None
    subject_target_ref: str | None
    subject_commit_sha: str
    subject_target_commit_sha: str | None
    subject_current_head_sha: str | None
    delivery_mode: str
    effective_credential_policy: dict[str, Any]
    pi_models_config_revision_id: uuid.UUID | None
    pi_models_config_source: str
    verification_conclusion: str | None
    verification_freshness: str | None
    local_definition_test: bool
    branch_name: str | None
    current_head_sha: str | None
    final_commit_sha: str | None
    change_request_number: int | None
    change_request_url: str | None
    reviewer_provider: str
    reviewer_provider_user_id: str
    reviewer_provider_username: str
    current_invocation_id: uuid.UUID | None
    current_node_execution_id: uuid.UUID | None
    current_wave_id: uuid.UUID | None
    error_type: str | None
    error_message: str | None
    created_at: datetime
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)


class PaginatedRuns(BaseModel):
    items: list[RunResponse]
    page: int
    page_size: int
    total: int
