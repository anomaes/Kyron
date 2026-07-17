import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunTriggerRequest(BaseModel):
    base_ref: str = Field(default="main", min_length=1, max_length=255)
    inputs: dict[str, Any] = Field(default_factory=dict)


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
    branch_name: str | None
    current_head_sha: str | None
    final_commit_sha: str | None
    mr_iid: int | None
    mr_url: str | None
    reviewer_gitlab_user_id: int
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
