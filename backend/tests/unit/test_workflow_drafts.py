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
    ) -> tuple[
        str,
        dict[str, WorkflowDefinition],
        dict[str, NodeTemplate],
        dict[str, str],
    ]:
        return "a" * 40, {current.id: current}, {}, {current.id: "teams/platform/root.json"}

    monkeypatch.setattr(service, "_load_remote", load_remote)
    test_project = project(tmp_path, cipher)
    changed = current.model_copy(update={"description": "locally edited"})
    saved = await service.save_draft(test_project, changed, "a" * 40)
    assert saved["outgoing_changes"] == 1
    assert (
        settings.RUN_DATA_BASE_PATH
        / "project_changes"
        / str(test_project.id)
        / "outgoing"
        / "workflows"
        / "teams"
        / "platform"
        / "root.json"
    ).is_file()

    template = NodeTemplate(
        id="print_text",
        name="Print text",
        description="A reusable echo step",
        node=changed.nodes[0],
    )
    saved_template = await service.save_template(test_project, template, "a" * 40)
    assert saved_template["outgoing_changes"] == 2

    _sha, workflows, templates, paths = await service._load_all(test_project)
    assert workflows["root"].description == "locally edited"
    assert paths["root"] == "teams/platform/root.json"
    assert templates["print_text"].node.type == "bash"
    _sha, catalog = await service.list_with_folders(test_project)
    assert [(item.id, folder) for item, folder in catalog] == [
        ("root", "teams/platform")
    ]
    assert not (tmp_path / "repos" / "project").exists()


async def test_applying_a_folder_move_removes_the_previous_workflow_file(
    tmp_path: Path, db_session: Any
) -> None:
    key = Fernet.generate_key()
    settings = Settings(
        RUN_DATA_BASE_PATH=tmp_path / "run-data",
        CREDENTIALS_ENCRYPTION_KEY=key.decode(),
        _env_file=None,
    )
    service = WorkflowService(
        db_session,
        settings,
        SecretCipher(key),
        GitManager(tmp_path / "repos"),
    )
    worktree = tmp_path / "worktree"
    old_path = worktree / ".workflowEngine" / "old" / "root.json"
    old_path.parent.mkdir(parents=True)
    old_path.write_text("{}", encoding="utf-8")
    template_path = worktree / ".workflowEngine" / "templates" / "root.json"
    template_path.parent.mkdir(parents=True)
    template_path.write_text("{}", encoding="utf-8")
    layer_path = tmp_path / "layer" / "workflows" / "new" / "root.json"
    layer_path.parent.mkdir(parents=True)
    layer_path.write_text("{\"id\": \"root\"}", encoding="utf-8")

    await service._apply_layer_to_worktree(worktree, tmp_path / "layer")

    assert not old_path.exists()
    assert (worktree / ".workflowEngine" / "new" / "root.json").is_file()
    assert template_path.is_file()


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


@pytest.mark.parametrize("folder", ["../escape", "/absolute", "templates", "bad\\path"])
async def test_workflow_folder_paths_reject_unsafe_locations(
    folder: str, tmp_path: Path, db_session: Any
) -> None:
    key = Fernet.generate_key()
    service = WorkflowService(
        db_session,
        Settings(
            RUN_DATA_BASE_PATH=tmp_path / "run-data",
            CREDENTIALS_ENCRYPTION_KEY=key.decode(),
            _env_file=None,
        ),
        SecretCipher(key),
        GitManager(tmp_path / "repos"),
    )
    with pytest.raises(ValueError, match="folder path is invalid"):
        await service.save_draft(
            project(tmp_path, service.cipher),
            definition(workflow()),
            "a" * 40,
            folder_path=folder,
        )
