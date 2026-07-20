"""Add resource-retention observability fields and audit events.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    run_columns = {
        column["name"] for column in inspector.get_columns("workflow_runs")
    }
    if "change_request_created_at" not in run_columns:
        op.add_column(
            "workflow_runs",
            sa.Column("change_request_created_at", sa.DateTime(timezone=True), nullable=True),
        )

    if "resource_audit_logs" in inspector.get_table_names():
        return
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "resource_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_path", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", json_type, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_resource_audit_logs_event_timestamp",
        "resource_audit_logs",
        ["event_type", "timestamp"],
    )
    op.create_index(
        "ix_resource_audit_logs_resource_path",
        "resource_audit_logs",
        ["resource_path"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "resource_audit_logs" in inspector.get_table_names():
        op.drop_table("resource_audit_logs")
    run_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("workflow_runs")
    }
    if "change_request_created_at" in run_columns:
        op.drop_column("workflow_runs", "change_request_created_at")
