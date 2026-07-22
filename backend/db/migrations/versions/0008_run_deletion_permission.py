"""Grant project administrators permission to delete inactive runs.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    roles = sa.table(
        "project_roles",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
    )
    permissions = sa.table(
        "project_role_permissions",
        sa.column("id", sa.Uuid()),
        sa.column("role_id", sa.Uuid()),
        sa.column("permission", sa.String()),
    )
    existing = set(
        connection.scalars(
            sa.select(permissions.c.role_id).where(permissions.c.permission == "run.delete")
        )
    )
    for role_id in connection.scalars(
        sa.select(roles.c.id).where(roles.c.key == "project-admin")
    ):
        if role_id not in existing:
            connection.execute(
                sa.insert(permissions).values(
                    id=uuid.uuid4(), role_id=role_id, permission="run.delete"
                )
            )


def downgrade() -> None:
    permissions = sa.table(
        "project_role_permissions",
        sa.column("permission", sa.String()),
    )
    op.get_bind().execute(
        sa.delete(permissions).where(permissions.c.permission == "run.delete")
    )
