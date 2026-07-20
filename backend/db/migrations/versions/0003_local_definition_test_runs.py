"""Mark runs that use project-local workflow definitions.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workflow_runs")}
    if "local_definition_test" in columns:
        return
    op.add_column(
        "workflow_runs",
        sa.Column(
            "local_definition_test",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "local_definition_test")
