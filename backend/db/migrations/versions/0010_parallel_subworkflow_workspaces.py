"""Add invocation-owned contexts and isolated sub-workflow workspaces.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    invocation_columns = {
        column["name"] for column in inspector.get_columns("workflow_invocations")
    }
    run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    wave_columns = {column["name"] for column in inspector.get_columns("execution_waves")}
    gate_columns = {column["name"] for column in inspector.get_columns("gate_instances")}
    lifecycle_columns = {
        column["name"]
        for column in inspector.get_columns("change_request_lifecycle_events")
    }
    if (
        {
            "invocation_workspaces",
            "subworkflow_batches",
            "subworkflow_batch_members",
            "run_change_requests",
        }
        <= tables
        and {"public_context", "scheduler_version", "workspace_id"}
        <= invocation_columns
        and "workspace_id" in wave_columns
        and {"workspace_id", "change_request_id"} <= gate_columns
        and "change_request_id" in lifecycle_columns
        and {
            "subject_type",
            "subject_ref",
            "subject_commit_sha",
            "delivery_mode",
            "effective_credential_policy",
        }
        <= run_columns
    ):
        return

    run_additions = [
        sa.Column("subject_type", sa.String(30), nullable=False, server_default="BRANCH"),
        sa.Column("subject_ref", sa.String(255), nullable=False, server_default=""),
        sa.Column("subject_change_request_number", sa.Integer()),
        sa.Column("subject_change_request_url", sa.Text()),
        sa.Column("subject_target_ref", sa.String(255)),
        sa.Column("subject_commit_sha", sa.String(40), nullable=False, server_default=""),
        sa.Column("subject_target_commit_sha", sa.String(40)),
        sa.Column("subject_current_head_sha", sa.String(40)),
        sa.Column("subject_checked_at", sa.DateTime(timezone=True)),
        sa.Column("subject_availability", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "delivery_mode", sa.String(30), nullable=False, server_default="PROPOSE_CHANGES"
        ),
        sa.Column(
            "effective_credential_policy",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("verification_conclusion", sa.String(30)),
        sa.Column("verification_freshness", sa.String(30)),
        sa.Column("verification_published_at", sa.DateTime(timezone=True)),
    ]
    for column in run_additions:
        op.add_column("workflow_runs", column)
    op.execute(
        sa.text(
            "UPDATE workflow_runs SET subject_ref = base_ref, "
            "subject_commit_sha = base_commit_sha, "
            "subject_current_head_sha = base_commit_sha"
        )
    )

    op.add_column(
        "workflow_invocations",
        sa.Column("public_context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "workflow_invocations",
        sa.Column("scheduler_version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "invocation_workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_invocation_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_invocations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "parent_workspace_id",
            sa.Uuid(),
            sa.ForeignKey("invocation_workspaces.id", ondelete="CASCADE"),
        ),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("base_commit_sha", sa.String(40), nullable=False),
        sa.Column("current_head_sha", sa.String(40), nullable=False),
        sa.Column("integrated_head_sha", sa.String(40)),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("worktree_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(100)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index(
        "ix_invocation_workspaces_run_id", "invocation_workspaces", ["run_id"]
    )
    op.create_index(
        "ix_invocation_workspaces_run_status",
        "invocation_workspaces",
        ["run_id", "status"],
    )
    with op.batch_alter_table("workflow_invocations") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_workflow_invocations_workspace_id",
            "invocation_workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_workflow_invocations_workspace_id", ["workspace_id"])

    op.create_table(
        "subworkflow_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_invocation_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_invocations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_workspace_id",
            sa.Uuid(),
            sa.ForeignKey("invocation_workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_commit_sha", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_type", sa.String(100)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_subworkflow_batches_run_id", "subworkflow_batches", ["run_id"])
    op.create_index(
        "ix_subworkflow_batches_run_status", "subworkflow_batches", ["run_id", "status"]
    )

    op.create_table(
        "subworkflow_batch_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("subworkflow_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_node_execution_id",
            sa.Uuid(),
            sa.ForeignKey("node_executions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "child_invocation_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_invocations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "child_workspace_id",
            sa.Uuid(),
            sa.ForeignKey("invocation_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("integration_order", sa.Integer(), nullable=False),
        sa.Column("allow_failure", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("integrated_commit_sha", sa.String(40)),
        sa.UniqueConstraint("batch_id", "integration_order"),
    )
    op.create_index(
        "ix_subworkflow_batch_members_batch_id",
        "subworkflow_batch_members",
        ["batch_id"],
    )

    op.create_table(
        "run_change_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("invocation_workspaces.id", ondelete="CASCADE"),
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_number", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_branch", sa.String(255), nullable=False),
        sa.Column("target_branch", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("target_sha", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "provider", "provider_number"),
    )
    op.create_index("ix_run_change_requests_run_id", "run_change_requests", ["run_id"])
    op.create_index(
        "ix_run_change_requests_project_id", "run_change_requests", ["project_id"]
    )
    op.create_index(
        "ix_run_change_requests_run_status", "run_change_requests", ["run_id", "status"]
    )
    op.create_index(
        "ix_run_change_requests_source_target",
        "run_change_requests",
        ["source_branch", "target_branch"],
    )

    with op.batch_alter_table("execution_waves") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_execution_waves_workspace_id",
            "invocation_workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_execution_waves_workspace_id", ["workspace_id"])
    with op.batch_alter_table("gate_instances") as batch:
        batch.add_column(sa.Column("workspace_id", sa.Uuid()))
        batch.add_column(sa.Column("change_request_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_gate_instances_workspace_id",
            "invocation_workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_gate_instances_change_request_id",
            "run_change_requests",
            ["change_request_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_gate_instances_workspace_id", ["workspace_id"])
        batch.create_index("ix_gate_instances_change_request_id", ["change_request_id"])
    with op.batch_alter_table("change_request_lifecycle_events") as batch:
        batch.add_column(sa.Column("change_request_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_change_request_lifecycle_events_change_request_id",
            "run_change_requests",
            ["change_request_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_change_request_lifecycle_events_change_request_id",
            ["change_request_id"],
        )

    op.execute(
        """
        UPDATE workflow_invocations
        SET public_context = input_context
        WHERE public_context IS NULL OR public_context = '{}'
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("change_request_lifecycle_events") as batch:
        batch.drop_index("ix_change_request_lifecycle_events_change_request_id")
        batch.drop_column("change_request_id")
    with op.batch_alter_table("gate_instances") as batch:
        batch.drop_index("ix_gate_instances_change_request_id")
        batch.drop_index("ix_gate_instances_workspace_id")
        batch.drop_column("change_request_id")
        batch.drop_column("workspace_id")
    with op.batch_alter_table("execution_waves") as batch:
        batch.drop_index("ix_execution_waves_workspace_id")
        batch.drop_column("workspace_id")
    op.drop_table("run_change_requests")
    op.drop_table("subworkflow_batch_members")
    op.drop_table("subworkflow_batches")
    with op.batch_alter_table("workflow_invocations") as batch:
        batch.drop_index("ix_workflow_invocations_workspace_id")
        batch.drop_column("workspace_id")
    op.drop_table("invocation_workspaces")
    op.drop_column("workflow_invocations", "scheduler_version")
    op.drop_column("workflow_invocations", "public_context")
    for column in [
        "verification_published_at",
        "verification_freshness",
        "verification_conclusion",
        "effective_credential_policy",
        "delivery_mode",
        "subject_availability",
        "subject_checked_at",
        "subject_current_head_sha",
        "subject_target_commit_sha",
        "subject_commit_sha",
        "subject_target_ref",
        "subject_change_request_url",
        "subject_change_request_number",
        "subject_ref",
        "subject_type",
    ]:
        op.drop_column("workflow_runs", column)
