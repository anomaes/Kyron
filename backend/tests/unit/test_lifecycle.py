from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import backend.lifecycle as lifecycle
from backend.config import Settings
from backend.db.models import Project, User, WorkflowRun
from backend.db.statuses import RunStatus
from backend.lifecycle import EngineRuntime


async def test_worker_supervisor_records_crash_without_backend_restart(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = User(email="crash@example.com", display_name="Crash test")
    db_session.add(user)
    await db_session.flush()
    project = Project(
        name="Crash project",
        git_url="https://github.test/acme/crash.git",
        provider="github",
        provider_project_id="999",
        provider_project_path="acme/crash",
        encrypted_access_token=b"unused",
        local_path=str(tmp_path / "repository"),
        default_branch="main",
        added_by=user.id,
    )
    db_session.add(project)
    await db_session.flush()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=RunStatus.RUNNING,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        reviewer_provider="github",
        reviewer_provider_user_id="7",
        reviewer_provider_username="alice",
    )
    db_session.add(run)
    await db_session.commit()

    @asynccontextmanager
    async def recovery_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    runtime = EngineRuntime(Settings(_env_file=None))

    async def crash(_: object) -> None:
        raise RuntimeError("sensitive provider response must not be persisted")

    monkeypatch.setattr(lifecycle, "session_factory", recovery_session)
    monkeypatch.setattr(runtime, "_execute_owned", crash)

    await runtime._execute(run.id)

    await db_session.refresh(run)
    assert run.status == RunStatus.INTERRUPTED
    assert run.error_type == "ENGINE_CRASH"
    assert "sensitive provider response" not in (run.error_message or "")
