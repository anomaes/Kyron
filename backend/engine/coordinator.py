from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import (
    EdgeEvaluation,
    GateInstance,
    InvocationWorkspace,
    NodeExecution,
    Project,
    RunChangeRequest,
    SubworkflowBatch,
    SubworkflowBatchMember,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import InvocationStatus, NodeStatus, RunStatus
from backend.engine.conditions import evaluate_condition
from backend.engine.context import expand_public_variables
from backend.engine.scheduler import DagScheduler, GraphDeadlockError, LogicalStatus
from backend.engine.waves import WaveExecutionError, WaveExecutor
from backend.integrations.code_host import (
    CodeHostClient,
    CodeHostError,
    ProviderUser,
    git_username,
    repository_locator,
)
from backend.integrations.git_manager import GitError, GitManager, project_git_locks
from backend.schemas.workflow import (
    HumanFeedbackNode,
    ReviewLoopNode,
    SubworkflowNode,
    WorkflowBundle,
    WorkflowDefinition,
)
from backend.services.approval_policy_service import ApprovalPolicyError, ApprovalPolicyService
from backend.services.crypto import SecretCipher
from backend.services.engine_log_service import EngineLogService
from backend.services.report_service import ReportService

logger = logging.getLogger(__name__)

PENDING_FEEDBACK_PUBLICATION = "FEEDBACK_PUBLICATION"
PENDING_FINAL_PUBLICATION = "FINAL_PUBLICATION"


class RunPaused(RuntimeError):
    pass


class RunExecutionError(RuntimeError):
    pass


class RunCoordinator:
    def __init__(
        self,
        session: AsyncSession,
        git: GitManager,
        code_host: CodeHostClient,
        cipher: SecretCipher,
        wave_executor: WaveExecutor,
        engine_logs: EngineLogService | None = None,
    ) -> None:
        self.session = session
        self.git = git
        self.code_host = code_host
        self.cipher = cipher
        self.wave_executor = wave_executor
        self.engine_logs = engine_logs

    async def execute_run(self, run_id: uuid.UUID) -> None:
        run = await self._run(run_id)
        project = await self._project(run.project_id)
        user = await self._user(run.triggered_by)
        bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
        logger.info(
            "Workflow run execution starting "
            "(run=%s, project=%s, workflow=%s, status=%s, commit=%s)",
            run.id,
            project.id,
            run.root_workflow_id,
            run.status,
            run.base_commit_sha[:12],
        )
        if run.status == RunStatus.QUEUED:
            async with project_git_locks.for_project(project.id):
                branch, worktree, run_data = await self.git.create_run_worktree(
                    Path(project.local_path),
                    run.id,
                    run.root_workflow_id,
                    run.base_commit_sha,
                )
            run.branch_name = branch
            run.worktree_path = str(worktree)
            run.run_data_path = str(run_data)
            run.current_head_sha = run.base_commit_sha
            run.public_context = {
                **run.public_context,
                **self._builtins(run, project, user, bundle.workflows[run.root_workflow_id]),
            }
            root = WorkflowInvocation(
                id=uuid.uuid4(),
                run_id=run.id,
                workflow_id=run.root_workflow_id,
                invocation_path="root",
                input_context=dict(run.public_context),
                public_context=dict(run.public_context),
                status=InvocationStatus.PENDING,
            )
            root_workspace = InvocationWorkspace(
                id=uuid.uuid4(),
                run_id=run.id,
                owner_invocation_id=root.id,
                mode="ROOT",
                status="READY",
                base_commit_sha=run.base_commit_sha,
                current_head_sha=run.base_commit_sha,
                branch_name=branch,
                worktree_path=str(worktree),
            )
            root.workspace_id = root_workspace.id
            self.session.add(root)
            self.session.add(root_workspace)
            run.status = RunStatus.RUNNING
            run.started_at = datetime.now(UTC)
            await self._write_log(
                run.id,
                "INFO",
                "RUN_STARTED",
                f"Workflow run started for {run.root_workflow_id}",
                invocation_path="root",
            )
            await self.session.commit()
            logger.info(
                "Run worktree initialized (run=%s, branch=%s, invocation=%s)",
                run.id,
                branch,
                root.id,
            )
        else:
            existing_root = await self.session.scalar(
                select(WorkflowInvocation).where(
                    WorkflowInvocation.run_id == run.id,
                    WorkflowInvocation.invocation_path == "root",
                )
            )
            if existing_root is None:
                raise RunExecutionError("Run has no root invocation")
            root = existing_root
            if root.workspace_id is None:
                if not run.worktree_path or not run.branch_name or not run.current_head_sha:
                    raise RunExecutionError("Run has no root workspace")
                root_workspace = InvocationWorkspace(
                    id=uuid.uuid4(),
                    run_id=run.id,
                    owner_invocation_id=root.id,
                    mode="ROOT",
                    status="RUNNING",
                    base_commit_sha=run.base_commit_sha,
                    current_head_sha=run.current_head_sha,
                    branch_name=run.branch_name,
                    worktree_path=run.worktree_path,
                )
                self.session.add(root_workspace)
                root.workspace_id = root_workspace.id
                if not root.public_context:
                    root.public_context = dict(run.public_context)
                await self.session.commit()
            if run.status == RunStatus.RESUMING:
                run.status = RunStatus.RUNNING
                await self._write_log(
                    run.id,
                    "INFO",
                    "RUN_RESUMED",
                    "Workflow run resumed",
                    invocation_path="root",
                )
                await self.session.commit()
                logger.info("Workflow run resumed (run=%s, invocation=%s)", run.id, root.id)
                if run.pending_operation:
                    await self._resume_pending_operation(run, bundle, project)
                    return

        try:
            await self.execute_invocation(run, root, bundle, project, user)
        except RunPaused:
            logger.info(
                "Workflow run paused for feedback (run=%s, node_execution=%s)",
                run.id,
                run.current_node_execution_id,
            )
            return
        except (WaveExecutionError, GraphDeadlockError, RunExecutionError) as exc:
            if run.status != RunStatus.FAILED:
                run.status = RunStatus.FAILED
                run.error_type = (
                    "GRAPH_DEADLOCK" if isinstance(exc, GraphDeadlockError) else "NODE_FAILURE"
                )
                run.error_message = str(exc)
            if run.delivery_mode == "REPORT_ONLY":
                run.verification_conclusion = "FAILURE"
            await self._write_log(
                run.id,
                "ERROR",
                "RUN_FAILED",
                run.error_message or str(exc),
                metadata={"error_type": run.error_type},
            )
            await self.session.commit()
            logger.error(
                "Workflow run failed (run=%s, error_type=%s): %s",
                run.id,
                run.error_type,
                exc,
            )
            return

        workflow = bundle.workflows[run.root_workflow_id]
        root.public_context = {
            **root.public_context,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
        }
        run.public_context = dict(root.public_context)
        run.pending_operation = PENDING_FINAL_PUBLICATION
        await self.session.commit()
        await self._finish_final_publication(run, project, workflow)

    async def _resume_pending_operation(
        self,
        run: WorkflowRun,
        bundle: WorkflowBundle,
        project: Project,
    ) -> None:
        if run.pending_operation == PENDING_FINAL_PUBLICATION:
            await self._finish_final_publication(
                run, project, bundle.workflows[run.root_workflow_id]
            )
            return
        if run.pending_operation != PENDING_FEEDBACK_PUBLICATION:
            raise RunExecutionError(f"Unsupported pending run operation '{run.pending_operation}'")
        if run.current_node_execution_id is None:
            raise RunExecutionError("Pending feedback publication has no node execution")
        execution = await self.session.get(NodeExecution, run.current_node_execution_id)
        if execution is None:
            raise RunExecutionError("Pending feedback publication node no longer exists")
        invocation = await self.session.get(WorkflowInvocation, execution.invocation_id)
        if invocation is None:
            raise RunExecutionError("Pending feedback publication invocation no longer exists")
        workflow = bundle.workflows.get(invocation.workflow_id)
        if workflow is None:
            raise RunExecutionError("Pending feedback workflow is absent from the run snapshot")
        node = next((item for item in workflow.nodes if item.id == execution.node_id), None)
        if not isinstance(node, (HumanFeedbackNode, ReviewLoopNode)):
            raise RunExecutionError("Pending feedback publication node is not a feedback node")
        iteration = int(execution.output_values.get("review_iteration", 1))
        await self._publish_feedback_checkpoint(
            run,
            invocation,
            workflow,
            node,
            execution,
            project,
            iteration=iteration,
        )

    async def _finish_final_publication(
        self,
        run: WorkflowRun,
        project: Project,
        workflow: WorkflowDefinition,
    ) -> None:
        assert run.worktree_path and run.branch_name
        final_sha = run.final_commit_sha
        if final_sha is None:
            final_message = expand_public_variables(
                workflow.settings.final_commit_message_template, run.public_context
            )
            final_sha = await self.git.checkpoint(Path(run.worktree_path), final_message)
            run.final_commit_sha = final_sha
            run.current_head_sha = final_sha
            await self.session.commit()
        if should_publish_run(run):
            await self._publish_change_request(run, project, workflow)
        run.pending_operation = None
        run.status = RunStatus.COMPLETED
        run.finished_at = datetime.now(UTC)
        run.current_invocation_id = None
        run.current_node_execution_id = None
        run.current_wave_id = None
        run.error_type = None
        run.error_message = None
        if run.delivery_mode == "REPORT_ONLY":
            run.verification_conclusion = "SUCCESS"
            run.verification_freshness = (
                "CURRENT"
                if run.subject_current_head_sha == run.subject_commit_sha
                else "STALE"
            )
            await self._publish_verification_result(
                run, project, workflow, conclusion="SUCCESS"
            )
        await self._write_log(
            run.id,
            "INFO",
            "RUN_COMPLETED",
            f"Workflow run completed at {final_sha[:12]}",
            invocation_path="root",
            metadata={"commit_sha": final_sha},
        )
        await self.session.commit()
        await ReportService(self.session).get(run)
        logger.info(
            "Workflow run completed (run=%s, workflow=%s, commit=%s)",
            run.id,
            run.root_workflow_id,
            final_sha[:12],
        )

    async def _publish_verification_result(
        self,
        run: WorkflowRun,
        project: Project,
        workflow: WorkflowDefinition,
        *,
        conclusion: str,
    ) -> None:
        publication = workflow.settings.verification_publication
        if not publication.publish_commit_status and not (
            publication.post_change_request_summary
            and run.subject_change_request_number is not None
        ):
            return
        token = self.cipher.decrypt(project.encrypted_access_token)
        repository = repository_locator(
            project.provider,
            project.provider_project_id,
            project.provider_project_path,
        )
        try:
            if publication.publish_commit_status:
                provider_state = (
                    "success"
                    if conclusion == "SUCCESS"
                    else ("failure" if project.provider == "github" else "failed")
                )
                await self.code_host.publish_commit_status(
                    repository,
                    run.subject_commit_sha,
                    token,
                    state=provider_state,
                    description=f"Kyron verification {conclusion.casefold()}",
                    target_url=run.subject_change_request_url or "",
                )
            if (
                publication.post_change_request_summary
                and run.subject_change_request_number is not None
            ):
                await self.code_host.post_comment(
                    repository,
                    run.subject_change_request_number,
                    token,
                    (
                        f"Kyron verification **{conclusion.casefold()}** for "
                        f"`{run.subject_commit_sha}`. "
                        f"Workflow definition: `{run.workflow_definition_commit_sha}`."
                    ),
                )
            run.verification_published_at = datetime.now(UTC)
        except Exception:
            if publication.publication_required:
                raise
            logger.exception(
                "Optional verification publication failed (run=%s)", run.id
            )
        finally:
            token = ""

    async def _publish_change_request(
        self,
        run: WorkflowRun,
        project: Project,
        workflow: WorkflowDefinition,
        *,
        node: HumanFeedbackNode | ReviewLoopNode | None = None,
        reviewers: list[ProviderUser] | None = None,
        workspace: InvocationWorkspace | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        worktree_path = workspace.worktree_path if workspace else run.worktree_path
        branch_name = workspace.branch_name if workspace else run.branch_name
        if not worktree_path or not branch_name:
            raise RunExecutionError("Publication workspace is incomplete")
        token = self.cipher.decrypt(project.encrypted_access_token)
        try:
            if workspace and workspace.parent_workspace_id:
                parent = await self.session.get(
                    InvocationWorkspace, workspace.parent_workspace_id
                )
                if parent is None:
                    raise RunExecutionError("Child review has no parent workspace")
                await self.git.push(
                    Path(parent.worktree_path),
                    parent.branch_name,
                    token,
                    username=git_username(project.provider),
                )
            await self.git.push(
                Path(worktree_path),
                branch_name,
                token,
                username=git_username(project.provider),
            )
            await self._ensure_merge_request(
                run,
                project,
                workflow,
                token,
                node=node,
                reviewers=reviewers,
                workspace=workspace,
                context=context,
            )
        finally:
            token = ""

    async def execute_invocation(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> dict[str, Any]:
        workflow = bundle.workflows[invocation.workflow_id]
        invocation.public_context = {
            **workflow.variables,
            **invocation.public_context,
            **invocation.input_context,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
            "INVOCATION_ID": str(invocation.id),
            "INVOCATION_PATH": invocation.invocation_path,
        }
        if invocation.parent_invocation_id is None:
            run.public_context = dict(invocation.public_context)
        invocation.status = InvocationStatus.RUNNING
        invocation.started_at = invocation.started_at or datetime.now(UTC)
        await self._write_log(
            run.id,
            "INFO",
            "INVOCATION_STARTED",
            f"Started {workflow.name}",
            invocation_path=invocation.invocation_path,
            metadata={"workflow_id": workflow.id},
        )
        await self.session.commit()
        logger.info(
            "Workflow invocation started "
            "(run=%s, invocation=%s, path=%s, workflow=%s)",
            run.id,
            invocation.id,
            invocation.invocation_path,
            workflow.id,
        )
        scheduler = DagScheduler(workflow)
        while True:
            executions = list(
                await self.session.scalars(
                    select(NodeExecution).where(NodeExecution.invocation_id == invocation.id)
                )
            )
            statuses = {
                execution.node_id: _logical_status(execution.status) for execution in executions
            }
            edges = list(
                await self.session.scalars(
                    select(EdgeEvaluation).where(EdgeEvaluation.invocation_id == invocation.id)
                )
            )
            edge_results = {edge.edge_id: edge.condition_result for edge in edges}
            if scheduler.complete(statuses):
                outputs = self._workflow_outputs(workflow, invocation.public_context)
                invocation.output_context = outputs
                invocation.status = InvocationStatus.SUCCESS
                invocation.finished_at = datetime.now(UTC)
                await self._write_log(
                    run.id,
                    "INFO",
                    "INVOCATION_COMPLETED",
                    f"Completed {workflow.name}",
                    invocation_path=invocation.invocation_path,
                    metadata={"workflow_id": workflow.id},
                )
                await self.session.commit()
                logger.info(
                    "Workflow invocation completed "
                    "(run=%s, invocation=%s, path=%s, workflow=%s)",
                    run.id,
                    invocation.id,
                    invocation.invocation_path,
                    workflow.id,
                )
                return outputs
            decision = scheduler.next(statuses, edge_results)
            logger.debug(
                "Scheduler decision (run=%s, invocation=%s, runnable=%s, skipped=%s, "
                "control_boundary=%s)",
                run.id,
                invocation.id,
                [node.id for node in decision.nodes],
                decision.skipped_node_ids,
                decision.control_boundary,
            )
            for node_id in decision.skipped_node_ids:
                execution = await self._node_execution(run, invocation, workflow, node_id)
                execution.status = NodeStatus.SKIPPED
                execution.finished_at = datetime.now(UTC)
                await self._persist_control_edges(
                    run, invocation, workflow, execution, success=False
                )
            if decision.skipped_node_ids:
                await self.session.commit()
            if not decision.nodes:
                continue
            if not decision.control_boundary:
                process_nodes = [
                    node for node in decision.nodes if node.type in {"bash", "script", "prompt"}
                ]
                await self.wave_executor.execute(
                    run,
                    invocation,
                    workflow,
                    process_nodes,  # type: ignore[arg-type]
                    bundle.project_pi,
                )
                continue
            if len(decision.nodes) > 1 and all(
                isinstance(item, SubworkflowNode)
                and item.config.execution_mode == "isolated_parallel"
                for item in decision.nodes
            ):
                await self._execute_parallel_subworkflows(
                    run,
                    invocation,
                    workflow,
                    [item for item in decision.nodes if isinstance(item, SubworkflowNode)],
                    bundle,
                    project,
                    user,
                )
                continue
            node = decision.nodes[0]
            if isinstance(node, SubworkflowNode):
                await self._execute_subworkflow(
                    run, invocation, workflow, node, bundle, project, user
                )
            elif isinstance(node, HumanFeedbackNode):
                await self._pause_for_feedback(
                    run, invocation, workflow, node, project, user, iteration=1
                )
            elif isinstance(node, ReviewLoopNode):
                await self._execute_review_loop(
                    run, invocation, workflow, node, bundle, project, user
                )
            else:
                raise RunExecutionError(f"Unsupported control node '{node.type}'")

    async def _execute_subworkflow(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: SubworkflowNode,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> None:
        if node.config.execution_mode in {"isolated", "isolated_parallel"}:
            await self._execute_isolated_subworkflow_batch(
                run,
                invocation,
                workflow,
                [node],
                bundle,
                project,
                user,
                parallel=False,
            )
            return
        execution = await self._node_execution(run, invocation, workflow, node.id)
        execution.status = NodeStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        child_path = f"{invocation.invocation_path}/{node.id}"
        child = await self.session.scalar(
            select(WorkflowInvocation).where(
                WorkflowInvocation.run_id == run.id,
                WorkflowInvocation.invocation_path == child_path,
            )
        )
        if child is None:
            mapped = {
                name: expand_public_variables(value, invocation.public_context)
                for name, value in node.config.inputs.items()
            }
            child = WorkflowInvocation(
                run_id=run.id,
                workflow_id=node.config.workflow_id,
                invocation_path=child_path,
                parent_invocation_id=invocation.id,
                parent_node_execution_id=execution.id,
                input_context=mapped,
                public_context={
                    **bundle.workflows[node.config.workflow_id].variables,
                    **mapped,
                    **self._child_builtins(
                        run,
                        node.config.workflow_id,
                        child_path,
                        parent_context=invocation.public_context,
                    ),
                },
                workspace_id=invocation.workspace_id,
                status=InvocationStatus.PENDING,
            )
            self.session.add(child)
            await self.session.commit()
            logger.info(
                "Subworkflow invocation created "
                "(run=%s, parent_invocation=%s, node=%s, child_invocation=%s, workflow=%s)",
                run.id,
                invocation.id,
                node.id,
                child.id,
                node.config.workflow_id,
            )
        try:
            outputs = await self.execute_invocation(run, child, bundle, project, user)
        except RunPaused:
            # A feedback checkpoint in the child suspends the whole invocation chain.
            # Keep the parent control node resumable; this is not an execution failure.
            raise
        except Exception:
            execution.status = NodeStatus.FAILED
            execution.finished_at = datetime.now(UTC)
            await self.session.commit()
            raise
        mapped_outputs = {
            parent_name: outputs[child_name]
            for child_name, parent_name in node.config.output_mapping.items()
            if child_name in outputs
        }
        invocation.public_context = {**invocation.public_context, **mapped_outputs}
        if invocation.parent_invocation_id is None:
            run.public_context = dict(invocation.public_context)
        execution.output_values = mapped_outputs
        execution.status = NodeStatus.SUCCESS
        execution.finished_at = datetime.now(UTC)
        await self._persist_control_edges(run, invocation, workflow, execution, success=True)
        await self.session.commit()
        logger.info(
            "Subworkflow node completed (run=%s, invocation=%s, node=%s)",
            run.id,
            invocation.id,
            node.id,
        )

    async def _execute_parallel_subworkflows(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        nodes: list[SubworkflowNode],
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> None:
        await self._execute_isolated_subworkflow_batch(
            run,
            invocation,
            workflow,
            nodes,
            bundle,
            project,
            user,
            parallel=True,
        )

    async def _execute_isolated_subworkflow_batch(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        nodes: list[SubworkflowNode],
        bundle: WorkflowBundle,
        project: Project,
        user: User,
        *,
        parallel: bool,
    ) -> None:
        if invocation.workspace_id is None:
            raise RunExecutionError("Parent invocation has no durable workspace")
        parent_workspace = await self.session.get(
            InvocationWorkspace, invocation.workspace_id
        )
        if parent_workspace is None:
            raise RunExecutionError("Parent invocation workspace does not exist")
        parent_worktree = Path(parent_workspace.worktree_path)
        await self.git.ensure_clean(parent_worktree)
        parent_head = await self.git.head_sha(parent_worktree)

        node_by_execution: dict[uuid.UUID, SubworkflowNode] = {}
        members: list[SubworkflowBatchMember] = []
        for node in sorted(nodes, key=lambda item: item.id):
            execution = await self._node_execution(run, invocation, workflow, node.id)
            node_by_execution[execution.id] = node
            existing_member = await self.session.scalar(
                select(SubworkflowBatchMember).where(
                    SubworkflowBatchMember.parent_node_execution_id == execution.id
                )
            )
            if existing_member is not None:
                members.append(existing_member)

        batch: SubworkflowBatch | None = None
        if members:
            batch = await self.session.get(SubworkflowBatch, members[0].batch_id)
            if batch is None or any(member.batch_id != batch.id for member in members):
                raise RunExecutionError("Parallel sub-workflow batch state is inconsistent")
            if batch.base_commit_sha != parent_head and batch.status not in {
                "SUCCESS",
                "FAILED",
            }:
                raise RunExecutionError("Parent workspace moved while a child batch was active")
        else:
            batch = SubworkflowBatch(
                id=uuid.uuid4(),
                run_id=run.id,
                parent_invocation_id=invocation.id,
                parent_workspace_id=parent_workspace.id,
                base_commit_sha=parent_head,
                status="CREATING",
                started_at=datetime.now(UTC),
            )
            self.session.add(batch)
            frozen_parent_context = dict(invocation.public_context)
            for order, node in enumerate(sorted(nodes, key=lambda item: item.id), start=1):
                execution = await self._node_execution(run, invocation, workflow, node.id)
                execution.status = NodeStatus.RUNNING
                execution.started_at = execution.started_at or datetime.now(UTC)
                child_path = f"{invocation.invocation_path}/{node.id}"
                mapped = {
                    name: expand_public_variables(value, frozen_parent_context)
                    for name, value in node.config.inputs.items()
                }
                child_id = uuid.uuid4()
                workspace_id = uuid.uuid4()
                safe_node = "".join(
                    character if character.isalnum() or character == "_" else "_"
                    for character in node.id
                )
                branch = (
                    f"workflow/{run.id.hex[:8]}/{workspace_id.hex[:8]}_{safe_node}"
                )
                worktree = self.git.worktree_base_path / str(workspace_id)
                child = WorkflowInvocation(
                    id=child_id,
                    run_id=run.id,
                    workflow_id=node.config.workflow_id,
                    invocation_path=child_path,
                    parent_invocation_id=invocation.id,
                    parent_node_execution_id=execution.id,
                    input_context=mapped,
                    public_context={
                        **bundle.workflows[node.config.workflow_id].variables,
                        **mapped,
                        **self._child_builtins(
                            run,
                            node.config.workflow_id,
                            child_path,
                            parent_context=frozen_parent_context,
                            workspace_id=workspace_id,
                            workspace_branch=branch,
                            workspace_base_commit_sha=parent_head,
                        ),
                    },
                    workspace_id=workspace_id,
                    status=InvocationStatus.PENDING,
                )
                child_workspace = InvocationWorkspace(
                    id=workspace_id,
                    run_id=run.id,
                    owner_invocation_id=child_id,
                    parent_workspace_id=parent_workspace.id,
                    mode="ISOLATED_PARALLEL" if parallel else "ISOLATED",
                    status="CREATING",
                    base_commit_sha=parent_head,
                    current_head_sha=parent_head,
                    branch_name=branch,
                    worktree_path=str(worktree),
                )
                member = SubworkflowBatchMember(
                    id=uuid.uuid4(),
                    batch_id=batch.id,
                    parent_node_execution_id=execution.id,
                    child_invocation_id=child.id,
                    child_workspace_id=child_workspace.id,
                    integration_order=order,
                    allow_failure=node.config.allow_failure,
                    status="PENDING",
                )
                self.session.add_all([child, child_workspace, member])
                members.append(member)
            await self.session.commit()

            try:
                async with project_git_locks.for_project(project.id):
                    for member in sorted(members, key=lambda item: item.integration_order):
                        node = node_by_execution[member.parent_node_execution_id]
                        workspace = await self.session.get(
                            InvocationWorkspace, member.child_workspace_id
                        )
                        if workspace is None:
                            raise RunExecutionError("Child workspace row disappeared")
                        branch, worktree = await self.git.create_invocation_worktree(
                            Path(project.local_path),
                            run.id,
                            workspace.id,
                            node.id,
                            parent_head,
                        )
                        workspace.branch_name = branch
                        workspace.worktree_path = str(worktree)
                        workspace.status = "READY"
                batch.status = "RUNNING"
                await self.session.commit()
            except Exception as exc:
                batch.status = "FAILED"
                batch.error_type = "SUBWORKFLOW_WORKSPACE_CREATION_FAILED"
                batch.error_message = str(exc)
                run.status = RunStatus.FAILED
                run.error_type = batch.error_type
                run.error_message = str(exc)
                await self.session.commit()
                raise RunExecutionError(str(exc)) from exc

        if batch.status == "SUCCESS":
            return
        if batch.status == "FAILED":
            raise RunExecutionError(batch.error_message or "Sub-workflow batch failed")

        open_gate_invocation_ids = set(
            await self.session.scalars(
                select(GateInstance.invocation_id).where(
                    GateInstance.run_id == run.id,
                    GateInstance.status == "OPEN",
                    GateInstance.invocation_id.in_(
                        [member.child_invocation_id for member in members]
                    ),
                )
            )
        )
        runnable_members = [
            member
            for member in members
            if member.status not in {"SUCCESS", "FAILED"}
            and member.child_invocation_id not in open_gate_invocation_ids
        ]
        if parallel and len(runnable_members) > 1:
            results = await asyncio.gather(
                *[
                    self._execute_isolated_member_in_new_session(
                        run.id, member.child_invocation_id
                    )
                    for member in runnable_members
                ]
            )
        else:
            results = []
            for member in runnable_members:
                runnable_child = await self.session.get(
                    WorkflowInvocation, member.child_invocation_id
                )
                if runnable_child is None:
                    raise RunExecutionError("Child invocation does not exist")
                try:
                    await self.execute_invocation(
                        run, runnable_child, bundle, project, user
                    )
                    results.append("SUCCESS")
                except RunPaused:
                    results.append("PAUSED")
                except Exception as exc:
                    runnable_child.status = InvocationStatus.FAILED
                    failed_workspace = await self.session.get(
                        InvocationWorkspace, member.child_workspace_id
                    )
                    if failed_workspace is not None:
                        failed_workspace.status = "FAILED"
                        failed_workspace.error_type = "SUBWORKFLOW_FAILED"
                        failed_workspace.error_message = str(exc)
                    results.append("FAILED")
                await self.session.commit()

        await self.session.refresh(batch)
        if batch is None:
            raise RunExecutionError("Sub-workflow batch disappeared")
        members = list(
            await self.session.scalars(
                select(SubworkflowBatchMember)
                .where(SubworkflowBatchMember.batch_id == batch.id)
                .order_by(SubworkflowBatchMember.integration_order)
                .execution_options(populate_existing=True)
            )
        )
        paused = bool(open_gate_invocation_ids)
        required_failure: str | None = None
        for member, result in zip(runnable_members, results, strict=True):
            refreshed = next(item for item in members if item.id == member.id)
            if result == "SUCCESS":
                refreshed.status = "SUCCESS"
            elif result == "PAUSED":
                refreshed.status = "AWAITING_FEEDBACK"
                paused = True
            elif refreshed.allow_failure:
                refreshed.status = "FAILED"
            else:
                refreshed.status = "FAILED"
                required_failure = "A required isolated sub-workflow failed"

        if required_failure:
            batch.status = "FAILED"
            batch.error_type = "SUBWORKFLOW_FAILED"
            batch.error_message = required_failure
            batch.finished_at = datetime.now(UTC)
            run.status = RunStatus.FAILED
            run.error_type = batch.error_type
            run.error_message = required_failure
            await self.session.commit()
            raise RunExecutionError(required_failure)
        if paused:
            batch.status = "BLOCKED"
            run.status = RunStatus.AWAITING_FEEDBACK
            await self.session.commit()
            raise RunPaused()

        integrable = [member for member in members if member.status == "SUCCESS"]
        batch.status = "INTEGRATING"
        await self.session.commit()
        child_heads: list[str] = []
        for member in integrable:
            workspace = await self.session.get(
                InvocationWorkspace, member.child_workspace_id
            )
            if workspace is None:
                raise RunExecutionError("Child workspace does not exist")
            await self.session.refresh(workspace)
            await self.git.ensure_clean(Path(workspace.worktree_path))
            actual_head = await self.git.head_sha(Path(workspace.worktree_path))
            if actual_head != workspace.current_head_sha:
                raise RunExecutionError("Child workspace HEAD does not match durable state")
            child_heads.append(workspace.current_head_sha)
        try:
            async with project_git_locks.for_project(project.id):
                integrated_head = await self.git.integrate_heads(
                    parent_worktree, batch.base_commit_sha, child_heads
                )
        except GitError as exc:
            batch.status = "FAILED"
            batch.error_type = "SUBWORKFLOW_INTEGRATION_CONFLICT"
            batch.error_message = str(exc)
            batch.finished_at = datetime.now(UTC)
            run.status = RunStatus.FAILED
            run.error_type = batch.error_type
            run.error_message = str(exc)
            await self.session.commit()
            raise RunExecutionError(str(exc)) from exc

        published_child_review = await self.session.scalar(
            select(RunChangeRequest.id).where(
                RunChangeRequest.workspace_id.in_(
                    [member.child_workspace_id for member in members]
                ),
                RunChangeRequest.kind == "WORKSPACE_REVIEW",
            )
        )
        if published_child_review is not None and should_publish_run(run):
            token = self.cipher.decrypt(project.encrypted_access_token)
            try:
                await self.git.push(
                    parent_worktree,
                    parent_workspace.branch_name,
                    token,
                    username=git_username(project.provider),
                )
            except Exception as exc:
                await self.git.reset_wave(parent_worktree, batch.base_commit_sha)
                batch.status = "FAILED"
                batch.error_type = "SUBWORKFLOW_PARENT_PUSH_FAILED"
                batch.error_message = str(exc)
                batch.finished_at = datetime.now(UTC)
                run.status = RunStatus.FAILED
                run.error_type = batch.error_type
                run.error_message = str(exc)
                await self.session.commit()
                raise RunExecutionError(str(exc)) from exc
            finally:
                token = ""

        parent_workspace.current_head_sha = integrated_head
        if parent_workspace.mode == "ROOT":
            run.current_head_sha = integrated_head
        for member in members:
            node = node_by_execution[member.parent_node_execution_id]
            integrated_execution = await self.session.get(
                NodeExecution, member.parent_node_execution_id
            )
            integrated_child = await self.session.get(
                WorkflowInvocation, member.child_invocation_id
            )
            integrated_workspace = await self.session.get(
                InvocationWorkspace, member.child_workspace_id
            )
            if (
                integrated_execution is None
                or integrated_child is None
                or integrated_workspace is None
            ):
                raise RunExecutionError("Sub-workflow integration state is incomplete")
            await self.session.refresh(integrated_child)
            await self.session.refresh(integrated_workspace)
            if member.status == "SUCCESS":
                mapped_outputs = {
                    parent_name: integrated_child.output_context[child_name]
                    for child_name, parent_name in node.config.output_mapping.items()
                    if child_name in integrated_child.output_context
                }
                invocation.public_context = {
                    **invocation.public_context,
                    **mapped_outputs,
                }
                integrated_execution.output_values = mapped_outputs
                member.status = "INTEGRATED"
                member.integrated_commit_sha = integrated_head
                integrated_workspace.status = "INTEGRATED"
                integrated_workspace.integrated_head_sha = integrated_head
                integrated_workspace.finished_at = datetime.now(UTC)
                integrated_execution.status = NodeStatus.SUCCESS
                integrated_execution.finished_at = datetime.now(UTC)
                await self._persist_control_edges(
                    run, invocation, workflow, integrated_execution, success=True
                )
            else:
                integrated_execution.status = NodeStatus.SUCCESS
                integrated_execution.finished_at = datetime.now(UTC)
                integrated_execution.output_values = {"allow_failure": True}
                await self._persist_control_edges(
                    run, invocation, workflow, integrated_execution, success=True
                )
        if invocation.parent_invocation_id is None:
            run.public_context = dict(invocation.public_context)
        batch.status = "SUCCESS"
        batch.finished_at = datetime.now(UTC)
        await self.session.commit()

    async def _execute_isolated_member_in_new_session(
        self, run_id: uuid.UUID, invocation_id: uuid.UUID
    ) -> str:
        if self.session.bind is None:
            raise RunExecutionError("Database session is not bound")
        factory = async_sessionmaker(self.session.bind, expire_on_commit=False)
        async with factory() as session:
            run = await session.get(WorkflowRun, run_id)
            invocation = await session.get(WorkflowInvocation, invocation_id)
            if run is None or invocation is None:
                return "FAILED"
            project = await session.get(Project, run.project_id)
            user = await session.get(User, run.triggered_by)
            if project is None or user is None:
                return "FAILED"
            bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
            engine_logs = (
                EngineLogService(
                    session,
                    self.engine_logs.broadcaster,
                    self.engine_logs.redactor,
                )
                if self.engine_logs is not None
                else None
            )
            waves = WaveExecutor(
                session,
                self.git,
                self.wave_executor.node_executor,
                self.wave_executor.credential_loader,
                engine_logs,
            )
            coordinator = RunCoordinator(
                session,
                self.git,
                self.code_host,
                self.cipher,
                waves,
                engine_logs,
            )
            try:
                await coordinator.execute_invocation(
                    run, invocation, bundle, project, user
                )
                return "SUCCESS"
            except RunPaused:
                return "PAUSED"
            except Exception as exc:
                invocation.status = InvocationStatus.FAILED
                workspace = (
                    await session.get(InvocationWorkspace, invocation.workspace_id)
                    if invocation.workspace_id
                    else None
                )
                if workspace is not None:
                    workspace.status = "FAILED"
                    workspace.error_type = "SUBWORKFLOW_FAILED"
                    workspace.error_message = str(exc)
                await session.commit()
                return "FAILED"

    async def _execute_review_loop(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: ReviewLoopNode,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> None:
        execution = await self._node_execution(run, invocation, workflow, node.id)
        metadata = dict(execution.output_values)
        iteration = int(metadata.get("review_iteration", 1))
        maximum = node.config.max_iterations or workflow.settings.max_review_iterations
        if iteration > maximum:
            execution.status = NodeStatus.FAILED
            execution.error_message = "Maximum review iterations reached"
            run.status = RunStatus.FAILED
            run.error_type = "MAX_REVIEW_ITERATIONS_REACHED"
            run.error_message = execution.error_message
            await self.session.commit()
            logger.error(
                "Review loop exceeded its iteration limit "
                "(run=%s, invocation=%s, node=%s, iteration=%s, maximum=%s)",
                run.id,
                invocation.id,
                node.id,
                iteration,
                maximum,
            )
            raise RunExecutionError(execution.error_message)
        child_workflow_id = (
            node.config.initial_workflow_id
            if iteration == 1
            else node.config.revision_workflow_id or node.config.initial_workflow_id
        )
        mapping = node.config.inputs if iteration == 1 else node.config.revision_inputs
        kind = "initial" if iteration == 1 else "revision"
        child_path = f"{invocation.invocation_path}/{node.id}/{kind}[{iteration}]"
        child = await self.session.scalar(
            select(WorkflowInvocation).where(
                WorkflowInvocation.run_id == run.id,
                WorkflowInvocation.invocation_path == child_path,
            )
        )
        execution.status = NodeStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        if child is None:
            child_inputs = {
                name: expand_public_variables(value, invocation.public_context)
                for name, value in mapping.items()
            }
            child = WorkflowInvocation(
                run_id=run.id,
                workflow_id=child_workflow_id,
                invocation_path=child_path,
                parent_invocation_id=invocation.id,
                parent_node_execution_id=execution.id,
                loop_iteration=iteration,
                input_context=child_inputs,
                public_context={
                    **bundle.workflows[child_workflow_id].variables,
                    **child_inputs,
                    **self._child_builtins(
                        run,
                        child_workflow_id,
                        child_path,
                        parent_context=invocation.public_context,
                    ),
                    "REVIEW_ITERATION": iteration,
                },
                workspace_id=invocation.workspace_id,
                status=InvocationStatus.PENDING,
            )
            self.session.add(child)
            await self.session.commit()
        outputs = await self.execute_invocation(run, child, bundle, project, user)
        mapped_outputs = {
            parent_name: outputs[child_name]
            for child_name, parent_name in node.config.output_mapping.items()
            if child_name in outputs
        }
        invocation.public_context = {**invocation.public_context, **mapped_outputs}
        if invocation.parent_invocation_id is None:
            run.public_context = dict(invocation.public_context)
        execution.output_values = {
            **mapped_outputs,
            "review_iteration": iteration,
            "max_iterations": maximum,
            "last_child_invocation_id": str(child.id),
        }
        await self._pause_for_feedback(
            run, invocation, workflow, node, project, user, iteration=iteration
        )

    async def _pause_for_feedback(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: HumanFeedbackNode | ReviewLoopNode,
        project: Project,
        user: User,
        *,
        iteration: int,
    ) -> None:
        execution = await self._node_execution(run, invocation, workflow, node.id)
        execution.status = NodeStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        execution.output_values = {
            **execution.output_values,
            "review_iteration": iteration,
        }
        workspace = (
            await self.session.get(InvocationWorkspace, invocation.workspace_id)
            if invocation.workspace_id
            else None
        )
        # The compatibility pointer is safe only for the serialized root workspace.
        # Isolated gates recover from their own PUBLISHING gate record, so concurrent
        # children never overwrite one another's publication identity.
        if workspace is None or workspace.mode == "ROOT":
            run.pending_operation = PENDING_FEEDBACK_PUBLICATION
            run.current_invocation_id = invocation.id
            run.current_node_execution_id = execution.id
            run.current_wave_id = None
        await self.session.commit()
        await self._publish_feedback_checkpoint(
            run,
            invocation,
            workflow,
            node,
            execution,
            project,
            iteration=iteration,
        )
        raise RunPaused()

    async def _publish_feedback_checkpoint(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: HumanFeedbackNode | ReviewLoopNode,
        execution: NodeExecution,
        project: Project,
        *,
        iteration: int,
    ) -> None:
        workspace = (
            await self.session.get(InvocationWorkspace, invocation.workspace_id)
            if invocation.workspace_id
            else None
        )
        worktree_path = workspace.worktree_path if workspace else run.worktree_path
        if not worktree_path:
            raise RunExecutionError("Feedback invocation has no workspace")
        gate = await self.session.scalar(
            select(GateInstance).where(
                GateInstance.node_execution_id == execution.id,
                GateInstance.iteration == iteration,
            )
        )
        if gate is None:
            try:
                policy_snapshot, eligible_snapshot = await ApprovalPolicyService(
                    self.session
                ).snapshot(
                    project,
                    node.config.approval_policy,
                    triggering_user_id=run.triggered_by,
                )
            except ApprovalPolicyError as exc:
                raise RunExecutionError(str(exc)) from exc
            context = {**invocation.public_context, "REVIEW_ITERATION": iteration}
            message = expand_public_variables(node.config.commit_message, context)
            head = await self.git.checkpoint(Path(worktree_path), message)
            gate = GateInstance(
                run_id=run.id,
                invocation_id=invocation.id,
                node_execution_id=execution.id,
                workspace_id=workspace.id if workspace else None,
                iteration=iteration,
                checkpoint_commit_sha=head,
                policy_key=node.config.approval_policy,
                policy_snapshot=policy_snapshot,
                eligible_snapshot=eligible_snapshot,
                status="PUBLISHING",
            )
            self.session.add(gate)
            if workspace is not None:
                workspace.current_head_sha = head
                workspace.status = "AWAITING_FEEDBACK"
            if workspace is None or workspace.mode == "ROOT":
                run.current_head_sha = head
            await self.session.commit()
        reviewers = _provider_reviewers(gate.eligible_snapshot)
        if should_publish_run(run):
            await self._publish_change_request(
                run,
                project,
                workflow,
                node=node,
                reviewers=reviewers,
                workspace=(
                    workspace
                    if workspace is not None and workspace.mode != "ROOT"
                    else None
                ),
                context=invocation.public_context,
            )
            change_request = (
                await self.session.scalar(
                    select(RunChangeRequest).where(
                        RunChangeRequest.workspace_id == workspace.id,
                        RunChangeRequest.status == "OPEN",
                    )
                )
                if workspace is not None
                else None
            )
            if change_request is not None:
                gate.change_request_id = change_request.id
        gate.status = "OPEN"
        execution.status = NodeStatus.AWAITING_FEEDBACK
        open_or_running = (
            await self.session.scalar(
                select(InvocationWorkspace.id).where(
                    InvocationWorkspace.run_id == run.id,
                    InvocationWorkspace.id != workspace.id,
                    InvocationWorkspace.status.in_(["READY", "RUNNING"]),
                )
            )
            if workspace is not None
            else None
        )
        run.status = (
            RunStatus.RUNNING if open_or_running is not None else RunStatus.AWAITING_FEEDBACK
        )
        if (
            run.pending_operation == PENDING_FEEDBACK_PUBLICATION
            and run.current_node_execution_id == execution.id
        ):
            run.pending_operation = None
        run.current_invocation_id = invocation.id
        run.current_node_execution_id = execution.id
        run.current_wave_id = None
        await self._write_log(
            run.id,
            "INFO",
            "FEEDBACK_GATE_OPENED",
            f"Waiting for feedback on {node.label}",
            invocation_path=invocation.invocation_path,
            node_path=execution.node_path,
            metadata={"gate_id": str(gate.id), "iteration": iteration},
        )
        await self.session.commit()
        logger.info(
            "Feedback gate opened "
            "(run=%s, invocation=%s, node=%s, gate=%s, iteration=%s, eligible_reviewers=%s)",
            run.id,
            invocation.id,
            node.id,
            gate.id,
            iteration,
            len(reviewers),
        )

    async def _write_log(
        self,
        run_id: uuid.UUID,
        level: str,
        event_type: str,
        message: str,
        *,
        invocation_path: str | None = None,
        node_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.engine_logs is not None:
            await self.engine_logs.write(
                run_id,
                level,
                event_type,
                message,
                invocation_path=invocation_path,
                node_path=node_path,
                metadata=metadata,
            )

    async def _ensure_merge_request(
        self,
        run: WorkflowRun,
        project: Project,
        workflow: WorkflowDefinition,
        token: str,
        *,
        node: HumanFeedbackNode | ReviewLoopNode | None = None,
        reviewers: list[ProviderUser] | None = None,
        workspace: InvocationWorkspace | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        source_branch = workspace.branch_name if workspace else run.branch_name
        if source_branch is None:
            raise RunExecutionError("Publication branch is missing")
        target_branch = run.base_ref
        if workspace and workspace.parent_workspace_id:
            parent = await self.session.get(
                InvocationWorkspace, workspace.parent_workspace_id
            )
            if parent is None:
                raise RunExecutionError("Child publication target workspace is missing")
            target_branch = parent.branch_name
        title_template = (
            node.config.mr_title
            if node and node.config.mr_title
            else workflow.settings.mr_title_template
        )
        description_template = (
            node.config.mr_description
            if node and node.config.mr_description
            else workflow.settings.mr_description_template
        )
        publication_context = context or run.public_context
        title = expand_public_variables(title_template, publication_context)
        description = expand_public_variables(description_template, publication_context)
        reviewers = reviewers or [
            ProviderUser(
                id=run.reviewer_provider_user_id,
                username=run.reviewer_provider_username,
            )
        ]
        repository = repository_locator(
            project.provider, project.provider_project_id, project.provider_project_path
        )
        workspace_request = (
            await self.session.scalar(
                select(RunChangeRequest).where(
                    RunChangeRequest.workspace_id == workspace.id,
                    RunChangeRequest.kind == "WORKSPACE_REVIEW",
                    RunChangeRequest.status == "OPEN",
                )
            )
            if workspace
            else None
        )
        provider_number = (
            workspace_request.provider_number
            if workspace_request is not None
            else run.change_request_number
        )
        if provider_number is None:
            change_request = await self.code_host.find_change_request(
                repository,
                token,
                source_branch=source_branch,
                target_branch=target_branch,
            )
            if change_request is None:
                try:
                    change_request = await self.code_host.create_change_request(
                        repository,
                        token,
                        source_branch=source_branch,
                        target_branch=target_branch,
                        title=title,
                        description=description,
                        reviewers=reviewers,
                    )
                except CodeHostError:
                    # The provider may have accepted the POST before the response was lost.
                    # Reconcile by the run's unique source branch before reporting failure.
                    change_request = await self.code_host.find_change_request(
                        repository,
                        token,
                        source_branch=source_branch,
                        target_branch=target_branch,
                    )
                    if change_request is None:
                        raise
            provider_number = change_request.number
            if workspace:
                workspace_request = RunChangeRequest(
                    run_id=run.id,
                    project_id=project.id,
                    workspace_id=workspace.id,
                    kind="WORKSPACE_REVIEW",
                    provider=project.provider,
                    provider_number=change_request.number,
                    url=change_request.url,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    status="OPEN",
                    head_sha=workspace.current_head_sha,
                )
                self.session.add(workspace_request)
            else:
                run.change_request_number = change_request.number
                run.change_request_url = change_request.url
                run.change_request_created_at = datetime.now(UTC)
                root_workspace = await self.session.scalar(
                    select(InvocationWorkspace).where(
                        InvocationWorkspace.run_id == run.id,
                        InvocationWorkspace.mode == "ROOT",
                    )
                )
                existing_final = await self.session.scalar(
                    select(RunChangeRequest).where(
                        RunChangeRequest.run_id == run.id,
                        RunChangeRequest.kind == "FINAL",
                    )
                )
                if existing_final is None:
                    self.session.add(
                        RunChangeRequest(
                            run_id=run.id,
                            project_id=project.id,
                            workspace_id=root_workspace.id if root_workspace else None,
                            kind="FINAL",
                            provider=project.provider,
                            provider_number=change_request.number,
                            url=change_request.url,
                            source_branch=source_branch,
                            target_branch=target_branch,
                            status="OPEN",
                            head_sha=run.current_head_sha or run.base_commit_sha,
                        )
                    )
            await self.session.commit()
            logger.info(
                "Change request recorded (run=%s, change_request=%s)",
                run.id,
                change_request.number,
            )
        if provider_number is None:
            raise RunExecutionError("Change request publication did not return a number")
        await self.code_host.update_change_request_reviewers(
            repository,
            provider_number,
            token,
            reviewers,
        )
        logger.info(
            "Change request reviewers updated (run=%s, change_request=%s, reviewers=%s)",
            run.id,
            provider_number,
            len(reviewers),
        )

    async def _node_execution(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node_id: str,
    ) -> NodeExecution:
        execution = await self.session.scalar(
            select(NodeExecution).where(
                NodeExecution.invocation_id == invocation.id,
                NodeExecution.node_id == node_id,
            )
        )
        if execution is not None:
            return execution
        node = next(item for item in workflow.nodes if item.id == node_id)
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
        return execution

    async def _persist_control_edges(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        execution: NodeExecution,
        *,
        success: bool,
    ) -> None:
        workspace = (
            await self.session.get(InvocationWorkspace, invocation.workspace_id)
            if invocation.workspace_id
            else None
        )
        worktree_path = workspace.worktree_path if workspace else run.worktree_path
        if not worktree_path:
            raise RunExecutionError("Control invocation has no workspace")
        existing = set(
            await self.session.scalars(
                select(EdgeEvaluation.edge_id).where(
                    EdgeEvaluation.source_node_execution_id == execution.id
                )
            )
        )
        for edge in workflow.edges:
            if edge.source != execution.node_id or edge.id in existing:
                continue
            if success:
                result, value = evaluate_condition(
                    edge.condition,
                    exit_code=0,
                    stdout="",
                    stderr="",
                    public_context=invocation.public_context,
                    worktree=Path(worktree_path),
                )
            else:
                result, value = False, None
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

    @staticmethod
    def _workflow_outputs(workflow: WorkflowDefinition, context: dict[str, Any]) -> dict[str, Any]:
        return {
            name: expand_public_variables(definition.source, context)
            for name, definition in workflow.outputs.items()
        }

    @staticmethod
    def _builtins(
        run: WorkflowRun, project: Project, user: User, workflow: WorkflowDefinition
    ) -> dict[str, str]:
        return {
            "RUN_ID": str(run.id),
            "RUN_ID_SHORT": run.id.hex[:8],
            "ROOT_WORKFLOW_ID": run.root_workflow_id,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
            "PROJECT_ID": str(project.id),
            "PROJECT_NAME": project.name,
            "BASE_REF": run.base_ref,
            "BASE_COMMIT_SHA": run.base_commit_sha,
            "BRANCH": run.branch_name or "",
            "WORKTREE_PATH": run.worktree_path or "",
            "RUN_DATA_PATH": run.run_data_path or "",
            "USER_NAME": user.display_name,
            "USER_EMAIL": user.email,
            "CODE_HOST_PROVIDER": run.reviewer_provider,
            "PROVIDER_USER_ID": run.reviewer_provider_user_id,
            "PROVIDER_USERNAME": run.reviewer_provider_username,
            "GITLAB_USER_ID": (
                run.reviewer_provider_user_id if run.reviewer_provider == "gitlab" else ""
            ),
            "GITLAB_USERNAME": (
                run.reviewer_provider_username if run.reviewer_provider == "gitlab" else ""
            ),
        }

    @staticmethod
    def _child_builtins(
        run: WorkflowRun,
        workflow_id: str,
        invocation_path: str,
        *,
        parent_context: dict[str, Any] | None = None,
        workspace_id: uuid.UUID | None = None,
        workspace_branch: str = "",
        workspace_base_commit_sha: str = "",
    ) -> dict[str, str]:
        immutable_keys = {
            "PROJECT_ID",
            "PROJECT_NAME",
            "RUN_DATA_PATH",
            "USER_NAME",
            "USER_EMAIL",
            "CODE_HOST_PROVIDER",
            "PROVIDER_USER_ID",
            "PROVIDER_USERNAME",
            "GITLAB_USER_ID",
            "GITLAB_USERNAME",
        }
        inherited = {
            key: str(value)
            for key, value in (parent_context or {}).items()
            if key in immutable_keys
        }
        return {
            **inherited,
            "RUN_ID": str(run.id),
            "RUN_ID_SHORT": run.id.hex[:8],
            "ROOT_WORKFLOW_ID": run.root_workflow_id,
            "WORKFLOW_ID": workflow_id,
            "INVOCATION_PATH": invocation_path,
            "BASE_REF": run.base_ref,
            "BASE_COMMIT_SHA": run.base_commit_sha,
            "WORKSPACE_ID": str(workspace_id) if workspace_id else "",
            "WORKSPACE_BRANCH": workspace_branch,
            "WORKSPACE_BASE_COMMIT_SHA": workspace_base_commit_sha,
        }

    async def _run(self, run_id: uuid.UUID) -> WorkflowRun:
        run = await self.session.get(WorkflowRun, run_id)
        if run is None:
            raise RunExecutionError("Run does not exist")
        return run

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise RunExecutionError("Project does not exist")
        return project

    async def _user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise RunExecutionError("Triggering user does not exist")
        return user


def should_publish_run(run: WorkflowRun) -> bool:
    """Only delivery runs backed by reviewed definitions publish Git state."""

    return (
        not run.local_definition_test
        and getattr(run, "delivery_mode", "PROPOSE_CHANGES") != "REPORT_ONLY"
    )


def _logical_status(status: str) -> LogicalStatus:
    mapping = {
        NodeStatus.PENDING: LogicalStatus.PENDING,
        NodeStatus.RUNNING: LogicalStatus.RUNNING,
        NodeStatus.SUCCESS: LogicalStatus.SUCCESS,
        NodeStatus.SKIPPED: LogicalStatus.SKIPPED,
        NodeStatus.FAILED: LogicalStatus.FAILED,
        NodeStatus.CANCELLED: LogicalStatus.FAILED,
        NodeStatus.INTERRUPTED: LogicalStatus.FAILED,
        NodeStatus.AWAITING_FEEDBACK: LogicalStatus.RUNNING,
    }
    return mapping[NodeStatus(status)]


def _provider_reviewers(snapshot: dict[str, Any]) -> list[ProviderUser]:
    reviewers: dict[tuple[str, str], ProviderUser] = {}
    for requirement in snapshot.get("requirements", []):
        for actor in requirement.get("users", []):
            key = (str(actor["provider_user_id"]), str(actor["provider_username"]))
            reviewers[key] = ProviderUser(id=key[0], username=key[1])
    return list(reviewers.values())
