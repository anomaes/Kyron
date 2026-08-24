"""Add short-lived VS Code device authorization and client sessions.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "vscode_device_authorizations" not in inspector.get_table_names():
        op.create_table(
            "vscode_device_authorizations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("device_code_hash", sa.String(64), nullable=False),
            sa.Column("user_code", sa.String(9), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("user_id", sa.Uuid()),
            sa.Column("provider_identity_id", sa.Uuid()),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("approved_at", sa.DateTime(timezone=True)),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["provider_identity_id"], ["provider_identities.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("device_code_hash"),
            sa.UniqueConstraint("user_code"),
        )
        op.create_index(
            "ix_vscode_device_authorizations_user_id",
            "vscode_device_authorizations",
            ["user_id"],
        )
        op.create_index(
            "ix_vscode_device_authorizations_provider_identity_id",
            "vscode_device_authorizations",
            ["provider_identity_id"],
        )
    if "vscode_client_sessions" not in inspector.get_table_names():
        op.create_table(
            "vscode_client_sessions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("provider_identity_id", sa.Uuid(), nullable=False),
            sa.Column("access_token_hash", sa.String(64), nullable=False),
            sa.Column("refresh_token_hash", sa.String(64), nullable=False),
            sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
            sa.Column("revoked_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["provider_identity_id"], ["provider_identities.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("access_token_hash"),
            sa.UniqueConstraint("refresh_token_hash"),
        )
        op.create_index(
            "ix_vscode_client_sessions_user_id", "vscode_client_sessions", ["user_id"]
        )
        op.create_index(
            "ix_vscode_client_sessions_provider_identity_id",
            "vscode_client_sessions",
            ["provider_identity_id"],
        )


def downgrade() -> None:
    op.drop_table("vscode_client_sessions")
    op.drop_table("vscode_device_authorizations")
