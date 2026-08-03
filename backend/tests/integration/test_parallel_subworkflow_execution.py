from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.database import Base
from backend.db.models import (
    InvocationWorkspace,
    Project,
    SubworkflowBatch,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import RunStatus
from backend.engine.coordinator import RunCoordinator
from backend.engine.nodes.process_nodes import ProcessNodeExecutor
from backend.engine.process_registry import ProcessRegistry
from backend.engine.process_runner import ProcessRunner
from backend.engine.waves import WaveExecutor
from backend.integrations.code_host import CodeHostClient
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition
from backend.services.crypto import SecretCipher
from backend.services.log_broadcaster import LogBroadcaster
from backend.tests.fixtures.workflows import workflow


async def _git(*args: str, cwd: Path) -> str:
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


def _child(workflow_id: str, filename: str, result: str) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        workflow(
            workflow_id,
            outputs={
                "RESULT": {
                    "type": "string",
                    "source": "${NODE_write_STDOUT}",
                }
            },
            nodes=[
                {
                    "id": "write",
                    "type": "bash",
                    "label": "write",
                    "config": {
                        "command": (
                            f"printf '{workflow_id}' > {filename}; "
                            f"printf '{result}'"
                        ),
                        "shell": "/bin/bash",
                    },
                }
            ],
        )
    )


async def test_ready_parallel_children_use_distinct_worktrees_and_integrate(
    tmp_path: Path,
) -> None:
    clone_root = tmp_path / "repos"
    repository = clone_root / "project"
    worktree_root = tmp_path / "worktrees"
    run_data_root = tmp_path / "run-data"
    repository.mkdir(parents=True)
    await _git("init", "-b", "main", cwd=repository)
    await _git("config", "user.email", "test@example.com", cwd=repository)
    await _git("config", "user.name", "Test", cwd=repository)
    (repository / "base.txt").write_text("base\n")
    await _git("add", "base.txt", cwd=repository)
    await _git("commit", "-m", "base", cwd=repository)
    base_sha = await _git("rev-parse", "HEAD", cwd=repository)

    root = WorkflowDefinition.model_validate(
        workflow(
            outputs={
                "A": {"type": "string", "source": "${A_RESULT}"},
                "B": {"type": "string", "source": "${B_RESULT}"},
            },
            nodes=[
                {
                    "id": "a",
                    "type": "subworkflow",
                    "label": "a",
                    "config": {
                        "workflow_id": "child_a",
                        "execution_mode": "isolated_parallel",
                        "output_mapping": {"RESULT": "A_RESULT"},
                    },
                },
                {
                    "id": "b",
                    "type": "subworkflow",
                    "label": "b",
                    "config": {
                        "workflow_id": "child_b",
                        "execution_mode": "isolated_parallel",
                        "output_mapping": {"RESULT": "B_RESULT"},
                    },
                },
            ],
        )
    )
    child_a = _child("child_a", "a.txt", "result-a")
    child_b = _child("child_b", "b.txt", "result-b")
    bundle = WorkflowBundle(
        base_commit_sha=base_sha,
        root_workflow_id="root",
        workflows={"root": root, "child_a": child_a, "child_b": child_b},
        reference_graph={"root": ["child_a", "child_b"], "child_a": [], "child_b": []},
    )

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'parallel.db'}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    manager = GitManager(clone_root, worktree_root, run_data_root)
    async with factory() as session:
        user = User(email="runner@example.com", display_name="Runner")
        session.add(user)
        await session.flush()
        project = Project(
            name="Project",
            git_url="https://example.invalid/project.git",
            provider="github",
            provider_project_id="1",
            provider_project_path="example/project",
            encrypted_access_token=b"unused",
            local_path=str(repository),
            default_branch="main",
            added_by=user.id,
        )
        session.add(project)
        await session.flush()
        run = WorkflowRun(
            root_workflow_id="root",
            project_id=project.id,
            triggered_by=user.id,
            status=RunStatus.QUEUED,
            base_ref="main",
            base_commit_sha=base_sha,
            workflow_definition_commit_sha=base_sha,
            workflow_bundle_snapshot=bundle.model_dump(mode="json"),
            local_definition_test=True,
            public_context={},
            reviewer_provider="github",
            reviewer_provider_user_id="7",
            reviewer_provider_username="runner",
        )
        session.add(run)
        await session.commit()

        async def credentials(_: Any) -> dict[str, str]:
            return {}

        waves = WaveExecutor(
            session,
            manager,
            ProcessNodeExecutor(
                ProcessRunner(ProcessRegistry(), LogBroadcaster(), 0.1)
            ),
            credentials,
        )
        coordinator = RunCoordinator(
            session,
            manager,
            cast(CodeHostClient, object()),
            cast(SecretCipher, object()),
            waves,
        )
        await coordinator.execute_run(run.id)
        await session.refresh(run)

        assert run.status == RunStatus.COMPLETED
        assert run.worktree_path
        assert (Path(run.worktree_path) / "a.txt").read_text() == "child_a"
        assert (Path(run.worktree_path) / "b.txt").read_text() == "child_b"
        root_invocation = await session.scalar(
            select(WorkflowInvocation).where(
                WorkflowInvocation.run_id == run.id,
                WorkflowInvocation.invocation_path == "root",
            )
        )
        assert root_invocation is not None
        assert root_invocation.output_context == {"A": "result-a", "B": "result-b"}
        workspaces = list(
            await session.scalars(
                select(InvocationWorkspace).where(
                    InvocationWorkspace.run_id == run.id
                )
            )
        )
        assert sorted(item.mode for item in workspaces) == [
            "ISOLATED_PARALLEL",
            "ISOLATED_PARALLEL",
            "ROOT",
        ]
        assert len({item.worktree_path for item in workspaces}) == 3
        batch = await session.scalar(
            select(SubworkflowBatch).where(SubworkflowBatch.run_id == run.id)
        )
        assert batch is not None
        assert batch.status == "SUCCESS"

    await engine.dispose()
