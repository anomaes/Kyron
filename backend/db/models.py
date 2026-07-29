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
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderIdentity(Base):
    __tablename__ = "provider_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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
    __table_args__ = (UniqueConstraint("provider", "provider_project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    git_url: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_project_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    encrypted_access_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    local_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    pi: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectRole(Base):
    __tablename__ = "project_roles"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProjectRolePermission(Base):
    __tablename__ = "project_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    permission: Mapped[str] = mapped_column(String(100), nullable=False)


class ProjectMembershipRole(Base):
    __tablename__ = "project_membership_roles"
    __table_args__ = (UniqueConstraint("membership_id", "role_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_memberships.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="CASCADE"), index=True, nullable=False
    )


class ApprovalPolicy(Base):
    __tablename__ = "approval_policies"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    initiator_may_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    distinct_approvers_across_requirements: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    eligible_approvers_may_give_feedback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ApprovalPolicyRequirement(Base):
    __tablename__ = "approval_policy_requirements"
    __table_args__ = (UniqueConstraint("policy_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_policies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quorum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    include_triggering_user: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )


class ApprovalRequirementRole(Base):
    __tablename__ = "approval_requirement_roles"
    __table_args__ = (UniqueConstraint("requirement_id", "role_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_policy_requirements.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_roles.id", ondelete="CASCADE"), index=True, nullable=False
    )


class ApprovalRequirementUser(Base):
    __tablename__ = "approval_requirement_users"
    __table_args__ = (UniqueConstraint("requirement_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_policy_requirements.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )


class GovernanceProfile(Base):
    __tablename__ = "governance_profiles"
    __table_args__ = (UniqueConstraint("project_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    applies_to_tags: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    required_policy_keys: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    prohibit_self_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_total_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_status_queued", "status", "queued_at"),
        Index("ix_workflow_runs_project_created", "project_id", "created_at"),
        Index("ix_workflow_runs_change_request_project", "change_request_number", "project_id"),
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
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, default="BRANCH")
    subject_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subject_change_request_number: Mapped[int | None] = mapped_column(Integer)
    subject_change_request_url: Mapped[str | None] = mapped_column(Text)
    subject_target_ref: Mapped[str | None] = mapped_column(String(255))
    subject_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    subject_target_commit_sha: Mapped[str | None] = mapped_column(String(40))
    subject_current_head_sha: Mapped[str | None] = mapped_column(String(40))
    subject_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subject_availability: Mapped[str] = mapped_column(
        String(30), nullable=False, default="ACTIVE"
    )
    delivery_mode: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PROPOSE_CHANGES"
    )
    effective_credential_policy: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    verification_conclusion: Mapped[str | None] = mapped_column(String(30))
    verification_freshness: Mapped[str | None] = mapped_column(String(30))
    verification_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    workflow_definition_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    workflow_bundle_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    local_definition_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    trigger_actor_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    branch_name: Mapped[str | None] = mapped_column(String(255))
    worktree_path: Mapped[str | None] = mapped_column(Text)
    run_data_path: Mapped[str | None] = mapped_column(Text)
    current_head_sha: Mapped[str | None] = mapped_column(String(40))
    final_commit_sha: Mapped[str | None] = mapped_column(String(40))
    change_request_number: Mapped[int | None] = mapped_column(Integer)
    change_request_url: Mapped[str | None] = mapped_column(Text)
    change_request_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewer_provider_username: Mapped[str] = mapped_column(String(255), nullable=False)
    current_invocation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    current_node_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    current_wave_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    pending_operation: Mapped[str | None] = mapped_column(String(50))
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
    public_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    output_context: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="SET NULL"), index=True
    )
    scheduler_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvocationWorkspace(Base):
    __tablename__ = "invocation_workspaces"
    __table_args__ = (
        UniqueConstraint("owner_invocation_id"),
        Index("ix_invocation_workspaces_run_status", "run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), nullable=False
    )
    parent_workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CREATING")
    base_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    current_head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    integrated_head_sha: Mapped[str | None] = mapped_column(String(40))
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    worktree_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class SubworkflowBatch(Base):
    __tablename__ = "subworkflow_batches"
    __table_args__ = (
        Index("ix_subworkflow_batches_run_status", "run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), nullable=False
    )
    parent_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    base_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CREATING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_type: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class SubworkflowBatchMember(Base):
    __tablename__ = "subworkflow_batch_members"
    __table_args__ = (
        UniqueConstraint("parent_node_execution_id"),
        UniqueConstraint("child_invocation_id"),
        UniqueConstraint("child_workspace_id"),
        UniqueConstraint("batch_id", "integration_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subworkflow_batches.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_node_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE"), nullable=False
    )
    child_invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), nullable=False
    )
    child_workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    integration_order: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="PENDING")
    integrated_commit_sha: Mapped[str | None] = mapped_column(String(40))


class RunChangeRequest(Base):
    __tablename__ = "run_change_requests"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", "provider_number"),
        Index("ix_run_change_requests_run_status", "run_id", "status"),
        Index("ix_run_change_requests_source_target", "source_branch", "target_branch"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_number: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    target_sha: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ExecutionWave(Base):
    __tablename__ = "execution_waves"
    __table_args__ = (UniqueConstraint("invocation_id", "wave_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="SET NULL"), index=True
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
    pi_usage: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)


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
    author_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    author_provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author_username: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    provider_comment_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GateInstance(Base):
    __tablename__ = "gate_instances"
    __table_args__ = (UniqueConstraint("node_execution_id", "iteration"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    invocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_invocations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    node_execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("node_executions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invocation_workspaces.id", ondelete="CASCADE"), index=True
    )
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run_change_requests.id", ondelete="SET NULL"), index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    checkpoint_commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    eligible_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GateDecision(Base):
    __tablename__ = "gate_decisions"
    __table_args__ = (Index("ix_gate_decisions_gate_created", "gate_instance_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gate_instance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gate_instances.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    requirement_keys: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthorizationAuditEvent(Base):
    __tablename__ = "authorization_audit_events"
    __table_args__ = (
        Index("ix_authorization_audit_project_created", "project_id", "created_at"),
        Index("ix_authorization_audit_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RunReport(Base):
    __tablename__ = "run_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChangeRequestLifecycleEvent(Base):
    __tablename__ = "change_request_lifecycle_events"
    __table_args__ = (Index("ix_change_request_lifecycle_run_created", "run_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("run_change_requests.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_username: Mapped[str] = mapped_column(String(255), nullable=False)
    merge_commit_sha: Mapped[str | None] = mapped_column(String(64))
    provider_delivery_id: Mapped[str | None] = mapped_column(String(255))
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
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_project_id: Mapped[str | None] = mapped_column(String(255))
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED", nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)


class ResourceAuditLog(Base):
    __tablename__ = "resource_audit_logs"
    __table_args__ = (
        Index("ix_resource_audit_logs_event_timestamp", "event_type", "timestamp"),
        Index("ix_resource_audit_logs_resource_path", "resource_path"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_path: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    details: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
