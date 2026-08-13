from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser
from backend.config import Settings
from backend.db.models import Project, User
from backend.engine.snapshot import BundleResolutionError, WorkflowNotFoundError
from backend.engine.validation import parse_workflow
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowBundle
from backend.services.crypto import SecretCipher
from backend.services.workflow_service import WorkflowService
from backend.tests.fixtures.workflows import workflow


async def test_legacy_branch_fallback_forces_restrictive_run_policy(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    settings = Settings(
        _env_file=None,
        CREDENTIALS_ENCRYPTION_KEY=key.decode(),
        PROJECT_CLONE_BASE_PATH=tmp_path / "repos",
        WORKTREE_BASE_PATH=tmp_path / "worktrees",
        RUN_DATA_BASE_PATH=tmp_path / "runs",
    )
    cipher = SecretCipher(key)
    user_row = User(email="runner@example.com", display_name="Runner")
    db_session.add(user_row)
    await db_session.flush()
    project = Project(
        name="Project",
        git_url="https://github.example/acme/project.git",
        provider="github",
        provider_project_id="1",
        provider_project_path="acme/project",
        encrypted_access_token=cipher.encrypt("token"),
        local_path=str(tmp_path / "repos" / "project"),
        default_branch="main",
        added_by=user_row.id,
    )
    db_session.add(project)
    await db_session.flush()
    raw_definition = workflow()
    raw_definition["settings"] = {
        "delivery_mode": "propose_changes",
        "credential_access": {"mode": "all", "keys": []},
    }
    definition, errors = parse_workflow(raw_definition)
    assert not errors and definition is not None
    branch_bundle = WorkflowBundle(
        base_commit_sha="b" * 40,
        root_workflow_id="root",
        workflows={"root": definition},
        reference_graph={"root": []},
    )
    service = WorkflowService(
        db_session,
        settings,
        cipher,
        GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        ),
    )
    calls: list[str] = []

    async def snapshot(
        _project: Project, _workflow_id: str, ref: str, **_: object
    ) -> tuple[str, WorkflowBundle]:
        calls.append(ref)
        if ref == "main":
            raise WorkflowNotFoundError("missing from trusted branch")
        return "b" * 40, branch_bundle

    async def resolve_subject_sha(_project: Project, ref: str) -> str:
        assert ref == "feature"
        return "b" * 40

    monkeypatch.setattr(service, "snapshot_for_run", snapshot)
    monkeypatch.setattr(service, "_resolve_subject_sha", resolve_subject_sha)
    user = AuthenticatedUser(
        id=user_row.id,
        email=user_row.email,
        display_name=user_row.display_name,
        avatar_url=None,
        provider="github",
        provider_user_id="7",
        provider_username="runner",
    )

    run = await service.create_run(project, user, "root", {}, base_ref="feature")

    assert calls == ["main", "feature"]
    assert run.delivery_mode == "REPORT_ONLY"
    assert run.effective_credential_policy == {"mode": "none", "keys": []}


async def test_legacy_branch_fallback_does_not_hide_other_snapshot_failures(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key()
    settings = Settings(_env_file=None)
    user_row = User(email="runner-invalid@example.com", display_name="Runner")
    db_session.add(user_row)
    await db_session.flush()
    cipher = SecretCipher(key)
    project = Project(
        name="Project invalid",
        git_url="https://github.example/acme/project.git",
        provider="github",
        provider_project_id="2",
        provider_project_path="acme/project",
        encrypted_access_token=cipher.encrypt("token"),
        local_path=str(tmp_path / "project"),
        default_branch="main",
        added_by=user_row.id,
    )
    service = WorkflowService(
        db_session,
        settings,
        cipher,
        GitManager(
            settings.PROJECT_CLONE_BASE_PATH,
            settings.WORKTREE_BASE_PATH,
            settings.RUN_DATA_BASE_PATH,
        ),
    )
    calls = 0

    async def snapshot(*_: object, **__: object) -> tuple[str, WorkflowBundle]:
        nonlocal calls
        calls += 1
        raise BundleResolutionError("trusted workflow is invalid")

    monkeypatch.setattr(service, "snapshot_for_run", snapshot)
    user = AuthenticatedUser(
        id=user_row.id,
        email=user_row.email,
        display_name=user_row.display_name,
        avatar_url=None,
        provider="github",
        provider_user_id="8",
        provider_username="runner",
    )

    with pytest.raises(BundleResolutionError, match="trusted workflow is invalid"):
        await service.create_run(project, user, "root", {}, base_ref="feature")
    assert calls == 1
