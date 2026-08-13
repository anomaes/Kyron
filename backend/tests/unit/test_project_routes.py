from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import backend.api.project_routes as project_routes
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import AuthorizationAuditEvent, Project
from backend.services.project_service import ProjectService


class GovernanceProjectService:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.deleted = False

    async def get(self, project_id: uuid.UUID) -> Project:
        assert project_id == self.project.id
        return self.project

    async def fetch(self, project_id: uuid.UUID) -> str:
        assert project_id == self.project.id
        return "a" * 40

    async def delete(self, project_id: uuid.UUID) -> None:
        assert project_id == self.project.id
        self.deleted = True


async def test_project_fetch_and_deletion_are_audited(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow(*_: object) -> None:
        return None

    monkeypatch.setattr(project_routes, "authorize_project", allow)
    project = Project(
        id=uuid.uuid4(),
        name="Governance",
        git_url="https://github.test/acme/governance.git",
        provider="github",
        provider_project_id="governance",
        provider_project_path="acme/governance",
        encrypted_access_token=b"unused",
        local_path=str(tmp_path / "governance"),
        default_branch="main",
        added_by=uuid.uuid4(),
    )
    service = GovernanceProjectService(project)
    user = AuthenticatedUser(
        id=uuid.uuid4(),
        email="admin@example.com",
        display_name="Admin",
        avatar_url=None,
        provider="github",
        provider_user_id="7",
        provider_username="admin",
        is_system_admin=True,
    )

    fetched = await project_routes.fetch_project(
        project.id,
        user,
        db_session,
        cast(ProjectService, service),
    )
    response = await project_routes.delete_project(
        project.id,
        user,
        db_session,
        cast(ProjectService, service),
    )

    assert fetched == {"commit_sha": "a" * 40}
    assert response.status_code == 204
    assert service.deleted
    actions = list(
        await db_session.scalars(
            select(AuthorizationAuditEvent.action).order_by(
                AuthorizationAuditEvent.id
            )
        )
    )
    assert actions == ["PROJECT_FETCHED", "PROJECT_DELETED"]
