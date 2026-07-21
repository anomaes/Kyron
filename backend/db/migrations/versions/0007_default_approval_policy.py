"""Add dynamic workflow-triggerer requirements and seed the default policy.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    requirement_columns = {
        column["name"] for column in inspector.get_columns("approval_policy_requirements")
    }
    if "include_triggering_user" not in requirement_columns:
        op.add_column(
            "approval_policy_requirements",
            sa.Column(
                "include_triggering_user",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )
    _seed_existing_projects()


def downgrade() -> None:
    connection = op.get_bind()
    policies = sa.table(
        "approval_policies",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.String()),
    )
    requirements = sa.table(
        "approval_policy_requirements",
        sa.column("policy_id", sa.Uuid()),
    )
    default_ids = list(
        connection.scalars(sa.select(policies.c.id).where(policies.c.key == "default"))
    )
    if default_ids:
        connection.execute(
            sa.delete(requirements).where(requirements.c.policy_id.in_(default_ids))
        )
        connection.execute(sa.delete(policies).where(policies.c.id.in_(default_ids)))
    op.drop_column("approval_policy_requirements", "include_triggering_user")


def _seed_existing_projects() -> None:
    connection = op.get_bind()
    projects = sa.table("projects", sa.column("id", sa.Uuid()))
    policies = sa.table(
        "approval_policies",
        sa.column("id", sa.Uuid()),
        sa.column("project_id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("initiator_may_approve", sa.Boolean()),
        sa.column("distinct_approvers_across_requirements", sa.Boolean()),
        sa.column("eligible_approvers_may_give_feedback", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    requirements = sa.table(
        "approval_policy_requirements",
        sa.column("id", sa.Uuid()),
        sa.column("policy_id", sa.Uuid()),
        sa.column("key", sa.String()),
        sa.column("name", sa.String()),
        sa.column("quorum", sa.Integer()),
        sa.column("include_triggering_user", sa.Boolean()),
    )
    existing = set(
        connection.scalars(
            sa.select(policies.c.project_id).where(policies.c.key == "default")
        )
    )
    now = datetime.now(UTC)
    for project_id in connection.scalars(sa.select(projects.c.id)):
        if project_id in existing:
            continue
        policy_id = uuid.uuid4()
        connection.execute(
            sa.insert(policies).values(
                id=policy_id,
                project_id=project_id,
                key="default",
                name="Workflow triggerer",
                description=(
                    "Allows only the user who triggered the workflow to approve or provide "
                    "feedback."
                ),
                enabled=True,
                initiator_may_approve=True,
                distinct_approvers_across_requirements=True,
                eligible_approvers_may_give_feedback=True,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            sa.insert(requirements).values(
                id=uuid.uuid4(),
                policy_id=policy_id,
                key="triggerer",
                name="Workflow triggerer approval",
                quorum=1,
                include_triggering_user=True,
            )
        )
