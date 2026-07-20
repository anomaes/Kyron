from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography.fernet import Fernet

from backend.config import Settings
from backend.db.models import Project, WorkflowRun
from backend.engine.coordinator import should_publish_run
from backend.engine.validation import parse_workflow
from backend.integrations.git_manager import GitManager
from backend.schemas.run import RunTriggerRequest
from backend.schemas.workflow import NodeTemplate, WorkflowDefinition
from backend.services.crypto import SecretCipher
from backend.services.workflow_service import WorkflowService
from backend.tests.fixtures.workflows import workflow


def definition(data: dict[str, Any]) -> WorkflowDefinition:
    parsed, errors = parse_workflow(data)
    assert not errors
    assert parsed is not None
    return parsed


def project(tmp_path: Path, cipher: SecretCipher) -> Project:
    return Project(
        id=uuid.uuid4(),
        name="Test",
        git_url="https://example.test/acme/repo.git",
        provider="github",
        provider_project_id="1",
        provider_project_path="acme/repo",
        encrypted_access_token=cipher.encrypt("token"),
        local_path=str(tmp_path / "repos" / "project"),
        default_branch="main",
        added_by=uuid.uuid4(),
    )


async def test_workflow_and_template_saves_are_project_local(
    tmp_path: Path, db_session: Any, monkeypatch: Any
) -> None:
    key = Fernet.generate_key()
    cipher = SecretCipher(key)
    settings = Settings(
        PROJECT_CLONE_BASE_PATH=tmp_path / "repos",
        WORKTREE_BASE_PATH=tmp_path / "worktrees",
        RUN_DATA_BASE_PATH=tmp_path / "run-data",
        CREDENTIALS_ENCRYPTION_KEY=key.decode(),
        _env_file=None,
    )
    service = WorkflowService(
        db_session,
        settings,
        cipher,
        GitManager(settings.PROJECT_CLONE_BASE_PATH, settings.WORKTREE_BASE_PATH),
    )
    current = definition(workflow())

    async def load_remote(
        _project: Project,
    ) -> tuple[str, dict[str, WorkflowDefinition], dict[str, NodeTemplate]]:
        return "a" * 40, {current.id: current}, {}

    monkeypatch.setattr(service, "_load_remote", load_remote)
    test_project = project(tmp_path, cipher)
    changed = current.model_copy(update={"description": "locally edited"})
    saved = await service.save_draft(test_project, changed, "a" * 40)
    assert saved["outgoing_changes"] == 1

    template = NodeTemplate(
        id="print_text",
        name="Print text",
        description="A reusable echo step",
        node=changed.nodes[0],
    )
    saved_template = await service.save_template(test_project, template, "a" * 40)
    assert saved_template["outgoing_changes"] == 2

    _sha, workflows, templates = await service._load_all(test_project)
    assert workflows["root"].description == "locally edited"
    assert templates["print_text"].node.type == "bash"
    assert not (tmp_path / "repos" / "project").exists()


def test_local_definition_run_option_is_explicit() -> None:
    assert not RunTriggerRequest().use_local_definitions
    assert RunTriggerRequest(use_local_definitions=True).use_local_definitions


def test_local_definition_runs_never_publish() -> None:
    local = cast(WorkflowRun, SimpleNamespace(local_definition_test=True))
    reviewed = cast(WorkflowRun, SimpleNamespace(local_definition_test=False))
    assert not should_publish_run(local)
    assert should_publish_run(reviewed)


def test_local_definition_paths_reject_traversal() -> None:
    with pytest.raises(ValueError, match="invalid"):
        WorkflowService._require_identifier("../../escape")
