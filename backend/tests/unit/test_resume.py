from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    ExecutionWave,
    GateInstance,
    NodeAttempt,
    NodeExecution,
    Project,
    RunLog,
    RunReport,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import AttemptStatus, NodeStatus, RunStatus, WaveStatus
from backend.engine.resume import mark_run_interrupted, prepare_resume
from backend.engine.task_registry import TaskRegistry
from backend.integrations.git_manager import GitManager


class RecordingGit:
    def __init__(self) -> None:
        self.resets: list[tuple[Path, str]] = []

    async def reset_wave(self, worktree: Path, sha: str) -> None:
        self.resets.append((worktree, sha))


async def _run(session: AsyncSession, tmp_path: Path, status: RunStatus) -> WorkflowRun:
    user = User(email=f"{uuid.uuid4()}@example.com", display_name="Runner")
    session.add(user)
    await session.flush()
    project = Project(
        name="Resume project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id=str(uuid.uuid4()),
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "repository"),
        default_branch="main",
        added_by=user.id,
    )
    session.add(project)
    await session.flush()
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    run = WorkflowRun(
        root_workflow_id="root",
        project_id=project.id,
        triggered_by=user.id,
        status=status,
        base_ref="main",
        base_commit_sha="a" * 40,
        workflow_definition_commit_sha="a" * 40,
        workflow_bundle_snapshot={},
        public_context={},
        worktree_path=str(worktree),
        current_head_sha="b" * 40,
        reviewer_provider="gitlab",
        reviewer_provider_user_id="7",
        reviewer_provider_username="runner",
    )
    session.add(run)
    await session.flush()
    return run


async def test_resume_resets_failed_wave_and_parent_control_chain(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.FAILED)
    root = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="RUNNING"
    )
    db_session.add(root)
    await db_session.flush()
    parent = NodeExecution(
        run_id=run.id,
        invocation_id=root.id,
        node_id="child",
        node_path="root/child",
        node_type="subworkflow",
        status=NodeStatus.FAILED,
    )
    db_session.add(parent)
    await db_session.flush()
    child = WorkflowInvocation(
        run_id=run.id,
        workflow_id="child",
        invocation_path="root/child",
        parent_invocation_id=root.id,
        parent_node_execution_id=parent.id,
        status="RUNNING",
    )
    db_session.add(child)
    await db_session.flush()
    wave = ExecutionWave(
        run_id=run.id,
        invocation_id=child.id,
        wave_index=1,
        status=WaveStatus.ROLLED_BACK,
        start_commit_sha="c" * 40,
    )
    db_session.add(wave)
    await db_session.flush()
    run.current_wave_id = wave.id
    failed = NodeExecution(
        run_id=run.id,
        invocation_id=child.id,
        wave_id=wave.id,
        node_id="task",
        node_path="root/child/task",
        node_type="bash",
        status=NodeStatus.FAILED,
        error_message="failed",
    )
    db_session.add(failed)
    await db_session.commit()
    git = RecordingGit()

    resumed = await prepare_resume(db_session, cast(GitManager, git), run.id)

    assert resumed.status == RunStatus.RESUMING
    assert failed.status == NodeStatus.PENDING
    assert parent.status == NodeStatus.PENDING
    assert child.status == "PENDING"
    assert root.status == "PENDING"
    assert git.resets == [(Path(run.worktree_path or ""), "c" * 40)]


async def test_cancelled_gate_resumes_without_scheduling_execution(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.CANCELLED)
    invocation = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="RUNNING"
    )
    db_session.add(invocation)
    await db_session.flush()
    node = NodeExecution(
        run_id=run.id,
        invocation_id=invocation.id,
        node_id="review",
        node_path="root/review",
        node_type="human_feedback",
        status=NodeStatus.AWAITING_FEEDBACK,
    )
    db_session.add(node)
    await db_session.flush()
    run.current_invocation_id = invocation.id
    run.current_node_execution_id = node.id
    db_session.add(
        GateInstance(
            run_id=run.id,
            invocation_id=invocation.id,
            node_execution_id=node.id,
            checkpoint_commit_sha="b" * 40,
            policy_key="review",
            policy_snapshot={},
            eligible_snapshot={},
            status="OPEN",
        )
    )
    db_session.add(RunReport(run_id=run.id, payload={"run": {"status": "CANCELLED"}}))
    await db_session.commit()
    git = RecordingGit()

    resumed = await prepare_resume(db_session, cast(GitManager, git), run.id)

    assert resumed.status == RunStatus.AWAITING_FEEDBACK
    assert resumed.cancel_requested_at is None
    assert git.resets == []
    assert await db_session.scalar(select(RunReport).where(RunReport.run_id == run.id)) is None


