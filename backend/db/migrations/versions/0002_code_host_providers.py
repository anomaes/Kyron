"""Add provider-neutral identities and code-host fields.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Revision 0001 intentionally creates the then-current SQLAlchemy metadata.
    # A brand-new installation therefore already has this revision's schema,
    # while an installation that previously ran 0001 needs the conversion below.
    if "provider_identities" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "provider_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_provider_identities_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_identities"),
        sa.UniqueConstraint("user_id", name="uq_provider_identities_user_id"),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_provider_identities_provider"
        ),
    )
    op.execute(
        """
        INSERT INTO provider_identities
            (id, user_id, provider, provider_user_id, username, created_at, updated_at)
        SELECT CAST(md5(CAST(id AS text) || '-gitlab') AS uuid), id, 'gitlab',
               CAST(gitlab_user_id AS text), gitlab_username, created_at, last_login_at
        FROM users
        """
    )
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "oauth_provider")
    op.drop_column("users", "gitlab_username")
    op.drop_column("users", "gitlab_user_id")

    op.add_column("projects", sa.Column("provider", sa.String(30), nullable=True))
    op.add_column(
        "projects", sa.Column("provider_project_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "projects", sa.Column("provider_project_path", sa.String(1024), nullable=True)
    )
    op.execute(
        """
        UPDATE projects
        SET provider = 'gitlab',
            provider_project_id = CAST(gitlab_project_id AS text),
            provider_project_path = CAST(gitlab_project_id AS text)
        """
    )
    for column in ("provider", "provider_project_id", "provider_project_path"):
        op.alter_column("projects", column, nullable=False)
    op.drop_constraint("uq_projects_gitlab_project_id", "projects", type_="unique")
    op.drop_column("projects", "gitlab_project_id")
    op.create_unique_constraint(
        "uq_projects_provider", "projects", ["provider", "provider_project_id"]
    )

    op.add_column(
        "workflow_runs", sa.Column("change_request_number", sa.Integer(), nullable=True)
    )
    op.add_column(
        "workflow_runs", sa.Column("change_request_url", sa.Text(), nullable=True)
    )
    op.add_column(
        "workflow_runs", sa.Column("reviewer_provider", sa.String(30), nullable=True)
    )
    op.add_column(
        "workflow_runs",
        sa.Column("reviewer_provider_user_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("reviewer_provider_username", sa.String(255), nullable=True),
    )
    op.execute(
        """
        UPDATE workflow_runs AS runs
        SET change_request_number = runs.mr_iid,
            change_request_url = runs.mr_url,
            reviewer_provider = 'gitlab',
            reviewer_provider_user_id = CAST(runs.reviewer_gitlab_user_id AS text),
            reviewer_provider_username = identities.username
        FROM provider_identities AS identities
        WHERE identities.user_id = runs.triggered_by
        """
    )
    for column in (
        "reviewer_provider",
        "reviewer_provider_user_id",
        "reviewer_provider_username",
    ):
        op.alter_column("workflow_runs", column, nullable=False)
    op.drop_index("ix_workflow_runs_mr_project", table_name="workflow_runs")
    op.drop_column("workflow_runs", "reviewer_gitlab_user_id")
    op.drop_column("workflow_runs", "mr_url")
    op.drop_column("workflow_runs", "mr_iid")
    op.create_index(
        "ix_workflow_runs_change_request_project",
        "workflow_runs",
        ["change_request_number", "project_id"],
    )

    op.add_column(
        "feedback_events", sa.Column("author_provider", sa.String(30), nullable=True)
    )
    op.add_column(
        "feedback_events",
        sa.Column("author_provider_user_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "feedback_events", sa.Column("provider_comment_id", sa.String(255), nullable=True)
    )
    op.execute(
        """
        UPDATE feedback_events
        SET author_provider = 'gitlab',
            author_provider_user_id = CAST(author_gitlab_user_id AS text),
            provider_comment_id = CAST(gitlab_note_id AS text)
        """
    )
    op.alter_column("feedback_events", "author_provider", nullable=False)
    op.alter_column("feedback_events", "author_provider_user_id", nullable=False)
    op.drop_column("feedback_events", "gitlab_note_id")
    op.drop_column("feedback_events", "author_gitlab_user_id")

    op.add_column(
        "webhook_deliveries", sa.Column("provider", sa.String(30), nullable=True)
    )
    op.add_column(
        "webhook_deliveries",
        sa.Column("provider_project_id", sa.String(255), nullable=True),
    )
    op.execute(
        """
        UPDATE webhook_deliveries
        SET provider = 'gitlab',
            provider_project_id = CAST(gitlab_project_id AS text),
            delivery_key = 'gitlab:' || delivery_key
        """
    )
    op.alter_column("webhook_deliveries", "provider", nullable=False)
    op.drop_column("webhook_deliveries", "gitlab_project_id")


def downgrade() -> None:
    raise RuntimeError("Downgrading provider-neutral identity history is not supported")
