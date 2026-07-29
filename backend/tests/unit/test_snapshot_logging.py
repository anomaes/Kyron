from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import pytest

from backend.engine.definition_yaml import (
    DefinitionYamlError,
    dump_definition_yaml,
    load_definition_yaml,
)
from backend.engine.snapshot import BundleResolutionError, WorkflowSnapshotLoader
from backend.integrations.git_manager import GitManager
from backend.tests.fixtures.workflows import workflow


class StubGit:
    def __init__(self, raw: str, files: list[str] | None = None) -> None:
        self.raw = raw
        self.files = files or [".workflowEngine/root.yaml"]

    async def show_file(self, *_args: object) -> str:
        return self.raw

    async def list_files(self, *_args: object) -> list[str]:
        return self.files


async def test_duplicate_workflow_ids_across_folders_are_rejected(tmp_path: Path) -> None:
    loader = WorkflowSnapshotLoader(
        cast(
            GitManager,
            StubGit(
                dump_definition_yaml(workflow()),
                [
                    ".workflowEngine/team-a/root.yaml",
                    ".workflowEngine/team-b/root.yaml",
                ],
            ),
        )
    )

    with pytest.raises(BundleResolutionError, match="used by multiple files"):
        await loader.load(
            tmp_path,
            "c" * 40,
            "root",
            max_timeout=14400,
            max_review_iterations=10,
            max_subworkflow_depth=8,
        )


async def test_json_workflow_files_are_not_indexed(tmp_path: Path) -> None:
    loader = WorkflowSnapshotLoader(
        cast(
            GitManager,
            StubGit(
                dump_definition_yaml(workflow()),
                [".workflowEngine/root.json"],
            ),
        )
    )

    with pytest.raises(BundleResolutionError, match="does not exist"):
        await loader.load(
            tmp_path,
            "d" * 40,
            "root",
            max_timeout=14400,
            max_review_iterations=10,
            max_subworkflow_depth=8,
        )


async def test_invalid_workflow_yaml_logs_location_and_reason_without_contents(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw = "id: root\ntoken: must-not-be-logged\nnodes:\n  - [\n"
    with pytest.raises(DefinitionYamlError) as parse_error:
        load_definition_yaml(raw)
    expected = parse_error.value
    loader = WorkflowSnapshotLoader(cast(GitManager, StubGit(raw)))
    caplog.set_level(logging.WARNING, logger="backend.engine.snapshot")

    with pytest.raises(
        BundleResolutionError,
        match=rf"line {expected.line}, column {expected.column}",
    ):
        await loader.load(
            tmp_path,
            "a" * 40,
            "root",
            max_timeout=14400,
            max_review_iterations=10,
            max_subworkflow_depth=8,
        )

    assert "Workflow YAML parsing failed" in caplog.text
    assert "workflow=root" in caplog.text
    assert "file=.workflowEngine/root.yaml" in caplog.text
    assert f"line={expected.line}, column={expected.column}" in caplog.text
    assert str(expected) in caplog.text
    assert "must-not-be-logged" not in caplog.text


async def test_invalid_workflow_schema_logs_each_validation_path_and_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    invalid = workflow()
    invalid["nodes"][0]["config"].pop("command")
    loader = WorkflowSnapshotLoader(cast(GitManager, StubGit(dump_definition_yaml(invalid))))
    caplog.set_level(logging.WARNING, logger="backend.engine.snapshot")

    with pytest.raises(BundleResolutionError, match="Workflow 'root' is invalid"):
        await loader.load(
            tmp_path,
            "b" * 40,
            "root",
            max_timeout=14400,
            max_review_iterations=10,
            max_subworkflow_depth=8,
        )

    assert "Workflow schema parsing failed" in caplog.text
    assert "workflows.root.nodes.0" in caplog.text
    assert "[SCHEMA_ERROR]" in caplog.text
    assert "Field required" in caplog.text
