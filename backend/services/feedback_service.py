from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    EdgeEvaluation,
    FeedbackEvent,
    NodeExecution,
    Project,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import NodeStatus, RunStatus
from backend.engine.conditions import evaluate_condition
from backend.integrations.gitlab_client import GitLabClient
from backend.schemas.workflow import ReviewLoopNode, WorkflowBundle, WorkflowDefinition
from backend.services.crypto import SecretCipher

ScheduleContinuation = Callable[[uuid.UUID], Awaitable[None]]


class FeedbackError(RuntimeError):
    pass


class FeedbackService:
    def __init__(
        self,
        session: AsyncSession,
        cipher: SecretCipher,
        gitlab: GitLabClient,
        schedule_continuation: ScheduleContinuation,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.gitlab = gitlab
        self.schedule_continuation = schedule_continuation

    async def accept(
        self,
        run_id: uuid.UUID,
        *,
        event_type: str,
        source: str,
        author_gitlab_user_id: int,
        author_username: str,
        message: str = "",
        author_user_id: uuid.UUID | None = None,
        gitlab_note_id: int | None = None,
    ) -> FeedbackEvent:
        run = await self.session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        if run is None:
            raise LookupError("Run does not exist")
        if run.status != RunStatus.AWAITING_FEEDBACK:
            raise FeedbackError("Run is not awaiting feedback")
        if author_gitlab_user_id != run.reviewer_gitlab_user_id:
            raise PermissionError("Only the triggering user may continue this run")
        if event_type not in {"approval", "comment"}:
            raise FeedbackError("Unsupported feedback event type")
        clean_message = message.strip()
        if event_type == "comment" and not clean_message:
            raise FeedbackError("Feedback message must not be empty")
        if not run.current_node_execution_id or not run.current_invocation_id:
            raise FeedbackError("Run has no waiting checkpoint")
        execution = await self.session.get(NodeExecution, run.current_node_execution_id)
        invocation = await self.session.get(WorkflowInvocation, run.current_invocation_id)
        project = await self.session.get(Project, run.project_id)
        if execution is None or invocation is None or project is None:
            raise FeedbackError("Waiting checkpoint state is incomplete")
        bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
        workflow = bundle.workflows[invocation.workflow_id]
        node = next(item for item in workflow.nodes if item.id == execution.node_id)
        iteration = int(execution.output_values.get("review_iteration", 1))

        run.status = RunStatus.RUNNING
        run.status_version += 1
        await self.session.commit()
        token = self.cipher.decrypt(project.encrypted_access_token)
        try:
            if event_type == "approval":
                if not run.mr_iid:
                    raise FeedbackError("Run has no merge request to reset")
                await self.gitlab.wait_for_approval_sync(
                    project.gitlab_project_id, run.mr_iid, token
                )
                await self.gitlab.reset_approvals(project.gitlab_project_id, run.mr_iid, token)
        except Exception:
            run.status = RunStatus.AWAITING_FEEDBACK
            run.status_version += 1
            await self.session.commit()
            token = ""
            raise

        event = FeedbackEvent(
            run_id=run.id,
            node_execution_id=execution.id,
            iteration=iteration,
            event_type=event_type,
            source=source,
            author_user_id=author_user_id,
            author_gitlab_user_id=author_gitlab_user_id,
            author_username=author_username,
            message=clean_message,
            gitlab_note_id=gitlab_note_id,
        )
        self.session.add(event)
        run.public_context = {
            **run.public_context,
            "FEEDBACK": clean_message,
            "FEEDBACK_TYPE": event_type,
            "FEEDBACK_AUTHOR": author_username,
        }
        if isinstance(node, ReviewLoopNode) and event_type == "comment":
            next_iteration = iteration + 1
            maximum = node.config.max_iterations or workflow.settings.max_review_iterations
            if next_iteration > maximum:
                execution.status = NodeStatus.FAILED
                execution.error_message = "Maximum review iterations reached"
                run.status = RunStatus.FAILED
                run.error_type = "MAX_REVIEW_ITERATIONS_REACHED"
                run.error_message = execution.error_message
                run.finished_at = datetime.now(UTC)
            else:
                execution.status = NodeStatus.PENDING
                execution.output_values = {
                    **execution.output_values,
                    "review_iteration": next_iteration,
                    "max_iterations": maximum,
                }
                execution.finished_at = None
                run.public_context = {
                    **run.public_context,
                    "REVIEW_ITERATION": next_iteration,
                }
        else:
            execution.status = NodeStatus.SUCCESS
            execution.finished_at = datetime.now(UTC)
            await self._persist_edges(run, invocation, execution, workflow)
        run.current_node_execution_id = None
        run.current_wave_id = None
        await self.session.commit()

        try:
            if source == "frontend" and run.mr_iid:
                if event_type == "approval":
                    note = (
                        f"Approved via Workflow Engine by {author_username}.\n"
                        "The intermediate approval was reset; a fresh GitLab approval is "
                        "required for final merge."
                    )
                else:
                    note = (
                        f"@yoke {clean_message}\n\n"
                        f"Submitted via Workflow Engine by {author_username}."
                    )
                note_result = await self.gitlab.post_note(
                    project.gitlab_project_id, run.mr_iid, token, note
                )
                if note_result.get("id"):
                    event.gitlab_note_id = int(note_result["id"])
                    await self.session.commit()
        finally:
            token = ""
        if run.status == RunStatus.RUNNING:
            await self.schedule_continuation(run.id)
        return event

    async def _persist_edges(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        execution: NodeExecution,
        workflow: WorkflowDefinition,
    ) -> None:
        assert run.worktree_path
        for edge in workflow.edges:
            if edge.source != execution.node_id:
                continue
            result, value = evaluate_condition(
                edge.condition,
                exit_code=0,
                stdout="",
                stderr="",
                public_context=run.public_context,
                worktree=Path(run.worktree_path),
            )
            self.session.add(
                EdgeEvaluation(
                    run_id=run.id,
                    invocation_id=invocation.id,
                    source_node_execution_id=execution.id,
                    edge_id=edge.id,
                    target_node_id=edge.target,
                    condition_result=result,
                    evaluated_value=value,
                )
            )
