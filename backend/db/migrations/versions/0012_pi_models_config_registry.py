"""Add versioned system-admin Pi models configuration.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "pi_models_config_revisions" not in tables:
        op.create_table(
            "pi_models_config_revisions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("document", json_type, nullable=False),
            sa.Column("required_credentials", json_type, nullable=False),
            sa.Column("provider_catalog", json_type, nullable=False),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("version"),
        )
    if "pi_models_config_state" not in tables:
        op.create_table(
            "pi_models_config_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("active_revision_id", sa.Uuid()),
            sa.Column("updated_by", sa.Uuid()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["active_revision_id"],
                ["pi_models_config_revisions.id"],
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    existing_revision_fk = any(
        foreign_key.get("constrained_columns") == ["pi_models_config_revision_id"]
        for foreign_key in inspector.get_foreign_keys("workflow_runs")
    )
    with op.batch_alter_table("workflow_runs") as batch:
        if "pi_models_config_revision_id" not in run_columns:
            batch.add_column(sa.Column("pi_models_config_revision_id", sa.Uuid()))
        if "pi_models_config_source" not in run_columns:
            batch.add_column(
                sa.Column(
                    "pi_models_config_source",
                    sa.String(length=20),
                    # Rows queued before this migration have no snapshot. Mark them so
                    # the runtime can retain the pre-registry fallback behavior.
                    server_default="legacy",
                    nullable=False,
                )
            )
        if "pi_models_config_snapshot" not in run_columns:
            batch.add_column(sa.Column("pi_models_config_snapshot", json_type))
        if not existing_revision_fk:
            batch.create_foreign_key(
                "fk_workflow_runs_pi_models_config_revision",
                "pi_models_config_revisions",
                ["pi_models_config_revision_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        if "pi_models_config_source" not in run_columns:
            batch.alter_column("pi_models_config_source", server_default="builtin")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    run_columns = {column["name"] for column in inspector.get_columns("workflow_runs")}
    revision_fk = next(
        (
            foreign_key.get("name")
            for foreign_key in inspector.get_foreign_keys("workflow_runs")
            if foreign_key.get("constrained_columns") == ["pi_models_config_revision_id"]
        ),
        None,
    )
    with op.batch_alter_table("workflow_runs") as batch:
        if revision_fk is not None:
            batch.drop_constraint(revision_fk, type_="foreignkey")
        for column in (
            "pi_models_config_snapshot",
            "pi_models_config_source",
            "pi_models_config_revision_id",
        ):
            if column in run_columns:
                batch.drop_column(column)
    tables = set(inspector.get_table_names())
    if "pi_models_config_state" in tables:
        op.drop_table("pi_models_config_state")
    if "pi_models_config_revisions" in tables:
        op.drop_table("pi_models_config_revisions")
