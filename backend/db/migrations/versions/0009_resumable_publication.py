"""Track resumable external publication operations.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workflow_runs")}
    if "pending_operation" in columns:
        return
    op.add_column("workflow_runs", sa.Column("pending_operation", sa.String(50)))


def downgrade() -> None:
    op.drop_column("workflow_runs", "pending_operation")
