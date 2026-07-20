"""Add project authorization, governed gates, audit reports, and lifecycle events.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    inspector = sa.inspect(op.get_bind())
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "is_active" not in user_columns:
        op.add_column(
            "users",
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        )
    if "is_system_admin" not in user_columns:
        op.add_column(
            "users",
            sa.Column("is_system_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    if "trigger_actor_snapshot" not in run_columns:
        op.add_column(
            "workflow_runs",
            sa.Column(
                "trigger_actor_snapshot",
                json_type,
                server_default=sa.text("'{}'"),
                nullable=False,
            ),
        )
    if "project_memberships" in inspector.get_table_names():
        return

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id"),
    )
    op.create_index("ix_project_memberships_project_id", "project_memberships", ["project_id"])
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])
    op.create_table(
        "project_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key"),
    )
    op.create_index("ix_project_roles_project_id", "project_roles", ["project_id"])
    op.create_table(
        "project_role_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["project_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission"),
    )
    op.create_index("ix_project_role_permissions_role_id", "project_role_permissions", ["role_id"])
    op.create_table(
        "project_membership_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["project_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["project_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "role_id"),
    )
    op.create_index(
        "ix_project_membership_roles_membership_id", "project_membership_roles", ["membership_id"]
    )
    op.create_index("ix_project_membership_roles_role_id", "project_membership_roles", ["role_id"])

    op.create_table(
        "approval_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("initiator_may_approve", sa.Boolean(), nullable=False),
        sa.Column("distinct_approvers_across_requirements", sa.Boolean(), nullable=False),
        sa.Column("eligible_approvers_may_give_feedback", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key"),
    )
    op.create_index("ix_approval_policies_project_id", "approval_policies", ["project_id"])
    op.create_table(
        "approval_policy_requirements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quorum", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["approval_policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "key"),
    )
    op.create_index(
        "ix_approval_policy_requirements_policy_id", "approval_policy_requirements", ["policy_id"]
    )
    op.create_table(
        "approval_requirement_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["approval_policy_requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["project_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "role_id"),
    )
    op.create_index(
        "ix_approval_requirement_roles_requirement_id",
        "approval_requirement_roles",
        ["requirement_id"],
    )
    op.create_index(
        "ix_approval_requirement_roles_role_id", "approval_requirement_roles", ["role_id"]
    )
    op.create_table(
        "approval_requirement_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requirement_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["approval_policy_requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "user_id"),
    )
    op.create_index(
        "ix_approval_requirement_users_requirement_id",
        "approval_requirement_users",
        ["requirement_id"],
    )
    op.create_index(
        "ix_approval_requirement_users_user_id", "approval_requirement_users", ["user_id"]
    )
    op.create_table(
        "governance_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("applies_to_tags", json_type, nullable=False),
        sa.Column("required_policy_keys", json_type, nullable=False),
        sa.Column("prohibit_self_approval", sa.Boolean(), nullable=False),
        sa.Column("min_total_approvals", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key"),
    )
    op.create_index("ix_governance_profiles_project_id", "governance_profiles", ["project_id"])

    op.create_table(
        "gate_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("node_execution_id", sa.Uuid(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("checkpoint_commit_sha", sa.String(40), nullable=False),
        sa.Column("policy_key", sa.String(100), nullable=False),
        sa.Column("policy_snapshot", json_type, nullable=False),
        sa.Column("eligible_snapshot", json_type, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invocation_id"], ["workflow_invocations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_execution_id"], ["node_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_execution_id", "iteration"),
    )
    for column in ("run_id", "invocation_id", "node_execution_id"):
        op.create_index(f"ix_gate_instances_{column}", "gate_instances", [column])
    op.create_table(
        "gate_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gate_instance_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_snapshot", json_type, nullable=False),
        sa.Column("requirement_keys", json_type, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("superseded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["gate_instance_id"], ["gate_instances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gate_decisions_gate_instance_id", "gate_decisions", ["gate_instance_id"])
    op.create_index(
        "ix_gate_decisions_gate_created", "gate_decisions", ["gate_instance_id", "created_at"]
    )
    op.create_table(
        "authorization_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_snapshot", json_type, nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=True),
        sa.Column("details", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_authorization_audit_project_created",
        "authorization_audit_events",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_authorization_audit_actor_created",
        "authorization_audit_events",
        ["actor_user_id", "created_at"],
    )
    op.create_table(
        "run_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "change_request_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("actor_provider_user_id", sa.String(255), nullable=False),
        sa.Column("actor_username", sa.String(255), nullable=False),
        sa.Column("merge_commit_sha", sa.String(64), nullable=True),
        sa.Column("provider_delivery_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_change_request_lifecycle_events_run_id", "change_request_lifecycle_events", ["run_id"]
    )
    op.create_index(
        "ix_change_request_lifecycle_run_created",
        "change_request_lifecycle_events",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    for table in (
        "change_request_lifecycle_events",
        "run_reports",
        "authorization_audit_events",
        "gate_decisions",
        "gate_instances",
        "governance_profiles",
        "approval_requirement_users",
        "approval_requirement_roles",
        "approval_policy_requirements",
        "approval_policies",
        "project_membership_roles",
        "project_role_permissions",
        "project_roles",
        "project_memberships",
    ):
        op.drop_table(table)
    op.drop_column("workflow_runs", "trigger_actor_snapshot")
    op.drop_column("users", "is_system_admin")
    op.drop_column("users", "is_active")
