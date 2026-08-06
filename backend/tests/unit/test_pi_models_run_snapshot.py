from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

import backend.services.pi_models_config_service as config_service_module
from backend.auth.dependencies import AuthenticatedUser
from backend.config import Settings
from backend.db.models import Project, User
from backend.engine.validation import parse_workflow
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowBundle
from backend.services.crypto import SecretCipher
from backend.services.pi_models_config_service import PiModelsConfigService
from backend.services.workflow_service import WorkflowService
from backend.tests.fixtures.workflows import workflow


async def accept_document(_: object) -> None:
    pass


async def test_run_snapshots_the_active_provider_revision(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_service_module, "validate_models_document", accept_document)
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
    document = {
        "providers": {
            "private-gateway": {
                "baseUrl": "https://llm.example.com/v1",
                "api": "openai-completions",
                "apiKey": "$CUSTOM_LLM_API_KEY",
                "models": [{"id": "example-model"}],
            }
        }
    }
    revision = await PiModelsConfigService(db_session, settings).create_and_activate(
        document, user_row.id
    )
    definition, errors = parse_workflow(workflow())
    assert not errors and definition is not None
    bundle = WorkflowBundle(
        base_commit_sha="a" * 40,
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

    async def snapshot(*_: object, **__: object) -> tuple[str, WorkflowBundle]:
        return "a" * 40, bundle

    monkeypatch.setattr(service, "snapshot_for_run", snapshot)
    user = AuthenticatedUser(
        id=user_row.id,
        email=user_row.email,
        display_name=user_row.display_name,
        avatar_url=None,
        provider="github",
        provider_user_id="7",
        provider_username="runner",
    )

    run = await service.create_run(project, user, "root", {})

    assert run.pi_models_config_revision_id == revision.id
    assert run.pi_models_config_source == "database"
    assert run.pi_models_config_snapshot == document
