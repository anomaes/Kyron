from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.engine.snapshot import WorkflowSnapshotLoader
from backend.integrations.git_manager import GitManager
from backend.schemas.pi import PiSettings
from backend.tests.fixtures.workflows import workflow


async def git(*args: str, cwd: Path) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip()


async def test_bundle_is_loaded_transitively_from_one_exact_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    definitions = repository / ".workflowEngine"
    definitions.mkdir(parents=True)
    await git("init", "-b", "main", cwd=repository)
    await git("config", "user.email", "test@example.com", cwd=repository)
    await git("config", "user.name", "Test", cwd=repository)

    root = workflow(
        nodes=[
            {
                "id": "child",
                "type": "subworkflow",
                "label": "child",
                "config": {"workflow_id": "child"},
            }
        ]
    )
    (definitions / "root.json").write_text(json.dumps(root))
    (definitions / "child.json").write_text(
        json.dumps(workflow("child", tags=["implementation"]))
    )
    await git("add", ".workflowEngine", cwd=repository)
    await git("commit", "-m", "workflows", cwd=repository)
    sha = await git("rev-parse", "HEAD", cwd=repository)

    loader = WorkflowSnapshotLoader(GitManager(tmp_path / "unused-clones"))
    bundle = await loader.load(
        repository,
        sha,
        "root",
        max_timeout=14400,
        max_review_iterations=10,
        max_subworkflow_depth=8,
        project_pi=PiSettings(model="project-model"),
    )
    assert bundle.base_commit_sha == sha
    assert set(bundle.workflows) == {"root", "child"}
    assert bundle.reference_graph == {"root": ["child"], "child": []}
    assert bundle.workflows["child"].tags == ["implementation"]
    assert bundle.project_pi.model == "project-model"
