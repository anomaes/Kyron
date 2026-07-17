"""Create the complete durable workflow domain.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

from alembic import op

from backend.db import models  # noqa: F401
from backend.db.database import Base

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=False)
