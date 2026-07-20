from __future__ import annotations

import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import Project, User
from backend.integrations.git_manager import GitManager
from backend.services.crypto import SecretCipher
from backend.services.project_service import ProjectService


async def test_delete_removes_clone_and_local_definition_changes(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    clone_root = tmp_path / "repos"
    worktree_root = tmp_path / "worktrees"
    run_data_root = tmp_path / "run-data"
    project_id = uuid.uuid4()
    clone = clone_root / str(project_id)
    changes = run_data_root / "project_changes" / str(project_id)
    clone.mkdir(parents=True)
    changes.mkdir(parents=True)
    (clone / "repository-data").write_text("local clone", encoding="utf-8")
    (changes / "draft.json").write_text("{}", encoding="utf-8")

    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        display_name="Owner",
    )
    project = Project(
        id=project_id,
        name="Disposable",
        git_url="https://github.example/acme/disposable.git",
        provider="github",
        provider_project_id="42",
        provider_project_path="acme/disposable",
        encrypted_access_token=b"ciphertext",
        local_path=str(clone),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add_all([user, project])
    await db_session.commit()

    key = Fernet.generate_key()
    settings = Settings(
        PROJECT_CLONE_BASE_PATH=clone_root,
        WORKTREE_BASE_PATH=worktree_root,
        RUN_DATA_BASE_PATH=run_data_root,
        CREDENTIALS_ENCRYPTION_KEY=key.decode(),
        _env_file=None,
    )
    service = ProjectService(
        db_session,
        settings,
        SecretCipher(key),
        GitManager(clone_root, worktree_root, run_data_root),
    )

    await service.delete(project_id)
    await db_session.commit()

    assert await db_session.get(Project, project_id) is None
    assert not clone.exists()
    assert not changes.exists()
