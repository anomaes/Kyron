from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from backend.db.database import Base

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    gitlab_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    gitlab_username: Mapped[str] = mapped_column(String(255), nullable=False)
    oauth_provider: Mapped[str] = mapped_column(String(50), default="gitlab", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "key_name"),
        CheckConstraint(
            "key_name ~ '^[A-Za-z_][A-Za-z0-9_]*$'",
            name="credential_key_name_format",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key_name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    git_url: Mapped[str] = mapped_column(Text, nullable=False)
    gitlab_project_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    encrypted_access_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status_queued", "status", "queued_at"),
        Index("ix_workflow_runs_project_created", "project_id", "created_at"),
        Index("ix_workflow_runs_mr_project", "mr_iid", "project_id"),
        Index("ix_workflow_runs_triggered_created", "triggered_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    root_workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    triggered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    status_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    base_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    base_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    workflow_definition_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    workflow_bundle_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    public_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    branch_name: Mapped[str | None] = mapped_column(String(255))
    worktree_path: Mapped[str | None] = mapped_column(Text)
    run_data_path: Mapped[str | None] = mapped_column(Text)
    current_head_sha: Mapped[str | None] = mapped_column(String(40))
    final_commit_sha: Mapped[str | None] = mapped_column(String(40))
    mr_iid: Mapped[int | None] = mapped_column(Integer)
    mr_url: Mapped[str | None] = mapped_column(Text)
    reviewer_gitlab_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    current_node_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    current_wave_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowInvocation(Base):
    __tablename__ = "workflow_invocations"
    __table_args__ = (UniqueConstraint("run_id", "invocation_path"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    invocation_path: Mapped[str] = mapped_column(Text, nullable=False)
    parent_invocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE")
    )
    parent_node_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    loop_iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    output_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionWave(Base):
    __tablename__ = "execution_waves"
    __table_args__ = (UniqueConstraint("invocation_id", "wave_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), index=True
    )
    wave_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    start_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    end_commit_sha: Mapped[str | None] = mapped_column(String(40))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class NodeExecution(Base):
    __tablename__ = "node_executions"
    __table_args__ = (UniqueConstraint("invocation_id", "node_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), index=True
    )
    wave_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("execution_waves.id"))
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_path: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    current_attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_path: Mapped[str | None] = mapped_column(Text)
    stderr_path: Mapped[str | None] = mapped_column(Text)
    output_values: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class NodeAttempt(Base):
    __tablename__ = "node_attempts"
    __table_args__ = (UniqueConstraint("node_execution_id", "attempt_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    node_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="RUNNING", nullable=False)
    process_pid: Mapped[int | None] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class EdgeEvaluation(Base):
    __tablename__ = "edge_evaluations"
    __table_args__ = (UniqueConstraint("source_node_execution_id", "edge_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), index=True
    )
    source_node_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE")
    )
    edge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    condition_result: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    node_execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("node_executions.id"))
    iteration: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    author_gitlab_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    author_username: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    gitlab_note_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunLog(Base):
    __tablename__ = "run_logs"
    __table_args__ = (Index("ix_run_logs_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"))
    invocation_path: Mapped[str | None] = mapped_column(Text)
    node_path: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    log_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_TYPE, default=dict, nullable=False
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    delivery_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    gitlab_project_id: Mapped[int | None] = mapped_column(BigInteger)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
