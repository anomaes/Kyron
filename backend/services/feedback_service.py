from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AuthorizationAuditEvent,
    EdgeEvaluation,
    FeedbackEvent,
    GateDecision,
    GateInstance,
    InvocationWorkspace,
    NodeExecution,
    Project,
    RunChangeRequest,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import NodeStatus, RunStatus
from backend.engine.conditions import evaluate_condition
from backend.integrations.code_host import CodeHostClient, ProviderUser, repository_locator
from backend.schemas.workflow import (
    HumanFeedbackNode,
    ReviewLoopNode,
    WorkflowBundle,
    WorkflowDefinition,
)
from backend.services.approval_policy_service import actor_requirement_keys, approvals_satisfy
from backend.services.crypto import SecretCipher

ScheduleContinuation = Callable[[uuid.UUID], Awaitable[None]]

logger = logging.getLogger(__name__)


class FeedbackError(RuntimeError):
    pass


class FeedbackService:
    def __init__(
        self,
        session: AsyncSession,
        cipher: SecretCipher,
        code_host: CodeHostClient,
        schedule_continuation: ScheduleContinuation,
    ) -> None:
        self.session = session
        self.cipher = cipher
        self.code_host = code_host
        self.schedule_continuation = schedule_continuation

    async def accept(
        self,
        run_id: uuid.UUID,
        *,
        event_type: str,
        source: str,
        author_provider: str,
        author_provider_user_id: str,
        author_username: str,
        message: str = "",
        author_user_id: uuid.UUID | None = None,
        provider_comment_id: str | None = None,
        provider_review_id: str | None = None,
        gate_id: uuid.UUID | None = None,
        provider_head_sha: str | None = None,
    ) -> GateDecision:
        run = await self.session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        if run is None:
            raise LookupError("Run does not exist")
        if run.status not in {RunStatus.RUNNING, RunStatus.AWAITING_FEEDBACK}:
            raise FeedbackError("Run has no active feedback checkpoint")
        if author_provider != run.reviewer_provider:
            raise PermissionError("Sign in with the run's code-host provider")
        if source != "frontend" and source != run.reviewer_provider:
            raise PermissionError("Feedback provider does not match this run")
        if event_type not in {"approval", "comment"}:
            raise FeedbackError("Unsupported feedback event type")
        clean_message = message.strip()
        if event_type == "comment" and not clean_message:
            raise FeedbackError("Feedback message must not be empty")
        gate = await self._open_gate(run.id, gate_id)
        if (
            provider_head_sha is not None
            and provider_head_sha != gate.checkpoint_commit_sha
        ):
            raise FeedbackError("Approval or feedback refers to a stale checkpoint")
        execution = await self.session.get(NodeExecution, gate.node_execution_id)
        invocation = await self.session.get(WorkflowInvocation, gate.invocation_id)
        project = await self.session.get(Project, run.project_id)
        if execution is None or invocation is None or project is None:
            raise FeedbackError("Waiting checkpoint state is incomplete")
        bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
        workflow = bundle.workflows[invocation.workflow_id]
        node = next(item for item in workflow.nodes if item.id == execution.node_id)
        if isinstance(node, HumanFeedbackNode):
            if event_type == "approval" and not node.config.allow_approval:
                raise FeedbackError("This gate does not accept approvals")
            if event_type == "comment" and not node.config.allow_comment_feedback:
                raise FeedbackError("This gate does not accept revision feedback")
        iteration = gate.iteration
        requirement_keys = actor_requirement_keys(
            gate.eligible_snapshot, author_provider, author_provider_user_id
        )
        if not requirement_keys:
            raise PermissionError("You are not eligible to respond to this gate")
        if event_type == "comment" and not gate.policy_snapshot.get(
            "eligible_approvers_may_give_feedback", True
        ):
            raise PermissionError("This approval policy does not permit revision feedback")
        actor = _eligible_actor(gate.eligible_snapshot, author_provider, author_provider_user_id)
        if actor is None:
            raise PermissionError("You are not eligible to respond to this gate")
        actor_user_id = author_user_id or uuid.UUID(str(actor["user_id"]))
        existing_decisions = list(
            await self.session.scalars(
                select(GateDecision)
                .where(GateDecision.gate_instance_id == gate.id)
                .order_by(GateDecision.created_at)
            )
        )
        identity_key = f"{author_provider}:{author_provider_user_id}"
        if event_type == "approval" and any(
            item.event_type == "approval"
            and (
                f"{item.actor_snapshot.get('provider')}:"
                f"{item.actor_snapshot.get('provider_user_id')}"
            )
            == identity_key
            for item in existing_decisions
        ):
            raise FeedbackError("You have already approved this checkpoint")
        decision = GateDecision(
            gate_instance_id=gate.id,
            event_type=event_type,
            source=source,
            actor_user_id=actor_user_id,
            actor_snapshot={**actor, "display_name": author_username or actor.get("display_name")},
            requirement_keys=requirement_keys,
            message=clean_message,
            provider_event_id=provider_review_id or provider_comment_id,
        )
        self.session.add(decision)
        await self.session.flush()
        approvals = [
            {
                "provider_identity": (
                    f"{item.actor_snapshot.get('provider')}:"
                    f"{item.actor_snapshot.get('provider_user_id')}"
                ),
                "requirement_keys": item.requirement_keys,
            }
            for item in [*existing_decisions, decision]
            if item.event_type == "approval" and not item.superseded
        ]
        gate_satisfied = event_type == "approval" and approvals_satisfy(
            gate.policy_snapshot, gate.eligible_snapshot, approvals
        )

        change_request = (
            await self.session.get(RunChangeRequest, gate.change_request_id)
            if gate.change_request_id
            else None
        )
        provider_number = (
            change_request.provider_number
            if change_request is not None
            else run.change_request_number
        )
        needs_token = bool(
            provider_number
            and (gate_satisfied or (source == "frontend" and event_type == "comment"))
        )
        token = self.cipher.decrypt(project.encrypted_access_token) if needs_token else ""
        try:
            if gate_satisfied and provider_number:
                repository = repository_locator(
                    project.provider,
                    project.provider_project_id,
                    project.provider_project_path,
                )
                approval_decisions = [
                    item
                    for item in [*existing_decisions, decision]
                    if item.event_type == "approval"
                ]
                if project.provider == "gitlab":
                    latest = approval_decisions[-1]
                    await self.code_host.consume_approval(
                        repository,
                        provider_number,
                        token,
                        ProviderUser(
                            id=str(latest.actor_snapshot["provider_user_id"]),
                            username=str(latest.actor_snapshot["provider_username"]),
                        ),
                        latest.provider_event_id,
                    )
                else:
                    for approval in approval_decisions:
                        await self.code_host.consume_approval(
                            repository,
                            provider_number,
                            token,
                            ProviderUser(
                                id=str(approval.actor_snapshot["provider_user_id"]),
                                username=str(approval.actor_snapshot["provider_username"]),
                            ),
                            approval.provider_event_id,
                        )
        except Exception:
            await self.session.rollback()
            await self.session.refresh(run)
            token = ""
            raise

        event = FeedbackEvent(
            run_id=run.id,
            node_execution_id=execution.id,
            iteration=iteration,
            event_type=event_type,
            source=source,
            author_user_id=actor_user_id,
            author_provider=author_provider,
            author_provider_user_id=author_provider_user_id,
            author_username=author_username,
            message=clean_message,
            provider_comment_id=provider_comment_id,
        )
        self.session.add(event)
        self.session.add(
            AuthorizationAuditEvent(
                project_id=run.project_id,
                run_id=run.id,
                actor_user_id=actor_user_id,
                actor_snapshot=decision.actor_snapshot,
                action="GATE_APPROVED" if event_type == "approval" else "GATE_FEEDBACK_SUBMITTED",
                target_type="gate_instance",
                target_id=str(gate.id),
                details={
                    "checkpoint_commit_sha": gate.checkpoint_commit_sha,
                    "requirement_keys": requirement_keys,
                    "quorum_satisfied": gate_satisfied,
                },
            )
        )
        invocation.public_context = {
            **invocation.public_context,
            "FEEDBACK": clean_message,
            "FEEDBACK_TYPE": event_type,
            "FEEDBACK_AUTHOR": author_username,
        }
        if invocation.parent_invocation_id is None:
            run.public_context = dict(invocation.public_context)
        if event_type == "approval" and not gate_satisfied:
            await self.session.commit()
            return decision

        run.status = RunStatus.RUNNING
        run.status_version += 1
        gate.status = "APPROVED" if event_type == "approval" else "CHANGES_REQUESTED"
        gate.resolved_at = datetime.now(UTC)
        if event_type == "comment":
            await self.session.execute(
                update(GateDecision)
                .where(
                    GateDecision.gate_instance_id == gate.id,
                    GateDecision.event_type == "approval",
                )
                .values(superseded=True)
            )
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
                invocation.public_context = {
                    **invocation.public_context,
                    "REVIEW_ITERATION": next_iteration,
                }
                if invocation.parent_invocation_id is None:
                    run.public_context = dict(invocation.public_context)
        else:
            execution.status = NodeStatus.SUCCESS
            execution.finished_at = datetime.now(UTC)
            await self._persist_edges(run, invocation, execution, workflow)
        if run.current_node_execution_id == execution.id:
            run.current_node_execution_id = None
            run.current_wave_id = None
        await self.session.commit()

        try:
            if source == "frontend" and provider_number:
                if event_type == "approval":
                    note = (
                        f"Approved via Workflow Engine by {author_username}.\n"
                        "The intermediate approval was consumed; a fresh provider approval is "
                        "required for final merge."
                    )
                else:
                    note = (
                        f"@kyron {clean_message}\n\n"
                        f"Submitted via Workflow Engine by {author_username}."
                    )
                try:
                    note_result = await self.code_host.post_comment(
                        repository_locator(
                            project.provider,
                            project.provider_project_id,
                            project.provider_project_path,
                        ),
                        provider_number,
                        token,
                        note,
                    )
                except Exception:
                    logger.exception(
                        "Could not publish gate response to code host (run=%s, gate=%s)",
                        run.id,
                        gate.id,
                    )
                else:
                    event.provider_comment_id = note_result.id
                    decision.provider_event_id = decision.provider_event_id or note_result.id
                    await self.session.commit()
        finally:
            token = ""
        if run.status == RunStatus.RUNNING:
            await self.schedule_continuation(run.id)
        return decision

    async def override(
        self,
        run_id: uuid.UUID,
        *,
        reason: str,
        actor_user_id: uuid.UUID,
        actor_snapshot: dict[str, object],
        gate_id: uuid.UUID | None = None,
    ) -> GateDecision:
        run = await self.session.scalar(
            select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
        )
        if run is None or run.status not in {
            RunStatus.RUNNING,
            RunStatus.AWAITING_FEEDBACK,
        }:
            raise FeedbackError("Run has no active feedback checkpoint")
        gate = await self._open_gate(run.id, gate_id)
        execution = await self.session.get(NodeExecution, gate.node_execution_id)
        invocation = await self.session.get(WorkflowInvocation, gate.invocation_id)
        if execution is None or invocation is None:
            raise FeedbackError("Waiting checkpoint state is incomplete")
        decision = GateDecision(
            gate_instance_id=gate.id,
            event_type="override",
            source="admin",
            actor_user_id=actor_user_id,
            actor_snapshot=actor_snapshot,
            requirement_keys=[],
            message=reason.strip(),
        )
        self.session.add(decision)
        gate.status = "OVERRIDDEN"
        gate.resolved_at = datetime.now(UTC)
        bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
        workflow = bundle.workflows[invocation.workflow_id]
        execution.status = NodeStatus.SUCCESS
        execution.finished_at = datetime.now(UTC)
        await self._persist_edges(run, invocation, execution, workflow)
        run.status = RunStatus.RUNNING
        run.status_version += 1
        if run.current_node_execution_id == execution.id:
            run.current_node_execution_id = None
            run.current_wave_id = None
        self.session.add(
            AuthorizationAuditEvent(
                project_id=run.project_id,
                run_id=run.id,
                actor_user_id=actor_user_id,
                actor_snapshot=actor_snapshot,
                action="GATE_OVERRIDDEN",
                target_type="gate_instance",
                target_id=str(gate.id),
                details={
                    "reason": reason.strip(),
                    "checkpoint_commit_sha": gate.checkpoint_commit_sha,
                },
            )
        )
        await self.session.commit()
        await self.schedule_continuation(run.id)
        return decision

    async def _open_gate(
        self, run_id: uuid.UUID, gate_id: uuid.UUID | None
    ) -> GateInstance:
        query = (
            select(GateInstance)
            .where(GateInstance.run_id == run_id, GateInstance.status == "OPEN")
            .with_for_update()
        )
        if gate_id is not None:
            gate = await self.session.scalar(query.where(GateInstance.id == gate_id))
            if gate is None:
                raise FeedbackError("Gate is not open")
            return gate
        gates = list(await self.session.scalars(query))
        if not gates:
            raise FeedbackError("Run has no open gate instance")
        if len(gates) > 1:
            raise FeedbackError("Run has multiple open gates; address a gate explicitly")
        return gates[0]

    async def _persist_edges(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        execution: NodeExecution,
        workflow: WorkflowDefinition,
    ) -> None:
        workspace = (
            await self.session.get(InvocationWorkspace, invocation.workspace_id)
            if invocation.workspace_id
            else None
        )
        worktree_path = workspace.worktree_path if workspace else run.worktree_path
        if not worktree_path:
            raise FeedbackError("Feedback invocation has no workspace")
        for edge in workflow.edges:
            if edge.source != execution.node_id:
                continue
            result, value = evaluate_condition(
                edge.condition,
                exit_code=0,
                stdout="",
                stderr="",
                public_context=invocation.public_context,
                worktree=Path(worktree_path),
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


def _eligible_actor(
    snapshot: dict[str, object], provider: str, provider_user_id: str
) -> dict[str, object] | None:
    requirements = snapshot.get("requirements", [])
    if not isinstance(requirements, list):
        return None
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        users = requirement.get("users", [])
        if not isinstance(users, list):
            continue
        for actor in users:
            if (
                isinstance(actor, dict)
                and actor.get("provider") == provider
                and actor.get("provider_user_id") == provider_user_id
            ):
                return actor
    return None
