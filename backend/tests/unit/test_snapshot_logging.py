from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast

import pytest

from backend.engine.snapshot import BundleResolutionError, WorkflowSnapshotLoader
from backend.integrations.git_manager import GitManager
from backend.tests.fixtures.workflows import workflow


class StubGit:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def show_file(self, *_args: object) -> str:
        return self.raw


async def test_invalid_workflow_json_logs_location_and_reason_without_contents(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    raw = '{"id": "root", "token": "must-not-be-logged",}'
    with pytest.raises(json.JSONDecodeError) as parse_error:
        json.loads(raw)
    expected = parse_error.value
    loader = WorkflowSnapshotLoader(cast(GitManager, StubGit(raw)))
    caplog.set_level(logging.WARNING, logger="backend.engine.snapshot")

    with pytest.raises(
        BundleResolutionError,
        match=rf"line {expected.lineno}, column {expected.colno}",
    ):
        await loader.load(
            tmp_path,
            "a" * 40,
            "root",
            max_timeout=14400,
            max_review_iterations=10,
            max_subworkflow_depth=8,
        )

    assert "Workflow JSON parsing failed" in caplog.text
    assert "workflow=root" in caplog.text
    assert "file=.workflowEngine/root.json" in caplog.text
    assert f"line={expected.lineno}, column={expected.colno}" in caplog.text
    assert expected.msg in caplog.text
    assert "must-not-be-logged" not in caplog.text


async def test_invalid_workflow_schema_logs_each_validation_path_and_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    invalid = workflow()
    invalid["nodes"][0]["config"].pop("command")
    loader = WorkflowSnapshotLoader(cast(GitManager, StubGit(json.dumps(invalid))))
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
