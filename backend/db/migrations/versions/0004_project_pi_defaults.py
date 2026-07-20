"""Add project-wide Pi defaults.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("projects")}
    if "pi" in columns:
        return
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column(
        "projects",
        sa.Column("pi", json_type, nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("projects", "pi")
