"""Persist aggregate Pi usage for each node attempt.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("node_attempts")
    }
    if "pi_usage" in columns:
        return
    usage_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.add_column("node_attempts", sa.Column("pi_usage", usage_type))


def downgrade() -> None:
    op.drop_column("node_attempts", "pi_usage")
