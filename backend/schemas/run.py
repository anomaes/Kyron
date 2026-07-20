import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunTriggerRequest(BaseModel):
    base_ref: str = Field(default="main", min_length=1, max_length=255)
    inputs: dict[str, Any] = Field(default_factory=dict)
    use_local_definitions: bool = False


class RunTriggerResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    base_commit_sha: str


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
