from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    EdgeEvaluation,
    ExecutionWave,
    NodeAttempt,
    NodeExecution,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import AttemptStatus, NodeStatus, RunStatus, WaveStatus
from backend.engine.conditions import evaluate_condition
from backend.engine.context import expand_public_variables, output_variables
from backend.engine.nodes.process_nodes import NodeExecutionRequest, ProcessNodeExecutor
from backend.engine.pi.command import resolve_pi_settings
from backend.engine.process_runner import ProcessResult
from backend.integrations.git_manager import GitManager
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import BashNode, PromptNode, ScriptNode, WorkflowDefinition

logger = logging.getLogger(__name__)

ProcessWorkflowNode = BashNode | ScriptNode | PromptNode
CredentialLoader = Callable[[uuid.UUID], Awaitable[dict[str, str]]]


class WaveExecutionError(RuntimeError):
    def __init__(self, wave_id: uuid.UUID, message: str) -> None:
        super().__init__(message)
        self.wave_id = wave_id


class NodeProcessFailure(RuntimeError):
    def __init__(self, node: ProcessWorkflowNode, result: ProcessResult) -> None:
        super().__init__(f"Node '{node.id}' exited with code {result.exit_code}")
        self.node = node
        self.result = result


class WaveExecutor:
    def __init__(
        self,
        session: AsyncSession,
        git: GitManager,
        node_executor: ProcessNodeExecutor,
        credential_loader: CredentialLoader,
    ) -> None:
        self.session = session
        self.git = git
        self.node_executor = node_executor
        self.credential_loader = credential_loader

    async def execute(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        nodes: list[ProcessWorkflowNode],
        project_pi: PiSettings | None = None,
    ) -> ExecutionWave:
        if not run.worktree_path or not run.run_data_path:
            raise WaveExecutionError(uuid.uuid4(), "Run filesystem paths are not configured")
        worktree = Path(run.worktree_path)
        run_data = Path(run.run_data_path)
        await self.git.ensure_clean(worktree)
        start_sha = await self.git.head_sha(worktree)
        wave_index = (
            await self.session.scalar(
                select(func.coalesce(func.max(ExecutionWave.wave_index), 0)).where(
                    ExecutionWave.invocation_id == invocation.id
                )
            )
            or 0
        ) + 1
        wave = ExecutionWave(
            run_id=run.id,
            invocation_id=invocation.id,
            wave_index=wave_index,
            status=WaveStatus.RUNNING,
            start_commit_sha=start_sha,
            started_at=datetime.now(UTC),
        )
        self.session.add(wave)
        await self.session.flush()
        executions: dict[str, NodeExecution] = {}
        attempts: dict[str, NodeAttempt] = {}
        for node in nodes:
            execution = await self.session.scalar(
                select(NodeExecution).where(
                    NodeExecution.invocation_id == invocation.id,
                    NodeExecution.node_id == node.id,
                )
            )
            if execution is None:
                execution = NodeExecution(
                    run_id=run.id,
                    invocation_id=invocation.id,
                    node_id=node.id,
                    node_path=f"{invocation.invocation_path}/{node.id}",
                    node_type=node.type,
                    status=NodeStatus.PENDING,
                )
                self.session.add(execution)
                await self.session.flush()
            execution.wave_id = wave.id
            execution.current_attempt += 1
            execution.status = NodeStatus.RUNNING
            execution.started_at = execution.started_at or datetime.now(UTC)
            execution.finished_at = None
            attempt = NodeAttempt(
                node_execution_id=execution.id,
                attempt_number=execution.current_attempt,
                status=AttemptStatus.RUNNING,
            )
            self.session.add(attempt)
            executions[node.id] = execution
            attempts[node.id] = attempt
        run.current_invocation_id = invocation.id
        run.current_wave_id = wave.id
        await self.session.commit()
        logger.info(
            "Execution wave started "
            "(run=%s, invocation=%s, wave=%s, index=%s, nodes=%s, commit=%s)",
            run.id,
            invocation.id,
            wave.id,
            wave.wave_index,
            [node.id for node in nodes],
            start_sha[:12],
        )

        async def run_node(node: ProcessWorkflowNode) -> tuple[ProcessWorkflowNode, ProcessResult]:
            execution = executions[node.id]
            attempt = attempts[node.id]
            logger.info(
                "Node attempt started "
                "(run=%s, invocation=%s, wave=%s, node=%s, type=%s, attempt=%s)",
                run.id,
                invocation.id,
                wave.id,
                node.id,
                node.type,
                attempt.attempt_number,
            )
            secrets = await self.credential_loader(run.triggered_by)
            node_pi = (
                PiSettings(
                    provider=node.config.provider,
                    model=node.config.model,
                    skill=node.config.skill,
                )
                if isinstance(node, PromptNode)
                else PiSettings()
            )
            result = await self.node_executor.execute(
                node,
                NodeExecutionRequest(
                    run_id=run.id,
                    attempt_id=attempt.id,
                    node_path=execution.node_path,
                    worktree=worktree,
                    output_directory=(
                        run_data
                        / "outputs"
                        / _safe_node_path(execution.node_path)
                        / f"attempt-{attempt.attempt_number}"
                    ),
                    public_context=dict(run.public_context),
                    secrets=secrets,
                    default_timeout=workflow.settings.timeout_per_node_seconds,
                    max_preview_bytes=workflow.settings.max_output_variable_bytes,
                    pi=resolve_pi_settings(
                        project_pi or PiSettings(), workflow.settings.pi, node_pi
                    ),
                ),
            )
            allow_failure = bool(getattr(node.config, "allow_failure", False))
            if (result.exit_code != 0 or result.timed_out) and not allow_failure:
                raise NodeProcessFailure(node, result)
            return node, result

        tasks = {
            node.id: asyncio.create_task(run_node(node), name=f"wave-{wave.id}-{node.id}")
            for node in nodes
        }
        done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_EXCEPTION)
        failure = next(
            (task.exception() for task in done if not task.cancelled() and task.exception()),
            None,
        )
        if failure:
            for task in pending:
                task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)

        results: dict[str, ProcessResult] = {}
        failed_node_id: str | None = None
        for node_id, task in tasks.items():
            attempt = attempts[node_id]
            execution = executions[node_id]
            attempt.finished_at = datetime.now(UTC)
            execution.finished_at = attempt.finished_at
            if task.cancelled():
                attempt.status = AttemptStatus.CANCELLED
                execution.status = NodeStatus.CANCELLED
                logger.warning(
                    "Node attempt cancelled after another node failed "
                    "(run=%s, wave=%s, node=%s, attempt=%s)",
                    run.id,
                    wave.id,
                    node_id,
                    attempt.attempt_number,
                )
                continue
            exception = task.exception()
            if isinstance(exception, NodeProcessFailure):
                failed_node_id = node_id
                result = exception.result
                results[node_id] = result
                attempt.status = AttemptStatus.FAILED
                attempt.error_type = "NODE_TIMEOUT" if result.timed_out else "NODE_FAILURE"
                attempt.error_message = str(exception)
                execution.status = NodeStatus.FAILED
                execution.error_message = str(exception)
                logger.error(
                    "Node attempt failed "
                    "(run=%s, invocation=%s, invocation_path=%s, workflow=%s, wave=%s, "
                    "node=%s, attempt=%s, exit_code=%s, timed_out=%s): %s%s",
                    run.id,
                    invocation.id,
                    invocation.invocation_path,
                    workflow.id,
                    wave.id,
                    node_id,
                    attempt.attempt_number,
                    result.exit_code,
                    result.timed_out,
                    exception,
                    _failure_diagnostics(result),
                )
            elif exception is not None:
                failed_node_id = node_id
                attempt.status = AttemptStatus.FAILED
                attempt.error_type = "INTERNAL_ERROR"
                attempt.error_message = str(exception)
                execution.status = NodeStatus.FAILED
                execution.error_message = str(exception)
                logger.error(
                    "Node attempt crashed "
                    "(run=%s, wave=%s, node=%s, attempt=%s): %s",
                    run.id,
                    wave.id,
                    node_id,
                    attempt.attempt_number,
                    exception,
                    exc_info=(type(exception), exception, exception.__traceback__),
                )
            else:
                _, result = task.result()
                results[node_id] = result
                attempt.status = AttemptStatus.SUCCESS
                execution.status = NodeStatus.SUCCESS
                logger.info(
                    "Node attempt completed "
                    "(run=%s, wave=%s, node=%s, attempt=%s, exit_code=%s)",
                    run.id,
                    wave.id,
                    node_id,
                    attempt.attempt_number,
                    result.exit_code,
                )
            if node_id in results:
                result = results[node_id]
                attempt.exit_code = result.exit_code
                execution.exit_code = result.exit_code
                execution.stdout_path = str(result.stdout_path.relative_to(run_data))
                execution.stderr_path = str(result.stderr_path.relative_to(run_data))

        if failed_node_id:
            wave.status = WaveStatus.FAILED
            wave.error_message = executions[failed_node_id].error_message
            wave.finished_at = datetime.now(UTC)
            await self.session.commit()
            try:
                await self.git.reset_wave(worktree, start_sha)
            except Exception as exc:
                run.status = RunStatus.FAILED
                run.error_type = "WORKTREE_RECOVERY_FAILED"
                run.error_message = str(exc)
                await self.session.commit()
                logger.exception(
                    "Wave rollback failed (run=%s, wave=%s, commit=%s): %s",
                    run.id,
                    wave.id,
                    start_sha[:12],
                    exc,
                )
                raise WaveExecutionError(wave.id, str(exc)) from exc
            wave.status = WaveStatus.ROLLED_BACK
            run.status = RunStatus.FAILED
            run.error_type = "NODE_FAILURE"
            run.error_message = wave.error_message
            run.current_node_execution_id = executions[failed_node_id].id
            await self.session.commit()
            logger.error(
                "Execution wave rolled back after node failure "
                "(run=%s, invocation=%s, wave=%s, failed_node=%s, commit=%s)",
                run.id,
                invocation.id,
                wave.id,
                failed_node_id,
                start_sha[:12],
            )
            raise WaveExecutionError(wave.id, wave.error_message or "Wave failed")

        for node in nodes:
            result = results[node.id]
            execution = executions[node.id]
            relative_stdout = str(result.stdout_path.relative_to(run_data))
            relative_stderr = str(result.stderr_path.relative_to(run_data))
            values = output_variables(
                node.id,
                result.exit_code,
                result.stdout_preview,
                result.stderr_preview,
                relative_stdout,
                relative_stderr,
            )
            execution.output_values = values
            run.public_context = {**run.public_context, **values}
            for edge in workflow.edges:
                if edge.source != node.id:
                    continue
                condition_result, evaluated_value = evaluate_condition(
                    edge.condition,
                    exit_code=result.exit_code,
                    stdout=result.stdout_preview,
                    stderr=result.stderr_preview,
                    public_context=run.public_context,
                    worktree=worktree,
                )
                self.session.add(
                    EdgeEvaluation(
                        run_id=run.id,
                        invocation_id=invocation.id,
                        source_node_execution_id=execution.id,
                        edge_id=edge.id,
                        target_node_id=edge.target,
                        condition_result=condition_result,
                        evaluated_value=evaluated_value,
                    )
                )

        commit_message = expand_public_variables(
            workflow.settings.wave_commit_message_template,
            {
                **run.public_context,
                "WORKFLOW_ID": workflow.id,
                "WAVE_INDEX": wave.wave_index,
            },
        )
        end_sha = (
            await self.git.checkpoint(worktree, commit_message)
            if workflow.settings.auto_commit_after_wave
            else await self.git.head_sha(worktree)
        )
        wave.end_commit_sha = end_sha
        wave.status = WaveStatus.SUCCESS
        wave.finished_at = datetime.now(UTC)
        run.current_head_sha = end_sha
        await self.session.commit()
        logger.info(
            "Execution wave completed "
            "(run=%s, invocation=%s, wave=%s, nodes=%s, commit=%s)",
            run.id,
            invocation.id,
            wave.id,
            [node.id for node in nodes],
            end_sha[:12],
        )
        return wave


def _safe_node_path(node_path: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in node_path
    )


def _failure_diagnostics(result: ProcessResult) -> str:
    sections: list[str] = []
    for stream, content, truncated in (
        ("stderr", result.stderr_tail, result.stderr_tail_truncated),
        ("stdout", result.stdout_tail, result.stdout_tail_truncated),
    ):
        diagnostic = content.strip()
        if not diagnostic:
            continue
        prefix = "[earlier output omitted]\n" if truncated else ""
        sections.append(f"{stream}:\n{prefix}{diagnostic}")
    return "\n" + "\n".join(sections) if sections else "\nNo stdout or stderr was captured."