async def test_cancelled_process_wave_resumes_from_wave_checkpoint(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.CANCELLED)
    invocation = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="RUNNING"
    )
    db_session.add(invocation)
    await db_session.flush()
    wave = ExecutionWave(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_index=1,
        status=WaveStatus.CANCELLED,
        start_commit_sha="c" * 40,
    )
    db_session.add(wave)
    await db_session.flush()
    run.current_wave_id = wave.id
    node = NodeExecution(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_id=wave.id,
        node_id="task",
        node_path="root/task",
        node_type="prompt",
        status=NodeStatus.CANCELLED,
    )
    db_session.add(node)
    await db_session.commit()
    git = RecordingGit()

    resumed = await prepare_resume(db_session, cast(GitManager, git), run.id)

    assert resumed.status == RunStatus.RESUMING
    assert node.status == NodeStatus.PENDING
    assert invocation.status == "PENDING"
    assert git.resets == [(Path(run.worktree_path or ""), "c" * 40)]


async def test_task_registry_can_wait_for_failed_task_before_rescheduling() -> None:
    registry = TaskRegistry(1)
    run_id = uuid.uuid4()
    started = asyncio.Event()
    release = asyncio.Event()
    replacement_ran = asyncio.Event()

    async def finishing_task() -> None:
        started.set()
        await release.wait()

    async def replacement() -> None:
        replacement_ran.set()

    assert await registry.schedule(run_id, finishing_task) is True
    await started.wait()

    async def reschedule() -> None:
        await registry.wait(run_id)
        assert await registry.schedule(run_id, replacement) is True

    pending = asyncio.create_task(reschedule())
    await asyncio.sleep(0)
    assert not pending.done()
    release.set()
    await pending
    await registry.wait(run_id)
    assert replacement_ran.is_set()


async def test_worker_crash_marks_active_state_interrupted(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.RUNNING)
    run.pending_operation = "FEEDBACK_PUBLICATION"
    invocation = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="RUNNING"
    )
    db_session.add(invocation)
    await db_session.flush()
    wave = ExecutionWave(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_index=1,
        status=WaveStatus.RUNNING,
        start_commit_sha="b" * 40,
    )
    db_session.add(wave)
    await db_session.flush()
    node = NodeExecution(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_id=wave.id,
        node_id="task",
        node_path="root/task",
        node_type="bash",
        status=NodeStatus.RUNNING,
    )
    db_session.add(node)
    await db_session.flush()
    attempt = NodeAttempt(
        node_execution_id=node.id,
        attempt_number=1,
        status=AttemptStatus.RUNNING,
    )
    db_session.add(attempt)
    await db_session.commit()

    changed = await mark_run_interrupted(
        db_session,
        run.id,
        error_type="ENGINE_CRASH",
        error_message="Workflow worker stopped unexpectedly (RuntimeError)",
    )

    assert changed is True
    assert run.status == RunStatus.INTERRUPTED
    assert run.pending_operation == "FEEDBACK_PUBLICATION"
    assert wave.status == WaveStatus.INTERRUPTED
    assert node.status == NodeStatus.INTERRUPTED
    assert attempt.status == AttemptStatus.INTERRUPTED
    event = await db_session.scalar(select(RunLog).where(RunLog.run_id == run.id))
    assert event is not None
    assert event.event_type == "RUN_INTERRUPTED"


async def test_pending_publication_resumes_without_a_failed_wave(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.INTERRUPTED)
    run.pending_operation = "FINAL_PUBLICATION"
    await db_session.commit()
    git = RecordingGit()

    resumed = await prepare_resume(db_session, cast(GitManager, git), run.id)

    assert resumed.status == RunStatus.RESUMING
    assert resumed.pending_operation == "FINAL_PUBLICATION"
    assert git.resets == [(Path(run.worktree_path or ""), "b" * 40)]


async def test_interrupted_control_node_does_not_replay_historical_failed_wave(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    run = await _run(db_session, tmp_path, RunStatus.INTERRUPTED)
    invocation = WorkflowInvocation(
        run_id=run.id, workflow_id="root", invocation_path="root", status="RUNNING"
    )
    db_session.add(invocation)
    await db_session.flush()
    historical = ExecutionWave(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_index=1,
        status=WaveStatus.ROLLED_BACK,
        start_commit_sha="c" * 40,
    )
    current = ExecutionWave(
        run_id=run.id,
        invocation_id=invocation.id,
        wave_index=2,
        status=WaveStatus.SUCCESS,
        start_commit_sha="d" * 40,
        end_commit_sha="b" * 40,
    )
    db_session.add_all([historical, current])
    await db_session.flush()
    run.current_wave_id = current.id
    control = NodeExecution(
        run_id=run.id,
        invocation_id=invocation.id,
        node_id="child",
        node_path="root/child",
        node_type="subworkflow",
        status=NodeStatus.INTERRUPTED,
    )
    db_session.add(control)
    await db_session.commit()
    git = RecordingGit()

    resumed = await prepare_resume(db_session, cast(GitManager, git), run.id)

    assert resumed.status == RunStatus.RESUMING
    assert control.status == NodeStatus.PENDING
    assert historical.status == WaveStatus.ROLLED_BACK
    assert git.resets == [(Path(run.worktree_path or ""), "b" * 40)]
